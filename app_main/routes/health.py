import os
from typing import Any, Callable


class HealthRoutes:
    """Implementation for health and system capability routes."""

    def __init__(
        self,
        *,
        model_getter: Callable[[], Any],
        thinking_model_getter: Callable[[], Any],
        backend_type_getter: Callable[[], str],
    ) -> None:
        self._model_getter = model_getter
        self._thinking_model_getter = thinking_model_getter
        self._backend_type_getter = backend_type_getter

    def health(self) -> dict[str, Any]:
        """Basic health probe with current model + device + backend info."""
        model = self._model_getter()
        thinking_model = self._thinking_model_getter()
        main_id = getattr(model, "model_id", None)
        main_dev = getattr(model, "device", None)
        thinking_id = getattr(thinking_model, "model_id", None)
        thinking_dev = getattr(thinking_model, "device", None)
        return {
            "status": "ok",
            "model_id": main_id,
            "device": main_dev,
            "backend_type": self._backend_type_getter(),
            "thinking_model_id": thinking_id,
            "thinking_device": thinking_dev,
        }

    def configured_runtime_mode(self) -> str:
        raw = str(os.environ.get("LLMLOADER2_RUNTIME") or "").strip().lower()
        if raw in ("nvidia", "cuda"):
            return "nvidia"
        if raw == "vulkan":
            return "vulkan"
        return "cpu"

    def allow_cuda_probe(self) -> bool:
        return self.configured_runtime_mode() == "nvidia"

    def system_capabilities(self) -> dict[str, Any]:
        import torch

        caps: dict[str, Any] = {}

        def supports(device: str, dtype_name: str) -> bool:
            try:
                dt_map = {"float16": torch.float16, "bfloat16": torch.bfloat16, "float32": torch.float32}
                dt = dt_map.get(dtype_name)
                if dt is None:
                    return False
                if device == "cpu":
                    torch.ones(1, dtype=dt)
                    return True
                if device == "cuda":
                    if not self.allow_cuda_probe():
                        return False
                    if not torch.cuda.is_available():
                        return False
                    torch.ones(1, dtype=dt, device="cuda")
                    return True
                if device == "mps":
                    ok = getattr(torch.backends, "mps", None)
                    if not ok or not torch.backends.mps.is_available():
                        return False
                    torch.ones(1, dtype=dt, device="mps")
                    return True
                return False
            except Exception:
                return False

        cpu_dtypes = [d for d in ["float32", "bfloat16", "float16"] if supports("cpu", d)]
        caps["cpu"] = {"available": True, "dtypes": cpu_dtypes}

        try:
            cuda_avail = self.allow_cuda_probe() and torch.cuda.is_available()
            cuda_count = torch.cuda.device_count() if cuda_avail else 0
            cuda_name = torch.cuda.get_device_name(0) if cuda_avail and cuda_count > 0 else None
        except Exception:
            cuda_avail, cuda_count, cuda_name = False, 0, None
        cuda_dtypes = [d for d in ["bfloat16", "float16", "float32"] if supports("cuda", d)] if cuda_avail else []
        caps["cuda"] = {"available": bool(cuda_avail), "count": int(cuda_count), "name": cuda_name, "dtypes": cuda_dtypes}

        try:
            mps_avail = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
        except Exception:
            mps_avail = False
        mps_dtypes = [d for d in ["float16", "float32"] if supports("mps", d)] if mps_avail else []
        caps["mps"] = {"available": bool(mps_avail), "dtypes": mps_dtypes}

        model = self._model_getter()
        curr_id = getattr(model, "model_id", None)
        curr_device = getattr(model, "device", None)
        return {
            "model_id": curr_id,
            "device_current": curr_device,
            "caps": caps,
        }

    def gpu_status(self) -> dict[str, Any]:
        """
        Return VRAM usage and configured caps for all CUDA GPUs.

        This intentionally preserves the original CUDA-only probe behavior.
        Non-CUDA backends return an empty GPU list.
        """
        import torch

        gpus: list[dict[str, Any]] = []

        cap_gib: float | None = None
        backend_label: str | None = None

        model = self._model_getter()
        if model is not None:
            cap_gib = getattr(model, "gpu_vram_cap_gib", None)
            backend_label = getattr(model, "backend", None) or model.__class__.__name__

        if self.allow_cuda_probe() and torch.cuda.is_available():
            num = torch.cuda.device_count()
            for idx in range(num):
                props = torch.cuda.get_device_properties(idx)
                total_gib = props.total_memory / (1024**3)
                used_bytes = torch.cuda.memory_allocated(idx)
                used_gib = used_bytes / (1024**3)

                gpus.append(
                    {
                        "index": idx,
                        "name": props.name,
                        "used_gib": round(float(used_gib), 2),
                        "total_gib": round(float(total_gib), 2),
                        "cap_gib": float(cap_gib) if cap_gib is not None else None,
                        "backend": backend_label if idx == 0 else None,
                    }
                )

        return {"gpus": gpus}
