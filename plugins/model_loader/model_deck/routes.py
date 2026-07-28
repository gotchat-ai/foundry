from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

from plugins.gui_helpers._framework.services import get_plugin_service
from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled

from .schema_utils import load_schema_dir, merge_defaults, validate_required
from .local_loaders import diffusers as diffusers_loader
from .local_loaders import video as video_loader
from .local_loaders import three_d as three_d_loader
from .local_loaders import text_llm as text_llm_loader
from .local_loaders import vlm as vlm_loader
from .local_loaders import os_agent as os_agent_loader
from .local_loaders import retrieval as retrieval_loader
from .local_loaders import safety as safety_loader
from .local_loaders import speech as speech_loader
from .local_loaders import image_gen_gguf as image_gen_gguf_loader

GUI_PLUGIN_ID = "model_deck"
LOADER_ID = "model_loader.model_deck"
_LOCAL_LOADERS = {
    diffusers_loader.LOADER_ID: diffusers_loader,
    video_loader.LOADER_ID: video_loader,
    three_d_loader.LOADER_ID: three_d_loader,
    text_llm_loader.LOADER_ID: text_llm_loader,
    vlm_loader.LOADER_ID: vlm_loader,
    os_agent_loader.LOADER_ID: os_agent_loader,
    retrieval_loader.LOADER_ID: retrieval_loader,
    safety_loader.LOADER_ID: safety_loader,
    speech_loader.LOADER_ID: speech_loader,
    image_gen_gguf_loader.LOADER_ID: image_gen_gguf_loader,
}


def _schema_dir() -> str:
    return os.path.join(os.path.dirname(__file__), "schemas")


def _current_runtime() -> str:
    return str(os.environ.get("LLMLOADER2_RUNTIME") or "").strip().lower()


def _find_field(fields: list[dict[str, Any]], key: str) -> Optional[dict[str, Any]]:
    for field in fields:
        if not isinstance(field, dict):
            continue
        if str(field.get("key") or "").strip() == key:
            return field
    return None


def _find_fields(fields: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        if str(field.get("key") or "").strip() == key:
            out.append(field)
    return out


def _insert_field_after(fields: list[dict[str, Any]], after_key: str, field: dict[str, Any]) -> None:
    for idx, current in enumerate(fields):
        if not isinstance(current, dict):
            continue
        if str(current.get("key") or "").strip() == after_key:
            fields.insert(idx + 1, field)
            return
    fields.append(field)


def _intel_gpu_choices() -> list[dict[str, Any]]:
    py = shutil.which("python") or sys.executable
    if not py:
        return []
    probe = r"""
import json
out = []
try:
    import torch
    xpu = getattr(torch, "xpu", None)
    ok = bool(xpu is not None and xpu.is_available())
    if ok:
        count = int(xpu.device_count())
        for idx in range(count):
            name = ""
            total = None
            try:
                name = str(xpu.get_device_name(idx) or "")
            except Exception:
                name = ""
            try:
                props = xpu.get_device_properties(idx)
                total = getattr(props, "total_memory", None)
                if total is None:
                    total = getattr(props, "total_global_mem_size", None)
            except Exception:
                total = None
            label = f"{idx}: {name or 'Intel GPU'}"
            if isinstance(total, int) and total > 0:
                label += f" ({total / (1024 ** 3):.1f} GiB)"
            out.append({"value": str(idx), "label": label})
except Exception:
    pass
print(json.dumps(out))
"""
    try:
        proc = subprocess.run(
            [py, "-c", probe],
            capture_output=True,
            text=True,
            timeout=5,
            env=dict(os.environ),
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    try:
        data = json.loads(proc.stdout.strip() or "[]")
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "").strip()
        label = str(item.get("label") or "").strip()
        if value:
            out.append({"value": value, "label": label or value})
    return out


def _runtime_scoped_schemas() -> Dict[str, Any]:
    schemas = copy.deepcopy(load_schema_dir(_schema_dir()))
    runtime = _current_runtime()
    is_intel = runtime in ("intel", "xpu", "sycl")

    for schema in schemas.values():
        if not isinstance(schema, dict):
            continue
        fields = schema.get("fields")
        if not isinstance(fields, list):
            continue
        for field in fields:
            if not isinstance(field, dict):
                continue
            if str(field.get("key") or "").strip() != "backend":
                continue
            choices = field.get("choices")
            if not isinstance(choices, list):
                continue
            filtered_choices = []
            for choice in choices:
                if isinstance(choice, dict):
                    value = str(choice.get("value") or "").strip().lower()
                    if value == "comfyui":
                        continue
                    filtered_choices.append(choice)
                else:
                    value = str(choice or "").strip()
                    if value.lower() == "comfyui":
                        continue
                    filtered_choices.append(choice)
            if filtered_choices != choices:
                field["choices"] = filtered_choices
                default_value = str(field.get("default") or "").strip().lower()
                valid_values = {
                    str((item.get("value") if isinstance(item, dict) else item) or "").strip().lower()
                    for item in filtered_choices
                }
                if default_value and default_value not in valid_values:
                    replacement = filtered_choices[0] if filtered_choices else ""
                    field["default"] = replacement.get("value") if isinstance(replacement, dict) else replacement

    text_schema = schemas.get("text_llm")
    if isinstance(text_schema, dict):
        fields = text_schema.get("fields")
        if isinstance(fields, list):
            if is_intel:
                fields[:] = [
                    field for field in fields
                    if str((field or {}).get("key") or "").strip() != "flash_attn"
                ]
            if is_intel:
                main_gpu = _find_field(fields, "main_gpu")
                choices = _intel_gpu_choices()
                if isinstance(main_gpu, dict) and choices:
                    main_gpu["type"] = "enum"
                    main_gpu["choices"] = choices
                    main_gpu["default"] = str(main_gpu.get("default", "0") or "0")
                    main_gpu["description"] = "Select the Intel GPU device id used by llama.cpp SYCL."

    for type_id in ("vlm",):
        schema = schemas.get(type_id)
        if not isinstance(schema, dict):
            continue
        fields = schema.get("fields")
        if not isinstance(fields, list):
            continue
        if _find_field(fields, "main_gpu") is not None:
            continue
        field: dict[str, Any] = {
            "key": "main_gpu",
            "label": "Main GPU device id",
            "default": 0,
        }
        if is_intel:
            choices = _intel_gpu_choices()
            if choices:
                field["type"] = "enum"
                field["choices"] = choices
                field["default"] = "0"
                field["description"] = "Select the Intel GPU device id used by llama.cpp SYCL."
            else:
                field["type"] = "int"
        else:
            field["type"] = "int"
        _insert_field_after(fields, "n_gpu_layers_offset", field)

    image_schema = schemas.get("image_gen")
    if isinstance(image_schema, dict):
        fields = image_schema.get("fields")
        if isinstance(fields, list):
            sd_cpp_device_choices = [
                {"value": "vulkan", "label": "vulkan"},
                {"value": "cpu", "label": "cpu"},
                {"value": "cuda", "label": "cuda"},
            ]
            if runtime == "cuda":
                sd_cpp_device_choices = [
                    {"value": "cuda", "label": "cuda"},
                    {"value": "cpu", "label": "cpu"},
                    {"value": "vulkan", "label": "vulkan"},
                ]
            elif runtime in ("intel", "xpu", "sycl", "vulkan"):
                sd_cpp_device_choices = [
                    {"value": "vulkan", "label": "vulkan"},
                    {"value": "cpu", "label": "cpu"},
                    {"value": "cuda", "label": "cuda"},
                ]
            for field in _find_fields(fields, "device"):
                label = str(field.get("label") or "").strip().lower()
                if label != "device (sd_cpp)":
                    continue
                field["type"] = "enum"
                field["choices"] = sd_cpp_device_choices
                default_val = str(field.get("default") or "").strip().lower()
                if default_val not in ("vulkan", "cpu", "cuda"):
                    field["default"] = sd_cpp_device_choices[0]["value"]
                field["description"] = "Valid stable-diffusion-cpp device backends for this runtime."

    return schemas


def _runtime_scoped_settings(type_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(settings or {})
    runtime = _current_runtime()
    is_intel = runtime in ("intel", "xpu", "sycl")
    if type_id == "text_llm":
        if is_intel:
            out.pop("flash_attn", None)
    elif type_id == "vlm":
        if is_intel:
            out.pop("flash_attn", None)
    elif type_id == "image_gen":
        backend = str(out.get("backend") or out.get("image_gen_backend") or "").strip().lower()
        device = str(out.get("device") or "").strip().lower()
        if backend == "sd_cpp":
            if device == "xps":
                out["device"] = "vulkan" if runtime in ("intel", "xpu", "sycl", "vulkan") else "cpu"
            elif device in ("xpu", "sycl", "level_zero", "intel") and runtime in ("intel", "xpu", "sycl", "vulkan"):
                out["device"] = "vulkan"
    return out


def _get_deck(app: Any) -> Dict[str, Any]:
    svc = get_plugin_service(app, "model_deck")
    if not isinstance(svc, dict):
        raise HTTPException(503, "model_deck service unavailable")
    load_deck = svc.get("load_deck")
    ensure_defaults = svc.get("ensure_defaults")
    if not callable(load_deck) or not callable(ensure_defaults):
        raise HTTPException(503, "model_deck deck helpers unavailable")
    return ensure_defaults(load_deck())


def _find_model(deck: Dict[str, Any], type_id: str, model_id: str) -> Dict[str, Any]:
    types = deck.get("types") if isinstance(deck.get("types"), dict) else {}
    t = types.get(type_id)
    if not isinstance(t, dict):
        raise HTTPException(404, f"unknown type_id: {type_id}")
    models = t.get("models") if isinstance(t.get("models"), list) else []
    for m in models:
        if isinstance(m, dict) and str(m.get("model_id")) == str(model_id):
            return m
    raise HTTPException(404, f"unknown model_id: {model_id}")


class LoadRequest(BaseModel):
    type_id: str
    model_id: Optional[str] = None
    pid: Optional[str] = None
    sid: Optional[str] = None


class UnloadRequest(BaseModel):
    loader_id: str = Field(..., description="Underlying loader id to unload, e.g. model_loader.gguf")
    pid: Optional[str] = None
    sid: Optional[str] = None


def install(app) -> None:
    reg = getattr(app.state, "model_loader_registry", None)
    if isinstance(reg, dict):
        reg.setdefault(LOADER_ID, {"id": LOADER_ID, "name": "Model Deck Loader"})
        reg.setdefault("model_loader.model_deck.diffusers", {"id": "model_loader.model_deck.diffusers", "name": "Model Deck Diffusers (stub)"})
        reg.setdefault("model_loader.model_deck.video", {"id": "model_loader.model_deck.video", "name": "Model Deck Video (stub)"})
        reg.setdefault("model_loader.model_deck.3d", {"id": "model_loader.model_deck.3d", "name": "Model Deck 3D (stub)"})
        reg.setdefault("model_loader.model_deck.image_gen_gguf", {"id": "model_loader.model_deck.image_gen_gguf", "name": "Model Deck ImageGen GGUF (stub)"})

    r = APIRouter()

    @r.get("/v1/model_deck_loader/schema")
    def schema(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        return {"ok": True, "loader_id": LOADER_ID, "runtime": _current_runtime(), "schemas": _runtime_scoped_schemas()}

    @r.post("/v1/model_deck_loader/load")
    def load(request: Request, req: LoadRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)

        deck = _get_deck(app)
        types = deck.get("types") if isinstance(deck.get("types"), dict) else {}
        t = types.get(req.type_id)
        if not isinstance(t, dict):
            raise HTTPException(404, f"unknown type_id: {req.type_id}")

        mid = str(req.model_id or t.get("default_model_id") or "").strip()
        if not mid:
            raise HTTPException(404, "no model_id and no default set for type")

        m = _find_model(deck, req.type_id, mid)
        loader_id = str(m.get("loader_id") or "").strip()
        if not loader_id:
            raise HTTPException(400, "deck model missing loader_id")

        settings = dict(m.get("settings") or {})
        if req.pid is not None:
            settings.setdefault("pid", req.pid)
        if req.sid is not None:
            settings.setdefault("sid", req.sid)

        sch = _runtime_scoped_schemas().get(req.type_id) or {}
        settings = merge_defaults(sch, settings)
        settings = _runtime_scoped_settings(req.type_id, settings)
        err = validate_required(sch, settings)
        if err:
            raise HTTPException(400, err)

        if loader_id in _LOCAL_LOADERS:
            res = _LOCAL_LOADERS[loader_id].load(request, settings)
            return {"ok": True, "delegated": True, "loader_id": loader_id, "model_id": mid, "result": res}

        reg = getattr(app.state, "model_loader_registry", None)
        plugin = reg.get(loader_id) if hasattr(reg, "get") else None
        if plugin is None:
            raise HTTPException(400, f"loader not installed: {loader_id}")

        if hasattr(plugin, "load"):
            res = plugin.load(request, settings)
            return {"ok": True, "delegated": True, "loader_id": loader_id, "model_id": mid, "result": res}

        return {"ok": True, "delegated": False, "loader_id": loader_id, "model_id": mid, "settings": settings}

    @r.post("/v1/model_deck_loader/unload")
    def unload(request: Request, req: UnloadRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)

        loader_id = str(req.loader_id or "").strip()
        if not loader_id:
            raise HTTPException(400, "loader_id required")

        if loader_id in _LOCAL_LOADERS:
            res = _LOCAL_LOADERS[loader_id].unload(request, {"pid": req.pid, "sid": req.sid})
            return {"ok": True, "delegated": True, "loader_id": loader_id, "result": res}

        reg = getattr(app.state, "model_loader_registry", None)
        plugin = reg.get(loader_id) if hasattr(reg, "get") else None
        if plugin is None:
            raise HTTPException(400, f"loader not installed: {loader_id}")

        if hasattr(plugin, "unload"):
            res = plugin.unload(request, {"pid": req.pid, "sid": req.sid})
            return {"ok": True, "delegated": True, "loader_id": loader_id, "result": res}

        return {"ok": True, "delegated": False, "loader_id": loader_id, "pid": req.pid, "sid": req.sid}

    app.include_router(r)

    from .local_loaders.diffusers import install as install_diffusers
    from .local_loaders.video import install as install_video
    from .local_loaders.three_d import install as install_3d
    from .local_loaders.text_llm import install as install_text_llm
    from .local_loaders.vlm import install as install_vlm
    from .local_loaders.os_agent import install as install_os_agent
    from .local_loaders.retrieval import install as install_retrieval
    from .local_loaders.safety import install as install_safety
    from .local_loaders.speech import install as install_speech
    from .local_loaders.image_gen_gguf import install as install_image_gen_gguf
    install_diffusers(app)
    install_video(app)
    install_3d(app)
    install_text_llm(app)
    install_vlm(app)
    install_os_agent(app)
    install_retrieval(app)
    install_safety(app)
    install_speech(app)
    install_image_gen_gguf(app)
