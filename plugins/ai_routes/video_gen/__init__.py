from __future__ import annotations

from typing import Any, Dict, Optional

from plugins.ai_routes.base import BaseRoute, RouterCore
from plugins.ai_routes.model_deck_utils import VideoGenRunner


PLUGIN_ID = "video_gen"
PLUGIN_TITLE = "Video Gen"
PLUGIN_NAME = "Video Gen"
PLUGIN_DESCRIPTION = "Text-to-video generation using the model_deck video_gen default model."
PLUGIN_TYPE = "control"
AGENT_LINKABLE = True
MODEL_TYPE = "video_gen"

PLUGIN_CONFIG_SCHEMA = [
    {"key": "video_gen_width", "label": "Width", "type": "int", "default": "848"},
    {"key": "video_gen_height", "label": "Height", "type": "int", "default": "480"},
    {"key": "video_gen_frames", "label": "Frames", "type": "int", "default": "32"},
    {"key": "video_gen_fps", "label": "FPS", "type": "int", "default": "16"},
    {"key": "video_gen_steps", "label": "Inference steps", "type": "int", "default": "50"},
    {"key": "video_gen_guidance", "label": "Guidance scale", "type": "float", "default": "6.0"},
    {"key": "video_gen_seed", "label": "Seed", "type": "int", "default": ""},
    {"key": "video_gen_use_worker", "label": "Use worker process", "type": "bool", "default": "1"},
    {"key": "video_gen_worker_timeout_s", "label": "Worker timeout (s, 0=disable)", "type": "int", "default": "0"},
]


class VideoGenRoute(BaseRoute):
    route_id = "video_gen"
    MODEL_TYPE = MODEL_TYPE
    short_description = "Generate a video from a text prompt using the model_deck video_gen default."
    backend_types: set[str] = {"hf", "hf_assist", "gguf", "vllm", "auto"}

    def handle(self, req: Any) -> Any:
        prompt = self._extract_user_text(req)
        if not prompt.strip():
            return {"route_id": self.route_id, "ok": False, "error": "empty_prompt"}

        settings = self._merge_settings(req)
        if self._is_canceled(settings):
            return {"route_id": self.route_id, "ok": False, "error": "canceled"}
        cancel_cb = self._cancel_cb(settings)
        use_worker = bool(self._to_int(settings.get("video_gen_use_worker"), 1))
        worker_timeout = self._to_int(settings.get("video_gen_worker_timeout_s"), 0)
        runner = VideoGenRunner(
            core=self.core,
            settings=settings,
            model_type=self.MODEL_TYPE,
            prefer_worker=use_worker,
            worker_timeout=worker_timeout,
        )
        if getattr(runner, "error", None):
            return {"route_id": self.route_id, "ok": False, "error": runner.error}
        info = getattr(runner, "info", {}) or {}

        self.emit_status("Loading video model...", step=0, total=1)

        model_settings = dict(info.get("settings") or {})

        width = self._to_int(settings.get("video_gen_width"), 0) or self._to_int(model_settings.get("width"), 848)
        height = self._to_int(settings.get("video_gen_height"), 0) or self._to_int(model_settings.get("height"), 480)
        frames = self._to_int(settings.get("video_gen_frames"), 0) or self._to_int(model_settings.get("frames"), 32)
        fps = self._to_int(settings.get("video_gen_fps"), 0) or self._to_int(model_settings.get("fps"), 16)
        steps = self._to_int(settings.get("video_gen_steps"), 0) or self._to_int(model_settings.get("steps"), 50)
        guidance = self._to_float(settings.get("video_gen_guidance"), 0.0)
        if guidance <= 0:
            guidance = self._to_float(model_settings.get("guidance_scale"), 6.0)

        seed = settings.get("video_gen_seed")
        if seed in (None, ""):
            seed = model_settings.get("seed")
        seed_val = None
        if seed not in (None, ""):
            try:
                seed_val = int(seed)
            except Exception:
                seed_val = None

        self.emit_status(f"Rendering video ({steps} steps)...", step=0, total=steps)
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
            self.emit_status(f"Rendering video ({step_i}/{total_i})...", step=step_i, total=total_i)

        try:
            result = runner.generate(
                prompt=prompt,
                num_frames=frames,
                num_inference_steps=steps,
                guidance_scale=guidance,
                width=width,
                height=height,
                fps=fps,
                seed=seed_val,
                progress_callback=_progress,
                cancel_cb=cancel_cb,
            )
        except RuntimeError as exc:
            if str(exc).lower().startswith("canceled"):
                return {"route_id": self.route_id, "ok": False, "error": "canceled"}
            raise
        if not result.get("ok"):
            return {"route_id": self.route_id, "ok": False, "error": result.get("error") or "video_gen_failed"}
        out_path = result.get("out_path") or ""
        url = result.get("url") or ""
        self.emit_status("Video generation complete.", step=steps, total=steps)
        return {
            "route_id": self.route_id,
            "ok": True,
            "prompt": prompt,
            "video_path": out_path,
            "video_url": url,
            "gen_settings": {
                "width": width,
                "height": height,
                "frames": frames,
                "fps": fps,
                "steps": steps,
                "guidance_scale": guidance,
                "seed": seed_val,
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
        ext = getattr(req, "ext", None)
        if isinstance(ext, dict):
            over = ext.get("video_gen_settings")
            if isinstance(over, dict):
                settings.update(over)
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
    return [VideoGenRoute(core=core)]
