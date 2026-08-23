import sys
import time
from pathlib import Path
from typing import Any, Callable

import requests
from fastapi import HTTPException, Request


class AiJobRoutes:
    """Read-only job and scheduler status route implementations."""

    def __init__(
        self,
        *,
        jobs_getter: Callable[[], dict[str, dict[str, Any]]],
        ai_jobs_registry_getter: Callable[[], Any],
        gen_scheduler_getter: Callable[[], Any],
        settings_getter: Callable[[], dict[str, Any]],
        active_model_getter: Callable[[], Any],
        slots_cache_getter: Callable[[], Any],
        slots_cache_setter: Callable[[dict[str, Any]], None],
        app_getter: Callable[[], Any],
        cancel_flags_getter: Callable[[], dict[str, bool]],
        cancelled_jobs_getter: Callable[[], Any],
        model_workflow_state_getter: Callable[[], Any],
        turn_bus_getter: Callable[[], Any],
    ) -> None:
        self._jobs_getter = jobs_getter
        self._ai_jobs_registry_getter = ai_jobs_registry_getter
        self._gen_scheduler_getter = gen_scheduler_getter
        self._settings_getter = settings_getter
        self._active_model_getter = active_model_getter
        self._slots_cache_getter = slots_cache_getter
        self._slots_cache_setter = slots_cache_setter
        self._app_getter = app_getter
        self._cancel_flags_getter = cancel_flags_getter
        self._cancelled_jobs_getter = cancelled_jobs_getter
        self._model_workflow_state_getter = model_workflow_state_getter
        self._turn_bus_getter = turn_bus_getter

    def job_status(self, job_id: str) -> dict[str, Any]:
        job = self._jobs_getter().get(job_id)
        if not job:
            return {"status": "not_found"}
        job.setdefault("status", job.get("state", "queued"))
        job.setdefault("state", job.get("status", "queued"))
        job.setdefault("progress", job.get("percent", 0))
        job.setdefault("message", "")
        job.setdefault("stage", job.get("phase", ""))
        job.setdefault("job_id", job_id)
        job.setdefault("queued_at", job.get("queued_at"))
        job.setdefault("started_at", job.get("started_at"))
        job.setdefault("finished_at", job.get("finished_at"))
        return job

    def ai_jobs_status(self, request: Request) -> dict[str, Any]:
        reg = self._ai_jobs_registry_getter()
        if not reg:
            return {"jobs": []}
        include_slots = (
            str(request.query_params.get("include_slots") or "").strip().lower()
            in ("1", "true", "yes", "on")
        )

        jobs = reg.snapshot()
        try:
            positions = self._gen_scheduler_getter().queue_positions()
        except Exception:
            positions = {}

        for job in jobs:
            job_id = str(job.get("job_id") or "")
            if job_id and job_id in positions:
                job["queue_pos"] = positions[job_id]
            elif job.get("status") == "running":
                job["queue_pos"] = 0

        jobs.sort(key=lambda j: j.get("created_ts", 0))

        settings = self._settings_getter() or {}
        scheduler = self._gen_scheduler_getter()
        scheduler_info: dict[str, Any] = {
            "workers": int(getattr(scheduler, "_num_workers", 0) or 0) or None,
            "default_per_model_parallel": int(settings.get("per_model_parallel", 1) or 1),
        }
        try:
            active = self._active_model_getter()
            backend_mode = str(getattr(active, "backend_mode", "") or "").strip().lower()
            scheduler_info["backend_mode"] = backend_mode or None
            if backend_mode == "llama_server":
                configured_parallel = int(settings.get("per_model_parallel", 1) or 1)
                llama_parallel = getattr(active, "parallel_slots", None)
                llama_parallel = int(llama_parallel or 0) if llama_parallel not in (None, "") else None
                cont_batching = getattr(active, "cont_batching", None)
                effective_parallel = configured_parallel
                if (configured_parallel <= 1) and (cont_batching is not False) and llama_parallel and llama_parallel > 0:
                    effective_parallel = max(1, llama_parallel)
                scheduler_info.update(
                    {
                        "llama_server_url": str(getattr(active, "base_url", "") or "").strip() or None,
                        "parallel_slots": llama_parallel,
                        "cont_batching": cont_batching,
                        "effective_per_model_parallel": effective_parallel,
                        "serialized_by_app_lock": not bool(
                            (cont_batching is not False) and (llama_parallel or 0) > 1
                        ),
                    }
                )
                base_url = str(getattr(active, "base_url", "") or "").strip()
                if include_slots and base_url:
                    try:
                        slots_cache = self._slots_cache_getter()
                        now_ts = time.time()
                        cached_slots = None
                        if isinstance(slots_cache, dict):
                            cache_url = str(slots_cache.get("base_url") or "").strip()
                            cache_ts = float(slots_cache.get("ts") or 0.0)
                            if cache_url == base_url and (now_ts - cache_ts) < 3.0:
                                cached_slots = slots_cache.get("slots")
                        if cached_slots is None:
                            resp = requests.get(f"{base_url}/slots", timeout=1.5)
                            if resp.ok:
                                cached_slots = resp.json()
                                self._slots_cache_setter(
                                    {
                                        "base_url": base_url,
                                        "ts": now_ts,
                                        "slots": cached_slots,
                                    }
                                )
                        if isinstance(cached_slots, list):
                            scheduler_info["slot_count"] = len(cached_slots)
                            scheduler_info["busy_slots"] = sum(
                                1 for s in cached_slots if isinstance(s, dict) and s.get("is_processing")
                            )
                    except Exception:
                        pass
        except Exception:
            pass
        return {"jobs": jobs, "scheduler": scheduler_info}

    def release_model_workflow_value(self, value: Any, seen: set[int] | None = None) -> None:
        if seen is None:
            seen = set()
        if value is None:
            return
        ident = id(value)
        if ident in seen:
            return
        seen.add(ident)
        try:
            tools_dir = str(Path(__file__).resolve().parents[2] / "tools")
            if tools_dir not in sys.path:
                sys.path.insert(0, tools_dir)
            from ltx_native_gguf_bridge import release_module_gguf_tensors

            release_module_gguf_tensors(value)
        except Exception:
            pass
        if isinstance(value, dict):
            for child in list(value.values()):
                self.release_model_workflow_value(child, seen)
            value.clear()
            return
        if isinstance(value, list):
            for child in list(value):
                self.release_model_workflow_value(child, seen)
            value.clear()
            return
        if isinstance(value, tuple):
            for child in value:
                self.release_model_workflow_value(child, seen)
            return
        for attr in ("_registry", "registry"):
            try:
                registry = getattr(value, attr)
            except Exception:
                continue
            try:
                registry.clear()
            except Exception:
                self.release_model_workflow_value(registry, seen)
        for attr in ("_state_dicts", "state_dict", "sd", "model", "module", "builder"):
            try:
                child = getattr(value, attr)
            except Exception:
                continue
            self.release_model_workflow_value(child, seen)
            try:
                setattr(value, attr, None)
            except Exception:
                pass

    def release_model_workflow_resources(
        self,
        job_id: str,
        release_value: Callable[[Any, set[int] | None], None] | None = None,
    ) -> list[str]:
        released: list[str] = []
        try:
            release_value = release_value or self.release_model_workflow_value
            mw_state = self._model_workflow_state_getter()
            if isinstance(mw_state, dict):
                runs = mw_state.get("runs")
                resources = mw_state.get("resources")
                if isinstance(runs, dict):
                    runs.pop(job_id, None)
                if isinstance(resources, dict):
                    prefix = f"{job_id}:"
                    for rk in list(resources.keys()):
                        if str(rk).startswith(prefix):
                            release_value(resources.get(rk), None)
                            resources.pop(rk, None)
                            released.append(str(rk))
        except Exception:
            released = []
        return released

    def cleanup_memory_caches(self) -> None:
        try:
            import gc

            gc.collect()
        except Exception:
            pass
        try:
            import torch

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

    def ai_jobs_cancel(
        self,
        payload: dict[str, Any],
        request: Request,
        *,
        release_value: Callable[[Any, set[int] | None], None] | None = None,
    ) -> dict[str, Any]:
        job_id = str((payload or {}).get("job_id") or "").strip()
        if not job_id:
            raise HTTPException(status_code=400, detail="job_id required")
        reg = self._ai_jobs_registry_getter()
        if not reg:
            raise HTTPException(status_code=404, detail="job not found")
        job = reg.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")

        owner_username = None
        owner_alias = (request.headers.get("X-User-Alias") or "").strip()
        app = self._app_getter()
        try:
            from plugins.gui_helpers.collab_chat.routes import (
                _require_session_access,
                _require_user,
                _token_from_headers,
            )

            tok = _token_from_headers(request)
            if tok:
                u = _require_user(app, request)
                owner_username = u.username
                pid = job.get("pid") or ""
                sid = job.get("sid") or ""
                if pid and sid:
                    _require_session_access(app, u, pid, sid)
        except HTTPException:
            raise
        except Exception:
            owner_username = None

        if owner_username:
            if job.get("owner_username") != owner_username:
                raise HTTPException(status_code=403, detail="not your job")
        elif owner_alias:
            if job.get("owner_alias") != owner_alias:
                raise HTTPException(status_code=403, detail="not your job")

        canceled = False
        try:
            canceled = self._gen_scheduler_getter().cancel(job_id)
        except Exception:
            canceled = False

        try:
            self._cancel_flags_getter()[job_id] = True
        except Exception:
            pass
        try:
            cancelled = self._cancelled_jobs_getter()
            if isinstance(cancelled, dict):
                cancelled[job_id] = True
        except Exception:
            pass

        self.release_model_workflow_resources(job_id, release_value)
        self.cleanup_memory_caches()

        try:
            if canceled:
                self._turn_bus_getter().finish(job_id, ok=False, err="canceled")
        except Exception:
            pass

        if job.get("suppress_cancel_message"):
            reg.remove(job_id)
            return {"ok": True, "canceled": True}

        try:
            from plugins.gui_helpers.collab_chat.routes import _now_ts

            db = app.state.collab_db
            hub = app.state.collab_hub
            username = owner_username or owner_alias or "User"
            pid = job.get("pid") or ""
            sid = job.get("sid") or ""
            ts = _now_ts()
            content = f"{username} canceled"
            meta = {"ai_job_id": job_id, "ai_job_kind": job.get("kind"), "canceled": True}
            msg_id = job.get("asst_msg_id") or ""
            if msg_id:
                db.set_message_content(msg_id=msg_id, content=content)
                try:
                    hub.publish(
                        pid,
                        sid,
                        event="message",
                        data={
                            "msg": {
                                "msg_id": msg_id,
                                "pid": pid,
                                "sid": sid,
                                "ts": ts,
                                "role": "assistant",
                                "kind": "model",
                                "author_username": "assistant",
                                "author_alias": "assistant",
                                "content": content,
                                "meta": meta,
                            }
                        },
                    )
                except Exception:
                    pass
                try:
                    hub.publish(
                        pid,
                        sid,
                        event="done",
                        data={
                            "turn_id": job.get("collab_turn_id") or job_id,
                            "msg_id": msg_id,
                            "ok": False,
                            "error": "canceled",
                        },
                    )
                except Exception:
                    pass
            else:
                import secrets

                msg_id = secrets.token_hex(12)
                db.add_message(
                    msg_id=msg_id,
                    pid=pid,
                    sid=sid,
                    ts=ts,
                    role="assistant",
                    kind="model",
                    author_username="assistant",
                    author_alias="assistant",
                    content=content,
                    meta=meta,
                )
                try:
                    hub.publish(
                        pid,
                        sid,
                        event="message",
                        data={
                            "msg": {
                                "msg_id": msg_id,
                                "pid": pid,
                                "sid": sid,
                                "ts": ts,
                                "role": "assistant",
                                "kind": "model",
                                "author_username": "assistant",
                                "author_alias": "assistant",
                                "content": content,
                                "meta": meta,
                            }
                        },
                    )
                except Exception:
                    pass
        except Exception:
            pass

        reg.remove(job_id)
        return {"ok": True, "canceled": True}
