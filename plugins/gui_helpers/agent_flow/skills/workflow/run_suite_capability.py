from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from pathlib import Path
from typing import Any, Dict

from _wfcommon import generated_dir, load_workflow_target, slugify
from generate_test_requests_capability import run as generate_test_requests_capability_run
from run_suite import run as run_suite_run


NAME = "workflow.run_suite_capability"
PERMISSIONS = ["workflow.run_suite_capability", "workflow.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    request_text = str(
        params.get("current_request_text")
        or params.get("request_text")
        or params.get("user_request")
        or params.get("request")
        or params.get("text")
        or (ctx or {}).get("original_request")
        or (ctx or {}).get("user_text")
        or ""
    ).strip()
    file_backed_request = any(
        token in request_text.lower()
        for token in (".csv", ".tsv", ".xlsx", ".xls", ".json", ".txt", ".md", ".pdf", ".docx", "/app/", "c:\\")
    )
    target = load_workflow_target(ctx, params)
    if not target.get("ok"):
        names_to_try = []
        flow_name = str(params.get("flow_name") or "").strip()
        if flow_name:
            names_to_try.append(flow_name)
        request_hint = str((ctx or {}).get("original_request") or (ctx or {}).get("user_text") or "").strip()
        if request_hint:
            names_to_try.append(request_hint[:72])
        for name_hint in names_to_try:
            root = generated_dir(ctx)
            slug = slugify(name_hint)
            candidates = sorted(
                [p for p in root.glob(f"{slug}_*") if p.is_dir()],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for bundle_dir in candidates:
                json_files = sorted([p for p in bundle_dir.glob("*.json") if p.is_file()])
                if not json_files:
                    continue
                target = load_workflow_target(
                    ctx,
                    {
                        "bundle_dir": str(bundle_dir),
                        "workflow_file": str(json_files[0]),
                        "flow_name": flow_name or name_hint,
                        "pid": str(params.get("pid") or "project2"),
                    },
                )
                if target.get("ok"):
                    break
            if target.get("ok"):
                break
    if not target.get("ok"):
        return target

    generated = generate_test_requests_capability_run(
        ctx,
        {
            "bundle_dir": str(target.get("bundle_dir") or ""),
            "workflow_file": str(target.get("workflow_file") or ""),
            "flow_name": str(target.get("flow_name") or ""),
            "pid": str(target.get("pid") or params.get("pid") or "project2"),
            "request_text": request_text,
            "current_request_text": request_text,
            "user_request": request_text,
        },
    )
    test_requests = generated.get("test_requests") if isinstance(generated.get("test_requests"), list) else []
    flow_ext = generated.get("flow_ext") if isinstance(generated.get("flow_ext"), dict) else {}

    def _number_param(name: str, default: float) -> float:
        raw = params.get(name, None)
        if raw is None or (isinstance(raw, str) and not str(raw).strip()):
            return default
        try:
            return float(raw)
        except Exception:
            return default

    default_min_requests = 1 if file_backed_request else 5
    default_max_requests = 1 if file_backed_request else 0
    default_wait_s = 150.0 if file_backed_request else 90.0

    out = run_suite_run(
        ctx,
        {
            "target_type": str(target.get("target_type") or ""),
            "bundle_dir": str(target.get("bundle_dir") or ""),
            "workflow_file": str(target.get("workflow_file") or ""),
            "flow_name": str(target.get("flow_name") or ""),
            "pid": str(target.get("pid") or params.get("pid") or "project2"),
            "workflow_json": target.get("workflow_json"),
            "temp_skill_dirs": [str(x or "").strip() for x in (target.get("temp_skill_dirs") or []) if str(x or "").strip()],
            "test_requests": test_requests,
            "flow_ext": flow_ext,
            "min_requests": int(params.get("min_requests") or default_min_requests),
            "max_requests": int(params.get("max_requests") or default_max_requests),
            "max_request_wait_s": _number_param("max_request_wait_s", default_wait_s),
            "poll_interval_s": _number_param("poll_interval_s", 1.0),
        },
    )
    if isinstance(out, dict):
        out.setdefault("generated_test_requests", test_requests)
        out.setdefault("flow_ext", flow_ext)
        data = out.get("data") if isinstance(out.get("data"), dict) else {}
        data.setdefault("generated_test_requests", test_requests)
        data.setdefault("flow_ext", flow_ext)
        out["data"] = data
    return out


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Run Suite Capability",
    "description": "Load a workflow target, generate capability-aware test requests, and run the real sandbox suite in one deterministic step.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "bundle_dir": {"type": "string"},
            "workflow_file": {"type": "string"},
            "flow_name": {"type": "string"},
            "pid": {"type": "string"},
            "min_requests": {"type": "integer"},
            "max_requests": {"type": "integer"},
            "max_request_wait_s": {"type": "number"},
            "poll_interval_s": {"type": "number"},
        },
        "additionalProperties": True,
    },
}
