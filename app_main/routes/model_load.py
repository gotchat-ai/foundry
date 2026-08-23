from typing import Any, Callable
from uuid import uuid4

from fastapi import HTTPException

from model_loader_gguf import GGUFChatModel
from model_loader_update import HFChatModelUpdate


class ModelLoadRoutes:
    """Implementation for main model load routes and async load jobs."""

    def __init__(
        self,
        *,
        app_getter: Callable[[], Any],
        jobs_getter: Callable[[], dict[str, dict[str, Any]]],
        executor_getter: Callable[[], Any],
        settings_getter: Callable[[], dict[str, Any]],
        gguf_path_resolver: Callable[[str], str],
        gguf_id_detector: Callable[[str], bool],
        model_getter: Callable[[], Any],
        model_setter: Callable[[Any], None],
    ) -> None:
        self._app_getter = app_getter
        self._jobs_getter = jobs_getter
        self._executor_getter = executor_getter
        self._settings_getter = settings_getter
        self._gguf_path_resolver = gguf_path_resolver
        self._gguf_id_detector = gguf_id_detector
        self._model_getter = model_getter
        self._model_setter = model_setter

    def _build_model(self, req: Any, *, log_prefix: str) -> tuple[Any, str]:
        settings = self._settings_getter() or {}
        use_fa2 = settings.get("use_fa2", False)
        gpu_mem_fraction = None
        if req.gpu_vram_percent and req.gpu_vram_percent > 0:
            gpu_mem_fraction = float(req.gpu_vram_percent) / 100.0

        model_id = (req.model_id or "").strip()

        if self._gguf_id_detector(model_id):
            model_path = self._gguf_path_resolver(model_id)
            llama_n_ctx = int(settings.get("llama_n_ctx", 8192))
            default_layers = int(settings.get("llama_n_gpu_layers", 0))
            n_gpu_layers = req.gguf_n_gpu_layers if req.gguf_n_gpu_layers is not None else default_layers
            try:
                n_gpu_layers = int(n_gpu_layers)
            except Exception:
                n_gpu_layers = default_layers

            if log_prefix.endswith("load_async"):
                print("n_gpu_layers: ", n_gpu_layers)

            llama_seed = int(settings.get("llama_seed", 0))
            new_model = GGUFChatModel(
                model_path=model_path,
                n_ctx=llama_n_ctx,
                n_threads=None,
                n_gpu_layers=max(0, int(n_gpu_layers)),
                seed=llama_seed,
            )
            try:
                print(
                    f"[{log_prefix}] built GGUFChatModel path={model_path} "
                    f"n_gpu_layers={max(0, int(n_gpu_layers))}",
                    flush=True,
                )
            except Exception:
                pass
            return new_model, model_id

        new_model = HFChatModelUpdate(
            model_id=model_id,
            device=req.device or "auto",
            dtype=req.dtype or "auto",
            quant=req.quant or "none",
            trust_remote_code=bool(req.trust_remote_code),
            use_fa2=use_fa2,
            gpu_mem_fraction=gpu_mem_fraction,
        )
        return new_model, model_id

    def _install_model(self, new_model: Any) -> None:
        app = self._app_getter()
        try:
            setter = getattr(app.state, "set_model", None)
            if callable(setter):
                setter(new_model)
            else:
                self._model_setter(new_model)
        except Exception:
            self._model_setter(new_model)

    def model_load(self, req: Any) -> dict[str, Any]:
        try:
            new_model, model_id = self._build_model(req, log_prefix="/v1/models/load")
        except Exception as exc:
            raise HTTPException(400, f"failed to load model: {exc}") from exc

        self._install_model(new_model)
        model = self._model_getter()
        return {
            "ok": True,
            "model_id": getattr(model, "model_id", model_id),
            "alias": getattr(model, "model_id_alias", model_id),
            "device": getattr(model, "device", "cpu"),
        }

    def load_job(self, job_id: str, req: Any) -> None:
        jobs = self._jobs_getter()
        jobs[job_id] = {
            "status": "running",
            "model_id": req.model_id,
            "device": req.device or "auto",
            "quant": req.quant or "none",
            "error": None,
        }
        try:
            new_model, _model_id = self._build_model(req, log_prefix="/v1/models/load_async")
            self._install_model(new_model)
            jobs[job_id]["status"] = "done"
        except Exception as exc:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(exc)

    def model_load_async(
        self,
        req: Any,
        *,
        load_job: Callable[[str, Any], None] | None = None,
    ) -> dict[str, str]:
        job_id = str(uuid4())
        self._jobs_getter()[job_id] = {
            "status": "queued",
            "model_id": req.model_id,
            "device": req.device or "auto",
            "quant": req.quant or "none",
            "error": None,
        }
        job_fn = load_job or (lambda jid, request: self.load_job(jid, request))
        self._executor_getter().submit(job_fn, job_id, req)
        return {"job_id": job_id}
