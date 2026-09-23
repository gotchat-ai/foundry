from __future__ import annotations

import gc
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, Hashable, Iterator, Tuple


def _release_module_gguf_tensors(value: Any) -> int:
    """Release packed GGUF tensor attrs on an owned module/builder object."""

    try:
        from pathlib import Path
        import sys

        tools = Path(__file__).resolve().parents[5] / "tools"
        text = str(tools)
        if text not in sys.path:
            sys.path.insert(0, text)
        from ltx_native_gguf_bridge import release_module_gguf_tensors  # type: ignore

        return int(release_module_gguf_tensors(value) or 0)
    except Exception:
        return 0


def _dispose_owned_model_object(value: Any, diagnostics: list[Any] | None = None, *, reason: str = "") -> Dict[str, Any]:
    """Best-effort release for model objects that this workflow explicitly owns.

    This deliberately avoids walking arbitrary object attributes.  It only uses
    common explicit release hooks and PyTorch module APIs, so cleanup can free
    model weights without corrupting interpreter/module globals.
    """

    report: Dict[str, Any] = {"reason": reason, "gguf_tensors_released": 0, "hooks": [], "errors": []}
    if value is None:
        return report
    report["gguf_tensors_released"] = _release_module_gguf_tensors(value)
    for name in ("close", "cleanup", "unload", "release"):
        try:
            fn = getattr(value, name, None)
        except Exception:
            continue
        if not callable(fn):
            continue
        try:
            fn()
            report["hooks"].append(name)
        except TypeError:
            continue
        except Exception as exc:
            report["errors"].append(f"{name}: {exc}")
    try:
        import torch  # type: ignore

        if isinstance(value, torch.nn.Module):
            # Moving to CPU can spike system RAM.  to_empty(meta) drops owned
            # parameter/buffer storage without copying it through host memory.
            try:
                value.to_empty(device="meta")
                report["hooks"].append("torch.nn.Module.to_empty(meta)")
            except Exception as exc:
                report["errors"].append(f"to_empty(meta): {exc}")
    except Exception:
        pass
    if diagnostics is not None and (report["gguf_tensors_released"] or report["hooks"] or report["errors"]):
        diagnostics.append({"cleanup_dispose": report})
    return report


def bool_setting(settings: Dict[str, Any] | None, key: str, default: bool = False) -> bool:
    value = (settings or {}).get(key, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return default


def prompt_cache_mode(
    settings: Dict[str, Any] | None,
    *,
    key: str = "prompt_encoder_cache_mode",
    legacy_bool_keys: tuple[str, ...] = (),
    default: str = "off",
) -> str:
    """Normalize a model-family prompt encoder cache setting.

    The mode describes residency after prompt encoding:
    - off: release the encoder object and accelerator memory.
    - cpu: keep a reusable object, but offload/release accelerator memory.
    - vram: keep a reusable object hot on the main accelerator.
    """

    settings = settings or {}
    raw = str(settings.get(key) or "").strip().lower()
    aliases = {
        "none": "off",
        "disabled": "off",
        "disable": "off",
        "false": "off",
        "0": "off",
        "no": "off",
        "gpu": "vram",
        "xpu": "vram",
        "cuda": "vram",
        "main": "vram",
        "main_video_device": "vram",
    }
    raw = aliases.get(raw, raw)
    if raw in {"off", "cpu", "vram"}:
        return raw
    for legacy_key in legacy_bool_keys:
        if bool_setting(settings, legacy_key, False):
            return "vram"
    return default if default in {"off", "cpu", "vram"} else "off"


def process_memory_trim() -> Dict[str, Any]:
    """Best-effort OS/native heap trim after model resources are released."""

    report: Dict[str, Any] = {"attempted": False, "method": "", "ok": False, "actions": [], "error": ""}
    try:
        if os.name == "nt":
            import ctypes  # type: ignore

            report["attempted"] = True
            report["method"] = "windows_heap_trim"
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            handle = kernel32.GetCurrentProcess()
            actions = report.setdefault("actions", [])
            for dll_name in ("ucrtbase", "msvcrt"):
                try:
                    crt = ctypes.CDLL(dll_name)
                    heapmin = getattr(crt, "_heapmin", None)
                    if callable(heapmin):
                        rc = int(heapmin())
                        actions.append({"name": f"{dll_name}._heapmin", "ok": rc == 0, "rc": rc})
                        break
                except Exception as exc:
                    actions.append({"name": f"{dll_name}._heapmin", "ok": False, "error": str(exc)})
            try:
                kernel32.GetProcessHeap.restype = ctypes.c_void_p
                heap = kernel32.GetProcessHeap()
                if heap:
                    kernel32.HeapCompact.argtypes = [ctypes.c_void_p, ctypes.c_uint]
                    kernel32.HeapCompact.restype = ctypes.c_size_t
                    compacted = int(kernel32.HeapCompact(ctypes.c_void_p(heap), 0) or 0)
                    actions.append({"name": "kernel32.HeapCompact", "ok": True, "bytes": compacted})
            except Exception as exc:
                actions.append({"name": "kernel32.HeapCompact", "ok": False, "error": str(exc)})
            ok = bool(psapi.EmptyWorkingSet(ctypes.c_void_p(handle)))
            actions.append({"name": "psapi.EmptyWorkingSet", "ok": ok, "winerr": 0 if ok else ctypes.get_last_error()})
            report["ok"] = any(bool(item.get("ok")) for item in actions if isinstance(item, dict))
            return report
        if sys.platform.startswith("linux"):
            import ctypes  # type: ignore

            report["attempted"] = True
            report["method"] = "libc.malloc_trim(0)"
            libc = ctypes.CDLL("libc.so.6")
            report["ok"] = bool(libc.malloc_trim(0))
            return report
    except Exception as exc:
        report["error"] = str(exc)
    return report


def accelerator_cleanup() -> None:
    """Best-effort Python + accelerator/native cache cleanup usable by any model node."""

    try:
        gc.collect()
    except Exception:
        pass
    try:
        import torch  # type: ignore

        if hasattr(torch, "xpu") and torch.xpu.is_available():
            try:
                torch.xpu.synchronize()
            except Exception:
                pass
            try:
                torch.xpu.empty_cache()
            except Exception:
                pass
        try:
            if hasattr(torch._C, "_host_emptyCache"):
                torch._C._host_emptyCache()
        except Exception:
            pass
        if hasattr(torch, "cuda") and torch.cuda.is_available():
            try:
                torch.cuda.synchronize()
            except Exception:
                pass
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass
    except Exception:
        pass
    try:
        gc.collect()
    except Exception:
        pass
    try:
        process_memory_trim()
    except Exception:
        pass


def comfy_global_cleanup(*, unload_models: bool = True, soft_empty: bool = True) -> Dict[str, Any]:
    """Best-effort ComfyUI global model-management cleanup.

    Comfy keeps its own process-global registry of loaded ModelPatcher objects
    in ``comfy.model_management.current_loaded_models``.  Releasing our per-run
    artifacts and calling ``torch.empty_cache`` is not enough if that registry
    still references patchers/GGUF tensors.  This mirrors Comfy's free-memory
    queue behavior: unload all known models, run GC, then soft-empty device
    caches.
    """

    report: Dict[str, Any] = {
        "attempted": False,
        "loaded_before": None,
        "loaded_after": None,
        "unload_called": False,
        "soft_empty_called": False,
        "errors": [],
    }
    try:
        from pathlib import Path
        import sys

        comfy_root = Path(__file__).resolve().parents[5] / "vendor" / "ComfyUI"
        if comfy_root.is_dir():
            text = str(comfy_root)
            if text not in sys.path:
                sys.path.insert(0, text)
        import comfy.model_management as model_management  # type: ignore

        report["attempted"] = True
        try:
            loaded = getattr(model_management, "current_loaded_models", None)
            if isinstance(loaded, list):
                report["loaded_before"] = len(loaded)
        except Exception as exc:
            report["errors"].append(f"loaded_before: {exc}")
        if unload_models and hasattr(model_management, "unload_all_models"):
            try:
                model_management.unload_all_models()
                report["unload_called"] = True
            except Exception as exc:
                report["errors"].append(f"unload_all_models: {exc}")
        try:
            gc.collect()
        except Exception:
            pass
        if soft_empty and hasattr(model_management, "soft_empty_cache"):
            try:
                try:
                    model_management.soft_empty_cache(force=True)
                except TypeError:
                    model_management.soft_empty_cache()
                report["soft_empty_called"] = True
            except Exception as exc:
                report["errors"].append(f"soft_empty_cache: {exc}")
        try:
            loaded = getattr(model_management, "current_loaded_models", None)
            if isinstance(loaded, list):
                report["loaded_after"] = len(loaded)
        except Exception as exc:
            report["errors"].append(f"loaded_after: {exc}")
    except Exception as exc:
        report["errors"].append(str(exc))
    accelerator_cleanup()
    return report


def resource_snapshot() -> Dict[str, Any]:
    """CPU/GPU memory snapshot for lifecycle diagnostics."""

    out: Dict[str, Any] = {"pid": os.getpid(), "ts_ms": int(time.time() * 1000)}
    try:
        import psutil  # type: ignore

        proc = psutil.Process(os.getpid())
        mem = proc.memory_info()
        out["process_rss_mb"] = round(float(getattr(mem, "rss", 0) or 0) / 1024 / 1024, 1)
        out["process_private_mb"] = round(float(getattr(mem, "private", getattr(mem, "vms", 0)) or 0) / 1024 / 1024, 1)
        vm = psutil.virtual_memory()
        out["system_used_mb"] = round(float(getattr(vm, "used", 0) or 0) / 1024 / 1024, 1)
        out["system_available_mb"] = round(float(getattr(vm, "available", 0) or 0) / 1024 / 1024, 1)
        out["system_used_pct"] = round(float(getattr(vm, "percent", 0.0) or 0.0), 1)
    except Exception as exc:
        out["psutil_error"] = str(exc)
    try:
        import torch  # type: ignore

        if hasattr(torch, "xpu") and torch.xpu.is_available():
            out["xpu_available"] = True
            try:
                out["xpu_allocated_mb"] = round(float(torch.xpu.memory_allocated()) / 1024 / 1024, 1)
                out["xpu_reserved_mb"] = round(float(torch.xpu.memory_reserved()) / 1024 / 1024, 1)
            except Exception as exc:
                out["xpu_memory_error"] = str(exc)
            try:
                free, total = torch.xpu.mem_get_info()
                out["xpu_free_mb"] = round(float(free) / 1024 / 1024, 1)
                out["xpu_total_mb"] = round(float(total) / 1024 / 1024, 1)
            except Exception as exc:
                out["xpu_mem_get_info_error"] = str(exc)
        else:
            out["xpu_available"] = False
        if hasattr(torch, "cuda") and torch.cuda.is_available():
            out["cuda_available"] = True
            try:
                out["cuda_allocated_mb"] = round(float(torch.cuda.memory_allocated()) / 1024 / 1024, 1)
                out["cuda_reserved_mb"] = round(float(torch.cuda.memory_reserved()) / 1024 / 1024, 1)
            except Exception as exc:
                out["cuda_memory_error"] = str(exc)
        else:
            out["cuda_available"] = False
    except Exception as exc:
        out["torch_error"] = str(exc)
    return out


@dataclass
class CachedResource:
    value: Any
    family: str
    role: str
    key: Tuple[Hashable, ...]
    mode: str
    created_ts: float
    last_used_ts: float
    metadata: Dict[str, Any]


@dataclass
class ManagedResource:
    value: Any
    family: str
    role: str
    key: Tuple[Hashable, ...]
    lifecycle: str
    created_ts: float
    metadata: Dict[str, Any]
    release_fn: Callable[[Any], None] | None = None


class ModelLifecycleManager:
    """Reusable lifecycle manager for graph model nodes.

    This intentionally does not know about Wan, LTX, Flux, etc.  Family-specific
    nodes provide load/encode/sample/decode code; this manager standardizes:
    resource cache keys, CPU/VRAM/off residency, Comfy ModelPatcher unloads,
    diagnostics, and accelerator cleanup.
    """

    _caches: Dict[Tuple[str, str, Tuple[Hashable, ...]], CachedResource] = {}
    _resources: Dict[Tuple[str, str, Tuple[Hashable, ...]], ManagedResource] = {}

    @classmethod
    def purge_global_resources(
        cls,
        *,
        family: str | None = None,
        model_management: Any | None = None,
        diagnostics: list[Any] | None = None,
    ) -> Dict[str, Any]:
        """Drop class-level lifecycle caches/resources for completed workflows."""

        prefix = str(family or "").strip()
        cache_items = [
            (key, item)
            for key, item in list(cls._caches.items())
            if not prefix or str(key[0]) == prefix
        ]
        resource_items = [
            (key, item)
            for key, item in list(cls._resources.items())
            if not prefix or str(key[0]) == prefix
        ]
        mgr = cls(family=prefix or "global", diagnostics=diagnostics if diagnostics is not None else [])
        released_values = 0
        custom_released = 0
        errors: list[str] = []
        for key, item in cache_items:
            try:
                mgr.unload_model_object(item.value, model_management=model_management, reason=f"global_cache_purge.{item.role}", unload_all=True)
                released_values += 1
            except Exception as exc:
                errors.append(f"cache {key}: {exc}")
            finally:
                cls._caches.pop(key, None)
        for key, item in resource_items:
            try:
                if item.release_fn is not None:
                    item.release_fn(item.value)
                    custom_released += 1
                else:
                    mgr.unload_model_object(item.value, model_management=model_management, reason=f"global_resource_purge.{item.role}", unload_all=True)
                released_values += 1
            except Exception as exc:
                errors.append(f"resource {key}: {exc}")
            finally:
                cls._resources.pop(key, None)
        accelerator_cleanup()
        return {
            "family": prefix or None,
            "cache_entries": len(cache_items),
            "resource_entries": len(resource_items),
            "released_values": released_values,
            "custom_released": custom_released,
            "remaining_cache_entries": len(cls._caches),
            "remaining_resource_entries": len(cls._resources),
            "errors": errors[:10],
        }

    def __init__(self, *, family: str, diagnostics: list[Any] | None = None, snapshot_fn: Callable[[], Dict[str, Any]] | None = None):
        self.family = str(family or "generic")
        self.diagnostics = diagnostics if diagnostics is not None else []
        self.snapshot_fn = snapshot_fn or resource_snapshot

    def snapshot(self, node: str, label: str, message: str = "", **extra: Any) -> Dict[str, Any]:
        row: Dict[str, Any] = {
            "node": node,
            "label": label,
            "message": message or f"resource snapshot: {label}",
            "resource_snapshot": self.snapshot_fn(),
        }
        row.update(extra)
        self.diagnostics.append(row)
        return row

    def cache_mode(self, settings: Dict[str, Any] | None, *, setting_key: str, legacy_bool_keys: tuple[str, ...] = (), default: str = "off") -> str:
        return prompt_cache_mode(settings, key=setting_key, legacy_bool_keys=legacy_bool_keys, default=default)

    def lifecycle_policy(self, settings: Dict[str, Any] | None, *, key: str = "lifecycle", default: str = "lazy_unload") -> str:
        raw = str((settings or {}).get(key) or (settings or {}).get("workflow_node_lifecycle_policy") or default).strip().lower()
        aliases = {
            "": default,
            "lazy": "lazy_unload",
            "unload": "lazy_unload",
            "off": "lazy_unload",
            "keep": "lazy_persist",
            "cache": "lazy_persist",
            "persist": "persist",
            "preload": "preload_persist",
        }
        raw = aliases.get(raw, raw)
        if raw in {"lazy_unload", "lazy_persist", "preload_persist", "persist", "terminal"}:
            return raw
        return default

    @contextmanager
    def node_scope(self, node: str, *, role: str = "", metadata: Dict[str, Any] | None = None) -> Iterator[None]:
        start = time.perf_counter()
        self.snapshot(node, f"{node}:before", f"{self.family}: enter node {node}", role=role, metadata=dict(metadata or {}))
        try:
            yield
        finally:
            self.snapshot(node, f"{node}:after", f"{self.family}: exit node {node}", role=role, elapsed_s=round(time.perf_counter() - start, 3))

    def register_resource(
        self,
        role: str,
        key: Tuple[Hashable, ...],
        value: Any,
        *,
        lifecycle: str = "lazy_unload",
        metadata: Dict[str, Any] | None = None,
        release_fn: Callable[[Any], None] | None = None,
    ) -> ManagedResource:
        resource = ManagedResource(
            value=value,
            family=self.family,
            role=role,
            key=key,
            lifecycle=lifecycle,
            created_ts=time.time(),
            metadata=dict(metadata or {}),
            release_fn=release_fn,
        )
        self._resources[(self.family, role, key)] = resource
        self.diagnostics.append(f"{self.family}: registered {role} resource lifecycle={lifecycle}")
        return resource

    def load_or_reuse_workflow_resource(
        self,
        resources: Dict[str, Any],
        resource_key: str,
        *,
        role: str,
        loader: Callable[[], Any],
        node: str = "model_node",
        lifecycle: str = "lazy_unload",
        metadata: Dict[str, Any] | None = None,
    ) -> tuple[Any, bool, float]:
        """Return an existing per-run resource or load/register a new one.

        This is the duplicate-resource guard for graph execution.  It prevents a
        node from reloading the same GGUF/VAE/LoRA-bearing object more than once
        inside the same workflow run when the resource key is deterministic.
        """

        start = time.perf_counter()
        if resource_key in resources and resources.get(resource_key) is not None:
            elapsed = time.perf_counter() - start
            self.diagnostics.append(
                {
                    "node": node,
                    "label": f"{node}:resource_reuse",
                    "message": f"{self.family}: reused existing {role} resource",
                    "resource_key": resource_key,
                    "elapsed_s": round(elapsed, 3),
                    "resource_snapshot": self.snapshot_fn(),
                }
            )
            return resources[resource_key], True, elapsed
        value = loader()
        resources[resource_key] = value
        self.register_resource(
            role,
            (resource_key,),
            value,
            lifecycle=lifecycle,
            metadata={"resource_key": resource_key, **dict(metadata or {})},
        )
        elapsed = time.perf_counter() - start
        self.diagnostics.append(
            {
                "node": node,
                "label": f"{node}:resource_loaded",
                "message": f"{self.family}: loaded {role} resource",
                "resource_key": resource_key,
                "elapsed_s": round(elapsed, 3),
                "resource_snapshot": self.snapshot_fn(),
            }
        )
        return value, False, elapsed

    def get_resource(self, role: str, key: Tuple[Hashable, ...]) -> ManagedResource | None:
        return self._resources.get((self.family, role, key))

    def release_resource(
        self,
        role: str,
        key: Tuple[Hashable, ...],
        *,
        model_management: Any | None = None,
        cleanup: bool = True,
        reason: str = "release",
    ) -> bool:
        resource = self._resources.pop((self.family, role, key), None)
        if resource is None:
            return False
        if resource.release_fn is not None:
            try:
                resource.release_fn(resource.value)
                self.diagnostics.append(f"{self.family}: custom released {role} resource ({reason})")
            except Exception as exc:
                self.diagnostics.append(f"{self.family}: warning during custom release for {role} ({reason}): {exc}")
        else:
            self.unload_model_object(resource.value, model_management=model_management, reason=f"{role}_{reason}", unload_all=False)
        if cleanup:
            accelerator_cleanup()
        self.diagnostics.append(f"{self.family}: released {role} resource ({reason})")
        return True

    def cache_get(self, role: str, key: Tuple[Hashable, ...], mode: str) -> CachedResource | None:
        if mode not in {"cpu", "vram"}:
            return None
        item = self._caches.get((self.family, role, key))
        if item is not None:
            item.last_used_ts = time.time()
        return item

    def cache_put(self, role: str, key: Tuple[Hashable, ...], value: Any, *, mode: str, metadata: Dict[str, Any] | None = None) -> CachedResource:
        item = CachedResource(
            value=value,
            family=self.family,
            role=role,
            key=key,
            mode=mode,
            created_ts=time.time(),
            last_used_ts=time.time(),
            metadata=dict(metadata or {}),
        )
        self._caches[(self.family, role, key)] = item
        return item

    def cache_drop(self, role: str, key: Tuple[Hashable, ...], *, model_management: Any | None = None, reason: str = "drop") -> bool:
        item = self._caches.pop((self.family, role, key), None)
        if item is None:
            return False
        self.unload_model_object(item.value, model_management=model_management, reason=f"cache_{reason}", unload_all=True)
        accelerator_cleanup()
        self.diagnostics.append(f"{self.family}: dropped cached {role} resource ({reason})")
        return True

    def unload_model_object(self, value: Any, *, model_management: Any | None = None, reason: str = "unload", unload_all: bool = False) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            for key, item in list(value.items()):
                if str(key).startswith("__"):
                    continue
                self.unload_model_object(item, model_management=model_management, reason=f"{reason}.{key}", unload_all=False)
            if unload_all and model_management is not None:
                try:
                    model_management.unload_all_models()
                except Exception as exc:
                    self.diagnostics.append(f"{self.family}: warning while unloading Comfy models for {reason}: {exc}")
            return
        if isinstance(value, (list, tuple)):
            for idx, item in enumerate(value):
                self.unload_model_object(item, model_management=model_management, reason=f"{reason}[{idx}]", unload_all=False)
            return
        _dispose_owned_model_object(value, self.diagnostics, reason=reason)
        if model_management is not None:
            try:
                patcher = getattr(value, "patcher", None)
                if patcher is not None:
                    try:
                        model_management.unload_model_and_clones(patcher, unload_additional_models=True, all_devices=True)
                    except TypeError:
                        model_management.unload_model_and_clones(patcher)
                    self.diagnostics.append(f"{self.family}: unloaded patcher for {reason}")
            except Exception as exc:
                self.diagnostics.append(f"{self.family}: warning while unloading patcher for {reason}: {exc}")
            if unload_all:
                try:
                    model_management.unload_all_models()
                except Exception as exc:
                    self.diagnostics.append(f"{self.family}: warning while unloading Comfy models for {reason}: {exc}")

    def finish_cached_resource(
        self,
        role: str,
        key: Tuple[Hashable, ...],
        value: Any,
        *,
        mode: str,
        model_management: Any | None = None,
        node: str = "model_node",
    ) -> None:
        if mode == "vram" and self.cache_get(role, key, mode) is not None:
            self.diagnostics.append(f"{self.family}: kept {role} cached in VRAM/main device")
            return
        if mode == "cpu" and self.cache_get(role, key, mode) is not None:
            self.unload_model_object(value, model_management=model_management, reason=f"{role}_cpu_cache", unload_all=False)
            accelerator_cleanup()
            self.diagnostics.append(f"{self.family}: kept {role} cached in CPU/offload state")
            return
        self.unload_model_object(value, model_management=model_management, reason=f"{role}_off", unload_all=True)
        accelerator_cleanup()
        self.diagnostics.append(f"{self.family}: released {role} after node {node}")
