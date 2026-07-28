from __future__ import annotations

import os
from pathlib import Path as _Path
import sys as _sys
import tempfile

_HERE = _Path(__file__).resolve().parent
_WF_DIR = _HERE.parent / "workflow"
if str(_WF_DIR) in _sys.path:
    _sys.path.remove(str(_WF_DIR))
_sys.path.insert(0, str(_WF_DIR))

import json
import re
from pathlib import Path
from typing import Any, Dict, List

def atomic_write_text(path: Path, content: str, *, make_backup: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(str(content or ""))
            fh.flush()
            os.fsync(fh.fileno())
        if make_backup and path.exists():
            backup = path.with_name(f"{path.name}.bk")
            backup.write_text(path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        os.replace(str(tmp_path), str(path))
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


def _parse_jsonish(value: Any) -> tuple[Any, List[str]]:
    warnings: List[str] = []
    if isinstance(value, (dict, list)):
        return value, warnings
    text = str(value or "").strip()
    if not text:
        return None, ["empty_json_input"]
    try:
        return json.loads(text), warnings
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1]), ["json_recovered_from_wrapped_text"]
        except Exception:
            pass
    return None, ["invalid_json"]


def ensure_flow_payload(value: Any, flow_name_hint: str = "") -> tuple[Dict[str, Any] | None, str, List[str]]:
    data, warnings = _parse_jsonish(value)
    if not isinstance(data, dict):
        return None, str(flow_name_hint or "").strip(), warnings
    if "flows" in data and isinstance(data.get("flows"), dict):
        flows = data.get("flows") or {}
        if len(flows) == 1:
            flow_name, flow_def = next(iter(flows.items()))
            if isinstance(flow_def, dict):
                return flow_def, str(flow_name or flow_name_hint or "").strip(), warnings
        return None, str(flow_name_hint or "").strip(), warnings + ["multiple_flows_not_supported"]
    flow_name = str(flow_name_hint or data.get("name") or data.get("flow_id") or "").strip()
    return data, flow_name, warnings


def extract_referenced_skills(flow: Dict[str, Any]) -> List[str]:
    out = set()
    nodes = flow.get("nodes") if isinstance(flow.get("nodes"), dict) else {}
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        ps = node.get("plugin_settings") if isinstance(node.get("plugin_settings"), dict) else {}
        for skill in ps.get("action_skills") or []:
            skill_id = str(skill or "").strip()
            if skill_id:
                out.add(skill_id)
        tool_cfg = ps.get("tool_config") if isinstance(ps.get("tool_config"), dict) else {}
        tool_name = str(tool_cfg.get("tool") or "").strip()
        if tool_name:
            out.add(tool_name)
    return sorted(out)


NAME = "workflow_exchange.quarantine_review"
PERMISSIONS = ["workflow_exchange.quarantine_review", "workflow_exchange.*", "workflow.*"]
_META = {
    "version": "1.0",
    "created_at": "2026-06-16T00:00:00+00:00",
    "last_updated": "2026-06-16T00:00:00+00:00",
    "dev_status": "tested",
    "test_status": {"state": "tested", "verified_by": "synthetic_workflow_harness", "verified_at": "2026-06-16T00:00:00+00:00"},
}


def _finding_lines(rows: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip()
        severity = str(row.get("severity") or "").strip() or "info"
        message = str(row.get("message") or "").strip()
        parts = [part for part in [severity, code, message] if part]
        if parts:
            out.append(" | ".join(parts))
    return out


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    bundle_dir_raw = str(params.get("bundle_dir") or "").strip()
    workflow_value = params.get("workflow_json") if params.get("workflow_json") is not None else params.get("workflow")
    flow, flow_name, warnings = ensure_flow_payload(workflow_value, str(params.get("flow_name") or "").strip())
    scan = params.get("scan") if isinstance(params.get("scan"), dict) else {}
    sanitization = params.get("sanitization") if isinstance(params.get("sanitization"), dict) else {}
    findings = scan.get("findings") if isinstance(scan.get("findings"), list) else []
    review_findings = sanitization.get("review_findings") if isinstance(sanitization.get("review_findings"), list) else []
    blocked_findings = sanitization.get("blocked_findings") if isinstance(sanitization.get("blocked_findings"), list) else []
    summary = {
        "flow_name": flow_name,
        "decision": str(scan.get("decision") or "allow").strip(),
        "finding_count": len(findings),
        "scan_findings": _finding_lines(findings),
        "review_findings": [str(item or "").strip() for item in review_findings if str(item or "").strip()],
        "blocked_findings": [str(item or "").strip() for item in blocked_findings if str(item or "").strip()],
        "workflow_referenced_skills": extract_referenced_skills(flow) if isinstance(flow, dict) else [],
        "recommendation": "manual_review_required" if findings or review_findings or blocked_findings else "clear",
    }
    report_path = ""
    if bundle_dir_raw:
        bundle_dir = Path(bundle_dir_raw)
        bundle_dir.mkdir(parents=True, exist_ok=True)
        report = [
            f"# Quarantine Review: {flow_name or 'workflow'}",
            "",
            f"Decision: {summary['decision']}",
            f"Finding count: {summary['finding_count']}",
            "",
            "Scan findings:",
        ]
        report.extend([f"- {line}" for line in summary["scan_findings"]] or ["- none"])
        report.extend(["", "Sanitizer review findings:"])
        report.extend([f"- {line}" for line in summary["review_findings"]] or ["- none"])
        report.extend(["", "Sanitizer blocked findings:"])
        report.extend([f"- {line}" for line in summary["blocked_findings"]] or ["- none"])
        report.extend(["", "Referenced workflow skills:"])
        report.extend([f"- {line}" for line in summary["workflow_referenced_skills"]] or ["- none"])
        report.extend(["", f"Recommendation: {summary['recommendation']}"])
        out = bundle_dir / "quarantine_review_report.md"
        atomic_write_text(out, "\n".join(report).strip() + "\n", make_backup=False)
        report_path = str(out)
    return {
        "ok": True,
        "flow_name": flow_name,
        "report_path": report_path,
        "summary": summary,
        "warnings": warnings,
        "data": {
            "flow_name": flow_name,
            "report_path": report_path,
            "summary": summary,
            "warnings": warnings,
        },
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow_exchange",
    "label": "Workflow Exchange Quarantine Review",
    "description": "Summarize scan and sanitization findings for quarantined imported workflow bundles and write a reviewer-readable report.",
    "permissions": PERMISSIONS,
    "metadata": _META,
    "params_schema": {
        "type": "object",
        "properties": {
            "bundle_dir": {"type": "string"},
            "flow_name": {"type": "string"},
            "workflow_json": {},
            "scan": {},
            "sanitization": {},
        },
        "additionalProperties": True,
    },
}
