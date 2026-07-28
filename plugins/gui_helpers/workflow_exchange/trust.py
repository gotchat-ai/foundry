from __future__ import annotations

from typing import Any, Dict


def summarize_trust(payload: Dict[str, Any]) -> Dict[str, Any]:
    trust = payload.get("trust") if isinstance(payload.get("trust"), dict) else {}
    return {
        "local_score": float(trust.get("local_score") or 0.0),
        "stability_score": float(trust.get("stability_score") or 0.0),
        "safety_score": float(trust.get("safety_score") or 0.0),
        "install_count": int(trust.get("install_count") or 0),
        "success_rate": float(trust.get("success_rate") or 0.0),
    }
