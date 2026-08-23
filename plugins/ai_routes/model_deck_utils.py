from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, Callable, List
import asyncio
import inspect
import multiprocessing
import os
import traceback
import time
from runtime_cuda import empty_accelerator_cache
from plugins.gui_helpers._framework.services import get_plugin_service


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".wmv"}


def _attachment_dict(item: Any) -> Dict[str, Any]:
    if item is None:
        return {}
    if isinstance(item, dict):
        return dict(item)
    try:
        if hasattr(item, "model_dump"):
            return dict(item.model_dump(exclude_none=True))
        if hasattr(item, "dict"):
            return dict(item.dict(exclude_none=True))
    except Exception:
        pass
    try:
        return dict(item)
    except Exception:
        return {}


def _extract_ordered_attachments(req: Any) -> List[Dict[str, Any]]:
    sources: List[Any] = []

    def _add(src: Any) -> None:
        if not src:
            return
        if isinstance(src, dict):
            nested = src.get("items") or src.get("attachments")
            if nested is not None:
                _add(nested)
                return
            sources.append(src)
            return
        if isinstance(src, (list, tuple)):
            sources.extend(src)
            return
        sources.append(src)

    if isinstance(req, dict):
        _add(req.get("attachments"))
        ext = req.get("ext") if isinstance(req.get("ext"), dict) else {}
        _add((ext or {}).get("attachments"))
        _add((ext or {}).get("media_attachments"))
        msgs = req.get("messages")
    else:
        _add(getattr(req, "attachments", None))
        ext = getattr(req, "ext", None)
        if isinstance(ext, dict):
            _add(ext.get("attachments"))
            _add(ext.get("media_attachments"))
        msgs = getattr(req, "messages", None)

    if isinstance(msgs, list):
        for msg in msgs:
            if not isinstance(msg, dict) or (msg.get("role") or "").lower() != "user":
                continue
            meta = msg.get("meta")
            if isinstance(meta, dict):
                _add(meta.get("attachments"))
            content = msg.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        _add(part.get("attachment") or part.get("file") or part.get("media"))

    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in sources:
        item = _attachment_dict(raw)
        if not item:
            continue
        path = item.get("path") or item.get("local_path") or item.get("file_path") or item.get("abs_path")
        url = item.get("url") or item.get("href") or item.get("download_url")
        name = item.get("name") or item.get("filename") or item.get("file_name") or (os.path.basename(str(path)) if path else "")
        mime = str(item.get("mime") or item.get("content_type") or item.get("type") or "").lower()
        kind = str(item.get("kind") or item.get("media_type") or item.get("category") or "").lower()
        key = str(path or url or name or repr(item))
        if key in seen:
            continue
        seen.add(key)
        out.append({**item, "path": path or "", "url": url or "", "name": name or "", "mime": mime, "kind": kind})
    return out


def normalize_workflow_media_inputs(req: Any) -> Dict[str, Any]:
    """Map chat-uploaded media into predictable first/last workflow inputs.

    Convention:
    - one image/video => source/first media
    - two images/videos => first media is source, second media is last/target
    - text prompt remains the route prompt; workflows may omit unused extras
    """
    images: List[str] = []
    videos: List[str] = []

    for item in _extract_ordered_attachments(req):
        path = str(item.get("path") or item.get("url") or "").strip()
        if not path:
            continue
        mime = str(item.get("mime") or "").lower()
        kind = str(item.get("kind") or "").lower()
        name = str(item.get("name") or path).lower()
        ext = os.path.splitext(name.split("?", 1)[0])[1].lower()
        is_image = kind == "image" or mime.startswith("image/") or ext in IMAGE_EXTENSIONS
        is_video = kind == "video" or mime.startswith("video/") or ext in VIDEO_EXTENSIONS
        if is_image:
            images.append(path)
        elif is_video:
            videos.append(path)

    out: Dict[str, Any] = {}
    if images:
        out.update({
            "input_image_paths": images,
            "image_paths": images,
            "source_image_path": images[0],
            "first_image_path": images[0],
            "input_image_path": images[0],
            "init_image_path": images[0],
            "reference_image_path": images[0],
        })
        if len(images) > 1:
            out.update({
                "last_image_path": images[1],
                "target_image_path": images[1],
                "end_image_path": images[1],
            })
    if videos:
        out.update({
            "input_video_paths": videos,
            "video_paths": videos,
            "source_video_path": videos[0],
            "first_video_path": videos[0],
            "input_video_path": videos[0],
            "init_video_path": videos[0],
            "reference_video_path": videos[0],
        })
        if len(videos) > 1:
            out.update({
                "last_video_path": videos[1],
                "target_video_path": videos[1],
                "end_video_path": videos[1],
            })
    if images or videos:
        out["workflow_media_inputs"] = {"images": images, "videos": videos}
    return out


def get_server_app(settings: Dict[str, Any], reg: Any) -> Any:
    app = settings.get("__server_app")
    if app is not None:
        return app
    if reg is not None:
        try:
            gguf_loader = reg.get("model_loader.gguf") if hasattr(reg, "get") else None
        except Exception:
            gguf_loader = None
        if gguf_loader is not None:
            app = getattr(gguf_loader, "_app", None)
            if app is not None:
                return app
    return None


def _model_deck_service(settings: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    app = get_server_app(settings, settings.get("__model_loader_registry", None))
    svc = get_plugin_service(app, "model_deck")
    return svc if isinstance(svc, dict) else None


def resolve_model_deck_default(
    settings: Dict[str, Any],
    model_type: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    reg = settings.get("__model_loader_registry", None)
    app = get_server_app(settings, reg)
    if app is None:
        return None, "server_app_missing"

    deck_svc = _model_deck_service(settings)
    if not isinstance(deck_svc, dict):
        return None, "model_deck_service_missing"

    try:
        load_deck = deck_svc.get("load_deck")
        ensure_defaults = deck_svc.get("ensure_defaults")
        get_type = deck_svc.get("get_type")
        find_model = deck_svc.get("find_model")
        if not callable(load_deck) or not callable(ensure_defaults) or not callable(get_type) or not callable(find_model):
            return None, "model_deck_service_incomplete"
        deck = ensure_defaults(load_deck())
        t = get_type(deck, model_type)
    except Exception as exc:
        return None, f"model_deck_load_failed: {exc}"

    if not isinstance(t, dict):
        return None, f"model_deck_type_missing:{model_type}"

    mid = str(t.get("default_model_id") or "").strip()
    if not mid:
        return None, "model_deck_default_missing"
    m = find_model(t, mid)
    if not m:
        return None, "model_deck_default_not_found"

    return {
        "model_id": mid,
        "loader_id": str(m.get("loader_id") or ""),
        "settings": dict(m.get("settings") or {}),
        "lazy": bool(m.get("lazy", True)),
        "persist": bool(m.get("persist", False)),
    }, None


def resolve_main_text_llm_fallback(settings: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    reg = settings.get("__model_loader_registry", None)
    app = get_server_app(settings, reg)
    if app is None:
        return None, "server_app_missing"
    provider = getattr(getattr(app, "state", None), "main_text_llm_provider", None)
    if not callable(provider):
        return None, "main_text_llm_provider_missing"
    try:
        provider_result = provider() or {}
    except Exception as exc:
        return None, f"main_text_llm_provider_failed: {exc}"
    model_id = str(provider_result.get("model_id") or "").strip()
    loader_id = str(provider_result.get("loader_id") or "").strip()
    if not model_id:
        return None, "main_text_llm_model_missing"
    if loader_id not in ("model_loader.model_deck.text_llm", "model_loader.gguf"):
        return None, f"main_text_llm_loader_unsupported:{loader_id}"
    return {
        "model_id": model_id,
        "loader_id": loader_id,
        "settings": dict(provider_result.get("settings") or {}),
        "lazy": False,
        "persist": True,
        "use_main_text_llm_fallback": True,
    }, None


class ModelDeckRunner:
    def __init__(
        self,
        *,
        core: Any,
        settings: Dict[str, Any],
        model_type: str,
        slot: str,
        prefer_worker: bool = True,
        worker_mode: str = "per_request",
        worker_timeout: int = 120,
        require_mmproj: bool = False,
    ) -> None:
        self.core = core
        self.settings = settings
        self.model_type = model_type
        self.slot = slot
        self.prefer_worker = bool(prefer_worker)
        self.worker_mode = str(worker_mode or "per_request").strip().lower()
        if self.worker_mode not in ("per_request", "per_call"):
            self.worker_mode = "per_request"
        self.worker_timeout = int(worker_timeout or 120)
        self.require_mmproj = bool(require_mmproj)

        self.error: Optional[str] = None
        self._worker = None
        self._worker_cfg: Optional[Dict[str, Any]] = None
        self._model_ctx: Dict[str, Any] = {}
        self._use_worker = False

        self._init_runtime()

    def plan(self, messages: list[Dict[str, Any]], params: Dict[str, Any], timeout_s: int | None = None) -> Dict[str, Any]:
        if self.error:
            return {"ok": False, "error": self.error}
        cancel_cb = params.get("cancel_cb")
        try:
            if callable(cancel_cb) and cancel_cb():
                return {"ok": False, "error": "canceled"}
        except Exception:
            pass
        if self._use_worker:
            if self.worker_mode == "per_call":
                mgr = getattr(self.core, "worker_manager", None)
                if mgr is None or not self._worker_cfg:
                    return {"ok": False, "error": "worker_unavailable"}
                return mgr.run_vlm_plan(self._worker_cfg, messages, params, timeout_s=timeout_s or self.worker_timeout)
            return self._worker.plan(messages, params, timeout_s=timeout_s or self.worker_timeout)

        model = self._model_ctx.get("model")
        if model is None:
            return {"ok": False, "error": "model_unavailable"}
        max_new_tokens = int(params.get("max_new_tokens") or 512)
        temperature = float(params.get("temperature") or 0.2)
        top_p = float(params.get("top_p") or 0.3)
        top_k = int(params.get("top_k") or 30)
        out = ""
        if hasattr(model, "chat_mm"):
            try:
                if callable(cancel_cb) and cancel_cb():
                    return {"ok": False, "error": "canceled"}
            except Exception:
                pass
            out = model.chat_mm(
                messages=messages,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
            )
        if not out:
            try:
                if callable(cancel_cb) and cancel_cb():
                    return {"ok": False, "error": "canceled"}
            except Exception:
                pass
            out = model.chat(
                messages=messages,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
            )
        return {"ok": True, "raw": out}

    def stream(
        self,
        messages: list[Dict[str, Any]],
        params: Dict[str, Any],
        timeout_s: int | None = None,
        token_cb: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        if self.error:
            return {"ok": False, "error": self.error}
        cancel_cb = params.get("cancel_cb")
        try:
            if callable(cancel_cb) and cancel_cb():
                return {"ok": False, "error": "canceled"}
        except Exception:
            pass
        if self._use_worker:
            if self.worker_mode == "per_call":
                mgr = getattr(self.core, "worker_manager", None)
                if mgr is None or not self._worker_cfg:
                    return {"ok": False, "error": "worker_unavailable"}
                return mgr.run_vlm_stream(
                    self._worker_cfg,
                    messages,
                    params,
                    timeout_s=timeout_s or self.worker_timeout,
                    token_cb=token_cb,
                )
            return self._worker.stream(
                messages,
                params,
                timeout_s=timeout_s or self.worker_timeout,
                token_cb=token_cb,
            )

        model = self._model_ctx.get("model")
        if model is None:
            return {"ok": False, "error": "model_unavailable"}
        max_new_tokens = int(params.get("max_new_tokens") or 512)
        temperature = float(params.get("temperature") or 0.2)
        top_p = float(params.get("top_p") or 0.3)
        token_chunk_size = int(params.get("token_chunk_size") or 8)
        pieces: List[str] = []
        if hasattr(model, "stream_chat"):
            for piece in model.stream_chat(
                messages=messages,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                token_chunk_size=token_chunk_size,
            ):
                try:
                    if callable(cancel_cb) and cancel_cb():
                        return {"ok": False, "error": "canceled", "raw": "".join(pieces)}
                except Exception:
                    pass
                if not piece:
                    continue
                pieces.append(piece)
                if callable(token_cb):
                    try:
                        token_cb(piece)
                    except Exception:
                        pass
            return {"ok": True, "raw": "".join(pieces)}

        out = ""
        if hasattr(model, "chat_mm"):
            try:
                if callable(cancel_cb) and cancel_cb():
                    return {"ok": False, "error": "canceled"}
            except Exception:
                pass
            out = model.chat_mm(
                messages=messages,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=int(params.get("top_k") or 30),
            )
        if not out:
            try:
                if callable(cancel_cb) and cancel_cb():
                    return {"ok": False, "error": "canceled"}
            except Exception:
                pass
            out = model.chat(
                messages=messages,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=int(params.get("top_k") or 30),
            )
        if out and callable(token_cb):
            try:
                token_cb(out)
            except Exception:
                pass
        return {"ok": True, "raw": out}

    def close(self) -> None:
        if self._use_worker and self._worker is not None and self.worker_mode != "per_call":
            try:
                self._worker.close()
            except Exception:
                pass
        if self._model_ctx and not self._model_ctx.get("persist"):
            loader = self._model_ctx.get("loader")
            if loader is not None and hasattr(loader, "unload_for"):
                try:
                    self._awaitable_call(loader.unload_for, self._model_ctx.get("sid"), self._model_ctx.get("slot"))
                except Exception:
                    pass
            if self._should_stop_managed_llama_server_after_unload(loader):
                try:
                    deck_svc = _model_deck_service(self._model_ctx.get("settings") or {})
                    stop_managed = deck_svc.get("stop_managed_llama_server_if_needed") if isinstance(deck_svc, dict) else None
                    if callable(stop_managed):
                        stop_managed(self._model_ctx.get("settings") or {})
                    print(
                        f"[model_deck_runner.close] stopped managed llama-server "
                        f"id={(self._model_ctx.get('settings') or {}).get('llama_server_managed_id')} "
                        f"slot={self._model_ctx.get('slot')}",
                        flush=True,
                    )
                except Exception as exc:
                    print(f"[model_deck_runner.close] managed_stop_failed error={exc}", flush=True)

    def _should_stop_managed_llama_server_after_unload(self, loader: Any) -> bool:
        settings = self._model_ctx.get("settings") or {}
        if str(settings.get("backend_mode") or "").strip().lower() != "llama_server":
            return False
        managed_id = str(settings.get("llama_server_managed_id") or "").strip()
        if not managed_id:
            return False
        if not self._model_ctx.get("managed_llama_server"):
            return False

        try:
            state = getattr(loader, "_state", {}) or {}
        except Exception:
            state = {}
        for _key, st in state.items():
            if not isinstance(st, dict):
                continue
            other_settings = st.get("settings") or {}
            other_managed = str(other_settings.get("llama_server_managed_id") or "").strip()
            if other_managed == managed_id:
                return False
        return True

    def _awaitable_call(self, fn, *args, **kwargs):
        res = fn(*args, **kwargs)
        if inspect.isawaitable(res):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(res)
            fut = asyncio.run_coroutine_threadsafe(res, loop)
            return fut.result()
        return res

    def _init_runtime(self) -> None:
        info, err = resolve_model_deck_default(self.settings, self.model_type)
        if err and str(self.model_type or "").strip() == "text_llm":
            info, err = resolve_main_text_llm_fallback(self.settings)
        if err:
            self.error = err
            return

        loader_id = str(info.get("loader_id") or "model_loader.gguf")
        backend_mode = str(((info.get("settings") or {}).get("backend_mode") or "")).strip().lower()
        worker_mgr = getattr(self.core, "worker_manager", None)
        if (
            self.prefer_worker
            and worker_mgr is not None
            and info.get("lazy")
            and not info.get("persist")
            and backend_mode != "llama_server"
            and loader_id in ("model_loader.gguf", "model_loader.model_deck.vlm")
        ):
            cfg, err = self._build_gguf_worker_cfg(info)
            if err:
                self.error = err
                return
            self._worker_cfg = cfg
            if self.worker_mode == "per_request":
                self._worker = worker_mgr.spawn_vlm_worker(
                    cfg,
                    meta={
                        "model_type": self.model_type,
                        "slot": self.slot,
                        "model_id": info.get("model_id"),
                        "loader_id": loader_id,
                        "lazy": bool(info.get("lazy", True)),
                        "persist": bool(info.get("persist", False)),
                        "source": "model_deck_runner",
                    },
                )
            self._use_worker = True
            return

        self._model_ctx = self._bind_model_from_deck(info, loader_id)
        if self._model_ctx.get("error"):
            self.error = str(self._model_ctx.get("error"))

    def _build_gguf_worker_cfg(self, info: Dict[str, Any]) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        reg = self.settings.get("__model_loader_registry", None)
        app = get_server_app(self.settings, reg)
        if app is None:
            return None, "server_app_missing"

        try:
            from plugins.model_loader.model_deck.local_loaders.gguf_bridge import map_gguf_settings
            deck_settings = dict(info.get("settings") or {})
            app = get_server_app(self.settings, reg)
            if app is not None:
                deck_settings.setdefault("__server_app", app)
            gguf_settings = map_gguf_settings(deck_settings, require_mmproj=self.require_mmproj)
        except Exception as exc:
            return None, f"model_deck_settings_invalid: {exc}"

        try:
            from plugins.model_loader.gguf import plugin as gguf_plugin
            model_path = gguf_plugin._resolve_gguf_path(
                app, gguf_settings.get("model_id"), gguf_settings.get("gguf_filename")
            )
            mmproj_id = gguf_settings.get("mmproj_path")
            mmproj_path = None
            if mmproj_id:
                mmproj_path = gguf_plugin._resolve_gguf_path(app, mmproj_id, None)
        except Exception as exc:
            return None, f"resolve_failed: {exc}"

        model_settings = dict(info.get("settings") or {})
        cfg = {
            "model_path": model_path,
            "mmproj_path": mmproj_path,
            "vision_handler": gguf_settings.get("vision_handler") or "auto",
            "n_ctx": gguf_settings.get("n_ctx") or model_settings.get("n_ctx") or 4096,
            "n_threads": model_settings.get("n_threads"),
            "n_gpu_layers": gguf_settings.get("n_gpu_layers") or 0,
            "chat_format": model_settings.get("chat_format") or None,
        }
        return cfg, None

    def _bind_model_from_deck(self, info: Dict[str, Any], loader_id: str) -> Dict[str, Any]:
        reg = self.settings.get("__model_loader_registry", None)
        if reg is None:
            return {"error": "model_loader_registry_missing"}

        app = get_server_app(self.settings, reg)
        use_main_fallback = bool(info.get("use_main_text_llm_fallback"))
        sid = "_default" if use_main_fallback else str(self.settings.get("__sid") or "_default")
        slot = "text_llm_main" if use_main_fallback else self.slot

        loader = reg.get(loader_id) if hasattr(reg, "get") else None
        gguf_loader = reg.get("model_loader.gguf") if hasattr(reg, "get") else None
        use_settings = dict(info.get("settings") or {})
        backend_mode = str((use_settings.get("backend_mode") or "")).strip().lower()
        managed_llama_server = False

        if use_main_fallback:
            loader_id = "model_loader.gguf"
            loader = gguf_loader

        if loader_id in ("model_loader.gguf", "model_loader.model_deck.vlm"):
            loader = gguf_loader
            if loader is None:
                return {"error": "model_loader.gguf missing"}
            try:
                from plugins.model_loader.model_deck.local_loaders.gguf_bridge import map_gguf_settings
                deck_svc = _model_deck_service(self.settings)
                if not isinstance(deck_svc, dict):
                    return {"error": "model_deck_service_missing"}
                app = get_server_app(self.settings, reg)
                if app is not None:
                    use_settings = dict(use_settings)
                    use_settings.setdefault("__server_app", app)
                use_settings = map_gguf_settings(use_settings, require_mmproj=self.require_mmproj)
                backend_mode = str(use_settings.get("backend_mode") or "").strip().lower()
                if backend_mode == "llama_server":
                    source_path = str(use_settings.get("model_id") or "").strip()
                    ensure_model_copy = deck_svc.get("ensure_llama_server_model_copy")
                    resolve_aux = deck_svc.get("resolve_aux_gguf_path")
                    start_managed = deck_svc.get("start_managed_llama_server_if_needed")
                    if not callable(ensure_model_copy) or not callable(resolve_aux) or not callable(start_managed):
                        return {"error": "model_deck_service_incomplete"}
                    _, rel_model_path = ensure_model_copy(source_path)
                    rel_mmproj_path = None
                    mmproj_path = resolve_aux(app, str(use_settings.get("mmproj_path") or "").strip())
                    if mmproj_path:
                        _, rel_mmproj_path = ensure_model_copy(mmproj_path)
                    managed_url = start_managed(
                        use_settings,
                        rel_model_path,
                        mmproj_relpath=rel_mmproj_path,
                    )
                    if managed_url:
                        use_settings["llama_server_url"] = managed_url
                        managed_llama_server = bool(str(use_settings.get("llama_server_managed_id") or "").strip())
                    elif not str(use_settings.get("llama_server_url") or "").strip():
                        return {"error": "llama_server_url_missing_for_vlm"}
            except Exception as exc:
                return {"error": f"model_deck_settings_invalid: {exc}"}
        elif loader is None or not hasattr(loader, "load_for"):
            return {"error": f"model_loader_missing:{loader_id}"}

        if not hasattr(loader, "get_model_for"):
            return {"error": f"model_loader_missing_get_model_for:{loader_id}"}

        model = loader.get_model_for(sid, slot)
        if model is None:
            try:
                load_res = self._awaitable_call(loader.load_for, sid, slot, settings=use_settings)
            except Exception as exc:
                return {"error": f"model_load_failed: {exc}"}
            if not (load_res or {}).get("ok", False):
                return {"error": f"model_load_failed: {load_res}"}
            model = loader.get_model_for(sid, slot)
        if model is None:
            return {"error": "loaded_model_missing"}

        return {
            "model": model,
            "loader": loader,
            "sid": sid,
            "slot": slot,
            "persist": bool(info.get("persist")),
            "settings": use_settings,
            "backend_mode": backend_mode,
            "managed_llama_server": managed_llama_server,
        }


def _save_image_worker(image: Any, fmt: str, output_dir: str) -> str:
    from uuid import uuid4

    ext = "png" if fmt == "png" else "jpg"
    name = f"image_gen_{uuid4().hex}.{ext}"
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, name)
    try:
        if fmt in ("jpg", "jpeg"):
            image = image.convert("RGB")
            image.save(path, format="JPEG", quality=95)
        else:
            image.save(path, format="PNG")
    except Exception:
        image.save(path)
    return path


def _image_gen_worker(conn, loader_id: str, model_settings: Dict[str, Any], params: Dict[str, Any]) -> None:
    try:
        from plugins.model_loader.model_deck.local_loaders.image_gen_gguf import routes as gguf_image_routes
        from plugins.model_loader.model_deck.local_loaders.diffusers import routes as diffusers_routes
        from plugins.model_loader.model_deck.local_loaders import custom_command_runtime

        prompt = str(params.get("prompt") or "")
        negative_prompt = params.get("negative_prompt")
        num_inference_steps = params.get("num_inference_steps")
        guidance_scale = params.get("guidance_scale")
        width = params.get("width")
        height = params.get("height")
        seed = params.get("seed")
        fmt = str(params.get("fmt") or "png").lower()
        output_dir = str(params.get("output_dir") or "").strip()

        out_path = ""
        url = ""

        def _progress(step: int, total: int) -> None:
            try:
                conn.send({"type": "progress", "step": int(step), "total": int(total)})
            except Exception:
                pass

        if str(model_settings.get("image_command_mode") or "standard").strip().lower() == "advanced":
            if not output_dir:
                output_dir = os.path.join(os.getcwd(), "data", "uploads")
            os.makedirs(output_dir, exist_ok=True)
            ext = "jpg" if fmt in ("jpg", "jpeg") else ("webp" if fmt == "webp" else "png")
            out_path = os.path.join(output_dir, f"image_gen_{int(time.time())}_{os.getpid()}.{ext}")
            custom_command_runtime.run_advanced_command(
                settings=model_settings,
                prefix="image",
                runtime_inputs={
                    "prompt": prompt,
                    "negative_prompt": negative_prompt or "",
                    "output_path": out_path,
                    "width": width or "",
                    "height": height or "",
                    "steps": num_inference_steps or "",
                    "num_inference_steps": num_inference_steps or "",
                    "guidance": guidance_scale or "",
                    "guidance_scale": guidance_scale or "",
                    "seed": seed or "",
                    "seed_arg": f"--seed {seed}" if seed not in (None, "") else "",
                },
            )
            if not os.path.isfile(out_path):
                raise RuntimeError(f"advanced image command did not create output: {out_path}")
            url = f"/uploads/{os.path.basename(out_path)}"
        elif loader_id == gguf_image_routes.LOADER_ID:
            out_path = gguf_image_routes.generate_text2image(
                prompt=prompt,
                settings=model_settings,
                negative_prompt=negative_prompt,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                width=width,
                height=height,
                seed=seed,
                progress_callback=_progress,
            )
            url = f"/uploads/{os.path.basename(out_path)}"
        else:
            images = diffusers_routes.generate_text2image(
                prompt=prompt,
                settings=model_settings,
                negative_prompt=negative_prompt,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                width=width,
                height=height,
                seed=seed,
                progress_callback=_progress,
            )
            image = None
            if isinstance(images, (list, tuple)) and images:
                image = images[0]
            elif images is not None:
                image = images
            if image is None:
                raise RuntimeError("no_image_generated")
            if not output_dir:
                output_dir = os.path.join(os.getcwd(), "data", "uploads")
            out_path = _save_image_worker(image, fmt, output_dir)
            url = f"/uploads/{os.path.basename(out_path)}"
            try:
                if hasattr(image, "close"):
                    image.close()
            except Exception:
                pass

        conn.send({"type": "result", "ok": True, "out_path": out_path, "url": url})
    except Exception as exc:
        conn.send({"type": "result", "ok": False, "error": str(exc), "trace": traceback.format_exc()})
    finally:
        try:
            conn.close()
        except Exception:
            pass


class ImageGenRunner:
    def __init__(
        self,
        *,
        core: Any,
        settings: Dict[str, Any],
        model_type: str = "image_gen",
        prefer_worker: bool = True,
        worker_timeout: int = 600,
    ) -> None:
        self.core = core
        self.settings = settings
        self.model_type = model_type
        self.prefer_worker = bool(prefer_worker)
        self.worker_timeout = int(worker_timeout or 600)
        self.error: Optional[str] = None
        self.info: Dict[str, Any] = {}
        self.loader_id: str = ""
        self._use_worker = False

        self._init_runtime()

    def _init_runtime(self) -> None:
        info, err = resolve_model_deck_default(self.settings, self.model_type)
        if err:
            self.error = err
            return
        self.info = info or {}
        self.loader_id = str(self.info.get("loader_id") or "")
        if self.prefer_worker and info.get("lazy") and not info.get("persist"):
            self._use_worker = True

    def close(self) -> None:
        return

    def generate(
        self,
        *,
        prompt: str,
        negative_prompt: Optional[str],
        num_inference_steps: int,
        guidance_scale: float,
        width: int,
        height: int,
        seed: Optional[int],
        fmt: str,
        progress_callback: Optional[Any] = None,
        cancel_cb: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if self.error:
            return {"ok": False, "error": self.error}
        info = self.info or {}

        from plugins.model_loader.model_deck.local_loaders.image_gen_gguf import routes as gguf_image_routes
        from plugins.model_loader.model_deck.local_loaders.diffusers import routes as diffusers_routes

        loader_id = str(info.get("loader_id") or "")
        allowed = {gguf_image_routes.LOADER_ID, diffusers_routes.LOADER_ID}
        if loader_id not in allowed:
            return {"ok": False, "error": f"unsupported_loader:{loader_id}"}
        model_settings = dict(info.get("settings") or {})
        model_settings.update(self.settings.get("image_gen_model_settings") or {})
        for key in (
            "image_gen_use_prompt_embeds",
            "debug_prompt_embeds",
            "use_prompt_embeds",
            "max_sequence_length",
        ):
            if key in self.settings:
                model_settings[key] = self.settings.get(key)
        if "__server_app" not in model_settings:
            app = get_server_app(self.settings, self.settings.get("__model_loader_registry"))
            if app is not None:
                model_settings["__server_app"] = app
        if "__model_loader_registry" not in model_settings and self.settings.get("__model_loader_registry") is not None:
            model_settings["__model_loader_registry"] = self.settings.get("__model_loader_registry")

        persist_raw = info.get("persist", False)
        if isinstance(persist_raw, str):
            persist = persist_raw.strip().lower() in ("1", "true", "yes", "on")
        else:
            persist = bool(persist_raw)

        if callable(cancel_cb) and cancel_cb():
            return {"ok": False, "error": "canceled"}

        if self._use_worker and not persist:
            worker_settings = self._prepare_worker_settings(loader_id, model_settings)
            return self._run_worker(
                loader_id=loader_id,
                model_settings=worker_settings,
                prompt=prompt,
                negative_prompt=negative_prompt,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                width=width,
                height=height,
                seed=seed,
                fmt=fmt,
                progress_callback=progress_callback,
                cancel_cb=cancel_cb,
            )

        if loader_id == gguf_image_routes.LOADER_ID:
            try:
                def _progress(step: int, total: int) -> None:
                    if callable(cancel_cb) and cancel_cb():
                        raise RuntimeError("canceled")
                    if callable(progress_callback):
                        progress_callback(step, total)

                out_path = gguf_image_routes.generate_text2image(
                    prompt=prompt,
                    settings=model_settings,
                    negative_prompt=negative_prompt,
                    num_inference_steps=num_inference_steps,
                    guidance_scale=guidance_scale,
                    width=width,
                    height=height,
                    seed=seed,
                    progress_callback=_progress if progress_callback or cancel_cb else None,
                )
            finally:
                if not persist:
                    try:
                        gguf_image_routes.unload(None, model_settings)
                    except Exception:
                        pass
                    self._cleanup_memory()
            return {"ok": True, "out_path": out_path, "url": f"/uploads/{os.path.basename(out_path)}"}

        try:
            def _progress(step: int, total: int) -> None:
                if callable(cancel_cb) and cancel_cb():
                    raise RuntimeError("canceled")
                if callable(progress_callback):
                    progress_callback(step, total)

            images = diffusers_routes.generate_text2image(
                prompt=prompt,
                settings=model_settings,
                negative_prompt=negative_prompt,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                width=width,
                height=height,
                seed=seed,
                progress_callback=_progress if progress_callback or cancel_cb else None,
            )
        finally:
            if not persist:
                try:
                    diffusers_routes.unload(None, model_settings)
                except Exception:
                    pass
                self._cleanup_memory()

        image = None
        if isinstance(images, (list, tuple)) and images:
            image = images[0]
        elif images is not None:
            image = images
        if image is None:
            return {"ok": False, "error": "no_image_generated"}

        out_dir = self._uploads_dir(model_settings)
        out_path = _save_image_worker(image, fmt, out_dir)
        try:
            if hasattr(image, "close"):
                image.close()
        except Exception:
            pass
        return {"ok": True, "out_path": out_path, "url": f"/uploads/{os.path.basename(out_path)}"}

    def _uploads_dir(self, model_settings: Dict[str, Any]) -> str:
        app = model_settings.get("__server_app")
        if app is None:
            reg = self.settings.get("__model_loader_registry", None)
            app = get_server_app(self.settings, reg)
        base = None
        if app is not None:
            base = getattr(app.state, "data_dir", None) or getattr(app.state, "workdir", None)
        if not base:
            base = os.path.join(os.getcwd(), "data")
        out = os.path.join(base, "uploads")
        os.makedirs(out, exist_ok=True)
        return out

    def _prepare_worker_settings(self, loader_id: str, model_settings: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(model_settings or {})
        for k in list(out.keys()):
            if str(k).startswith("__"):
                out.pop(k, None)

        out_dir = out.get("output_dir")
        if not out_dir:
            out["output_dir"] = self._uploads_dir(model_settings)

        if loader_id == "model_loader.model_deck.image_gen_gguf":
            try:
                from plugins.model_loader.model_deck.local_loaders.image_gen_gguf import routes as gguf_image_routes
                out["model_path"] = gguf_image_routes._resolve_model_path(out)
            except Exception:
                pass
        else:
            try:
                from plugins.model_loader.model_deck.local_loaders.diffusers import routes as diffusers_routes
                gguf_path = str(out.get("gguf_path") or "").strip()
                if gguf_path:
                    out["gguf_path"] = diffusers_routes._resolve_gguf_path_setting(None, model_settings, gguf_path)
                unet_path = str(out.get("sdxl_unet_path") or "").strip()
                if unet_path or out.get("sdxl_unet_repo") or out.get("sdxl_unet_filename"):
                    resolved = diffusers_routes._resolve_unet_path_setting(None, model_settings, unet_path)
                    if resolved:
                        out["sdxl_unet_path"] = resolved
            except Exception:
                pass
        return out

    def _run_worker(
        self,
        *,
        loader_id: str,
        model_settings: Dict[str, Any],
        prompt: str,
        negative_prompt: Optional[str],
        num_inference_steps: int,
        guidance_scale: float,
        width: int,
        height: int,
        seed: Optional[int],
        fmt: str,
        progress_callback: Optional[Any] = None,
        cancel_cb: Optional[Any] = None,
    ) -> Dict[str, Any]:
        ctx = multiprocessing.get_context("spawn")
        parent, child = ctx.Pipe()
        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "num_inference_steps": num_inference_steps,
            "guidance_scale": guidance_scale,
            "width": width,
            "height": height,
            "seed": seed,
            "fmt": fmt,
            "output_dir": model_settings.get("output_dir") or "",
        }
        proc = ctx.Process(
            target=_image_gen_worker,
            args=(child, loader_id, model_settings, payload),
            daemon=True,
        )
        proc.start()
        start = time.monotonic()
        try:
            last_step = -1
            last_total = None
            last_heartbeat = time.monotonic()
            heartbeat_total = int(num_inference_steps or 0)
            while True:
                if callable(cancel_cb) and cancel_cb():
                    try:
                        if proc.is_alive():
                            proc.terminate()
                    except Exception:
                        pass
                    return {"ok": False, "error": "canceled"}
                if parent.poll(0.1):
                    msg = parent.recv()
                    if isinstance(msg, dict) and msg.get("type") == "progress":
                        if callable(progress_callback):
                            try:
                                step = int(msg.get("step") or 0)
                                total = int(msg.get("total") or 0)
                                if step > last_step or total != last_total:
                                    last_step = step
                                    last_total = total
                                    progress_callback(step, total)
                            except Exception:
                                pass
                        last_heartbeat = time.monotonic()
                        continue
                    if isinstance(msg, dict) and msg.get("type") == "result":
                        msg.pop("type", None)
                        return msg
                    return msg
                if callable(progress_callback) and proc.is_alive() and (time.monotonic() - last_heartbeat) >= 4.0:
                    try:
                        progress_callback(max(last_step, 0), int(last_total or heartbeat_total or 0))
                    except Exception:
                        pass
                    last_heartbeat = time.monotonic()
                if self.worker_timeout > 0 and (time.monotonic() - start > self.worker_timeout):
                    return {"ok": False, "error": "worker_timeout"}
        finally:
            try:
                parent.close()
            except Exception:
                pass
            try:
                proc.join(timeout=2)
            except Exception:
                pass
            try:
                if proc.is_alive():
                    proc.terminate()
            except Exception:
                pass

    def _cleanup_memory(self) -> None:
        try:
            import gc
            gc.collect()
        except Exception:
            pass
        try:
            import torch
            empty_accelerator_cache(torch)
        except Exception:
            pass


def _video_gen_worker(conn, model_settings: Dict[str, Any], params: Dict[str, Any]) -> None:
    try:
        from plugins.model_loader.model_deck.local_loaders.video import routes as video_routes
        from plugins.model_loader.model_deck.local_loaders import custom_command_runtime

        prompt = str(params.get("prompt") or "")
        num_frames = params.get("num_frames")
        num_inference_steps = params.get("num_inference_steps")
        guidance_scale = params.get("guidance_scale")
        width = params.get("width")
        height = params.get("height")
        fps = params.get("fps")
        seed = params.get("seed")
        negative_prompt = params.get("negative_prompt")
        output_dir = str(params.get("output_dir") or "").strip()

        def _progress(step: int, total: int) -> None:
            try:
                conn.send({"type": "progress", "step": int(step), "total": int(total)})
            except Exception:
                pass

        if str(model_settings.get("video_command_mode") or "standard").strip().lower() == "advanced":
            if not output_dir:
                output_dir = os.path.join(os.getcwd(), "data", "uploads")
            os.makedirs(output_dir, exist_ok=True)
            out_path = os.path.join(output_dir, f"video_gen_{int(time.time())}_{os.getpid()}.mp4")
            custom_command_runtime.run_advanced_command(
                settings=model_settings,
                prefix="video",
                runtime_inputs={
                    "prompt": prompt,
                    "negative_prompt": negative_prompt or "",
                    "output_path": out_path,
                    "width": width or "",
                    "height": height or "",
                    "frames": num_frames or "",
                    "num_frames": num_frames or "",
                    "fps": fps or "",
                    "steps": num_inference_steps or "",
                    "num_inference_steps": num_inference_steps or "",
                    "guidance": guidance_scale or "",
                    "guidance_scale": guidance_scale or "",
                    "seed": seed or "",
                    "seed_arg": f"--seed {seed}" if seed not in (None, "") else "",
                },
            )
            if not os.path.isfile(out_path):
                raise RuntimeError(f"advanced video command did not create output: {out_path}")
        else:
            out_path = video_routes.generate_text2video(
                prompt=prompt,
                settings=model_settings,
                num_frames=num_frames,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                width=width,
                height=height,
                fps=fps,
                seed=seed,
                progress_callback=_progress,
                output_dir=output_dir or None,
            )
        url = f"/uploads/{os.path.basename(out_path)}"
        conn.send({"type": "result", "ok": True, "out_path": out_path, "url": url})
    except Exception as exc:
        conn.send({"type": "result", "ok": False, "error": str(exc), "trace": traceback.format_exc()})
    finally:
        try:
            conn.close()
        except Exception:
            pass


class VideoGenRunner:
    def __init__(
        self,
        *,
        core: Any,
        settings: Dict[str, Any],
        model_type: str = "video_gen",
        prefer_worker: bool = True,
        worker_timeout: int = 0,
    ) -> None:
        self.core = core
        self.settings = settings
        self.model_type = model_type
        self.prefer_worker = bool(prefer_worker)
        if worker_timeout is None:
            self.worker_timeout = 0
        else:
            try:
                self.worker_timeout = int(worker_timeout)
            except Exception:
                self.worker_timeout = 0
        if self.worker_timeout < 0:
            self.worker_timeout = 0
        self.error: Optional[str] = None
        self.info: Dict[str, Any] = {}
        self.loader_id: str = ""
        self._use_worker = False

        self._init_runtime()

    def _init_runtime(self) -> None:
        info, err = resolve_model_deck_default(self.settings, self.model_type)
        if err:
            self.error = err
            return
        self.info = info or {}
        self.loader_id = str(self.info.get("loader_id") or "")
        if self.prefer_worker and info.get("lazy") and not info.get("persist"):
            self._use_worker = True

    def close(self) -> None:
        return

    def generate(
        self,
        *,
        prompt: str,
        num_frames: int,
        num_inference_steps: int,
        guidance_scale: float,
        width: int,
        height: int,
        fps: int,
        seed: Optional[int],
        progress_callback: Optional[Any] = None,
        cancel_cb: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if self.error:
            return {"ok": False, "error": self.error}
        info = self.info or {}

        from plugins.model_loader.model_deck.local_loaders.video import routes as video_routes

        loader_id = str(info.get("loader_id") or "")
        if loader_id != video_routes.LOADER_ID:
            return {"ok": False, "error": f"unsupported_loader:{loader_id}"}

        model_settings = dict(info.get("settings") or {})
        model_settings.update(self.settings.get("video_gen_model_settings") or {})
        if "__server_app" not in model_settings:
            app = get_server_app(self.settings, self.settings.get("__model_loader_registry"))
            if app is not None:
                model_settings["__server_app"] = app
        if "__model_loader_registry" not in model_settings and self.settings.get("__model_loader_registry") is not None:
            model_settings["__model_loader_registry"] = self.settings.get("__model_loader_registry")

        persist_raw = info.get("persist", False)
        if isinstance(persist_raw, str):
            persist = persist_raw.strip().lower() in ("1", "true", "yes", "on")
        else:
            persist = bool(persist_raw)

        if self._use_worker and not persist:
            worker_settings = self._prepare_worker_settings(model_settings)
            return self._run_worker(
                model_settings=worker_settings,
                prompt=prompt,
                num_frames=num_frames,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                width=width,
                height=height,
                fps=fps,
                seed=seed,
                progress_callback=progress_callback,
                cancel_cb=cancel_cb,
            )

        try:
            def _progress(step: int, total: int) -> None:
                if callable(cancel_cb) and cancel_cb():
                    raise RuntimeError("canceled")
                if callable(progress_callback):
                    progress_callback(step, total)

            out_path = video_routes.generate_text2video(
                prompt=prompt,
                settings=model_settings,
                num_frames=num_frames,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                width=width,
                height=height,
                fps=fps,
                seed=seed,
                progress_callback=_progress if progress_callback or cancel_cb else None,
            )
        except RuntimeError as exc:
            if str(exc).lower().startswith("canceled"):
                return {"ok": False, "error": "canceled"}
            raise
        finally:
            if not persist:
                try:
                    video_routes.unload(None, model_settings)
                except Exception:
                    pass
                self._cleanup_memory()
        return {"ok": True, "out_path": out_path, "url": f"/uploads/{os.path.basename(out_path)}"}

    def _uploads_dir(self, model_settings: Dict[str, Any]) -> str:
        app = model_settings.get("__server_app")
        if app is None:
            reg = self.settings.get("__model_loader_registry", None)
            app = get_server_app(self.settings, reg)
        base = None
        if app is not None:
            base = getattr(app.state, "data_dir", None) or getattr(app.state, "workdir", None)
        if not base:
            base = os.path.join(os.getcwd(), "data")
        out = os.path.join(base, "uploads")
        os.makedirs(out, exist_ok=True)
        return out

    def _prepare_worker_settings(self, model_settings: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(model_settings or {})
        for k in list(out.keys()):
            if str(k).startswith("__"):
                out.pop(k, None)
        out_dir = out.get("output_dir")
        if not out_dir:
            out["output_dir"] = self._uploads_dir(model_settings)
        return out

    def _run_worker(
        self,
        *,
        model_settings: Dict[str, Any],
        prompt: str,
        num_frames: int,
        num_inference_steps: int,
        guidance_scale: float,
        width: int,
        height: int,
        fps: int,
        seed: Optional[int],
        progress_callback: Optional[Any] = None,
        cancel_cb: Optional[Any] = None,
    ) -> Dict[str, Any]:
        ctx = multiprocessing.get_context("spawn")
        parent, child = ctx.Pipe()
        payload = {
            "prompt": prompt,
            "num_frames": num_frames,
            "num_inference_steps": num_inference_steps,
            "guidance_scale": guidance_scale,
            "width": width,
            "height": height,
            "fps": fps,
            "seed": seed,
            "output_dir": model_settings.get("output_dir") or "",
        }
        proc = ctx.Process(
            target=_video_gen_worker,
            args=(child, model_settings, payload),
            daemon=True,
        )
        proc.start()
        start = time.monotonic()
        try:
            last_step = -1
            last_total = None
            while True:
                if callable(cancel_cb) and cancel_cb():
                    try:
                        if proc.is_alive():
                            proc.terminate()
                    except Exception:
                        pass
                    return {"ok": False, "error": "canceled"}
                if parent.poll(0.1):
                    msg = parent.recv()
                    if isinstance(msg, dict) and msg.get("type") == "progress":
                        if callable(progress_callback):
                            try:
                                step = int(msg.get("step") or 0)
                                total = int(msg.get("total") or 0)
                                if step > last_step or total != last_total:
                                    last_step = step
                                    last_total = total
                                    progress_callback(step, total)
                            except Exception:
                                pass
                        continue
                    if isinstance(msg, dict) and msg.get("type") == "result":
                        msg.pop("type", None)
                        return msg
                    return msg
                if self.worker_timeout > 0 and (time.monotonic() - start > self.worker_timeout):
                    return {"ok": False, "error": "worker_timeout"}
        finally:
            try:
                parent.close()
            except Exception:
                pass
            try:
                proc.join(timeout=2)
            except Exception:
                pass
            try:
                if proc.is_alive():
                    proc.terminate()
            except Exception:
                pass

    def _cleanup_memory(self) -> None:
        try:
            import gc
            gc.collect()
        except Exception:
            pass
        try:
            import torch
            empty_accelerator_cache(torch)
        except Exception:
            pass
