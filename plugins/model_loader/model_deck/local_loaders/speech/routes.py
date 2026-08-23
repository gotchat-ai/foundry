from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from string import Formatter
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled

from ..gguf_bridge import _get_cached_gguf_meta, _resolve_model_path
from .backends import list_speech_backends, resolve_speech_backend

GUI_PLUGIN_ID = "model_deck"
LEGACY_LOADER_ID = "model_loader.model_deck.speech"
LOADER_ID_ASR = "model_loader.model_deck.speech_asr"
LOADER_ID_TTS = "model_loader.model_deck.speech_tts"
APP_ROOT = Path(__file__).resolve().parents[5]
CRISPASR_MANAGER_STATE = APP_ROOT / "data" / "gui_helpers" / "crispasr_runtime_manager" / "state.json"

_EMPTY_STATE: Dict[str, Any] = {"loaded": False, "model_id": None, "settings": None, "ts": None, "last_error": ""}
_STATE_BY_LOADER: Dict[str, Dict[str, Any]] = {
    LEGACY_LOADER_ID: dict(_EMPTY_STATE),
    LOADER_ID_ASR: dict(_EMPTY_STATE),
    LOADER_ID_TTS: dict(_EMPTY_STATE),
}

_TTS_BACKENDS: List[Dict[str, Any]] = [
    {
        "id": "kokoro",
        "label": "Kokoro",
        "patterns": [r"\bkokoro\b"],
        "architectures": {"kokoro"},
        "runtime": "crispasr_tts",
        "note": "Kokoro TTS model detected. Usually pair the backbone with a Kokoro voice GGUF via --voice.",
    },
    {
        "id": "chatterbox",
        "label": "Chatterbox",
        "patterns": [r"\bchatterbox\b", r"kartoffelbox", r"lahgtna"],
        "architectures": {"chatterbox", "chatterbox-s3gen"},
        "runtime": "crispasr_tts",
        "note": "Chatterbox TTS model detected. Manual deployments often also need the S3Gen companion file via --codec-model.",
    },
    {
        "id": "vibevoice-tts",
        "label": "VibeVoice Realtime",
        "patterns": [r"\bvibevoice\b", r"realtime[-_ ]0\.?5b"],
        "architectures": {"vibevoice-tts", "vibevoice", "vibevoice-voice"},
        "runtime": "crispasr_tts",
        "note": "Realtime VibeVoice TTS model detected. Voice packs or reference voices vary by variant.",
    },
    {
        "id": "vibevoice-1.5b",
        "label": "VibeVoice 1.5B",
        "patterns": [r"vibevoice[-_ ]1\.?5b", r"\b1\.5b\b"],
        "architectures": {"vibevoice-tts", "vibevoice"},
        "runtime": "crispasr_tts",
        "note": "Base VibeVoice 1.5B TTS model detected. Commonly used with a reference WAV via --voice.",
    },
]


def _state_alias(loader_id: str) -> str:
    lid = str(loader_id or "").strip()
    if lid == LEGACY_LOADER_ID:
        return LOADER_ID_ASR
    return lid or LOADER_ID_ASR


def state_for_loader(loader_id: str) -> Dict[str, Any]:
    return dict(_STATE_BY_LOADER.get(_state_alias(loader_id)) or _EMPTY_STATE)


def _set_state(loader_id: str, **updates: Any) -> None:
    alias = _state_alias(loader_id)
    row = dict(_STATE_BY_LOADER.get(alias) or _EMPTY_STATE)
    row.update(updates)
    _STATE_BY_LOADER[alias] = row
    if alias == LOADER_ID_ASR:
        _STATE_BY_LOADER[LEGACY_LOADER_ID] = dict(row)


def _loader_id_from_settings(settings: Dict[str, Any], default_loader_id: str = LOADER_ID_ASR) -> str:
    raw = str((settings or {}).get("__loader_id") or "").strip()
    return _state_alias(raw or default_loader_id)


def _role_for_loader(loader_id: str) -> str:
    return "tts" if _state_alias(loader_id) == LOADER_ID_TTS else "asr"


def _device_base(device: str) -> str:
    text = str(device or "").strip().lower()
    if ":" in text:
        return text.split(":", 1)[0].strip()
    return text


def _resolve_device(settings: Dict[str, Any]) -> str:
    device = str(settings.get("device") or "").strip().lower()
    if not device or device == "auto":
        try:
            import torch
            from runtime_cuda import preferred_torch_device

            device = preferred_torch_device(torch)
        except Exception:
            device = "cpu"
    selection_mode = str(settings.get("gpu_selection_mode") or "").strip().lower()
    if selection_mode == "single" and ":" not in device and _device_base(device) in ("cuda", "xpu"):
        try:
            main_gpu = int(settings.get("main_gpu"))
        except Exception:
            main_gpu = 0
        if main_gpu >= 0:
            return f"{_device_base(device)}:{main_gpu}"
    return device or "cpu"


def _sanitize_path(value: Any) -> str:
    return str(value or "").strip().strip('"').strip()


def _host_os_id() -> str:
    return "windows" if os.name == "nt" else "posix"


def _managed_crispasr_path(settings: Dict[str, Any]) -> str:
    def _resolve_candidates(raw_path: str) -> str:
        base = Path(_sanitize_path(str(raw_path or "")))
        if not str(base):
            return ""
        candidates = [base]
        if _host_os_id() == "windows" and base.name.lower() == "crispasr.exe":
            parent = base.parent
            candidates.extend([
                parent / "Release" / "crispasr.exe",
                parent.parent / "Release" / "crispasr.exe" if parent.name.lower() == "bin" else parent / "bin" / "Release" / "crispasr.exe",
            ])
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return str(base)

    install_id = str(settings.get("managed_crispasr_install_id") or "").strip()
    if not install_id or not CRISPASR_MANAGER_STATE.is_file():
        return ""
    try:
        data = json.loads(CRISPASR_MANAGER_STATE.read_text(encoding="utf-8"))
    except Exception:
        return ""
    for row in data.get("installs", []) if isinstance(data, dict) else []:
        if str(row.get("install_id") or "").strip() != install_id:
            continue
        path = _resolve_candidates(str(row.get("executable_path") or ""))
        if path and Path(path).is_file():
            return path
    return ""


def _preferred_crispasr_cli_path(settings: Dict[str, Any]) -> str:
    direct = _sanitize_path(settings.get("crispasr_cli_path"))
    if direct and Path(direct).is_file():
        return direct
    managed = _managed_crispasr_path(settings)
    if managed and Path(managed).is_file():
        return managed
    return direct or managed or ""


def _python_crispasr_supported(backend_id: str) -> bool:
    backend = str(backend_id or "").strip().lower()
    if backend not in {"parakeet", "canary_qwen", "qwen3_asr", "generic_asr"}:
        return False
    try:
        import crispasr  # type: ignore

        available = []
        try:
            available = [str(x).strip().lower() for x in crispasr.Session.available_backends()]
        except Exception:
            available = []
        if backend == "generic_asr":
            return True
        return backend in available or not available
    except Exception:
        return False


def _asr_runtime_supported(backend_id: str, settings: Dict[str, Any]) -> bool:
    backend = str(backend_id or "").strip().lower()
    if backend == "whisper":
        return True
    if backend in {"parakeet", "canary_qwen", "qwen3_asr", "generic_asr"}:
        crispasr_path = _preferred_crispasr_cli_path(settings)
        if crispasr_path and Path(crispasr_path).is_file():
            return True
        if _python_crispasr_supported(backend):
            return True
    return False


def _tts_runtime_supported(settings: Dict[str, Any]) -> bool:
    crispasr_path = _preferred_crispasr_cli_path(settings)
    return bool(crispasr_path and Path(crispasr_path).is_file())


def _compatibility_error(backend_id: str, meta: Dict[str, Any], settings: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    backend = str(backend_id or "").strip().lower()
    if backend != "parakeet":
        return None
    has_legacy_namespace = any(str(key).startswith("stt.parakeet.") for key in (meta or {}).keys())
    has_crispasr_namespace = any(str(key).startswith("parakeet.") for key in (meta or {}).keys())
    if has_legacy_namespace and not has_crispasr_namespace:
        model_path = str(settings.get("model_path") or settings.get("model_id") or "").strip()
        return {
            "error": "speech_model_incompatible",
            "speech_backend": backend,
            "speech_runtime": str(settings.get("speech_runtime") or "").strip(),
            "resolved_device": str(settings.get("resolved_device") or "").strip(),
            "message": (
                "This Parakeet GGUF uses the older 'stt.parakeet.*' metadata layout and does not transcribe correctly "
                "through the current CrispASR runtime path. Use a CrispASR-compatible Parakeet GGUF, such as the newer "
                "CSTR Parakeet export, instead."
            ),
            "model_path": model_path,
            "detected_layout": "legacy_stt_parakeet",
            "recommended_search": "cstr parakeet",
        }
    return None


def _normalize_architecture(meta: Dict[str, Any]) -> str:
    return str(meta.get("general.architecture") or "").strip().lower()


def _resolve_tts_backend(*, requested_backend: str, model_ref: str, model_path: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta = dict(meta or {})
    requested = str(requested_backend or "auto").strip().lower() or "auto"
    architecture = _normalize_architecture(meta)
    haystack = " ".join(
        [
            str(model_ref or ""),
            str(model_path or ""),
            str(meta.get("general.name") or ""),
            str(meta.get("general.basename") or ""),
            str(meta.get("general.description") or ""),
        ]
    ).lower()
    selected = None
    if requested != "auto":
        for row in _TTS_BACKENDS:
            if str(row.get("id") or "").strip().lower() == requested:
                selected = row
                break
    if selected is None:
        for row in _TTS_BACKENDS:
            archs = {str(item or "").strip().lower() for item in (row.get("architectures") or set())}
            if architecture and architecture in archs:
                selected = row
                break
            for pattern in row.get("patterns") or []:
                try:
                    if re.search(str(pattern), haystack, flags=re.IGNORECASE):
                        selected = row
                        break
                except re.error:
                    continue
            if selected is not None:
                break
    if selected is None:
        selected = {
            "id": "generic_tts",
            "label": "Generic TTS",
            "runtime": "crispasr_tts",
            "note": "No specific TTS family matched. Use the advanced command template to describe any required companion files and flags.",
        }
    return {
        "backend_id": str(selected.get("id") or "").strip(),
        "backend_label": str(selected.get("label") or selected.get("id") or "").strip(),
        "runtime": str(selected.get("runtime") or "").strip(),
        "architecture": architecture or "unknown",
        "note": str(selected.get("note") or "").strip(),
        "requested_backend": requested,
        "auto_detected": requested == "auto",
    }


def _parse_json_field(settings: Dict[str, Any], key: str) -> Dict[str, Any]:
    raw = settings.get(key)
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except Exception as exc:
        raise HTTPException(400, f"{key} must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(400, f"{key} must be a JSON object")
    return dict(parsed)


def _speech_template_presets(role: str) -> Dict[str, Dict[str, Any]]:
    shared = {
        "generic_asr": {
            "argv": ["--backend", "{speech_backend}", "-m", "{model_path}", "-f", "{audio_path}"],
            "optional": [
                {"setting": "language", "flag": "-l"},
                {"setting": "beam_size", "flag": "-t"},
                {"setting": "task", "equals": "translate", "flag": "--translate", "mode": "bool_flag"},
                {"setting": "vad", "flag": "--vad", "mode": "bool_flag"},
                {"setting": "word_timestamps", "flag": "-owts", "mode": "bool_flag"},
            ],
            "append_extra_args_setting": "speech_runtime_extra_args",
        },
        "kokoro": {
            "argv": ["--backend", "{speech_backend}", "-m", "{model_path}", "--tts", "{input_text}", "--tts-output", "{output_path}"],
            "optional": [
                {"setting": "voice_path", "flag": "--voice"},
                {"setting": "language", "flag": "-l"},
            ],
            "append_extra_args_setting": "speech_runtime_extra_args",
        },
        "chatterbox": {
            "argv": ["--backend", "{speech_backend}", "-m", "{model_path}", "--tts", "{input_text}", "--tts-output", "{output_path}"],
            "optional": [
                {"setting": "companion_model_path", "flag": "--codec-model"},
                {"setting": "voice_path", "flag": "--voice"},
                {"setting": "language", "flag": "-l"},
                {"setting": "instruct_text", "flag": "--instruct"},
                {"setting": "temperature", "flag": "--temperature"},
            ],
            "append_extra_args_setting": "speech_runtime_extra_args",
        },
        "vibevoice_custom": {
            "argv": ["--backend", "{speech_backend}", "-m", "{model_path}", "--tts", "{input_text}", "--tts-output", "{output_path}"],
            "optional": [
                {"setting": "voice_path", "flag": "--voice"},
                {"setting": "language", "flag": "-l"},
                {"setting": "instruct_text", "flag": "--instruct"},
                {"setting": "temperature", "flag": "--temperature"},
            ],
            "append_extra_args_setting": "speech_runtime_extra_args",
        },
    }
    if role == "asr":
        return {"generic_asr": shared["generic_asr"]}
    return {
        "kokoro": shared["kokoro"],
        "chatterbox": shared["chatterbox"],
        "vibevoice_custom": shared["vibevoice_custom"],
    }


def _resolve_command_template(settings: Dict[str, Any], role: str) -> Dict[str, Any]:
    preset_id = str(settings.get("speech_template_preset") or "").strip().lower()
    preset_map = _speech_template_presets(role)
    preset = dict(preset_map.get(preset_id) or {})
    user_template = _parse_json_field(settings, "speech_runtime_template_json")
    merged = dict(preset)
    merged.update(user_template)
    if not isinstance(merged.get("argv"), list) or not merged.get("argv"):
        raise HTTPException(400, "speech runtime template requires a non-empty 'argv' array")
    optional_rows = merged.get("optional")
    if optional_rows is None:
        merged["optional"] = []
    elif not isinstance(optional_rows, list):
        raise HTTPException(400, "speech runtime template 'optional' must be an array")
    return merged


class _StrictFormatter(Formatter):
    def get_value(self, key, args, kwargs):
        if isinstance(key, str):
            if key not in kwargs:
                raise KeyError(key)
            return kwargs[key]
        return Formatter.get_value(self, key, args, kwargs)


def _split_extra_args(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [part for part in re.split(r"\s+", text) if part]


def _render_template_args(template: Dict[str, Any], context: Dict[str, Any], settings: Dict[str, Any]) -> List[str]:
    fmt = _StrictFormatter()
    args: List[str] = []
    for raw in template.get("argv") or []:
        token = str(raw or "")
        try:
            rendered = fmt.vformat(token, (), context)
        except KeyError as exc:
            raise HTTPException(400, f"speech runtime template placeholder is missing: {exc.args[0]}") from exc
        if rendered.strip():
            args.append(rendered)
    for row in template.get("optional") or []:
        if not isinstance(row, dict):
            continue
        flag = str(row.get("flag") or "").strip()
        setting_name = str(row.get("setting") or "").strip()
        if not flag or not setting_name:
            continue
        value = context.get(setting_name)
        mode = str(row.get("mode") or "value").strip().lower()
        expected = row.get("equals")
        if expected is not None and str(value) != str(expected):
            continue
        if mode == "bool_flag":
            if bool(value):
                args.append(flag)
            continue
        if value is None or str(value).strip() == "":
            continue
        args.extend([flag, str(value)])
    extra_setting = str(template.get("append_extra_args_setting") or "").strip()
    if extra_setting:
        args.extend(_split_extra_args(settings.get(extra_setting)))
    static_append = template.get("append_args")
    if isinstance(static_append, list):
        args.extend([str(x) for x in static_append if str(x).strip()])
    return args


def build_advanced_cli_args(*, settings: Dict[str, Any], role: str, runtime_inputs: Optional[Dict[str, Any]] = None) -> List[str]:
    cli_path = _preferred_crispasr_cli_path(settings)
    if not cli_path:
        raise HTTPException(400, "crispasr_cli_path not configured for advanced speech runtime")
    if not Path(cli_path).is_file():
        raise HTTPException(400, f"crispasr_cli_path not found: {cli_path}")
    template = _resolve_command_template(settings, role)
    assets = _parse_json_field(settings, "speech_runtime_assets_json")
    params = _parse_json_field(settings, "speech_runtime_params_json")
    context = dict(settings or {})
    context.update(params)
    context.update(assets)
    context.update(runtime_inputs or {})
    context["cli_path"] = cli_path
    return [cli_path] + _render_template_args(template, context, settings)


def _prepare_asr_settings(request: Request, settings: Dict[str, Any], loader_id: str) -> Dict[str, Any]:
    resolved_path = _resolve_model_path(settings, request, request.app)
    if not resolved_path or not Path(resolved_path).is_file():
        raise HTTPException(400, f"speech_model_not_found: {resolved_path or 'model_path required'}")
    model_ref = str(settings.get("model_path") or settings.get("model_id") or settings.get("model") or "").strip()
    try:
        meta = _get_cached_gguf_meta(request.app, model_ref, resolved_path)
    except Exception as exc:
        raise HTTPException(400, f"speech_model_metadata_unreadable: {exc}") from exc
    backend = resolve_speech_backend(
        requested_backend=str(settings.get("speech_backend") or "auto").strip(),
        model_ref=model_ref,
        model_path=resolved_path,
        meta=meta,
    )
    resolved_device = _resolve_device(settings)
    settings_copy = dict(settings or {})
    settings_copy["speech_backend"] = backend["backend_id"]
    settings_copy["speech_runtime"] = backend["runtime"]
    settings_copy["resolved_device"] = resolved_device
    settings_copy["model_path"] = resolved_path
    command_mode = str(settings_copy.get("speech_command_mode") or "standard").strip().lower()
    preferred_cli_path = _preferred_crispasr_cli_path(settings_copy)
    settings_copy["preferred_crispasr_cli_path"] = preferred_cli_path
    settings_copy["runtime_preference"] = "crispasr_cli" if preferred_cli_path else "python_crispasr"
    settings_copy["runtime_supported"] = True if command_mode == "advanced" else _asr_runtime_supported(backend["backend_id"], settings_copy)
    if command_mode == "advanced":
        _ = build_advanced_cli_args(
            settings=settings_copy,
            role="asr",
            runtime_inputs={"audio_path": "__preview.wav", "task": str(settings_copy.get("task") or "transcribe")},
        )
    compatibility_error = _compatibility_error(backend["backend_id"], meta, settings_copy)
    if compatibility_error:
        _set_state(loader_id, loaded=False, model_id=None, settings=settings_copy, ts=int(time.time()), last_error=f"speech_model_incompatible:{backend['backend_id']}")
        raise HTTPException(400, compatibility_error)
    if not settings_copy["runtime_supported"]:
        _set_state(loader_id, loaded=False, model_id=None, settings=settings_copy, ts=int(time.time()), last_error=f"speech_runtime_not_implemented:{backend['backend_id']}")
        raise HTTPException(
            400,
            {
                "error": "speech_runtime_not_implemented",
                "speech_backend": backend["backend_id"],
                "speech_runtime": backend["runtime"],
                "resolved_device": resolved_device,
                "message": (
                    f"Detected speech backend '{backend['backend_id']}', but no runnable speech runtime is configured for it yet. "
                    "Set a valid CrispASR runtime executable path or managed install first, or install the Python crispasr package as fallback."
                ),
            },
        )
    _set_state(loader_id, loaded=True, model_id=resolved_path, settings=settings_copy, ts=int(time.time()), last_error="")
    return {
        "ok": True,
        "loader_id": loader_id,
        "speech_backend": backend["backend_id"],
        "speech_runtime": backend["runtime"],
        "result": {
            "configured": True,
            "runtime_supported": True,
            "model_path": resolved_path,
            "architecture": backend["architecture"],
            "backend_label": backend["backend_label"],
            "auto_detected": backend["auto_detected"],
            "note": backend["note"],
            "resolved_device": resolved_device,
            "crispasr_cli_path": preferred_cli_path,
            "runtime_preference": settings_copy["runtime_preference"],
            "speech_command_mode": command_mode,
        },
    }


def _prepare_tts_settings(request: Request, settings: Dict[str, Any], loader_id: str) -> Dict[str, Any]:
    resolved_path = _resolve_model_path(settings, request, request.app)
    if not resolved_path or not Path(resolved_path).is_file():
        raise HTTPException(400, f"speech_tts_model_not_found: {resolved_path or 'model_path required'}")
    model_ref = str(settings.get("model_path") or settings.get("model_id") or settings.get("model") or "").strip()
    try:
        meta = _get_cached_gguf_meta(request.app, model_ref, resolved_path)
    except Exception as exc:
        raise HTTPException(400, f"speech_tts_model_metadata_unreadable: {exc}") from exc
    backend = _resolve_tts_backend(
        requested_backend=str(settings.get("speech_backend") or "auto").strip(),
        model_ref=model_ref,
        model_path=resolved_path,
        meta=meta,
    )
    resolved_device = _resolve_device(settings)
    settings_copy = dict(settings or {})
    settings_copy["speech_backend"] = backend["backend_id"]
    settings_copy["speech_runtime"] = backend["runtime"]
    settings_copy["resolved_device"] = resolved_device
    settings_copy["model_path"] = resolved_path
    command_mode = str(settings_copy.get("speech_command_mode") or "advanced").strip().lower()
    preferred_cli_path = _preferred_crispasr_cli_path(settings_copy)
    settings_copy["preferred_crispasr_cli_path"] = preferred_cli_path
    settings_copy["runtime_preference"] = "crispasr_cli"
    settings_copy["runtime_supported"] = _tts_runtime_supported(settings_copy)
    if command_mode == "advanced":
        _ = build_advanced_cli_args(
            settings=settings_copy,
            role="tts",
            runtime_inputs={"input_text": "Hello from Model Deck", "output_path": "preview.wav"},
        )
    if not settings_copy["runtime_supported"]:
        _set_state(loader_id, loaded=False, model_id=None, settings=settings_copy, ts=int(time.time()), last_error="speech_tts_runtime_not_configured")
        raise HTTPException(
            400,
            {
                "error": "speech_tts_runtime_not_configured",
                "speech_backend": backend["backend_id"],
                "speech_runtime": backend["runtime"],
                "resolved_device": resolved_device,
                "message": "TTS backends currently require a runnable CrispASR executable path or managed install.",
            },
        )
    _set_state(loader_id, loaded=True, model_id=resolved_path, settings=settings_copy, ts=int(time.time()), last_error="")
    return {
        "ok": True,
        "loader_id": loader_id,
        "speech_backend": backend["backend_id"],
        "speech_runtime": backend["runtime"],
        "result": {
            "configured": True,
            "runtime_supported": True,
            "model_path": resolved_path,
            "architecture": backend["architecture"],
            "backend_label": backend["backend_label"],
            "auto_detected": backend["auto_detected"],
            "note": backend["note"],
            "resolved_device": resolved_device,
            "crispasr_cli_path": preferred_cli_path,
            "runtime_preference": settings_copy["runtime_preference"],
            "speech_command_mode": command_mode,
        },
    }


def load_for_loader(loader_id: str, request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
    if _role_for_loader(loader_id) == "tts":
        return _prepare_tts_settings(request, settings, _state_alias(loader_id))
    return _prepare_asr_settings(request, settings, _state_alias(loader_id))


def unload_for_loader(loader_id: str, request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
    _set_state(loader_id, loaded=False, model_id=None, settings=None, ts=int(time.time()), last_error="")
    return {"ok": True, "loader_id": _state_alias(loader_id), "result": {"configured": False}}


def load(request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
    return load_for_loader(_loader_id_from_settings(settings), request, settings)


def unload(request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
    return unload_for_loader(_loader_id_from_settings(settings), request, settings)


def install(app) -> None:
    reg = getattr(app.state, "model_loader_registry", None)
    if isinstance(reg, dict):
        reg.setdefault(LEGACY_LOADER_ID, type("DeckSpeechLegacy", (), {"id": LEGACY_LOADER_ID, "name": "Model Deck Speech ASR (legacy)", "load": staticmethod(load), "unload": staticmethod(unload)})())
        reg.setdefault(LOADER_ID_ASR, type("DeckSpeechAsr", (), {"id": LOADER_ID_ASR, "name": "Model Deck Speech ASR", "load": staticmethod(load), "unload": staticmethod(unload)})())
        reg.setdefault(LOADER_ID_TTS, type("DeckSpeechTts", (), {"id": LOADER_ID_TTS, "name": "Model Deck Speech TTS", "load": staticmethod(load), "unload": staticmethod(unload)})())

    r = APIRouter()

    @r.get("/v1/model_loader/model_deck/speech/status")
    def status(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        return {
            "ok": True,
            "loader_ids": [LOADER_ID_ASR, LOADER_ID_TTS],
            "states": {
                LOADER_ID_ASR: state_for_loader(LOADER_ID_ASR),
                LOADER_ID_TTS: state_for_loader(LOADER_ID_TTS),
            },
            "asr_backends": list_speech_backends(),
            "tts_backends": [row["id"] for row in _TTS_BACKENDS] + ["generic_tts"],
        }

    app.include_router(r)
