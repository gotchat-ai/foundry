from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

try:
    from ..agent_flow.skills.security._prompt_injection_common import scan_text
except Exception:
    import importlib.util
    _P = Path(__file__).resolve().parent.parent / "agent_flow" / "skills" / "security" / "_prompt_injection_common.py"
    _S = importlib.util.spec_from_file_location("agent_flow_prompt_injection_common", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    scan_text = _M.scan_text
try:
    from .policy import blocked_findings_for_visibility
except Exception:
    import importlib.util
    _P3 = Path(__file__).resolve().parent / "policy.py"
    _S3 = importlib.util.spec_from_file_location("workflow_exchange_policy", _P3)
    _M3 = importlib.util.module_from_spec(_S3)
    assert _S3 is not None and _S3.loader is not None
    _S3.loader.exec_module(_M3)
    blocked_findings_for_visibility = _M3.blocked_findings_for_visibility


def _scanable_payload_text(payload: Dict[str, Any]) -> str:
    sections: Dict[str, Any] = {}
    for key in ("manifest", "workflow", "skills", "sanitization", "metadata", "title", "summary", "tags"):
        value = payload.get(key)
        if value is not None:
            sections[key] = value
    try:
        return json.dumps(sections, ensure_ascii=True, sort_keys=True, indent=2)
    except Exception:
        return str(sections)


def scan_package_payload(payload: Dict[str, Any], *, visibility: str) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    blocked_codes = blocked_findings_for_visibility(visibility)
    skills = payload.get("skills") if isinstance(payload.get("skills"), dict) else {}
    trusted_skill_files = skills.get("trusted_skill_files") if isinstance(skills.get("trusted_skill_files"), list) else []
    if str(visibility or "").strip().lower() == "public" and trusted_skill_files:
        findings.append({"code": "custom_code_public", "severity": "high", "message": "Public bundles must not include executable custom skill files."})
    sanitization = payload.get("sanitization") if isinstance(payload.get("sanitization"), dict) else {}
    for blocked in sanitization.get("blocked_findings") or []:
        findings.append({"code": str(blocked), "severity": "high", "message": f"Blocked finding present: {blocked}"})
    for review in sanitization.get("review_findings") or []:
        findings.append({"code": str(review), "severity": "medium", "message": f"Review finding present: {review}"})
    injection_scan = scan_text(_scanable_payload_text(payload))
    injection_decision = str(injection_scan.get("decision") or "allow")
    if injection_decision == "block":
        findings.append(
            {
                "code": "prompt_exfiltration",
                "severity": "high",
                "message": "Imported bundle contains prompt-injection or prompt-exfiltration patterns.",
                "scan_summary": injection_scan.get("summary"),
            }
        )
    elif injection_decision == "review":
        findings.append(
            {
                "code": "prompt_injection_detected",
                "severity": "medium",
                "message": "Imported bundle should be reviewed for prompt-injection patterns.",
                "scan_summary": injection_scan.get("summary"),
            }
        )
    decision = "allow"
    if any(str(row.get("code") or "") in blocked_codes for row in findings):
        decision = "block"
    elif findings:
        decision = "quarantine_review"
    return {
        "ok": decision != "block",
        "decision": decision,
        "findings": findings,
        "visibility": visibility,
        "prompt_injection_scan": injection_scan,
    }
