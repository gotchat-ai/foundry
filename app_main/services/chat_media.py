import base64
import mimetypes
import os
import subprocess
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple


class ChatMediaService:
    """Message normalization, system prompt injection, and media/video OCR helpers."""

    def __init__(
        self,
        *,
        settings_getter: Callable[[], dict[str, Any]],
        data_dir_getter: Callable[[], str],
        local_path_from_upload_url: Callable[[str], str | None],
    ) -> None:
        self._settings_getter = settings_getter
        self._data_dir_getter = data_dir_getter
        self._local_path_from_upload_url = local_path_from_upload_url

    @property
    def settings(self) -> dict[str, Any]:
        try:
            return self._settings_getter() or {}
        except Exception:
            return {}

    @property
    def data_dir(self) -> str:
        return self._data_dir_getter() or os.path.abspath("./data")

    def _coerce_msg_to_dict(self, m):
        """Coerce various message shapes into {'role': str, 'content': str}."""
        if isinstance(m, dict):
            role = m.get("role") or getattr(m, "role", None) or "user"
            content = m.get("content") if "content" in m else getattr(m, "content", None)
            if isinstance(content, list):
                try:
                    keep_mm = False
                    for part in content:
                        if not isinstance(part, dict):
                            continue
                        ptype = str(part.get("type") or "").lower()
                        if ptype and ptype not in ("text", "input_text"):
                            keep_mm = True
                            break
                        if "image_url" in part or "image" in part or "input_image" in part:
                            keep_mm = True
                            break
                    if keep_mm:
                        return {"role": role or "user", "content": content}
                    parts = []
                    for part in content:
                        if isinstance(part, dict):
                            t = part.get("text") or part.get("content") or ""
                            if t:
                                parts.append(str(t))
                    content = "\n".join(parts) if parts else str(content)
                except Exception:
                    content = str(content)
            return {"role": role or "user", "content": "" if content is None else str(content)}

        role = getattr(m, "role", None)
        content = getattr(m, "content", None)
        if role is not None or content is not None:
            return {"role": role or "user", "content": "" if content is None else str(content)}
        if isinstance(m, (tuple, list)) and len(m) >= 2:
            return {"role": str(m[0] or "user"), "content": "" if m[1] is None else str(m[1])}
        return {"role": "system", "content": "" if m is None else str(m)}

    def _normalize_messages(self, messages):
        return [self._coerce_msg_to_dict(x) for x in (messages or []) if x is not None]

    def _normalize_messages_text_only(self, messages):
        """Normalize messages and coerce any multimodal content into plain text."""
        out = []
        for m in self._normalize_messages(messages):
            if not isinstance(m, dict):
                continue
            content = m.get("content")
            if isinstance(content, list):
                try:
                    parts = []
                    for part in content:
                        if isinstance(part, dict):
                            ptype = part.get("type")
                            if ptype in ("image", "image_url", "input_image"):
                                continue
                            t = part.get("text") or part.get("content") or ""
                            if t:
                                parts.append(str(t))
                    content = "\n".join(parts) if parts else ""
                except Exception:
                    content = ""
            if not isinstance(content, str):
                content = str(content or "")
            out.append({"role": m.get("role") or "user", "content": content})
        return out

    def _collect_system_prompts_from_ext(self, ext: Dict[str, Any]) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        if not isinstance(ext, dict):
            return out
        sp_legacy = ext.get("system_prompt")
        if isinstance(sp_legacy, str) and sp_legacy.strip():
            out.append({"id": "system_prompt", "content": sp_legacy.strip()})
        sp = ext.get("system_prompts")
        if isinstance(sp, dict):
            items: List[Dict[str, str]] = []
            for k, v in sp.items():
                if not isinstance(v, str):
                    continue
                txt = v.strip()
                if txt:
                    items.append({"id": str(k), "content": txt})
            order = ext.get("system_prompts_order")
            if isinstance(order, list) and order:
                rank = {str(x): i for i, x in enumerate(order)}
                items.sort(key=lambda it: (rank.get(it["id"], 10_000), it["id"]))
            else:
                items.sort(key=lambda it: it["id"])
            out.extend(items)
            return out
        if isinstance(sp, list):
            items2: List[Dict[str, str]] = []
            for it in sp:
                if not isinstance(it, dict):
                    continue
                pid = str(it.get("id") or it.get("plugin_id") or "").strip()
                txt = it.get("content") if "content" in it else it.get("text")
                if not isinstance(txt, str):
                    continue
                txt = txt.strip()
                if not txt:
                    continue
                if not pid:
                    pid = "system_prompts"
                items2.append({"id": pid, "content": txt})
            order = ext.get("system_prompts_order")
            if isinstance(order, list) and order:
                rank = {str(x): i for i, x in enumerate(order)}
                items2.sort(key=lambda it: (rank.get(it["id"], 10_000), it["id"]))
            else:
                items2.sort(key=lambda it: it["id"])
            out.extend(items2)
        return out

    def _build_system_prompt_preamble(self, snippets: List[Dict[str, str]]) -> str:
        parts: List[str] = []
        for it in snippets:
            pid = str(it.get("id") or "").strip()
            txt = str(it.get("content") or "").strip()
            if not txt:
                continue
            if pid:
                parts.append(f"[{pid}]\n{txt}")
            else:
                parts.append(txt)
        return "\n\n".join(parts).strip()

    def _inject_system_prompts_into_messages(self, messages: List[Dict[str, Any]], ext: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(messages, list) or not messages:
            return messages
        if not isinstance(ext, dict):
            return messages
        snippets = self._collect_system_prompts_from_ext(ext)
        if not snippets:
            return messages
        preamble = self._build_system_prompt_preamble(snippets)
        if not preamble:
            return messages
        mode = str(ext.get("system_prompts_mode") or "user").strip().lower()
        marker = str(ext.get("system_prompts_marker") or "[[system_prompts]]").strip()
        try:
            for m in messages:
                if isinstance(m, dict) and isinstance(m.get("content"), str):
                    if marker and marker in m["content"]:
                        return messages
        except Exception:
            pass
        if mode == "system":
            return [{"role": "system", "content": f"{marker}\n{preamble}\n{marker}"}] + messages
        out = [dict(m) if isinstance(m, dict) else m for m in messages]
        for i in range(len(out) - 1, -1, -1):
            m = out[i]
            if not isinstance(m, dict):
                continue
            if str(m.get("role") or "").lower() != "user":
                continue
            content = m.get("content")
            if not isinstance(content, str):
                content = str(content or "")
            m["content"] = f"{marker}\n{preamble}\n{marker}\n\n{content}"
            out[i] = m
            return out
        return [{"role": "system", "content": f"{marker}\n{preamble}\n{marker}"}] + out

    def _fold_pjsonr_system_context_into_last_user(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        msgs = self._normalize_messages(messages)
        if not msgs:
            return msgs

        def _is_pjsonr_block(text: str) -> bool:
            t = str(text or "")
            if not t.strip():
                return False
            hits = 0
            for needle in ("PAGE:", "CONTEXT_NAME:", "JSON_URL:", "JSON_EXCERPTS", "FETCH_MORE:", "```pjsonr"):
                if needle in t:
                    hits += 1
            return hits >= 2

        pjsonr_blocks: List[str] = []
        kept: List[Dict[str, Any]] = []
        for m in msgs:
            try:
                if (m.get("role") == "system") and _is_pjsonr_block(m.get("content") or ""):
                    pjsonr_blocks.append(str(m.get("content") or ""))
                    continue
            except Exception:
                pass
            kept.append(m)
        if not pjsonr_blocks:
            return msgs
        marker = "[[pjsonr_context]]"
        ctx_text = "\n\n---\n\n".join([b for b in pjsonr_blocks if str(b or "").strip()]).strip()
        if not ctx_text:
            return kept
        out = [dict(m) if isinstance(m, dict) else m for m in kept]
        for i in range(len(out) - 1, -1, -1):
            m = out[i]
            if not isinstance(m, dict):
                continue
            if str(m.get("role") or "").lower() != "user":
                continue
            content = m.get("content")
            if not isinstance(content, str):
                content = str(content or "")
            if marker in content:
                out[i] = {"role": "user", "content": content}
                return out
            out[i] = {"role": "user", "content": f"{content}\n\n{marker}\n{ctx_text}\n{marker}"}
            return out
        out.append({"role": "user", "content": f"{marker}\n{ctx_text}\n{marker}"})
        return out

    def _inject_attachments_into_messages(self, messages: List[Dict[str, Any]], ext: Dict[str, Any], *, base_url: str = "") -> List[Dict[str, Any]]:
        if not isinstance(messages, list) or not messages:
            return messages
        if not isinstance(ext, dict):
            return messages
        src = ext.get("attachments") or ext.get("media_attachments") or []
        if isinstance(src, dict):
            src = src.get("items") or src.get("attachments") or []
        if not isinstance(src, list) or not src:
            return messages
        marker = str(ext.get("attachments_marker") or "[[attachments]]").strip()

        def _pick_url(a: Dict[str, Any]) -> str:
            url = a.get("path") or a.get("local_path") or a.get("url") or a.get("download_url") or ""
            if not isinstance(url, str):
                return ""
            data_dir = os.path.abspath("./data")
            url = os.path.join(data_dir, url)
            return url

        out = [dict(m) if isinstance(m, dict) else m for m in messages]
        for i in range(len(out) - 1, -1, -1):
            m = out[i]
            if not isinstance(m, dict):
                continue
            if str(m.get("role") or "").lower() != "user":
                continue
            content = m.get("content")
            text_parts: List[str] = []
            has_mm_part = False
            if isinstance(content, list):
                try:
                    for part in content:
                        if not isinstance(part, dict):
                            continue
                        ptype = part.get("type")
                        if ptype in ("image", "image_url", "input_image"):
                            has_mm_part = True
                            continue
                        t = part.get("text") or part.get("content") or ""
                        if t:
                            text_parts.append(str(t))
                except Exception:
                    text_parts = []
            content_text = "\n".join(text_parts) if text_parts else ""
            if not isinstance(content, list):
                content_text = str(content or "")
            att_text_lines: List[str] = []
            image_parts: List[Dict[str, Any]] = []
            seen_media: set[str] = set()
            for a in src:
                if not isinstance(a, dict):
                    continue
                url = _pick_url(a)
                local_path = a.get("path") or a.get("local_path") or ""
                if not local_path and url:
                    try:
                        local_path = self._local_path_from_upload_url(url) or ""
                    except Exception:
                        local_path = ""
                key = str(local_path or url or "")
                if key and key in seen_media:
                    continue
                if key:
                    seen_media.add(key)
                name = a.get("name") or a.get("filename") or a.get("file_name")
                if local_path and os.path.exists(str(local_path)):
                    try:
                        with open(str(local_path), "rb") as image_file:
                            encoded = base64.b64encode(image_file.read()).decode("utf-8")
                        mime = a.get("mime") or mimetypes.guess_type(str(local_path))[0] or "image/jpeg"
                        part = {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}
                        if name:
                            part["name"] = str(name)
                        image_parts.append(part)
                    except Exception:
                        pass
                elif url:
                    part = {"type": "image_url", "image_url": {"url": url}}
                    if name:
                        part["name"] = str(name)
                    image_parts.append(part)
                if not url:
                    continue
                if name:
                    att_text_lines.append(f"- {name}: {url}")
                else:
                    att_text_lines.append(f"- {url}")
            if image_parts:
                if has_mm_part:
                    return out
                parts = list(image_parts)
                if content_text:
                    parts.append({"type": "text", "text": content_text})
                m["content"] = parts
                out[i] = m
                return out
            if att_text_lines:
                att_text = f"{marker}\n" + "\n".join(att_text_lines) + f"\n{marker}"
                if isinstance(content, list):
                    if has_mm_part:
                        return out
                    parts = list(content)
                    parts.append({"type": "text", "text": att_text})
                    m["content"] = parts
                else:
                    m["content"] = f"{content_text}\n\n{att_text}" if content_text else att_text
                out[i] = m
            return out
        print(messages)
        return messages

    def _extract_attachments_from_req_or_payload(self, req_or_payload: Any) -> List[Dict[str, Any]]:
        if isinstance(req_or_payload, dict):
            src = req_or_payload.get("attachments") or []
            if not src:
                ext = req_or_payload.get("ext") if isinstance(req_or_payload.get("ext"), dict) else {}
                src = (ext or {}).get("attachments") or (ext or {}).get("media_attachments") or []
        else:
            src = getattr(req_or_payload, "attachments", None) or []
            if not src:
                ext = getattr(req_or_payload, "ext", None)
                if isinstance(ext, dict):
                    src = ext.get("attachments") or ext.get("media_attachments") or []
        seq = src if isinstance(src, (list, tuple)) else [src]
        out = []
        for a in seq:
            d = a.model_dump(exclude_none=True) if hasattr(a, "model_dump") else (a.dict(exclude_none=True) if hasattr(a, "dict") else dict(a))
            out.append({
                **d,
                "name": d.get("name") or d.get("filename") or d.get("file_name"),
                "mime": (d.get("mime") or d.get("content_type") or d.get("type") or "").lower(),
                "path": d.get("path") or d.get("local_path"),
                "url": d.get("url") or d.get("href"),
                "b64": d.get("b64") or d.get("base64"),
                "kind": (d.get("kind") or d.get("role") or d.get("category") or "").lower(),
                "rag_target": (d.get("rag_target") or d.get("target") or d.get("store") or "").lower(),
            })
        return out

    def _is_video_mime(self, m: Optional[str]) -> bool:
        return bool(m) and (m.startswith("video/") or m in {"application/octet-stream"})

    def _ffmpeg_exists(self) -> bool:
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True)
            return True
        except Exception:
            return False

    def _ensure_media_mount(self, sid: str) -> str:
        base = os.path.join(self.data_dir, "sessions", sid, "media")
        os.makedirs(base, exist_ok=True)
        return base

    def _ensure_media_url(self, local_path: str, sid: str) -> Optional[str]:
        base_rel = os.path.relpath(local_path, os.path.join(self.data_dir, "sessions"))
        return f"/media/{base_rel.replace(os.sep, '/')}"

    def _make_short_clip(self, src_path: str, dst_path: str, start_sec: float, dur_sec: float) -> bool:
        if not self._ffmpeg_exists():
            return False
        try:
            cmd = ["ffmpeg", "-y", "-ss", str(start_sec), "-t", str(dur_sec), "-i", src_path, "-an", "-c:v", "libx264", "-preset", "veryfast", dst_path]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            return proc.returncode == 0 and os.path.exists(dst_path) and os.path.getsize(dst_path) > 0
        except Exception:
            return False

    def _extract_key_frames_for_ocr(self, video_path: str, out_dir: str, max_frames: int) -> List[str]:
        if not self._ffmpeg_exists():
            return []
        made = []
        try:
            for i in range(max_frames):
                ts = i * 0.8
                out = os.path.join(out_dir, f"ocr_frame_{i}.png")
                proc = subprocess.run(["ffmpeg", "-y", "-ss", str(ts), "-i", video_path, "-vframes", "1", out], capture_output=True, text=True, timeout=60)
                if proc.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
                    made.append(out)
        except Exception:
            return []
        return made

    def _ocr_on_image_paths(self, img_paths: List[str]) -> str:
        try:
            from PIL import Image
            import pytesseract
        except Exception:
            return ""
        texts = []
        for p in img_paths:
            try:
                if os.path.exists(p):
                    t = pytesseract.image_to_string(Image.open(p))
                    if t and t.strip():
                        texts.append(t.strip())
            except Exception:
                pass
        return "\n".join(texts)

    def _inject_ocr_into_prompt(self, req_or_payload: Any, sid: str, base_prompt: str) -> Tuple[str, Dict[str, Any]]:
        cfg = self._video_ocr_cfg(self.settings)
        if not cfg["enabled"]:
            return base_prompt, {"enabled": False}
        atts = self._extract_attachments_from_req_or_payload(req_or_payload)
        media_root = self._ensure_media_mount(sid)
        img_candidates: List[str] = []
        for a in atts:
            if a.get("kind") == "video" or self._is_video_mime(a.get("mime")):
                p = a.get("path")
                if p and os.path.exists(p):
                    img_candidates += self._extract_key_frames_for_ocr(p, media_root, max_frames=cfg["max_frames"])
            elif (a.get("mime") or "").startswith("image/") and a.get("path") and os.path.exists(a["path"]):
                img_candidates.append(a["path"])
        ocr_text = self._ocr_on_image_paths(img_candidates)
        if not ocr_text.strip():
            return base_prompt, {"enabled": True, "frames": len(img_candidates), "added_chars": 0}
        new_prompt = f"{base_prompt}\n\n[OCR]\n{ocr_text}\n[/OCR]\n"
        return new_prompt, {"enabled": True, "frames": len(img_candidates), "added_chars": len(ocr_text), "text": ocr_text}

    def _transform_video_attachments(self, req_or_payload: Any, sid: str, request: Any = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        cfg = self._video_ocr_cfg(self.settings)
        mode = cfg["mode"]
        clip_seconds = cfg["clip_seconds"]
        atts = self._extract_attachments_from_req_or_payload(req_or_payload)
        out: List[Dict[str, Any]] = []
        meta = {"mode": mode, "transformed": [], "skipped": []}
        media_root = self._ensure_media_mount(sid)
        for a in atts:
            if not any([a.get("path"), a.get("url"), a.get("b64")]) or not (self._is_video_mime(a.get("mime")) or a.get("kind") == "video"):
                out.append(a)
                continue
            local_path = a.get("path") if a.get("path") and os.path.exists(a["path"]) else None
            if mode == "url":
                if local_path:
                    url = self._ensure_media_url(local_path, sid)
                    out.append({**a, "url": url, "kind": "video", "mime": a.get("mime") or "video/mp4"})
                    meta["transformed"].append({"name": a.get("name"), "as": "url", "url": url})
                else:
                    out.append(a)
                    meta["skipped"].append({"name": a.get("name"), "reason": "no_local_path_for_url_mode"})
                continue
            if local_path:
                clip_name = f"clip_{uuid.uuid4().hex}.mp4"
                clip_path = os.path.join(media_root, clip_name)
                ok = self._make_short_clip(local_path, clip_path, start_sec=0.0, dur_sec=float(clip_seconds))
                if ok:
                    url = self._ensure_media_url(clip_path, sid)
                    out.append({**a, "path": clip_path, "url": url, "kind": "video", "mime": "video/mp4", "name": a.get("name") or clip_name})
                    meta["transformed"].append({"name": a.get("name"), "as": "clip", "path": clip_path, "url": url})
                    continue
            out.append(a)
            meta["skipped"].append({"name": a.get("name"), "reason": "clip_failed_or_no_path"})
        return out, meta

    def _collect_keys_with_prefix(self, obj: Any, prefix: str = "video_ocr_") -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        def rec(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    if isinstance(k, str) and k.startswith(prefix):
                        out[k] = v
                    rec(v)
            elif isinstance(x, list):
                for i in x:
                    rec(i)
        rec(obj or {})
        return out

    def _video_ocr_cfg(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        raw = self._collect_keys_with_prefix(settings, "video_ocr_")
        return {
            "enabled": bool(raw.get("video_ocr_enabled", False)),
            "mode": str(raw.get("video_ocr_mode", "clip")).lower(),
            "clip_seconds": float(raw.get("video_ocr_clip_seconds", 3)),
            "max_frames": int(raw.get("video_ocr_max_frames", 3)),
            "echo_in_messages": bool(raw.get("video_ocr_echo_in_messages", False)),
            "echo_text_in_ext": bool(raw.get("video_ocr_echo_text_in_ext", False)),
            "serve_base": raw.get("video_ocr_serve_base", None),
        }

