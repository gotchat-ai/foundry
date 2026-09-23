from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict


def _default_vendor_root() -> Path:
    return Path(__file__).resolve().parents[5] / "vendor" / "ComfyUI-GGUF"


def _default_comfyui_root() -> Path:
    return Path(__file__).resolve().parents[5] / "vendor" / "ComfyUI"


def _maybe_add_comfyui_runtime_path(comfyui_root: str = "") -> Dict[str, Any]:
    root_text = str(comfyui_root or "").strip()
    root = Path(root_text).expanduser().resolve() if root_text else _default_comfyui_root()
    out = {"comfyui_root": str(root), "comfyui_root_exists": root.is_dir(), "added": False}
    if root.is_dir() and str(root) not in sys.path:
        sys.path.insert(0, str(root))
        out["added"] = True
    return out


def probe(vendor_root: str = "", comfyui_root: str = "") -> Dict[str, Any]:
    root = Path(str(vendor_root or "")).expanduser() if vendor_root else _default_vendor_root()
    root = root.resolve()
    comfyui_runtime = _maybe_add_comfyui_runtime_path(comfyui_root)
    out: Dict[str, Any] = {
        "available": False,
        "vendor_root": str(root),
        **comfyui_runtime,
        "loader": "loader.gguf_sd_loader",
        "ops": "ops.GGMLOps",
        "patcher": "nodes.GGUFModelPatcher",
        "reason": "",
    }
    if not root.is_dir():
        out["reason"] = "vendor_root_missing"
        return out
    try:
        import torch  # noqa: F401
        import gguf  # noqa: F401
    except Exception as exc:
        out["reason"] = f"missing_runtime_dependency:{type(exc).__name__}:{exc}"
        return out
    # ComfyUI-GGUF's quant-aware modules depend on ComfyUI's comfy.*, nodes, and
    # folder_paths modules. We only activate the embedded bridge when those are
    # importable, otherwise the workflow still keeps explicit node handles and
    # can use the checkpoint runner fallback.
    try:
        import comfy.ops  # noqa: F401
        import comfy.model_patcher  # noqa: F401
        import folder_paths  # noqa: F401
        import nodes  # noqa: F401
    except Exception as exc:
        out["reason"] = f"comfy_runtime_unavailable:{type(exc).__name__}:{exc}"
        return out
    try:
        package_name = "llmloader2_vendor_comfyui_gguf"
        init_file = root / "__init__.py"
        if package_name not in sys.modules:
            spec = importlib.util.spec_from_file_location(
                package_name,
                str(init_file),
                submodule_search_locations=[str(root)],
            )
            if spec is None or spec.loader is None:
                out["reason"] = "vendor_import_spec_failed"
                return out
            module = importlib.util.module_from_spec(spec)
            sys.modules[package_name] = module
            spec.loader.exec_module(module)
        loader_mod = __import__(f"{package_name}.loader", fromlist=["gguf_sd_loader"])
        ops_mod = __import__(f"{package_name}.ops", fromlist=["GGMLOps", "GGMLTensor"])
        nodes_mod = __import__(f"{package_name}.nodes", fromlist=["GGUFModelPatcher"])
        out.update({
            "available": True,
            "reason": "ok",
            "package": package_name,
            "has_gguf_sd_loader": hasattr(loader_mod, "gguf_sd_loader"),
            "has_ggml_ops": hasattr(ops_mod, "GGMLOps"),
            "has_ggml_tensor": hasattr(ops_mod, "GGMLTensor"),
            "has_model_patcher": hasattr(nodes_mod, "GGUFModelPatcher"),
        })
        return out
    except Exception as exc:
        out["reason"] = f"vendor_import_failed:{type(exc).__name__}:{exc}"
        return out


def load_state_dict_handle(path: str, *, vendor_root: str = "", comfyui_root: str = "", is_text_model: bool = False) -> Dict[str, Any]:
    status = probe(vendor_root, comfyui_root=comfyui_root)
    if not status.get("available"):
        return {
            "ok": False,
            "bridge": status,
            "state_dict": None,
            "extra": {},
        }
    package = str(status.get("package") or "llmloader2_vendor_comfyui_gguf")
    loader_mod = __import__(f"{package}.loader", fromlist=["gguf_sd_loader"])
    state_dict, extra = loader_mod.gguf_sd_loader(path, is_text_model=is_text_model)
    return {
        "ok": True,
        "bridge": status,
        "state_dict": state_dict,
        "extra": extra if isinstance(extra, dict) else {},
        "tensor_count": len(state_dict) if isinstance(state_dict, dict) else 0,
    }
