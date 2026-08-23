from __future__ import annotations

from typing import Any, Dict, Optional

from plugins.ai_routes.base import BaseRoute, RouterCore
from plugins.ai_routes.model_deck_utils import ImageGenRunner, normalize_workflow_media_inputs


PLUGIN_ID = "image_gen"
PLUGIN_TITLE = "Image Gen"
PLUGIN_NAME = "Image Gen"
PLUGIN_DESCRIPTION = "Text-to-image generation using the model_deck image_gen default model."
PLUGIN_TYPE = "control"
AGENT_LINKABLE = True
MODEL_TYPE = "image_gen"

PLUGIN_CONFIG_SCHEMA = [
    {"key": "image_gen_width", "label": "Width", "type": "int", "default": "1024"},
    {"key": "image_gen_height", "label": "Height", "type": "int", "default": "1024"},
    {"key": "image_gen_steps", "label": "Inference steps", "type": "int", "default": "30"},
    {"key": "image_gen_guidance", "label": "Guidance scale", "type": "float", "default": "7.0"},
    {"key": "image_gen_seed", "label": "Seed", "type": "int", "default": ""},
    {"key": "image_gen_system_prompt", "label": "System prompt", "type": "str", "default": ""},
    {"key": "image_gen_use_prompt_embeds", "label": "Use prompt embeddings", "type": "bool", "default": "0"},
    {"key": "image_gen_negative_prompt", "label": "Negative prompt", "type": "str", "default": ""},
    {
        "key": "image_gen_format",
        "label": "Image format",
        "type": "enum",
        "options": ["png", "jpeg"],
        "default": "png",
    },
    {"key": "image_gen_use_worker", "label": "Use worker process", "type": "bool", "default": "1"},
    {"key": "image_gen_worker_timeout_s", "label": "Worker timeout (s, 0 = disabled)", "type": "int", "default": "600"},
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



class ImageGenRoute(BaseRoute):
    route_id = "image_gen"
    MODEL_TYPE = MODEL_TYPE
    short_description = "Generate an image from a text prompt using the model_deck image_gen default."
    backend_types: set[str] = {"hf", "hf_assist", "gguf", "vllm", "auto"}

    def handle(self, req: Any) -> Any:
        prompt = self._extract_user_text(req)
        if not prompt.strip():
            return {"route_id": self.route_id, "ok": False, "error": "empty_prompt"}

        def _emit_status(status: str, *, phase: str = "", step: Optional[int] = None, total: Optional[int] = None) -> None:
            cb = None
            try:
                cb = (self.core.settings or {}).get("__router_diag_cb")
            except Exception:
                cb = None
            if not callable(cb):
                return
            payload: Dict[str, Any] = {"router_status": status, "route_id": self.route_id}
            if phase:
                payload["phase"] = phase
            if step is not None:
                payload["step"] = int(step)
            if total is not None:
                payload["total"] = int(total)
            try:
                cb(payload)
            except Exception:
                pass

        settings = self._merge_settings(req)
        media_inputs = normalize_workflow_media_inputs(req)
        if media_inputs:
            settings.update(media_inputs)
            model_overrides = settings.get("image_gen_model_settings")
            if not isinstance(model_overrides, dict):
                model_overrides = {}
            model_overrides.update(media_inputs)
            settings["image_gen_model_settings"] = model_overrides
        cancel_cb = self._cancel_cb(settings)
        if self._is_canceled(settings):
            return {"route_id": self.route_id, "ok": False, "error": "canceled"}
        system_prompt = str(settings.get("image_gen_system_prompt") or "").strip()
        if system_prompt:
            prompt = f"{system_prompt}\n{prompt}"
        if settings.get("debug_prompt_embeds"):
            try:
                print(
                    "[image_gen] debug_prompt_embeds",
                    {
                        "use_prompt_embeds": settings.get("image_gen_use_prompt_embeds"),
                        "prompt_chars": len(prompt or ""),
                        "negative_prompt_chars": len(str(settings.get("image_gen_negative_prompt") or "")),
                    },
                )
            except Exception:
                pass
        use_worker = bool(self._to_int(settings.get("image_gen_use_worker"), 1))
        worker_timeout = self._to_int(settings.get("image_gen_worker_timeout_s"), 600)
        runner = self.prepare_image_gen_runner(
            settings=settings,
            model_type=self.MODEL_TYPE,
            prefer_worker=use_worker,
            worker_timeout=worker_timeout,
        )
        if getattr(runner, "error", None):
            return {"route_id": self.route_id, "ok": False, "error": runner.error}
        info = getattr(runner, "info", {}) or {}

        _emit_status("Loading image model...", phase="loading")

        model_settings = dict(info.get("settings") or {})

        negative_prompt = str(settings.get("image_gen_negative_prompt") or "").strip()
        if not negative_prompt:
            negative_prompt = str(model_settings.get("negative_prompt") or "").strip()
        negative_prompt = negative_prompt or None

        width = self._to_int(settings.get("image_gen_width"), 0) or self._to_int(model_settings.get("width"), 1024)
        height = self._to_int(settings.get("image_gen_height"), 0) or self._to_int(model_settings.get("height"), 1024)
        steps = self._to_int(settings.get("image_gen_steps"), 0) or self._to_int(model_settings.get("steps"), 30)
        guidance = self._to_float(settings.get("image_gen_guidance"), 0.0)
        if guidance <= 0:
            guidance = self._to_float(model_settings.get("cfg_scale"), 7.0)

        seed = settings.get("image_gen_seed")
        if seed in (None, ""):
            seed = model_settings.get("seed")
        seed_val = None
        if seed not in (None, ""):
            try:
                seed_val = int(seed)
            except Exception:
                seed_val = None

        fmt = str(settings.get("image_gen_format") or model_settings.get("output_ext") or "png").lower()
        if fmt not in ("png", "jpeg", "jpg"):
            fmt = "png"

        _emit_status(f"Rendering image ({steps} steps)...", phase="render", step=0, total=steps)
        last_step = {"value": -1}

        def _progress(step: int, total: int) -> None:
            if callable(cancel_cb) and cancel_cb():
                raise RuntimeError("canceled")
            try:
                step_i = int(step)
                total_i = int(total)
            except Exception:
                return
            if step_i <= last_step["value"]:
                return
            last_step["value"] = step_i
            _emit_status(
                f"Rendering image ({step_i}/{total_i})...",
                phase="render",
                step=step_i,
                total=total_i,
            )

        try:
            result = runner.generate(
                prompt=prompt,
                negative_prompt=negative_prompt,
                num_inference_steps=steps,
                guidance_scale=guidance,
                width=width,
                height=height,
                seed=seed_val,
                fmt=fmt,
                progress_callback=_progress,
                cancel_cb=cancel_cb,
            )
        except RuntimeError as exc:
            if str(exc).lower().startswith("canceled"):
                return {"route_id": self.route_id, "ok": False, "error": "canceled"}
            raise
        if not result.get("ok"):
            out = {"route_id": self.route_id, "ok": False, "error": result.get("error") or "image_gen_failed"}
            if result.get("trace"):
                out["trace"] = result.get("trace")
            return out
        out_path = result.get("out_path") or ""
        url = result.get("url") or ""
        _emit_status("Saving image...", phase="save")
        _emit_status("Image generation complete.", phase="done", step=steps, total=steps)
        return {
            "route_id": self.route_id,
            "ok": True,
            "prompt": prompt,
            "image_path": out_path,
            "image_url": url,
            "gen_settings": {
                "width": width,
                "height": height,
                "steps": steps,
                "guidance_scale": guidance,
                "seed": seed_val,
                "format": fmt,
            },
        }

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
        ext = req.get("ext") if isinstance(req, dict) else getattr(req, "ext", None)
        if isinstance(ext, dict):
            settings.update(_plugin_settings_from_ext(ext, self.route_id))
        if "image_gen_use_prompt_embeds" not in settings:
            settings["image_gen_use_prompt_embeds"] = False
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
    return [ImageGenRoute(core=core)]
