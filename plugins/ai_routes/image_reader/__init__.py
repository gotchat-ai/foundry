from __future__ import annotations

import base64
import io
import mimetypes
import os
import time
from typing import Any, Dict, List, Optional

from plugins.ai_routes.base import BaseRoute, RouterCore


PLUGIN_ID = "image_reader"
PLUGIN_TITLE = "Image Reader"
PLUGIN_NAME = "Image Reader"
PLUGIN_DESCRIPTION = "Read and describe an uploaded image using the model_deck VLM."
PLUGIN_TYPE = "control"
AGENT_LINKABLE = True
MODEL_TYPE = "vlm"

PLUGIN_CONFIG_SCHEMA = [
    {"key": "image_reader_use_worker", "label": "Use worker process", "type": "bool", "default": "1"},
    {
        "key": "image_reader_worker_mode",
        "label": "Worker mode",
        "type": "enum",
        "options": ["per_request", "per_call"],
        "default": "per_request",
    },
    {"key": "image_reader_worker_timeout_s", "label": "Worker timeout (s)", "type": "int", "default": "120"},
    {"key": "image_reader_max_new_tokens", "label": "Max new tokens", "type": "int", "default": "512"},
    {"key": "image_reader_system_prompt", "label": "System prompt", "type": "str", "default": ""},
    {"key": "image_reader_temperature", "label": "Temperature", "type": "float", "default": "0.2"},
    {"key": "image_reader_top_p", "label": "Top-p", "type": "float", "default": "0.7"},
    {"key": "image_reader_top_k", "label": "Top-k", "type": "int", "default": "40"},
    {"key": "image_reader_stream", "label": "Stream response", "type": "bool", "default": "1"},
    {
        "key": "image_reader_image_format",
        "label": "Image format",
        "type": "enum",
        "options": ["png", "jpeg"],
        "default": "jpeg",
    },
    {"key": "image_reader_jpeg_quality", "label": "JPEG quality", "type": "int", "default": "75"},
    {"key": "image_reader_max_image_dim", "label": "Max image dimension", "type": "int", "default": "512"},
    {
        "key": "image_reader_image_source",
        "label": "Image source",
        "type": "enum",
        "options": ["auto", "path", "url", "data_uri"],
        "default": "data_uri",
    },
    {"key": "image_reader_max_data_uri_len", "label": "Max data URI length", "type": "int", "default": "60000"},
]


def _plugin_settings_from_ext(ext: Any, route_id: str) -> Dict[str, Any]:
    if not isinstance(ext, dict):
        return {}
    direct = ext.get(f"{route_id}_settings")
    if isinstance(direct, dict):
        return dict(direct)
    grouped = ext.get("router_plugin_settings")
    if isinstance(grouped, dict):
        nested = grouped.get(route_id)
        if isinstance(nested, dict):
            return dict(nested)
    return {}


def _file_to_data_uri(path: str, *, fmt: str, jpeg_quality: int, max_dim: int) -> Optional[str]:
    if not path or not os.path.exists(path):
        return None
    try:
        from PIL import Image
    except Exception:
        Image = None
    fmt = (fmt or "png").lower()
    if fmt not in ("png", "jpeg", "jpg"):
        fmt = "png"
    try:
        if Image is not None:
            img = Image.open(path)
            if max_dim and max_dim > 0:
                try:
                    img.thumbnail((int(max_dim), int(max_dim)))
                except Exception:
                    pass
            buf = io.BytesIO()
            if fmt in ("jpeg", "jpg"):
                try:
                    img = img.convert("RGB")
                except Exception:
                    pass
                quality = max(30, min(95, int(jpeg_quality)))
                img.save(buf, format="JPEG", quality=quality, optimize=True)
                b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                return "data:image/jpeg;base64," + b64
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            return "data:image/png;base64," + b64
    except Exception:
        pass
    try:
        with open(path, "rb") as f:
            data = f.read()
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        b64 = base64.b64encode(data).decode("utf-8")
        return f"data:{mime};base64,{b64}"
    except Exception:
        return None


def _extract_attachments(req: Any) -> List[Dict[str, Any]]:
    msgs = getattr(req, "messages", None)
    if isinstance(msgs, list) and msgs:
        for m in reversed(msgs):
            if not isinstance(m, dict):
                continue
            if (m.get("role") or "").lower() != "user":
                continue
            meta = m.get("meta")
            if isinstance(meta, dict):
                src = meta.get("attachments") or []
                return list(src) if isinstance(src, list) else []
            break
    if isinstance(req, dict):
        src = req.get("attachments") or []
        if not src:
            ext = req.get("ext") or {}
            src = (ext or {}).get("attachments") or (ext or {}).get("media_attachments") or []
        return list(src) if isinstance(src, list) else []
    src = getattr(req, "attachments", None) or []
    if isinstance(src, list) and src:
        return src
    ext = getattr(req, "ext", None)
    if isinstance(ext, dict):
        src = ext.get("attachments") or ext.get("media_attachments") or []
        return list(src) if isinstance(src, list) else []
    return []


def _pick_image_attachment(atts: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for a in reversed(atts or []):
        if not isinstance(a, dict):
            continue
        mime = str(a.get("mime") or a.get("content_type") or "").lower()
        kind = str(a.get("kind") or "").lower()
        if kind == "image" or mime.startswith("image/"):
            return a
    return None


def _resize_image_path(path: str, *, max_dim: int, jpeg_quality: int) -> Optional[str]:
    if not path or not os.path.exists(path) or max_dim <= 0:
        return path
    try:
        from PIL import Image
    except Exception:
        return path
    try:
        img = Image.open(path)
    except Exception:
        return path
    try:
        w, h = img.size
    except Exception:
        return path
    if w <= max_dim and h <= max_dim:
        return path
    try:
        img = img.convert("RGB")
    except Exception:
        pass
    try:
        img.thumbnail((int(max_dim), int(max_dim)))
    except Exception:
        return path

    base_dir = os.path.dirname(path) or os.getcwd()
    base_name = os.path.splitext(os.path.basename(path))[0]
    out_name = f"{base_name}_ir{int(max_dim)}.jpg"
    out_path = os.path.join(base_dir, out_name)
    try:
        img.save(out_path, format="JPEG", quality=max(30, min(95, int(jpeg_quality))), optimize=True)
        return out_path
    except Exception:
        return path


def _resolve_upload_url_to_path(url: str, settings: Dict[str, Any]) -> Optional[str]:
    if not url:
        return None
    if not url.startswith("/"):
        return None
    if not url.startswith("/uploads/"):
        return None
    app = settings.get("__server_app") if isinstance(settings, dict) else None
    base = None
    if app is not None:
        base = getattr(app.state, "data_dir", None) or getattr(app.state, "workdir", None)
    if not base:
        base = os.path.join(os.getcwd(), "data")
    path = os.path.join(base, url.lstrip("/"))
    return path if os.path.exists(path) else None


def _extract_image_from_messages(req: Any) -> Optional[Dict[str, Any]]:
    msgs = getattr(req, "messages", None)
    if not isinstance(msgs, list) or not msgs:
        return None
    last_user = None
    for m in reversed(msgs):
        if isinstance(m, dict) and (m.get("role") or "").lower() == "user":
            last_user = m
            break
    if last_user is None and isinstance(msgs[-1], dict):
        last_user = msgs[-1]
    if not isinstance(last_user, dict):
        return None
    meta = last_user.get("meta")
    if isinstance(meta, dict):
        atts = meta.get("attachments") or []
        if isinstance(atts, list):
            found = _pick_image_attachment(atts)
            if found:
                return found
    content = last_user.get("content")
    if not isinstance(content, list):
        return None
    for part in reversed(content):
        if not isinstance(part, dict):
            continue
        ptype = str(part.get("type") or "").lower()
        if ptype in ("image_url", "image"):
            url = ""
            if ptype == "image_url":
                url = part.get("image_url", {}).get("url") or part.get("url") or ""
            else:
                url = part.get("url") or part.get("image") or ""
            url = str(url or "").strip()
            if url:
                return {"url": url, "kind": "image", "mime": "image/*"}
    return None


class ImageReaderRoute(BaseRoute):
    route_id = "image_reader"
    MODEL_TYPE = MODEL_TYPE
    attachment_kinds = {"image"}
    short_description = "Read the image provided by the user. Read or describe an image that the user attached to the message."
    backend_types: set[str] = {"hf", "hf_assist", "gguf", "vllm", "auto"}

    def can_handle(self, req: Any) -> bool:
        if not super().can_handle(req):
            return False
        atts = _extract_attachments(req)
        if _pick_image_attachment(atts):
            return True
        if _extract_image_from_messages(req):
            return True
        return False

    def handle(self, req: Any) -> Any:
        user_text = self._extract_user_text(req)
        settings = self._merge_settings(req)
        if self._is_canceled(settings):
            return {"route_id": self.route_id, "ok": False, "error": "canceled"}
        base_url = ""
        ext = None
        if isinstance(req, dict):
            ext = req.get("ext")
        else:
            ext = getattr(req, "ext", None)
        if isinstance(ext, dict):
            base_url = str(ext.get("base_url") or ext.get("server_url") or "").strip().rstrip("/")
        use_worker = bool(self._to_int(settings.get("image_reader_use_worker"), 1))
        worker_timeout = self._to_int(settings.get("image_reader_worker_timeout_s"), 120)
        worker_mode = str(settings.get("image_reader_worker_mode") or "per_request").strip().lower()

        max_new_tokens = self._to_int(settings.get("image_reader_max_new_tokens"), 512)
        temperature = self._to_float(settings.get("image_reader_temperature"), 0.2)
        top_p = self._to_float(settings.get("image_reader_top_p"), 0.7)
        top_k = self._to_int(settings.get("image_reader_top_k"), 40)
        stream_enabled = bool(self._to_int(settings.get("image_reader_stream"), 1))

        image_format = str(settings.get("image_reader_image_format") or "png").lower()
        if image_format not in ("png", "jpeg", "jpg"):
            image_format = "png"
        jpeg_quality = self._to_int(settings.get("image_reader_jpeg_quality"), 75)
        max_dim = self._to_int(settings.get("image_reader_max_image_dim"), 512)
        if max_dim < 0:
            max_dim = 0
        image_source = str(settings.get("image_reader_image_source") or "auto").strip().lower()
        if image_source not in ("auto", "path", "url", "data_uri"):
            image_source = "auto"
        max_data_uri_len = self._to_int(settings.get("image_reader_max_data_uri_len"), 60000)

        atts = _extract_attachments(req)
        att = _pick_image_attachment(atts)
        if att is None:
            att = _extract_image_from_messages(req)
        if not att:
            return {"route_id": self.route_id, "ok": False, "error": "no_image_attachment"}

        runner = self.prepare_model_deck_runner(
            settings=settings,
            slot=self.route_id,
            prefer_worker=use_worker,
            worker_mode=worker_mode,
            worker_timeout=worker_timeout,
            require_mmproj=True,
        )
        if getattr(runner, "error", None):
            return {"route_id": self.route_id, "ok": False, "error": runner.error}

        try:
            self.emit_status("Analyzing image...", step=1, total=1)
            image_part = self._attachment_to_image_part(
                att,
                fmt=image_format,
                jpeg_quality=jpeg_quality,
                max_dim=max_dim,
                source=image_source,
                max_data_uri_len=max_data_uri_len,
                base_url=base_url,
                settings=settings,
            )
            if not image_part:
                return {"route_id": self.route_id, "ok": False, "error": "image_unavailable"}

            system_prompt = str(settings.get("image_reader_system_prompt") or "").strip()
            if not system_prompt:
                system_prompt = (
                    "You are a vision assistant. Read the image and answer the user request. "
                    "Be concise, but include key details you observe."
                )
            system_msg = {
                "role": "system",
                "content": system_prompt,
            }
            user_msg = {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text or "Describe this image."},
                    image_part,
                ],
            }
            diag_cb = None
            try:
                diag_cb = (self.core.settings or {}).get("__router_diag_cb")
            except Exception:
                diag_cb = None
            use_stream = bool(stream_enabled and callable(diag_cb))
            stream_text: List[str] = []
            last_emit = 0.0
            pending = ""

            def _emit_stream(force: bool = False) -> None:
                nonlocal last_emit, pending
                if not callable(diag_cb):
                    return
                if not pending and not force:
                    return
                now = time.monotonic()
                if not force and (now - last_emit) < 0.1 and len(pending) < 24:
                    return
                last_emit = now
                pending = ""
                try:
                    diag_cb({"router_result_text": "".join(stream_text), "route_id": self.route_id})
                except Exception:
                    pass

            def _on_token(piece: str) -> None:
                nonlocal pending
                if not piece:
                    return
                stream_text.append(piece)
                pending += piece
                _emit_stream(False)

            if use_stream:
                res = runner.stream(
                    [system_msg, user_msg],
                    params={
                        "max_new_tokens": max_new_tokens,
                        "temperature": temperature,
                        "top_p": top_p,
                        "top_k": top_k,
                    },
                    timeout_s=worker_timeout,
                    token_cb=_on_token,
                )
                _emit_stream(True)
            else:
                res = runner.plan(
                    [system_msg, user_msg],
                    params={
                        "max_new_tokens": max_new_tokens,
                        "temperature": temperature,
                        "top_p": top_p,
                        "top_k": top_k,
                    },
                    timeout_s=worker_timeout,
                )
            if not isinstance(res, dict) or not res.get("ok"):
                return {"route_id": self.route_id, "ok": False, "error": res.get("error") if isinstance(res, dict) else "vlm_failed"}
            answer = str(res.get("raw") or "").strip()
            if not answer:
                return {"route_id": self.route_id, "ok": False, "error": "empty_response"}
            return {"route_id": self.route_id, "ok": True, "answer": answer}
        finally:
            try:
                runner.close()
            except Exception:
                pass

    def _attachment_to_image_part(
        self,
        att: Dict[str, Any],
        *,
        fmt: str,
        jpeg_quality: int,
        max_dim: int,
        source: str,
        max_data_uri_len: int,
        base_url: str,
        settings: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        path = str(att.get("path") or att.get("local_path") or "").strip()
        url = str(att.get("url") or att.get("download_url") or "").strip()
        if (not path) and url:
            local_from_url = _resolve_upload_url_to_path(url, settings)
            if local_from_url:
                path = local_from_url

        if source == "path":
            if path and os.path.exists(path):
                resized = _resize_image_path(path, max_dim=max_dim, jpeg_quality=jpeg_quality)
                return {"type": "image", "image": resized or path}
            return None
        if source == "url":
            if url:
                if url.startswith("/") and base_url:
                    url = f"{base_url}{url}"
                elif url.startswith("/"):
                    url = f"http://127.0.0.1:8000{url}"
                return {"type": "image_url", "image_url": {"url": url}}
            return None
        if source == "data_uri":
            if path:
                data_uri = _file_to_data_uri(path, fmt=fmt, jpeg_quality=jpeg_quality, max_dim=max_dim)
                if data_uri and (max_data_uri_len <= 0 or len(data_uri) <= max_data_uri_len):
                    return {"type": "image_url", "image_url": {"url": data_uri}}
            if url:
                if url.startswith("/") and base_url:
                    url = f"{base_url}{url}"
                elif url.startswith("/"):
                    local_from_url = _resolve_upload_url_to_path(url, settings)
                    if local_from_url:
                        data_uri = _file_to_data_uri(local_from_url, fmt=fmt, jpeg_quality=jpeg_quality, max_dim=max_dim)
                        if data_uri and (max_data_uri_len <= 0 or len(data_uri) <= max_data_uri_len):
                            return {"type": "image_url", "image_url": {"url": data_uri}}
                    url = f"http://127.0.0.1:8000{url}"
                return {"type": "image_url", "image_url": {"url": url}}
            return None

        # auto: prefer local path, then url; never inline base64 unless explicitly requested
        if path and os.path.exists(path):
            resized = _resize_image_path(path, max_dim=max_dim, jpeg_quality=jpeg_quality)
            return {"type": "image", "image": resized or path}
        if url:
            if url.startswith("/") and base_url:
                url = f"{base_url}{url}"
            elif url.startswith("/"):
                local_from_url = _resolve_upload_url_to_path(url, settings)
                if local_from_url:
                    return {"type": "image", "image": local_from_url}
                url = f"http://127.0.0.1:8000{url}"
            return {"type": "image_url", "image_url": {"url": url}}
        return None

    def _extract_user_text(self, req: Any) -> str:
        ext = None
        if isinstance(req, dict):
            ext = req.get("ext")
        else:
            ext = getattr(req, "ext", None)
        if isinstance(ext, dict):
            last = str(ext.get("last_user_content") or "").strip()
            if last:
                return last
        msgs = getattr(req, "messages", None)
        if isinstance(msgs, list) and msgs:
            last_user = None
            for m in reversed(msgs):
                if not isinstance(m, dict):
                    continue
                if (m.get("role") or "").lower() == "user":
                    last_user = m
                    break
            if last_user is None and isinstance(msgs[-1], dict):
                last_user = msgs[-1]
            if isinstance(last_user, dict):
                content = last_user.get("content") or ""
                if isinstance(content, list):
                    parts = []
                    for part in content:
                        if isinstance(part, dict):
                            t = part.get("text") or part.get("content") or ""
                            if t:
                                parts.append(str(t))
                    return "\n".join(parts)
                if isinstance(content, dict):
                    return str(content.get("text") or content.get("content") or "")
                return str(content)
        return ""

    def _merge_settings(self, req: Any) -> Dict[str, Any]:
        settings: Dict[str, Any] = dict(self.core.settings or {})
        ext = getattr(req, "ext", None)
        if isinstance(ext, dict):
            settings.update(_plugin_settings_from_ext(ext, self.route_id))
        return settings

    def _to_int(self, v: Any, default: int) -> int:
        try:
            if v is None or v == "":
                return int(default)
            return int(float(v))
        except Exception:
            return int(default)

    def _to_float(self, v: Any, default: float) -> float:
        try:
            if v is None or v == "":
                return float(default)
            return float(v)
        except Exception:
            return float(default)


def build_routes(core: RouterCore) -> list[BaseRoute]:
    return [ImageReaderRoute(core=core)]
