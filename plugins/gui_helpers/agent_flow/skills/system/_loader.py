from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def load_common() -> Any:
    path = Path(__file__).resolve().parent / "_common.py"
    spec = importlib.util.spec_from_file_location("agent_flow_system_common", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot_load_common:{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
