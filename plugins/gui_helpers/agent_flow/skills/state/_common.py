from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


def _root(ctx: Dict[str, Any]) -> Path:
    app = (ctx or {}).get("app") if isinstance(ctx, dict) else None
    base = getattr(getattr(app, "state", None), "data_dir", None) or getattr(getattr(app, "state", None), "workdir", None) or os.path.abspath("./data")
    return Path(str(base)).resolve() / "agent_flow_state"


def state_file(ctx: Dict[str, Any], params: Dict[str, Any]) -> Path:
    pid = str((params or {}).get("pid") or (ctx or {}).get("pid") or "default").strip() or "default"
    sid = str((params or {}).get("sid") or (ctx or {}).get("sid") or "default").strip() or "default"
    path = _root(ctx) / pid / f"{sid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_state(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    path = state_file(ctx, params)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(ctx: Dict[str, Any], params: Dict[str, Any], data: Dict[str, Any]) -> Path:
    path = state_file(ctx, params)
    path.write_text(json.dumps(data or {}, ensure_ascii=True, indent=2), encoding="utf-8")
    return path
