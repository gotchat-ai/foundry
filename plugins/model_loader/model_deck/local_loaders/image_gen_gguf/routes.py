from __future__ import annotations

import os
import shlex
import subprocess
import time
import inspect
from typing import Any, Dict, Optional, Tuple
from runtime_cuda import empty_accelerator_cache

from fastapi import APIRouter, Request, HTTPException
from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled

from plugins.model_loader.gguf import plugin as gguf_plugin
try:
    from plugins.gui_helpers._framework.event_bus import publish_gui_event
except Exception:
    publish_gui_event = None

GUI_PLUGIN_ID = "model_deck"
LOADER_ID = "model_loader.model_deck.image_gen_gguf"

_APP: Any = None
_STATE: Dict[str, Any] = {
    "loaded": False,
    "model_path": None,
    "settings": None,
    "ts": None,
}
_SDCPP: Optional[Any] = None
_SDCPP_LAST_KEY: Optional[str] = None
_INVALID_MODEL_REF_VALUES = {"", "none", "null", "undefined", "nan"}


def _clean_model_ref(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() in _INVALID_MODEL_REF_VALUES:
        return ""
    return text


def _resolve_model_path(settings: Dict[str, Any]) -> str:
    model_path = _clean_model_ref(settings.get("model_path") or settings.get("gguf_path"))
    if model_path:
        return model_path

    model_id = _clean_model_ref(settings.get("model_id") or settings.get("model"))
    gguf_filename = _clean_model_ref(settings.get("gguf_filename")) or None
    if not model_id:
        raise HTTPException(400, "model_path or model_id required")
    if _APP is None:
        raise HTTPException(400, "server_app_missing")
    return gguf_plugin._resolve_gguf_path(_APP, model_id, gguf_filename)


def _backend(settings: Dict[str, Any]) -> str:
    return str(settings.get("backend") or settings.get("image_gen_backend") or "gguf_cli").strip().lower()


def _sdcpp_key(settings: Dict[str, Any]) -> str:
    parts = [
        str(settings.get("model_path") or settings.get("gguf_path") or settings.get("model_id") or ""),
        str(settings.get("gguf_filename") or ""),
        str(settings.get("vae_path") or ""),
        str(settings.get("clip_path") or ""),
        str(settings.get("clip_l_path") or ""),
        str(settings.get("clip_g_path") or ""),
        str(settings.get("t5xxl_path") or ""),
        str(settings.get("t5_path") or ""),
        str(settings.get("device") or ""),
        str(settings.get("n_threads") or ""),
        str(settings.get("n_gpu_layers") or ""),
    ]
    return "|".join(parts)


def _normalize_sdcpp_device(raw: Any) -> Optional[str]:
    value = str(raw or "").strip().lower()
    if not value:
        return None
    runtime = str(os.environ.get("LLMLOADER2_RUNTIME") or "").strip().lower()
    if value == "xps":
        value = "xpu"
    if runtime in ("intel", "xpu", "sycl") and value in ("xpu", "sycl", "level_zero", "intel"):
        return "vulkan"
    return value


def _filter_kwargs(fn, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    try:
        sig = inspect.signature(fn)
    except Exception:
        return kwargs
    params = sig.parameters
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return kwargs
    allowed = {k for k in params.keys()}
    return {k: v for k, v in kwargs.items() if k in allowed}


def _sdcpp_build_kwargs(settings: Dict[str, Any]) -> Dict[str, Any]:
    model_path = _resolve_model_path(settings)
    device = _normalize_sdcpp_device(settings.get("device"))
    kwargs = {
        "model_path": model_path,
        "model": settings.get("model"),
        "vae_path": settings.get("vae_path"),
        "clip_path": settings.get("clip_path"),
        "clip_l_path": settings.get("clip_l_path"),
        "clip_g_path": settings.get("clip_g_path"),
        "t5xxl_path": settings.get("t5xxl_path"),
        "t5_path": settings.get("t5_path"),
        "device": device,
        "n_threads": settings.get("n_threads"),
        "n_gpu_layers": settings.get("n_gpu_layers"),
    }
    extra = settings.get("sdcpp_kwargs")
    if isinstance(extra, dict):
        kwargs.update(extra)
    return {k: v for k, v in kwargs.items() if v not in (None, "")}


def _sdcpp_load(settings: Dict[str, Any]) -> Any:
    global _SDCPP, _SDCPP_LAST_KEY
    key = _sdcpp_key(settings)
    if _SDCPP is not None and _SDCPP_LAST_KEY == key:
        return _SDCPP

    try:
        import stable_diffusion_cpp  # type: ignore
    except Exception as exc:
        raise HTTPException(500, f"stable_diffusion_cpp import failed: {exc}") from exc

    cls = getattr(stable_diffusion_cpp, "StableDiffusion", None)
    if cls is None:
        raise HTTPException(500, "stable_diffusion_cpp.StableDiffusion not found")

    kwargs = _sdcpp_build_kwargs(settings)
    kwargs = _filter_kwargs(cls.__init__, kwargs)
    try:
        _SDCPP = cls(**kwargs)
    except Exception as exc:
        raise HTTPException(500, f"sd_cpp load failed: {exc}") from exc
    _SDCPP_LAST_KEY = key
    return _SDCPP


def _sdcpp_txt2img(sd: Any, prompt: str, params: Dict[str, Any]) -> Any:
    fn = getattr(sd, "txt2img", None)
    if callable(fn):
        return fn(**_filter_kwargs(fn, params))
    if callable(sd):
        return sd(**_filter_kwargs(sd, params))
    raise HTTPException(500, "sd_cpp missing txt2img call")


def _sdcpp_normalize_image(out: Any) -> Any:
    if out is None:
        return None
    if hasattr(out, "images"):
        return out.images[0] if out.images else None
    if isinstance(out, (list, tuple)):
        return out[0] if out else None
    return out


def load(request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
    if str(settings.get("image_command_mode") or "standard").strip().lower() == "advanced":
        model_ref = str(settings.get("model_path") or settings.get("gguf_path") or settings.get("model_id") or "").strip()
        _STATE.update({
            "loaded": True,
            "model_path": model_ref or None,
            "settings": settings,
            "ts": int(time.time()),
        })
        if callable(publish_gui_event):
            try:
                publish_gui_event(
                    "processes.changed",
                    {"kind": "image_gen", "action": "load", "loader_id": LOADER_ID, "model_path": model_ref},
                )
            except Exception:
                pass
        return {
            "ok": True,
            "loader_id": LOADER_ID,
            "loaded": True,
            "model_path": model_ref,
            "mode": "advanced",
        }

    if _backend(settings) == "sd_cpp":
        _sdcpp_load(settings)
        _STATE.update({
            "loaded": True,
            "model_path": _resolve_model_path(settings),
            "settings": settings,
            "ts": int(time.time()),
        })
        if callable(publish_gui_event):
            try:
                publish_gui_event(
                    "processes.changed",
                    {"kind": "image_gen", "action": "load", "loader_id": LOADER_ID, "model_path": _STATE.get("model_path")},
                )
            except Exception:
                pass
        return {
            "ok": True,
            "loader_id": LOADER_ID,
            "loaded": True,
            "model_path": _STATE.get("model_path"),
        }

    model_path = _resolve_model_path(settings)
    if not os.path.isfile(model_path):
        raise HTTPException(400, f"model_path missing: {model_path}")

    _STATE.update({
        "loaded": True,
        "model_path": model_path,
        "settings": settings,
        "ts": int(time.time()),
    })
    if callable(publish_gui_event):
        try:
            publish_gui_event(
                "processes.changed",
                {"kind": "image_gen", "action": "load", "loader_id": LOADER_ID, "model_path": model_path},
            )
        except Exception:
            pass
    return {
        "ok": True,
        "loader_id": LOADER_ID,
        "loaded": True,
        "model_path": model_path,
    }


def unload(request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
    global _SDCPP, _SDCPP_LAST_KEY
    sd = _SDCPP
    _SDCPP = None
    _SDCPP_LAST_KEY = None
    try:
        import gc
        import torch
        if sd is not None and hasattr(sd, "close"):
            try:
                sd.close()
            except Exception:
                pass
        del sd
        gc.collect()
        empty_accelerator_cache(torch, str((_STATE.get("settings") or {}).get("device") or ""))
    except Exception:
        pass
    _STATE.update({
        "loaded": False,
        "model_path": None,
        "settings": None,
        "ts": None,
    })
    if callable(publish_gui_event):
        try:
            publish_gui_event(
                "processes.changed",
                {"kind": "image_gen", "action": "unload", "loader_id": LOADER_ID},
            )
        except Exception:
            pass
    return {"ok": True, "loader_id": LOADER_ID, "loaded": False}


def _settings_key(settings: Dict[str, Any]) -> str:
    parts = [
        str(settings.get("model_path") or settings.get("model_id") or ""),
        str(settings.get("gguf_filename") or ""),
        str(settings.get("cli_path") or ""),
        str(settings.get("cli_args") or ""),
    ]
    return "|".join(parts)


def ensure_loaded(settings: Dict[str, Any]) -> None:
    key = _settings_key(settings)
    if _STATE.get("loaded") and _STATE.get("settings") and _STATE.get("model_path"):
        if _settings_key(_STATE.get("settings") or {}) == key:
            return
    load(None, settings)


def generate_text2image(
    prompt: str,
    settings: Dict[str, Any],
    *,
    negative_prompt: Optional[str] = None,
    num_inference_steps: Optional[int] = None,
    guidance_scale: Optional[float] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    seed: Optional[int] = None,
    progress_callback: Optional[Any] = None,
) -> str:
    if _backend(settings) == "sd_cpp":
        sd = _sdcpp_load(settings)
        cb = None
        if callable(progress_callback):
            def _on_progress(step: int, steps: int, _time: float):
                try:
                    progress_callback(int(step) + 1, int(steps))
                except Exception:
                    pass
            cb = _on_progress
        params = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "steps": num_inference_steps,
            "cfg_scale": guidance_scale,
            "seed": seed,
            "progress_callback": cb,
        }
        params = {k: v for k, v in params.items() if v is not None}
        out = _sdcpp_txt2img(sd, prompt, params)
        image = _sdcpp_normalize_image(out)
        if image is None:
            raise HTTPException(500, "sd_cpp returned no image")
        out_dir = str(settings.get("output_dir") or "").strip()
        if not out_dir:
            base = None
            if _APP is not None:
                base = getattr(_APP.state, "data_dir", None) or getattr(_APP.state, "workdir", None)
            if not base:
                base = os.path.join(os.getcwd(), "data")
            out_dir = os.path.join(base, "uploads")
        os.makedirs(out_dir, exist_ok=True)
        ext = str(settings.get("output_ext") or "png").strip().lower()
        if ext not in ("png", "jpg", "jpeg", "webp"):
            ext = "png"
        out_path = os.path.join(out_dir, f"image_gen_{int(time.time())}_{os.getpid()}.{ext}")
        try:
            if ext in ("jpg", "jpeg"):
                image = image.convert("RGB")
                image.save(out_path, format="JPEG", quality=95)
            else:
                image.save(out_path, format="PNG")
        except Exception:
            image.save(out_path)
        return out_path

    ensure_loaded(settings)
    model_path = _STATE.get("model_path") or _resolve_model_path(settings)
    cli_path = str(settings.get("cli_path") or "").strip()
    if not cli_path:
        raise HTTPException(400, "cli_path required for GGUF image generation")
    if not os.path.exists(cli_path):
        raise HTTPException(400, f"cli_path missing: {cli_path}")

    out_dir = str(settings.get("output_dir") or "").strip()
    if not out_dir:
        base = None
        if _APP is not None:
            base = getattr(_APP.state, "data_dir", None) or getattr(_APP.state, "workdir", None)
        if not base:
            base = os.path.join(os.getcwd(), "data")
        out_dir = os.path.join(base, "uploads")
    os.makedirs(out_dir, exist_ok=True)

    ext = str(settings.get("output_ext") or "png").strip().lower()
    if ext not in ("png", "jpg", "jpeg", "webp"):
        ext = "png"
    out_path = os.path.join(out_dir, f"image_gen_{int(time.time())}_{os.getpid()}.{ext}")

    args_template = settings.get("cli_args")
    if isinstance(args_template, str) and args_template.strip():
        fmt = args_template
        seed_arg = f"--seed {seed}" if seed is not None else ""
        neg = negative_prompt or ""
        filled = fmt.format(
            model_path=model_path,
            prompt=prompt,
            out_path=out_path,
            width=width or "",
            height=height or "",
            steps=num_inference_steps or "",
            guidance=guidance_scale or "",
            negative_prompt=neg,
            seed=seed or "",
            seed_arg=seed_arg,
        )
        args = shlex.split(filled, posix=(os.name != "nt"))
        cmd = [cli_path] + args
    else:
        cmd = [
            cli_path,
            "--model",
            model_path,
            "--prompt",
            prompt,
            "--output",
            out_path,
        ]
        if width:
            cmd += ["--width", str(width)]
        if height:
            cmd += ["--height", str(height)]
        if num_inference_steps is not None:
            cmd += ["--steps", str(num_inference_steps)]
        if guidance_scale is not None:
            cmd += ["--cfg-scale", str(guidance_scale)]
        if negative_prompt:
            cmd += ["--negative-prompt", str(negative_prompt)]
        if seed is not None:
            cmd += ["--seed", str(seed)]

    timeout_s = int(settings.get("timeout_s") or 300)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    if proc.returncode != 0:
        raise HTTPException(500, f"image_gen_cli_failed: {proc.stderr.strip() or proc.stdout.strip()}")
    if not os.path.isfile(out_path):
        raise HTTPException(500, "image_gen_cli_no_output")
    return out_path


def install(app) -> None:
    global _APP
    _APP = app

    reg = getattr(app.state, "model_loader_registry", None)
    if isinstance(reg, dict):
        reg.setdefault(
            LOADER_ID,
            type(
                "DeckImageGenGgufStub",
                (),
                {"id": LOADER_ID, "name": "Model Deck ImageGen GGUF", "load": staticmethod(load), "unload": staticmethod(unload)},
            )(),
        )

    r = APIRouter()

    @r.get("/v1/model_loader/model_deck/image_gen_gguf/status")
    def status(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        return {"ok": True, "loader_id": LOADER_ID, "state": _STATE}

    app.include_router(r)
