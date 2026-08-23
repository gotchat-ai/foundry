from __future__ import annotations

import json
import os
import re
import tempfile
import gc
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:
    import torch as _torch_for_ggml_base
except Exception:
    _torch_for_ggml_base = None


def ensure_vendor_paths(repo_root: str | Path) -> None:
    root = Path(repo_root).resolve()
    vendor_roots = [
        root / "vendor" / "LTX-2",
    ]
    comfy_vendor_roots = [
        root / "vendor" / "ComfyUI-GGUF",
    ]
    candidates = []
    for vendor_root in vendor_roots:
        candidates.extend(
            [
                vendor_root / "packages" / "ltx-core" / "src",
                vendor_root / "packages" / "ltx-pipelines" / "src",
            ]
        )
    candidates.extend(comfy_vendor_roots)
    import sys

    for path in candidates:
        text = str(path)
        if path.exists() and text not in sys.path:
            sys.path.insert(0, text)


def _read_gguf(reader_path: str):
    import gguf

    return gguf.GGUFReader(reader_path)


def _get_field(reader: Any, field_name: str, field_type: type) -> Any:
    field = reader.get_field(field_name)
    if field is None:
        return None
    if field_type == str:
        return str(field.parts[field.data[-1]], encoding="utf-8")
    if field_type in (int, float, bool):
        return field_type(field.parts[field.data[-1]].item())
    raise TypeError(f"unsupported field type: {field_type!r}")


def _get_list_field(reader: Any, field_name: str, field_type: type) -> tuple[Any, ...] | None:
    field = reader.get_field(field_name)
    if field is None:
        return None
    if field_type == str:
        return tuple(str(field.parts[idx], encoding="utf-8") for idx in field.data)
    if field_type in (int, float, bool):
        return tuple(field_type(field.parts[idx][0]) for idx in field.data)
    raise TypeError(f"unsupported field list type: {field_type!r}")


def _get_orig_shape(reader: Any, tensor_name: str):
    import gguf
    import torch

    field_key = f"comfy.gguf.orig_shape.{tensor_name}"
    field = reader.get_field(field_key)
    if field is None:
        return None
    if len(field.types) != 2 or field.types[0] != gguf.GGUFValueType.ARRAY or field.types[1] != gguf.GGUFValueType.INT32:
        return None
    return torch.Size(tuple(int(field.parts[idx][0]) for idx in field.data))


def _extract_metadata(reader: Any) -> dict[str, Any]:
    import gguf

    out: dict[str, Any] = {}
    for field_name in reader.fields:
        try:
            field = reader.get_field(field_name)
            if len(field.types) != 1:
                continue
            kind = field.types[0]
            if kind == gguf.GGUFValueType.STRING:
                out[field_name] = str(field.parts[field.data[-1]], "utf-8")
            elif kind == gguf.GGUFValueType.INT32:
                out[field_name] = int(field.parts[field.data[-1]])
            elif kind == gguf.GGUFValueType.F32:
                out[field_name] = float(field.parts[field.data[-1]])
            elif kind == gguf.GGUFValueType.BOOL:
                out[field_name] = bool(field.parts[field.data[-1]])
        except Exception:
            continue
    return out


def _tensor_to_torch(tensor: Any):
    import torch
    import warnings

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="The given NumPy array is not writable")
        return torch.from_numpy(tensor.data)


class GGMLTensor(_torch_for_ggml_base.Tensor if _torch_for_ggml_base is not None else object):
    """Mmap-backed GGUF tensor wrapper.

    This mirrors the important part of ComfyUI-GGUF's GGMLTensor: keep the
    packed quantized bytes as the parameter storage and carry the real output
    shape/type as metadata. GGUF-aware modules dequantize this tensor only for
    the current layer forward pass.
    """

    def __new__(cls, data: Any, *, tensor_type: Any, tensor_shape: Any, **kwargs: Any):
        import torch

        if _torch_for_ggml_base is None:
            raise RuntimeError("torch is required for GGMLTensor")
        return torch.Tensor._make_subclass(cls, data, require_grad=False)

    def __init__(self, data: Any, *, tensor_type: Any, tensor_shape: Any, **kwargs: Any) -> None:
        import torch

        self.tensor_type = tensor_type
        self.tensor_shape = torch.Size(tuple(int(v) for v in tensor_shape))

    @property
    def shape(self):  # type: ignore[override]
        return getattr(self, "tensor_shape", super().shape)

    def clone(self, *args: Any, **kwargs: Any):
        return self

    def detach(self, *args: Any, **kwargs: Any):
        return self

    def to(self, *args: Any, **kwargs: Any):
        import torch

        if is_ggml_quantized_tensor(self):
            device = kwargs.get("device")
            for arg in args:
                if isinstance(arg, torch.Tensor):
                    device = arg.device
                elif isinstance(arg, (torch.device, str, int)):
                    device = arg
            new = super().to(device=device) if device is not None else self
        else:
            new = super().to(*args, **kwargs)
        if isinstance(new, GGMLTensor):
            new.tensor_type = getattr(self, "tensor_type", None)
            new.tensor_shape = getattr(self, "tensor_shape", new.shape)
            return new
        return GGMLTensor(
            new,
            tensor_type=getattr(self, "tensor_type", None),
            tensor_shape=getattr(self, "tensor_shape", new.shape),
        )


def is_ggml_quantized_tensor(tensor: Any) -> bool:
    try:
        import gguf

        return getattr(tensor, "tensor_type", None) not in (
            None,
            gguf.GGMLQuantizationType.F32,
            gguf.GGMLQuantizationType.F16,
        )
    except Exception:
        return False


def dequantize_ggml_tensor(tensor: Any, *, dtype: Any = None, device: Any = None) -> Any:
    import torch

    qtype = getattr(tensor, "tensor_type", None)
    shape = getattr(tensor, "tensor_shape", None)
    packed = tensor.as_subclass(torch.Tensor) if isinstance(tensor, GGMLTensor) else tensor
    out = _dequantize_tensor(packed, dtype=dtype, qtype=qtype, device=device, logical_shape=shape)
    if shape is not None:
        target_shape = tuple(int(v) for v in shape)
        try:
            out = out.reshape(target_shape)
        except RuntimeError:
            target_numel = 1
            for dim in target_shape:
                target_numel *= int(dim)
            if out.numel() < target_numel:
                raise
            if len(target_shape) == 2 and target_shape[0] > 0 and out.numel() % target_shape[0] == 0:
                padded = out.reshape(target_shape[0], -1)
                if padded.shape[1] >= target_shape[1]:
                    out = padded[:, : target_shape[1]].contiguous()
                else:
                    raise
            else:
                out = out.reshape(-1)[:target_numel].reshape(target_shape).contiguous()
    return out


def _safe_diag_print(message: str) -> None:
    try:
        print(str(message), flush=True)
    except Exception:
        # Agent Flow/service execution can leave stdout/stderr in a state where
        # Windows raises OSError(22) on flush/write. Diagnostics must never make
        # GGUF loading fail.
        pass


def _cast_runtime_tensor(value: Any, *, dtype: Any, device: Any) -> Any:
    if value is None:
        return None
    if is_ggml_quantized_tensor(value):
        return dequantize_ggml_tensor(value, dtype=dtype, device=device)
    return value.to(device=device, dtype=dtype, copy=False)


def release_module_gguf_tensors(module: Any) -> int:
    """Drop plain-attribute GGUF tensors that Module.to('meta') cannot see.

    Our GGUF-aware Linear/Embedding/Norm classes keep packed quantized tensors
    as normal object attributes instead of Parameters. That is what prevents
    PyTorch from eagerly expanding GGUF weights, but it also means generic
    module cleanup/offload helpers cannot release them. This helper walks the
    module tree and nulls only GGUF tensor attributes.
    """
    released = 0
    try:
        modules = list(module.modules())
    except Exception:
        modules = [module]
    for child in modules:
        try:
            names = list(vars(child).keys())
        except Exception:
            continue
        for name in names:
            if name.startswith("_"):
                continue
            try:
                value = getattr(child, name)
            except Exception:
                continue
            if is_ggml_quantized_tensor(value):
                try:
                    object.__setattr__(child, name, None)
                    released += 1
                except Exception:
                    pass
    return released


def move_module_gguf_tensors(module: Any, device: Any) -> tuple[int, int]:
    """Move packed GGUF tensor attributes to *device* without dequantizing them.

    This is the middle ground between the stable CPU lazy path and the broken
    eager/full-VRAM path: the model still keeps quantized packed GGUF tensors
    and each layer dequantizes on demand, but the packed backing storage can
    reside on the accelerator so dequant kernels do not have to page/copy from
    system RAM on every layer.
    """
    moved = 0
    total_bytes = 0
    try:
        modules = list(module.modules())
    except Exception:
        modules = [module]
    for child in modules:
        try:
            names = list(vars(child).keys())
        except Exception:
            continue
        for name in names:
            if name.startswith("_"):
                continue
            try:
                value = getattr(child, name)
            except Exception:
                continue
            if not is_ggml_quantized_tensor(value):
                continue
            try:
                new_value = value.to(device=device)
                object.__setattr__(child, name, new_value)
                moved += 1
                total_bytes += int(getattr(new_value, "nbytes", 0) or 0)
            except Exception as exc:
                _safe_diag_print(
                    "[ltx_native_gguf_bridge] failed to move packed GGUF tensor "
                    f"{type(child).__name__}.{name} to {device}: {exc}"
                )
    return moved, total_bytes


def _load_parameter_attr(module: Any, state_dict: dict[str, Any], prefix: str, attr: str) -> bool:
    import torch

    key = prefix + attr
    if key not in state_dict:
        return False
    value = state_dict[key]
    if is_ggml_quantized_tensor(value):
        # Quantized GGUF tensors are packed integer storage plus logical-shape
        # metadata. They cannot be wrapped in torch.nn.Parameter because
        # Parameter requires floating/complex tensors when autograd metadata is
        # attached, and PyTorch's normal load path also compares the packed
        # storage shape instead of the logical GGUF tensor shape. Keep the
        # packed tensor as a plain module attribute; the GGUF-aware forward
        # methods dequantize it on demand.
        params = getattr(module, "_parameters", None)
        if isinstance(params, dict) and attr in params:
            del params[attr]
        buffers = getattr(module, "_buffers", None)
        if isinstance(buffers, dict) and attr in buffers:
            del buffers[attr]
        object.__setattr__(module, attr, value)
        return True
    setattr(module, attr, torch.nn.Parameter(value, requires_grad=False))
    return True


@contextmanager
def gguf_patched_torch_nn():
    """Temporarily construct modules with GGUF-aware layer classes.

    This is intentionally local to model construction. It mirrors the ComfyUI
    GGUF idea without requiring a full ComfyUI runtime: packed GGUF tensors stay
    attached to modules, and each forward dequantizes only the active layer.
    """
    import torch
    import torch.nn.functional as F
    import torch.nn.modules.linear as linear_mod
    import torch.nn.modules.normalization as norm_mod
    import torch.nn.modules.sparse as sparse_mod

    orig_linear = torch.nn.Linear
    orig_embedding = torch.nn.Embedding
    orig_layer_norm = torch.nn.LayerNorm
    orig_group_norm = torch.nn.GroupNorm
    orig_linear_mod_linear = linear_mod.Linear
    orig_sparse_mod_embedding = sparse_mod.Embedding
    orig_norm_mod_layer_norm = norm_mod.LayerNorm
    orig_norm_mod_group_norm = norm_mod.GroupNorm
    orig_module_load_state_dict = torch.nn.Module.load_state_dict

    class GGUFLinear(torch.nn.Module):
        def __init__(self, in_features: int, out_features: int, bias: bool = True, device=None, dtype=None) -> None:
            super().__init__()
            self.in_features = int(in_features)
            self.out_features = int(out_features)
            self._gguf_runtime_dtype = dtype
            # Match ComfyUI-GGUF: do not allocate placeholder fp weights.
            # On Windows, torch.empty for every layer can reserve tens of GB of
            # system commit before the quantized GGUF tensors are even loaded.
            self.weight = None
            self.bias = None
            self._has_bias = bool(bias)

        def _load_from_state_dict(self, state_dict, prefix, local_metadata, strict, missing_keys, unexpected_keys, error_msgs):
            loaded_w = _load_parameter_attr(self, state_dict, prefix, "weight")
            loaded_b = _load_parameter_attr(self, state_dict, prefix, "bias") if self._has_bias else False
            if not loaded_w and strict:
                missing_keys.append(prefix + "weight")
            if self._has_bias and not loaded_b and strict:
                missing_keys.append(prefix + "bias")

        def forward(self, input):
            if self.weight is None:
                # ComfyUI-GGUF tolerates missing Linear weights created during
                # meta/streaming construction by materializing a zero fallback.
                # Do it lazily on the active input device so we do not recreate
                # the Windows placeholder-allocation spike at module init time.
                self.weight = torch.zeros(
                    (self.out_features, self.in_features),
                    device=getattr(input, "device", None),
                    dtype=getattr(input, "dtype", torch.float32),
                )
            dtype = getattr(input, "dtype", None) or self._gguf_runtime_dtype or torch.float32
            device = getattr(input, "device", torch.device("cpu"))
            weight = _cast_runtime_tensor(self.weight, dtype=dtype, device=device)
            bias = _cast_runtime_tensor(self.bias, dtype=dtype, device=device) if self.bias is not None else None
            return F.linear(input, weight, bias)

    class GGUFEmbedding(torch.nn.Module):
        def __init__(
            self,
            num_embeddings: int,
            embedding_dim: int,
            padding_idx=None,
            max_norm=None,
            norm_type: float = 2.0,
            scale_grad_by_freq: bool = False,
            sparse: bool = False,
            _weight=None,
            _freeze: bool = False,
            device=None,
            dtype=None,
        ) -> None:
            super().__init__()
            self.num_embeddings = int(num_embeddings)
            self.embedding_dim = int(embedding_dim)
            self._gguf_runtime_dtype = dtype
            self.padding_idx = padding_idx
            self.max_norm = max_norm
            self.norm_type = norm_type
            self.scale_grad_by_freq = scale_grad_by_freq
            self.sparse = sparse
            if _weight is None:
                # Avoid eager placeholder allocation for GGUF embeddings.
                self.weight = None
            else:
                self.weight = torch.nn.Parameter(_weight, requires_grad=not _freeze)

        def _load_from_state_dict(self, state_dict, prefix, local_metadata, strict, missing_keys, unexpected_keys, error_msgs):
            loaded = _load_parameter_attr(self, state_dict, prefix, "weight")
            if not loaded and strict:
                missing_keys.append(prefix + "weight")

        def forward(self, input):
            if self.weight is None:
                raise RuntimeError("GGUFEmbedding weight was not loaded")
            dtype = self._gguf_runtime_dtype
            if dtype is None:
                # Token id tensors are integer, so they do not tell us the
                # desired compute dtype. Prefer BF16 for accelerator text
                # encoders; defaulting this path to FP16 caused Gemma GGUF
                # hidden states to overflow/NaN on Intel XPU.
                device_type = str(getattr(getattr(input, "device", None), "type", "") or input.device).lower()
                dtype = torch.bfloat16 if device_type in {"xpu", "cuda"} else torch.float32
            weight = _cast_runtime_tensor(self.weight, dtype=dtype, device=input.device)
            return F.embedding(input, weight, self.padding_idx, self.max_norm, self.norm_type, self.scale_grad_by_freq, self.sparse)

    class GGUFLayerNorm(orig_layer_norm):
        def _load_from_state_dict(self, state_dict, prefix, local_metadata, strict, missing_keys, unexpected_keys, error_msgs):
            if is_ggml_quantized_tensor(state_dict.get(prefix + "weight")) or is_ggml_quantized_tensor(state_dict.get(prefix + "bias")):
                _load_parameter_attr(self, state_dict, prefix, "weight")
                _load_parameter_attr(self, state_dict, prefix, "bias")
                return
            return super()._load_from_state_dict(state_dict, prefix, local_metadata, strict, missing_keys, unexpected_keys, error_msgs)

        def forward(self, input):
            weight = _cast_runtime_tensor(self.weight, dtype=input.dtype, device=input.device) if self.weight is not None else None
            bias = _cast_runtime_tensor(self.bias, dtype=input.dtype, device=input.device) if self.bias is not None else None
            return F.layer_norm(input, self.normalized_shape, weight, bias, self.eps)

    class GGUFGroupNorm(orig_group_norm):
        def _load_from_state_dict(self, state_dict, prefix, local_metadata, strict, missing_keys, unexpected_keys, error_msgs):
            if is_ggml_quantized_tensor(state_dict.get(prefix + "weight")) or is_ggml_quantized_tensor(state_dict.get(prefix + "bias")):
                _load_parameter_attr(self, state_dict, prefix, "weight")
                _load_parameter_attr(self, state_dict, prefix, "bias")
                return
            return super()._load_from_state_dict(state_dict, prefix, local_metadata, strict, missing_keys, unexpected_keys, error_msgs)

        def forward(self, input):
            weight = _cast_runtime_tensor(self.weight, dtype=input.dtype, device=input.device) if self.weight is not None else None
            bias = _cast_runtime_tensor(self.bias, dtype=input.dtype, device=input.device) if self.bias is not None else None
            return F.group_norm(input, self.num_groups, weight, bias, self.eps)

    def _coerce_existing_module_for_quantized_attr(module: Any, attr: str) -> None:
        # Some upstream classes import/use torch.nn aliases before this context
        # swaps torch.nn.Embedding/Linear. If such a class was instantiated as a
        # regular PyTorch module, the normal assign=True load path will try to
        # install packed uint GGUF storage as a trainable Parameter and explode.
        # Convert the already-created module to the matching GGUF-aware subclass
        # before attaching packed weights so forward remains lazy/on-the-fly.
        if isinstance(module, orig_embedding) and not isinstance(module, GGUFEmbedding):
            module._gguf_runtime_dtype = getattr(getattr(module, "weight", None), "dtype", None)
            module.__class__ = GGUFEmbedding
        elif isinstance(module, orig_linear) and not isinstance(module, GGUFLinear):
            module._gguf_runtime_dtype = getattr(getattr(module, "weight", None), "dtype", None)
            module._has_bias = getattr(module, "bias", None) is not None
            module.__class__ = GGUFLinear
        elif isinstance(module, orig_layer_norm) and not isinstance(module, GGUFLayerNorm):
            module.__class__ = GGUFLayerNorm
        elif isinstance(module, orig_group_norm) and not isinstance(module, GGUFGroupNorm):
            module.__class__ = GGUFGroupNorm

    def _preload_quantized_gguf_attrs(root_module: Any, state_dict: dict[str, Any]) -> dict[str, Any]:
        if not any(is_ggml_quantized_tensor(value) for value in state_dict.values()):
            return state_dict
        remaining = dict(state_dict)
        for key, value in list(state_dict.items()):
            if not is_ggml_quantized_tensor(value):
                continue
            module_name, sep, attr = key.rpartition(".")
            if not sep or not attr:
                continue
            try:
                module = root_module.get_submodule(module_name)
            except Exception:
                continue
            _coerce_existing_module_for_quantized_attr(module, attr)
            if _load_parameter_attr(module, remaining, module_name + ".", attr):
                remaining.pop(key, None)
        return remaining

    def gguf_aware_load_state_dict(self, state_dict, *args, **kwargs):
        try:
            state_dict = _preload_quantized_gguf_attrs(self, state_dict)
        except Exception as exc:
            _safe_diag_print(f"[ltx_native_gguf_bridge] quantized preload skipped: {exc}")
        return orig_module_load_state_dict(self, state_dict, *args, **kwargs)

    torch.nn.Linear = GGUFLinear
    torch.nn.Embedding = GGUFEmbedding
    torch.nn.LayerNorm = GGUFLayerNorm
    torch.nn.GroupNorm = GGUFGroupNorm
    linear_mod.Linear = GGUFLinear
    sparse_mod.Embedding = GGUFEmbedding
    norm_mod.LayerNorm = GGUFLayerNorm
    norm_mod.GroupNorm = GGUFGroupNorm
    torch.nn.Module.load_state_dict = gguf_aware_load_state_dict
    try:
        yield
    finally:
        torch.nn.Linear = orig_linear
        torch.nn.Embedding = orig_embedding
        torch.nn.LayerNorm = orig_layer_norm
        torch.nn.GroupNorm = orig_group_norm
        linear_mod.Linear = orig_linear_mod_linear
        sparse_mod.Embedding = orig_sparse_mod_embedding
        norm_mod.LayerNorm = orig_norm_mod_layer_norm
        norm_mod.GroupNorm = orig_norm_mod_group_norm
        torch.nn.Module.load_state_dict = orig_module_load_state_dict


def gguf_lazy_configurator(base_configurator: Any):
    class LazyGGUFConfigurator:
        @classmethod
        def from_config(cls, config: dict):
            with gguf_patched_torch_nn():
                return base_configurator.from_config(config)

    LazyGGUFConfigurator.__name__ = f"LazyGGUF{getattr(base_configurator, '__name__', 'Configurator')}"
    return LazyGGUFConfigurator


def _dequantize_tensor(tensor: Any, *, dtype: Any, qtype: Any = None, device: Any = None, logical_shape: Any = None):
    import gguf
    import numpy as np
    import torch

    effective_qtype = qtype if qtype is not None else getattr(tensor, "tensor_type", None)
    target_device = device if device is not None else tensor.device
    if effective_qtype in (None, gguf.GGMLQuantizationType.F32, gguf.GGMLQuantizationType.F16):
        return tensor.to(device=target_device, dtype=dtype, copy=False)

    # Prefer the ComfyUI-GGUF torch dequant kernels when available.  The older
    # fallback below goes through tensor.cpu().numpy(), which makes accelerator
    # runs silently do most GGUF work in system RAM.  Comfy's kernels operate on
    # the packed tensor's current device, so this keeps the same lazy/on-demand
    # behavior but lets each active layer dequantize on XPU/CUDA.
    try:
        from dequant import dequantize as comfy_torch_dequantize  # type: ignore
        from dequant import dequantize_functions as comfy_dequantize_functions  # type: ignore

        if effective_qtype in comfy_dequantize_functions:
            packed = tensor.as_subclass(torch.Tensor) if isinstance(tensor, GGMLTensor) else tensor
            packed = packed.to(device=target_device, copy=False)
            if logical_shape is None:
                logical_shape = gguf.quants.quant_shape_from_byte_shape(tuple(packed.shape), effective_qtype)
            return comfy_torch_dequantize(
                packed,
                effective_qtype,
                tuple(int(v) for v in logical_shape),
                dtype=dtype,
            ).to(device=target_device, dtype=dtype, copy=False)
    except Exception as exc:
        _safe_diag_print(f"[ltx_native_gguf_bridge] torch GGUF dequant unavailable; using CPU fallback: {exc}")

    array = tensor.cpu().numpy()
    quant_cls = getattr(gguf.quants, "_type_traits", {}).get(effective_qtype)
    if quant_cls is None or getattr(array, "ndim", 0) < 2:
        raw = gguf.quants.dequantize(array, effective_qtype)
        return torch.from_numpy(raw).to(dtype=dtype, device=target_device)

    packed_rows = np.ascontiguousarray(array.reshape((-1, array.shape[-1])))
    unpacked_shape = gguf.quants.quant_shape_from_byte_shape(array.shape, effective_qtype)
    row_width = int(unpacked_shape[-1])
    target = torch.empty((packed_rows.shape[0], row_width), dtype=dtype, device=target_device)

    element_size = max(int(torch.empty((), dtype=dtype).element_size()), 1)
    target_chunk_bytes = 64 * 1024 * 1024
    rows_per_chunk = max(1, int(target_chunk_bytes // max(row_width * element_size, 1)))
    rows_per_chunk = min(rows_per_chunk, packed_rows.shape[0])

    for start in range(0, packed_rows.shape[0], rows_per_chunk):
        end = min(start + rows_per_chunk, packed_rows.shape[0])
        row_chunk = np.ascontiguousarray(packed_rows[start:end])
        part = quant_cls.dequantize_rows(row_chunk)
        part_t = torch.from_numpy(part.reshape((end - start, -1))).to(dtype=dtype, device=target_device)
        target[start:end].copy_(part_t)
        del part_t
        del part

    return target.reshape(unpacked_shape)


def _reshape_loaded_tensor(value: Any, tensor: Any, shape: Any, *, is_text_model: bool) -> Any:
    import torch

    candidates: list[tuple[int, ...]] = []
    if shape is not None:
        try:
            candidates.append(tuple(int(v) for v in shape))
        except Exception:
            pass
    try:
        candidates.append(tuple(int(v) for v in reversed(tensor.shape)))
    except Exception:
        pass
    try:
        candidates.append(tuple(int(v) for v in tensor.shape))
    except Exception:
        pass

    seen: set[tuple[int, ...]] = set()
    last_exc: Exception | None = None
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            return value.view(*candidate)
        except Exception as exc:
            last_exc = exc

    if is_text_model and getattr(value, "ndim", 0) == 1:
        for candidate in candidates:
            if len(candidate) == 2:
                rows, cols = candidate
                if cols > 0 and int(value.numel()) % int(cols) == 0:
                    try:
                        return value.view(int(value.numel()) // int(cols), int(cols))
                    except Exception as exc:
                        last_exc = exc

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("unable to reshape GGUF tensor")


GEMMA3_SD_MAP = {
    "blk.": "model.model.language_model.layers.",
    "attn_norm": "input_layernorm",
    "attn_q_norm.": "self_attn.q_norm.",
    "attn_k_norm.": "self_attn.k_norm.",
    "attn_v_norm.": "self_attn.v_norm.",
    "attn_q": "self_attn.q_proj",
    "attn_k": "self_attn.k_proj",
    "attn_v": "self_attn.v_proj",
    "attn_output": "self_attn.o_proj",
    "ffn_up": "mlp.up_proj",
    "ffn_down": "mlp.down_proj",
    "ffn_gate": "mlp.gate_proj",
    "ffn_norm": "pre_feedforward_layernorm",
    "post_ffw_norm": "post_feedforward_layernorm",
    "post_attention_norm": "post_attention_layernorm",
    "token_embd": "model.model.language_model.embed_tokens",
    "output_norm": "model.model.language_model.norm",
}


def _sd_map_replace(raw_sd: dict[str, Any], key_map: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in raw_sd.items():
        mapped = key
        for src, dst in key_map.items():
            mapped = mapped.replace(src, dst)
        out[mapped] = value
    return out


def _gemma3_norm_corrections(state_dict: dict[str, Any]) -> dict[str, Any]:
    import gguf
    import torch

    norm_patterns = (
        "input_layernorm.weight",
        "post_attention_layernorm.weight",
        "pre_feedforward_layernorm.weight",
        "post_feedforward_layernorm.weight",
        "self_attn.q_norm.weight",
        "self_attn.k_norm.weight",
        "model.norm.weight",
    )
    corrected: dict[str, Any] = {}
    for key, value in state_dict.items():
        if any(pattern in key for pattern in norm_patterns):
            qtype = getattr(value, "tensor_type", None)
            if qtype not in (None, gguf.GGMLQuantizationType.F32, gguf.GGMLQuantizationType.F16):
                value = dequantize_ggml_tensor(value, dtype=torch.float32)
            else:
                value = value.float()
            corrected[key] = value - 1.0
        else:
            corrected[key] = value
    return corrected


def _strip_quant_suffix(name: str) -> str:
    pattern = r"[-_]?(?:ud-)?i?q[0-9]_[a-z0-9_\-]{1,8}$"
    match = re.search(pattern, str(name or ""), re.IGNORECASE)
    if match:
        return name[: match.start()]
    return name


def _apply_text_model_remap(state_dict: dict[str, Any], *, arch_str: str | None, lazy_quantized: bool = False) -> dict[str, Any]:
    import torch

    arch = str(arch_str or "").strip().lower()
    if arch != "gemma3":
        return state_dict
    remapped = _sd_map_replace(state_dict, GEMMA3_SD_MAP)
    token_key = "model.model.language_model.embed_tokens.weight"
    token_tensor = remapped.get(token_key)
    if not lazy_quantized and token_tensor is not None and getattr(token_tensor, "shape", (0,))[0] >= 64 * 1024:
        remapped[token_key] = dequantize_ggml_tensor(token_tensor, dtype=torch.float16)
        token_tensor = remapped[token_key]
    if token_tensor is not None and "model.lm_head.weight" not in remapped:
        remapped["model.lm_head.weight"] = token_tensor
    return _gemma3_norm_corrections(remapped)


def load_gguf_state_dict(
    path: str,
    *,
    sd_ops: Any = None,
    device: Any = None,
    dtype: Any = None,
    handle_prefix: str | None = None,
    is_text_model: bool = False,
    lazy_quantized: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    import gguf
    import torch

    started = time.time()
    reader = _read_gguf(path)
    arch_str = _get_field(reader, "general.architecture", str)
    type_str = _get_field(reader, "general.type", str)
    metadata = _extract_metadata(reader)

    has_prefix = False
    prefix_len = 0
    if handle_prefix is not None:
        prefix_len = len(handle_prefix)
        tensor_names = set(tensor.name for tensor in reader.tensors)
        has_prefix = any(name.startswith(handle_prefix) for name in tensor_names)

    out: dict[str, Any] = {}
    total_size = 0
    device = device or torch.device("cpu")
    target_dtype = dtype or torch.float32

    loaded_count = 0
    lazy_count = 0
    device_text = str(device or "").lower()
    target_is_accelerator = bool(device_text and not device_text.startswith("cpu"))

    _safe_diag_print(
        "[ltx_native_gguf_bridge] load_gguf_state_dict "
        f"path={path} is_text_model={bool(is_text_model)} device={device} dtype={target_dtype} "
        f"tensor_count={len(reader.tensors)}"
    )

    for tensor in reader.tensors:
        raw_key = tensor.name
        key = raw_key
        if has_prefix:
            if not raw_key.startswith(handle_prefix):
                continue
            key = raw_key[prefix_len:]
        mapped_key = key if sd_ops is None else sd_ops.apply_to_key(key)
        if mapped_key is None:
            continue

        torch_tensor = _tensor_to_torch(tensor)
        shape = _get_orig_shape(reader, raw_key)
        if shape is None:
            shape = tuple(int(v) for v in reversed(tensor.shape))
        try:
            if getattr(tensor, "tensor_type", None) in {
                gguf.GGMLQuantizationType.F32,
                gguf.GGMLQuantizationType.F16,
                None,
            }:
                value = _reshape_loaded_tensor(torch_tensor, tensor, shape, is_text_model=is_text_model).to(
                    device=device, dtype=target_dtype, copy=False
                )
            else:
                should_keep_lazy = bool(lazy_quantized) and len(tuple(int(v) for v in shape)) == 2
                direct_parameter_markers = (
                    "scale_shift_table",
                    "learnable_registers",
                    "position",
                    "pos_embed",
                )
                if any(marker in raw_key for marker in direct_parameter_markers):
                    should_keep_lazy = False
                if should_keep_lazy:
                    value = GGMLTensor(
                        torch_tensor,
                        tensor_type=getattr(tensor, "tensor_type", None),
                        tensor_shape=shape,
                    )
                    lazy_count += 1
                else:
                    value = _reshape_loaded_tensor(
                        _dequantize_tensor(
                            torch_tensor,
                            dtype=target_dtype,
                            qtype=getattr(tensor, "tensor_type", None),
                            device=device,
                            logical_shape=shape,
                        ),
                        tensor,
                        shape,
                        is_text_model=is_text_model,
                    ).to(device=device, copy=False)
        except Exception as exc:
            tensor_shape = tuple(int(v) for v in getattr(tensor, "shape", ()))
            orig_shape = tuple(int(v) for v in shape) if shape is not None else None
            raise RuntimeError(
                "failed to load GGUF tensor "
                f"{raw_key!r} -> {mapped_key!r}; "
                f"tensor_shape={tensor_shape}; "
                f"orig_shape={orig_shape}; "
                f"quant_type={getattr(tensor, 'tensor_type', None)!r}; "
                f"packed_numel={int(getattr(torch_tensor, 'numel', lambda: 0)())}"
            ) from exc

        key_values = ((mapped_key, value),)
        if sd_ops is not None:
            key_values = [(row.new_key, row.new_value) for row in sd_ops.apply_to_key_value(mapped_key, value)]
        for final_key, final_value in key_values:
            out[final_key] = final_value
            total_size += int(getattr(final_value, "nbytes", 0))
        loaded_count += 1
        if target_is_accelerator and loaded_count % 16 == 0:
            try:
                gc.collect()
            except Exception:
                pass
            try:
                if hasattr(torch._C, "_host_emptyCache"):
                    torch._C._host_emptyCache()
            except Exception:
                pass

    if is_text_model:
        out = _apply_text_model_remap(out, arch_str=arch_str, lazy_quantized=lazy_quantized)

    _safe_diag_print(
        "[ltx_native_gguf_bridge] load_gguf_state_dict done "
        f"path={path} is_text_model={bool(is_text_model)} device={device} "
        f"loaded_tensors={len(out)} lazy_tensors={lazy_count} size_mb={round(total_size / 1024 / 1024, 1)} "
        f"elapsed_s={round(time.time() - started, 2)}"
    )

    return out, {
        "arch_str": arch_str,
        "type_str": type_str,
        "metadata": metadata,
        "size_bytes": total_size,
        "is_text_model": bool(is_text_model),
    }


def gguf_metadata_config(path: str) -> dict[str, Any]:
    reader = _read_gguf(path)
    metadata = _extract_metadata(reader)
    raw = metadata.get("config")
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def gguf_transformer_block_count(path: str, *, prefix: str = "model.diffusion_model.transformer_blocks.") -> int | None:
    reader = _read_gguf(path)
    block_ids: set[int] = set()
    for tensor in reader.tensors:
        name = str(getattr(tensor, "name", "") or "")
        if prefix not in name:
            continue
        try:
            tail = name.split(prefix, 1)[1]
            idx_text = tail.split(".", 1)[0]
            if idx_text.isdigit():
                block_ids.add(int(idx_text))
        except Exception:
            continue
    if not block_ids:
        return None
    return max(block_ids) + 1


def gguf_tensor_shape(path: str, tensor_name: str) -> tuple[int, ...] | None:
    reader = _read_gguf(path)
    for tensor in reader.tensors:
        if str(getattr(tensor, "name", "") or "") != str(tensor_name or ""):
            continue
        shape = _get_orig_shape(reader, tensor.name)
        if shape is not None:
            try:
                return tuple(int(v) for v in shape)
            except Exception:
                return None
        try:
            return tuple(int(v) for v in reversed(tuple(getattr(tensor, "shape", ()))))
        except Exception:
            return None
    return None


def gguf_has_tensor(path: str, tensor_name: str) -> bool:
    reader = _read_gguf(path)
    target = str(tensor_name or "")
    return any(str(getattr(tensor, "name", "") or "") == target for tensor in reader.tensors)


def gguf_ltx_inspection(path: str) -> dict[str, Any]:
    """Single-pass metadata/tensor inspection for LTX GGUF files.

    Avoid repeatedly constructing GGUFReader over a 15GB file just to answer
    config/has_tensor/shape questions. On Windows this was making Agent Flow
    appear stuck at step 2 and temporarily inflating process memory.
    """
    reader = _read_gguf(path)
    metadata = _extract_metadata(reader)
    raw_config = metadata.get("config")
    native_config: dict[str, Any] = {}
    if isinstance(raw_config, str) and raw_config.strip():
        try:
            parsed = json.loads(raw_config)
            if isinstance(parsed, dict):
                native_config = parsed
        except Exception:
            native_config = {}

    tensor_names: set[str] = set()
    shapes: dict[str, tuple[int, ...]] = {}
    block_ids: set[int] = set()
    prefixes = ("transformer_blocks.", "model.diffusion_model.transformer_blocks.")
    wanted_shapes = {
        "transformer_blocks.0.scale_shift_table",
        "model.diffusion_model.transformer_blocks.0.scale_shift_table",
        "transformer_blocks.0.audio_scale_shift_table",
        "model.diffusion_model.transformer_blocks.0.audio_scale_shift_table",
    }
    for tensor in reader.tensors:
        name = str(getattr(tensor, "name", "") or "")
        if not name:
            continue
        tensor_names.add(name)
        for prefix in prefixes:
            if name.startswith(prefix):
                tail = name[len(prefix):]
                idx_text = tail.split(".", 1)[0]
                if idx_text.isdigit():
                    block_ids.add(int(idx_text))
        if name in wanted_shapes:
            shape = _get_orig_shape(reader, name)
            if shape is None:
                try:
                    shape = tuple(int(v) for v in reversed(tuple(getattr(tensor, "shape", ()))))
                except Exception:
                    shape = None
            if shape is not None:
                try:
                    shapes[name] = tuple(int(v) for v in shape)
                except Exception:
                    pass

    return {
        "native_config": native_config,
        "tensor_names": tensor_names,
        "shapes": shapes,
        "block_count": (max(block_ids) + 1) if block_ids else None,
    }


def materialize_gemma_tokenizer_from_gguf(path: str, *, target_dir: str | Path | None = None) -> str:
    from sentencepiece import sentencepiece_model_pb2 as model

    target_root = Path(target_dir) if target_dir is not None else Path(
        tempfile.mkdtemp(prefix="gemma_gguf_tok_", dir=str(Path(path).resolve().parents[0]))
    )
    target_root.mkdir(parents=True, exist_ok=True)
    reader = _read_gguf(path)

    tokens = _get_list_field(reader, "tokenizer.ggml.tokens", str)
    scores = _get_list_field(reader, "tokenizer.ggml.scores", float)
    toktypes = _get_list_field(reader, "tokenizer.ggml.token_type", int)
    if not tokens or not scores or not toktypes:
        raise ValueError("GGUF tokenizer metadata is missing tokens/scores/token_type")

    spm = model.ModelProto()
    spm.normalizer_spec.name = "identity"
    spm.normalizer_spec.add_dummy_prefix = False
    spm.trainer_spec.model_type = 2
    spm.trainer_spec.input_format = "tsv"
    spm.trainer_spec.byte_fallback = True
    spm.trainer_spec.max_sentence_length = 4192
    spm.trainer_spec.bos_piece = "<bos>"
    for idx in range(len(tokens)):
        piece = spm.SentencePiece()
        piece.piece = tokens[idx]
        if idx == 3:
            piece.type = 2
            piece.score = 0.0
        else:
            piece.type = toktypes[idx]
            piece.score = scores[idx]
        spm.pieces.append(piece)
    spm.trainer_spec.vocab_size = len(spm.pieces)

    tokenizer_model = target_root / "tokenizer.model"
    tokenizer_model.write_bytes(bytes(spm.SerializeToString()))

    tokenizer_config = {
        "tokenizer_class": "GemmaTokenizer",
        "padding_side": "left",
        "model_max_length": 1024,
        "eos_token": "<eos>",
        "bos_token": "<bos>",
        "unk_token": "<unk>",
    }
    special_tokens_map = {
        "bos_token": "<bos>",
        "eos_token": "<eos>",
        "unk_token": "<unk>",
    }
    (target_root / "tokenizer_config.json").write_text(json.dumps(tokenizer_config, indent=2), encoding="utf-8")
    (target_root / "special_tokens_map.json").write_text(json.dumps(special_tokens_map, indent=2), encoding="utf-8")
    return str(target_root)


class GGUFStateDictLoader:
    def __init__(
        self,
        *,
        metadata_override: dict[str, Any] | None = None,
        handle_prefix: str | None = None,
        is_text_model: bool = False,
        default_dtype: Any = None,
        lazy_quantized: bool = False,
    ) -> None:
        self._metadata_override = dict(metadata_override or {})
        self._handle_prefix = handle_prefix
        self._is_text_model = bool(is_text_model)
        self._default_dtype = default_dtype
        self._lazy_quantized = bool(lazy_quantized)

    def metadata(self, path: str) -> dict:
        if self._metadata_override:
            return dict(self._metadata_override)
        return gguf_metadata_config(path)

    def load(self, path: str | list[str], sd_ops: Any = None, device: Any = None):
        if isinstance(path, list):
            if len(path) != 1:
                raise ValueError("GGUFStateDictLoader supports only a single GGUF path")
            src = path[0]
        else:
            src = path
        import torch
        from ltx_core.loader.primitives import StateDict

        sd, info = load_gguf_state_dict(
            src,
            sd_ops=sd_ops,
            device=device or torch.device("cpu"),
            dtype=self._default_dtype or torch.float32,
            handle_prefix=self._handle_prefix,
            is_text_model=self._is_text_model,
            lazy_quantized=self._lazy_quantized,
        )
        dtype_set = {tensor.dtype for tensor in sd.values() if hasattr(tensor, "dtype")}
        return StateDict(
            sd=sd,
            device=device or torch.device("cpu"),
            size=int(info.get("size_bytes") or 0),
            dtype=dtype_set,
        )


class GGUFStreamingDiskTensorReader:
    """Key-based tensor accessor for LTX block streaming over GGUF files.

    LTX's native ``DiskTensorReader`` is safetensors-only.  The streaming path
    needs the same interface, but for GGUF we keep the file mmap-backed and
    dequantize only the single requested tensor into the caller's staging buffer.
    """

    def __init__(self, paths: list[str]) -> None:
        if len(paths) != 1:
            raise ValueError("GGUF streaming supports one GGUF file per reader")
        self._path = str(paths[0])
        self._reader = _read_gguf(self._path)
        self._tensor_by_key = {str(getattr(tensor, "name", "") or ""): tensor for tensor in self._reader.tensors}

    def get_tensor(self, key: str):
        import gguf
        import torch

        tensor = self._tensor_by_key[key]
        data = _tensor_to_torch(tensor)
        qtype = getattr(tensor, "tensor_type", None)
        orig_shape = _get_orig_shape(self._reader, key)
        logical_shape = orig_shape or getattr(data, "shape", None)
        if qtype in (None, gguf.GGMLQuantizationType.F32, gguf.GGMLQuantizationType.F16):
            out = data
            if logical_shape is not None:
                out = out.reshape(tuple(int(v) for v in logical_shape))
            return out
        wrapped = GGMLTensor(data, tensor_type=qtype, tensor_shape=logical_shape or data.shape)
        # Keep disk streaming memory bounded: dequantize one tensor only, on CPU.
        return dequantize_ggml_tensor(wrapped, dtype=torch.float32, device=torch.device("cpu"))

    def close(self) -> None:
        self._tensor_by_key.clear()
        self._reader = None

    def __contains__(self, key: str) -> bool:
        return key in self._tensor_by_key

    def __iter__(self):
        return iter(self._tensor_by_key)


@contextmanager
def gguf_streaming_disk_reader_patch():
    """Teach LTX's block-streaming builder to use a GGUF reader for GGUF paths."""

    try:
        import ltx_core.block_streaming.builder as builder_mod
    except Exception:
        yield
        return

    orig_reader = getattr(builder_mod, "DiskTensorReader", None)

    class MixedStreamingDiskTensorReader:
        def __init__(self, paths: list[str]) -> None:
            path_list = [str(path or "") for path in paths]
            if path_list and all(path.lower().endswith(".gguf") for path in path_list):
                self._reader = GGUFStreamingDiskTensorReader(path_list)
            else:
                self._reader = orig_reader(paths)

        def get_tensor(self, key: str):
            return self._reader.get_tensor(key)

        def close(self) -> None:
            return self._reader.close()

        def __contains__(self, key: str) -> bool:
            return key in self._reader

        def __iter__(self):
            return iter(self._reader)

    if orig_reader is None:
        yield
        return
    builder_mod.DiskTensorReader = MixedStreamingDiskTensorReader
    try:
        yield
    finally:
        builder_mod.DiskTensorReader = orig_reader


class MixedGGUFSafetensorsLoader:
    def __init__(
        self,
        *,
        metadata_override: dict[str, Any] | None = None,
        handle_prefix: str | None = None,
        is_text_model: bool = False,
        default_dtype: Any = None,
        lazy_quantized: bool = False,
    ) -> None:
        self._gguf_loader = GGUFStateDictLoader(
            metadata_override=metadata_override,
            handle_prefix=handle_prefix,
            is_text_model=is_text_model,
            default_dtype=default_dtype,
            lazy_quantized=lazy_quantized,
        )
        from ltx_core.loader.sft_loader import SafetensorsStateDictLoader

        self._safetensors_loader = SafetensorsStateDictLoader()

    def metadata(self, path: str) -> dict:
        text = str(path or "").strip().lower()
        if text.endswith(".gguf"):
            return self._gguf_loader.metadata(path)
        return {}

    def load(self, path: str | list[str], sd_ops: Any = None, device: Any = None):
        if isinstance(path, list):
            if len(path) != 1:
                raise ValueError("MixedGGUFSafetensorsLoader supports only a single path at a time")
            src = path[0]
        else:
            src = path
        text = str(src or "").strip().lower()
        if text.endswith(".gguf"):
            return self._gguf_loader.load(src, sd_ops=sd_ops, device=device)
        return self._safetensors_loader.load(src, sd_ops=sd_ops, device=device)


class StaticConfigSafetensorsLoader:
    def __init__(self, *, config: dict[str, Any], base_loader: Any | None = None) -> None:
        self._config = dict(config or {})
        if base_loader is None:
            from ltx_core.loader.sft_loader import SafetensorsStateDictLoader

            base_loader = SafetensorsStateDictLoader()
        self._base_loader = base_loader

    def metadata(self, path: str) -> dict:
        return dict(self._config)

    def load(self, path: str | list[str], sd_ops: Any = None, device: Any = None):
        return self._base_loader.load(path, sd_ops=sd_ops, device=device)
