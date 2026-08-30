import os
import time
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import HTTPException


_INVALID_HF_ID_VALUES = {"", "none", "null", "undefined", "nan"}


def _clean_hf_id(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in _INVALID_HF_ID_VALUES else text


class ModelManagementRoutes:
    """Implementation for model unload route/job helpers."""

    def __init__(
        self,
        *,
        jobs_getter: Callable[[], dict[str, dict[str, Any]]],
        executor_getter: Callable[[], Any],
        main_model_getter: Callable[[], Any],
        main_model_setter: Callable[[Any], None],
        thinking_model_getter: Callable[[], Any],
        thinking_model_setter: Callable[[Any], None],
        thinking_pool_getter: Callable[[], dict[str, Any]],
        allow_cuda_probe: Callable[[], bool],
        settings_getter: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._jobs_getter = jobs_getter
        self._executor_getter = executor_getter
        self._main_model_getter = main_model_getter
        self._main_model_setter = main_model_setter
        self._thinking_model_getter = thinking_model_getter
        self._thinking_model_setter = thinking_model_setter
        self._thinking_pool_getter = thinking_pool_getter
        self._allow_cuda_probe = allow_cuda_probe
        self._settings_getter = settings_getter or (lambda: {})

    def dispose_model_if_possible(self, model_obj: Any) -> None:
        """
        Best-effort disposal of a model object.

        Tries common shutdown/close methods and then clears CUDA cache if available.
        """
        if model_obj is None:
            return

        for name in ("close", "shutdown", "dispose"):
            fn = getattr(model_obj, name, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass

        try:
            import torch

            if self._allow_cuda_probe() and torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def unload_job(
        self,
        job_id: str,
        req: Any,
        *,
        dispose_model: Callable[[Any], None] | None = None,
    ) -> None:
        jobs = self._jobs_getter()
        jobs[job_id] = {"status": "running", "target": req.target, "unloaded": [], "error": None}
        unloaded: list[str] = []
        dispose_model = dispose_model or self.dispose_model_if_possible

        try:
            tgt = (req.target or "all").lower()

            if tgt in ("main", "all") and self._main_model_getter() is not None:
                dispose_model(self._main_model_getter())
                self._main_model_setter(None)
                unloaded.append("main")

            if tgt in ("thinking", "all"):
                if self._thinking_model_getter() is not None:
                    dispose_model(self._thinking_model_getter())
                    self._thinking_model_setter(None)
                    unloaded.append("thinking")

                try:
                    thinking_pool = self._thinking_pool_getter()
                    for key, tm in list(thinking_pool.items()):
                        dispose_model(tm)
                        thinking_pool.pop(key, None)
                except Exception:
                    pass

            jobs[job_id].update({"status": "done", "unloaded": unloaded})
        except Exception as exc:
            jobs[job_id].update({"status": "error", "error": str(exc), "unloaded": unloaded})

    def model_unload_async(
        self,
        req: Any,
        *,
        unload_job: Callable[[str, Any], None] | None = None,
    ) -> dict[str, str]:
        job_id = str(uuid4())
        self._jobs_getter()[job_id] = {
            "status": "queued",
            "target": req.target,
            "unloaded": [],
            "error": None,
        }
        job_fn = unload_job or (lambda jid, request: self.unload_job(jid, request))
        self._executor_getter().submit(job_fn, job_id, req)
        return {"job_id": job_id}

    def openai_models(
        self,
        *,
        default_model_id: str | None = None,
        created_ts: int | None = None,
    ) -> dict[str, Any]:
        model_obj = self._main_model_getter()
        settings = self._settings_getter() or {}
        model_id = (
            getattr(model_obj, "model_id_alias", None)
            or getattr(model_obj, "model_id", None)
            or default_model_id
            or settings.get("model_id")
            or "local-model"
        )
        return {
            "object": "list",
            "data": [
                {
                    "id": model_id,
                    "object": "model",
                    "created": int(created_ts or time.time()),
                    "owned_by": "local",
                }
            ],
        }

    def list_models(self, depth: int = 3) -> dict[str, Any]:
        settings = self._settings_getter() or {}
        models_dir = settings.get("models_dir") or settings.get("hf_cache_dir") or "./models"
        root = Path(models_dir)
        results: list[dict[str, Any]] = []
        if not root.exists():
            return {"models_dir": str(root), "models": results}

        def is_hf_local_model(path: Path) -> bool:
            if not path.is_dir():
                return False
            if not (path / "config.json").exists():
                return False
            needles = [
                "tokenizer.json",
                "tokenizer.model",
                "model.safetensors",
                "model.safetensors.index.json",
            ]
            return any((path / needle).exists() for needle in needles)

        def dir_size(path: Path) -> int:
            total = 0
            for r, _ds, fs in os.walk(path):
                for f in fs:
                    try:
                        total += (Path(r) / f).stat().st_size
                    except Exception:
                        pass
            return total

        for r, _ds, _fs in os.walk(root):
            rel_depth = len(Path(r).relative_to(root).parts)
            if rel_depth > depth:
                continue
            path = Path(r)
            if is_hf_local_model(path):
                results.append(
                    {
                        "kind": "hf-local",
                        "label": path.name,
                        "path": str(path),
                        "size": dir_size(path),
                    }
                )
        results.sort(key=lambda x: (x["kind"], x["label"].lower()))
        return {"models_dir": str(root), "models": results}

    def model_download(
        self,
        req: Any,
        *,
        looks_like_gguf_id: Callable[[str], bool],
        resolve_gguf_path: Callable[[str], str],
        snapshot_download: Callable[..., str],
    ) -> dict[str, Any]:
        """
        Download a model without loading it.

        - For GGUF ids, resolve them to a local GGUF path.
        - For non-GGUF ids, keep the Hugging Face snapshot download flow.
        """
        model_id = _clean_hf_id(getattr(req, "model_id", ""))
        if not model_id:
            raise HTTPException(400, "model_id required")

        if looks_like_gguf_id(model_id):
            try:
                local_path = resolve_gguf_path(model_id)
                size_bytes = os.path.getsize(local_path)
            except Exception as exc:
                raise HTTPException(400, f"failed to download GGUF model: {exc}")

            return {
                "ok": True,
                "model_id": model_id,
                "path": local_path,
                "size_bytes": size_bytes,
                "type": "gguf",
            }

        try:
            local_path = snapshot_download(
                repo_id=model_id,
                revision=req.revision,
                allow_patterns=req.allow_patterns,
                ignore_patterns=req.ignore_patterns,
            )
            return {"ok": True, "model_id": model_id, "path": local_path}
        except Exception as exc:
            raise HTTPException(400, f"download failed: {exc}")

    def download_job(
        self,
        job_id: str,
        req_or_repo: Any,
        *,
        resolve_gguf_path: Callable[[str], str],
        safe_hf_download: Callable[..., Any],
        extra_kwargs: dict[str, Any] | None = None,
        job_update: Callable[..., None] | None = None,
        to_mapping: Callable[[Any], dict[str, Any]] | None = None,
        pick: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        import json
        import traceback

        def default_job_update(**kw: Any) -> None:
            try:
                jobs = self._jobs_getter()
                state = jobs.setdefault(job_id, {})
                if "status" in kw and "state" not in kw:
                    kw["state"] = kw["status"]
                state.update(kw)
                now = time.time()
                state["updated_at"] = now
                if state.get("state") == "running" and not state.get("started_at"):
                    state["started_at"] = now
                if state.get("state") in ("succeeded", "failed") and not state.get("finished_at"):
                    state["finished_at"] = now
            except Exception:
                pass

        def default_to_mapping(obj: Any) -> dict[str, Any]:
            if isinstance(obj, str):
                return {"repo_id": obj}
            if hasattr(obj, "model_dump"):
                try:
                    return obj.model_dump()
                except Exception:
                    pass
            if hasattr(obj, "dict"):
                try:
                    return obj.dict()
                except Exception:
                    pass
            if hasattr(obj, "__dict__"):
                try:
                    return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
                except Exception:
                    pass
            if isinstance(obj, dict):
                return obj
            return {}

        def default_pick(mapping: dict[str, Any], *names: str, default: Any = None) -> Any:
            for name in names:
                if name in mapping and mapping[name] is not None:
                    return mapping[name]
            return default

        job_update = job_update or default_job_update
        to_mapping = to_mapping or default_to_mapping
        pick = pick or default_pick

        req_map = to_mapping(req_or_repo)
        if extra_kwargs:
            req_map = {**req_map, **extra_kwargs}

        settings = self._settings_getter() or {}
        repo_id = _clean_hf_id(pick(req_map, "repo_id", "model_id", "model", "hf_repo", "model_repo"))
        revision = pick(req_map, "revision", "branch", default="main")
        cache_dir = pick(req_map, "cache_dir", "models_cache_dir", default=settings.get("hf_cache_dir"))
        local_only = bool(pick(req_map, "local_files_only", "localOnly", default=False))
        force = bool(pick(req_map, "force", "force_download", default=False))
        resume_dl = pick(req_map, "resume_download", default=None)
        if resume_dl is False:
            force = True
        etag_timeout = int(pick(req_map, "etag_timeout", default=settings.get("hf_etag_timeout", 15)) or 15)
        extra_files = pick(req_map, "extra_files", "hf_extra_files", default=settings.get("hf_extra_files") or []) or []

        if repo_id and isinstance(repo_id, str) and ".gguf" in repo_id.lower():
            try:
                job_update(
                    status="running",
                    progress=0,
                    stage="prepare",
                    message=f"Preparing GGUF download for {repo_id}",
                )
                local_path = resolve_gguf_path(repo_id)
                size_bytes = os.path.getsize(local_path)
                job_update(
                    status="succeeded",
                    progress=100,
                    stage="done",
                    message=f"Downloaded GGUF: {os.path.basename(local_path)}",
                    path=local_path,
                    size_bytes=size_bytes,
                )
                return {
                    "ok": True,
                    "downloaded": [local_path],
                    "skipped": [],
                    "errors": [],
                    "repo_id": repo_id,
                    "revision": revision,
                    "cache_dir": os.path.dirname(local_path),
                }
            except Exception as exc:
                tb = traceback.format_exc()
                job_update(
                    status="failed",
                    progress=0,
                    stage="exception",
                    message=f"GGUF download exception: {exc}",
                    traceback=tb,
                )
                return {"ok": False, "error": str(exc), "traceback": tb}

        if not repo_id:
            job_update(status="failed", progress=0, stage="error", message="repo_id/model_id missing")
            return {"ok": False, "error": "repo_id/model_id missing"}

        job_update(status="running", progress=0, stage="prepare", message=f"Preparing download for {repo_id}")

        required = ["config.json"]
        optional = [
            "generation_config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "tokenizer.model",
            "merges.txt",
            "vocab.json",
            "model.safetensors.index.json",
        ]
        for item in extra_files:
            if isinstance(item, str):
                optional.append(item)

        queue = [(f, True) for f in required] + [(f, False) for f in optional]
        completed = 0
        errors: list[dict[str, Any]] = []
        downloaded_paths: list[str] = []
        skipped_files: list[str] = []
        total_dynamic = len(queue)

        def set_progress(msg: str) -> None:
            pct = int((completed / max(1, total_dynamic)) * 100)
            job_update(progress=pct, message=msg, stage="download")

        try:
            while queue:
                filename, is_required = queue.pop(0)
                set_progress(f"Downloading {filename} ({completed + 1}/{total_dynamic})")
                res = safe_hf_download(
                    repo_id=repo_id,
                    filename=filename,
                    revision=revision,
                    cache_dir=cache_dir,
                    local_files_only=local_only,
                    force=force,
                    etag_timeout=etag_timeout,
                )
                if res.ok and res.path:
                    downloaded_paths.append(res.path)
                    if filename.endswith(".safetensors.index.json"):
                        try:
                            with open(res.path, "r", encoding="utf-8") as handle:
                                index = json.load(handle)
                            shards = sorted(set(index.get("weight_map", {}).values()))
                            for shard_name in shards:
                                if not any(shard_name == qf for qf, _ in queue):
                                    queue.append((shard_name, True))
                            total_dynamic = len(queue) + completed
                        except Exception as exc:
                            errors.append({"file": filename, "error": f"index-parse: {exc}"})
                elif res.ok and res.skipped:
                    skipped_files.append(filename)
                else:
                    errors.append({"file": filename, "error": res.error or "download failed"})
                    if is_required and filename != "model.safetensors":
                        job_update(status="failed", message=f"Failed: {filename}: {res.error}", stage="error")
                        return {
                            "ok": False,
                            "error": res.error or f"Failed to download {filename}",
                            "downloaded": downloaded_paths,
                            "skipped": skipped_files,
                            "errors": errors,
                        }
                completed += 1

            if not any(path.endswith(".safetensors") and not path.endswith(".index.json") for path in downloaded_paths):
                set_progress("Downloading model.safetensors (final stage)")
                res = safe_hf_download(
                    repo_id=repo_id,
                    filename="model.safetensors",
                    revision=revision,
                    cache_dir=cache_dir,
                    local_files_only=local_only,
                    force=force,
                    etag_timeout=etag_timeout,
                )
                completed += 1
                total_dynamic = max(total_dynamic, completed)
                if res.ok and res.path:
                    downloaded_paths.append(res.path)
                else:
                    errors.append({"file": "model.safetensors", "error": res.error or "missing"})

            ok = any(path.endswith(".safetensors") and not path.endswith(".index.json") for path in downloaded_paths)
            if not ok:
                errors.append({"file": "model", "error": "no weights found (neither shards nor model.safetensors)"})
            job_update(
                progress=100,
                status=("succeeded" if ok else "failed"),
                message=("Download complete" if ok else "Download incomplete — see errors"),
                stage="done",
            )
            return {
                "ok": ok,
                "downloaded": downloaded_paths,
                "skipped": skipped_files,
                "errors": errors,
                "repo_id": repo_id,
                "revision": revision,
                "cache_dir": cache_dir,
            }

        except Exception as exc:
            tb = traceback.format_exc()
            job_update(status="failed", progress=0, stage="exception", message=f"exception: {exc}", traceback=tb)
            return {"ok": False, "error": str(exc), "traceback": tb}

    def model_download_async(
        self,
        req: Any,
        *,
        download_job: Callable[[str, Any], dict[str, Any]] | None = None,
    ) -> dict[str, str]:
        job_id = str(uuid4())
        self._jobs_getter()[job_id] = {"status": "queued", "model_id": req.model_id, "path": None, "error": None}
        job_fn = download_job or (lambda jid, request: self.download_job(jid, request))
        self._executor_getter().submit(job_fn, job_id, req)
        return {"job_id": job_id}
