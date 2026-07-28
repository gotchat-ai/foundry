from __future__ import annotations

import json
import os
from typing import Any, Dict, List


def load_manifests(gui_helpers_dir: str) -> List[Dict[str, Any]]:
    """Load manifest.json files from helper subfolders (skipping _folders)."""
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(gui_helpers_dir):
        return out

    for name in os.listdir(gui_helpers_dir):
        if name.startswith("_"):
            continue
        mpath = os.path.join(gui_helpers_dir, name, "manifest.json")
        if os.path.isfile(mpath):
            try:
                with open(mpath, "r", encoding="utf-8") as f:
                    out.append(json.load(f))
            except Exception:
                pass
    return out
