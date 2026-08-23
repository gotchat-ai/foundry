from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


_BACKENDS: List[Dict[str, Any]] = [
    {
        "id": "whisper",
        "label": "Whisper",
        "patterns": [
            r"\bwhisper\b",
            r"large-v3",
            r"turbo",
        ],
        "architectures": {
            "whisper",
        },
        "runtime": "voice_stt",
        "note": "Whisper-compatible ASR model. Use the voice_stt backend with whisper.cpp or openai-whisper style transcription.",
    },
    {
        "id": "parakeet",
        "label": "Parakeet",
        "patterns": [
            r"\bparakeet\b",
            r"\btdt\b",
            r"nvidia[/\\_-].*parakeet",
        ],
        "architectures": {
            "parakeet",
            "nemo",
        },
        "runtime": "speech_backend_parakeet",
        "note": "Parakeet-family ASR model detected. This backend family is registered separately from Whisper so future Parakeet/NVIDIA NeMo runtime support can attach cleanly.",
    },
    {
        "id": "canary_qwen",
        "label": "Canary Qwen",
        "patterns": [
            r"\bcanary\b",
            r"canary[-_ ]qwen",
            r"nvidia[-_ /\\]*canary",
            r"canary[-_ ]?2\.?5b",
        ],
        "architectures": {
            "canary",
            "canary_qwen",
        },
        "runtime": "speech_backend_canary_qwen",
        "note": "NVIDIA Canary-Qwen family detected. Compatibility is registered for future downloads and backend routing.",
    },
    {
        "id": "qwen3_asr",
        "label": "Qwen3 ASR",
        "patterns": [
            r"qwen3[-_ ]asr",
            r"qwen[-_ ]?asr",
            r"qwen3[-_ ]?1\.?7b",
        ],
        "architectures": {
            "qwen3_asr",
            "qwen_asr",
        },
        "runtime": "speech_backend_qwen3_asr",
        "note": "Qwen3-ASR family detected. Compatibility is registered for future downloads and backend routing.",
    },
]


def list_speech_backends() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = [{"id": "auto", "label": "Auto-detect", "runtime": "auto"}]
    for row in _BACKENDS:
        rows.append({
            "id": str(row.get("id") or "").strip(),
            "label": str(row.get("label") or row.get("id") or "").strip(),
            "runtime": str(row.get("runtime") or "").strip(),
        })
    return rows


def _normalize_architecture(meta: Dict[str, Any]) -> str:
    return str(meta.get("general.architecture") or "").strip().lower()


def _build_haystack(model_ref: str, model_path: str, meta: Dict[str, Any]) -> str:
    fields = [
        str(model_ref or ""),
        str(model_path or ""),
        str(meta.get("general.name") or ""),
        str(meta.get("general.basename") or ""),
        str(meta.get("tokenizer.ggml.model") or ""),
        str(meta.get("general.description") or ""),
    ]
    return " ".join(item for item in fields if item).lower()


def resolve_speech_backend(
    *,
    requested_backend: str,
    model_ref: str,
    model_path: str,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    meta = dict(meta or {})
    requested = str(requested_backend or "auto").strip().lower() or "auto"
    architecture = _normalize_architecture(meta)
    haystack = _build_haystack(model_ref, model_path, meta)

    def _match_backend(row: Dict[str, Any]) -> bool:
        if architecture and architecture in {str(item).strip().lower() for item in (row.get("architectures") or set())}:
            return True
        for pattern in row.get("patterns") or []:
            try:
                if re.search(str(pattern), haystack, flags=re.IGNORECASE):
                    return True
            except re.error:
                continue
        return False

    selected: Optional[Dict[str, Any]] = None
    if requested != "auto":
        for row in _BACKENDS:
            if str(row.get("id") or "").strip().lower() == requested:
                selected = row
                break
    if selected is None:
        for row in _BACKENDS:
            if _match_backend(row):
                selected = row
                break
    if selected is None:
        selected = {
            "id": "generic_asr",
            "label": "Generic ASR",
            "runtime": "speech_backend_generic",
            "note": "No specific ASR family matched. The speech loader kept this as a generic ASR backend so future model families can still route without hardcoding every name.",
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
