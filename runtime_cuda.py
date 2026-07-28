from __future__ import annotations

import os


def _runtime_name() -> str:
    return str(os.environ.get("LLMLOADER2_RUNTIME") or "").strip().lower()


def cuda_runtime_enabled() -> bool:
    runtime = _runtime_name()
    return runtime in ("nvidia", "cuda")


def intel_runtime_enabled() -> bool:
    runtime = _runtime_name()
    return runtime in ("intel", "xpu", "sycl")


def cuda_available_safe(torch_module) -> bool:
    if not cuda_runtime_enabled():
        return False
    try:
        return bool(torch_module.cuda.is_available())
    except Exception:
        return False


def xpu_available_safe(torch_module) -> bool:
    if not intel_runtime_enabled():
        return False
    try:
        xpu_mod = getattr(torch_module, "xpu", None)
        return bool(xpu_mod is not None and xpu_mod.is_available())
    except Exception:
        return False


def mps_available_safe(torch_module) -> bool:
    try:
        backends = getattr(torch_module, "backends", None)
        mps_mod = getattr(backends, "mps", None)
        return bool(mps_mod is not None and mps_mod.is_available())
    except Exception:
        return False


def preferred_torch_device(torch_module, explicit: str | None = None) -> str:
    device = str(explicit or "").strip().lower()
    if device and device != "auto":
        return device
    if cuda_available_safe(torch_module):
        return "cuda"
    if xpu_available_safe(torch_module):
        return "xpu"
    if mps_available_safe(torch_module):
        return "mps"
    return "cpu"


def empty_accelerator_cache(torch_module, device: str | None = None) -> None:
    dev = str(device or preferred_torch_device(torch_module)).strip().lower()
    try:
        if dev == "cuda" and cuda_available_safe(torch_module):
            torch_module.cuda.empty_cache()
            if hasattr(torch_module.cuda, "ipc_collect"):
                torch_module.cuda.ipc_collect()
            if hasattr(torch_module.cuda, "synchronize"):
                torch_module.cuda.synchronize()
            return
        if dev == "xpu" and xpu_available_safe(torch_module):
            xpu_mod = getattr(torch_module, "xpu", None)
            if xpu_mod is not None and hasattr(xpu_mod, "empty_cache"):
                xpu_mod.empty_cache()
            if xpu_mod is not None and hasattr(xpu_mod, "synchronize"):
                xpu_mod.synchronize()
    except Exception:
        return
