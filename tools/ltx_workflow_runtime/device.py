from __future__ import annotations

import gc
from typing import Any, Optional


def norm(text: Any) -> str:
    return str(text or "").strip().lower()


def resolve_device(torch_module: Any, explicit: str = "") -> str:
    from runtime_cuda import preferred_torch_device

    device = str(explicit or "").strip().lower()
    if device and device != "auto":
        if device in ("cuda", "xpu", "mps"):
            return f"{device}:0"
        return device
    auto = preferred_torch_device(torch_module)
    if auto in ("cuda", "xpu", "mps"):
        return f"{auto}:0"
    return auto


def resolve_dtype(torch_module: Any, device: str, explicit: str = "") -> Any:
    text = norm(explicit)
    if text in ("fp16", "float16"):
        out = torch_module.float16
    elif text in ("bf16", "bfloat16"):
        out = torch_module.bfloat16
    elif text in ("fp32", "float32"):
        out = torch_module.float32
    else:
        out = torch_module.float16 if not str(device).startswith("cpu") else torch_module.float32
    if str(device).startswith("cpu") and out in (torch_module.float16, torch_module.bfloat16):
        return torch_module.float32
    return out


def resolve_text_encoding_device(torch_module: Any, runtime_device: str, explicit: str = "") -> str:
    text = norm(explicit)
    runtime_text = norm(runtime_device)
    if text in ("gpu", "runtime", "main"):
        if runtime_text.startswith("cpu"):
            return resolve_device(torch_module, "auto")
        return runtime_device
    if "gpu" in text and text not in ("cpu",):
        if runtime_text.startswith("cpu"):
            return resolve_device(torch_module, "auto")
        return runtime_device
    if text.startswith(("xpu", "cuda", "mps")):
        return text
    if runtime_text and text in ("video", "video_device", "main_video_device", runtime_text):
        return runtime_device
    if text in ("cpu", ""):
        return "cpu"
    resolved = resolve_device(torch_module, text)
    if not resolved or str(resolved).startswith("cpu"):
        if any(token in text for token in ("gpu", "xpu", "cuda", "mps", "intel")):
            return runtime_device
    return resolved or "cpu"


def resolve_text_encoding_dtype(torch_module: Any, device: str, runtime_dtype: Any) -> Any:
    if str(device).startswith("cpu"):
        return torch_module.float32
    return runtime_dtype


def cleanup_runtime_memory(torch_module: Any, device: Any, diagnostics: Optional[list[str]] = None, *, reason: str = "") -> None:
    label = str(reason or "cleanup").strip()
    try:
        gc.collect()
    except Exception:
        pass
    try:
        resolved = torch_module.device(device) if not isinstance(device, torch_module.device) else device
    except Exception:
        resolved = device
    device_type = str(getattr(resolved, "type", "") or resolved).split(":", 1)[0].lower()
    try:
        if device_type == "cuda" and hasattr(torch_module, "cuda") and torch_module.cuda.is_available():
            torch_module.cuda.empty_cache()
            torch_module.cuda.synchronize(resolved)
        elif device_type == "xpu":
            xpu_backend = getattr(torch_module, "xpu", None)
            if xpu_backend is not None and xpu_backend.is_available():
                if hasattr(xpu_backend, "empty_cache"):
                    xpu_backend.empty_cache()
                try:
                    xpu_backend.synchronize(resolved)
                except TypeError:
                    xpu_backend.synchronize()
        elif device_type == "mps":
            mps_backend = getattr(torch_module, "mps", None)
            if mps_backend is not None and hasattr(torch_module.backends, "mps") and torch_module.backends.mps.is_available():
                mps_backend.empty_cache()
                mps_backend.synchronize()
    except Exception as exc:
        if isinstance(diagnostics, list):
            diagnostics.append(f"runtime_cleanup: {label} accelerator cleanup warning: {exc}")
    try:
        if hasattr(torch_module._C, "_host_emptyCache"):
            torch_module._C._host_emptyCache()
    except Exception as exc:
        if isinstance(diagnostics, list):
            diagnostics.append(f"runtime_cleanup: {label} host cache cleanup warning: {exc}")
    if isinstance(diagnostics, list):
        diagnostics.append(f"runtime_cleanup: {label} complete on {resolved}")
