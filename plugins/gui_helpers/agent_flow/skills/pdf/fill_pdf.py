from __future__ import annotations

import importlib.util
import os
from typing import Any, Dict


TOOL_SPEC = {
    "id": "pdf.fill_pdf",
    "category": "pdf",
    "label": "Fill PDF",
    "description": "Compatibility alias for pdf.fill_form_fields.",
    "permissions": ["pdf.fill_pdf", "pdf.fill_form_fields", "pdf.*"],
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "pdf_path": {"type": "string"},
            "input_path": {"type": "string"},
            "values": {"type": "object"},
            "fields": {"type": "object"},
            "output_path": {"type": "string"},
            "output_dir": {"type": "string"},
            "first_name": {"type": "string"},
            "last_name": {"type": "string"},
            "target_repo_root": {"type": "string"},
            "allow_fuzzy_mapping": {"type": "boolean"},
        },
        "required": ["path"],
    },
}


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    path = os.path.join(os.path.dirname(__file__), "fill_form_fields.py")
    spec = importlib.util.spec_from_file_location("agent_flow_pdf_fill_pdf_alias", path)
    if spec is None or spec.loader is None:
        return {"ok": False, "data": {}, "warnings": ["alias_load_failed"]}
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, "run", None)
    if not callable(fn):
        return {"ok": False, "data": {}, "warnings": ["alias_run_missing"]}
    return fn(ctx, params)

