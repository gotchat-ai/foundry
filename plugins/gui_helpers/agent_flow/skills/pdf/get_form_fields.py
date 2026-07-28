from __future__ import annotations

import importlib.util
import os
from typing import Any, Dict


TOOL_SPEC = {
    "id": "pdf.get_form_fields",
    "category": "pdf",
    "label": "Get PDF form fields",
    "description": "Compatibility alias for pdf.read_form_fields.",
    "permissions": ["pdf.get_form_fields", "pdf.read_form_fields", "pdf.*"],
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "pdf_path": {"type": "string"},
            "filename": {"type": "string"},
            "target_repo_root": {"type": "string"},
        },
        "required": ["path"],
    },
}


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    # Direct alias to keep older / model-hallucinated skill names working.
    path = os.path.join(os.path.dirname(__file__), "read_form_fields.py")
    spec = importlib.util.spec_from_file_location("agent_flow_pdf_read_form_fields_alias", path)
    if spec is None or spec.loader is None:
        return {"ok": False, "data": {}, "warnings": ["alias_load_failed"]}
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, "run", None)
    if not callable(fn):
        return {"ok": False, "data": {}, "warnings": ["alias_run_missing"]}
    return fn(ctx, params)
