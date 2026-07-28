from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple


DEFAULT_PLACEHOLDER = "<prompt_injection_redacted>"

PATTERNS: List[Tuple[str, str, str]] = [
    ("override_previous_instructions", "high", r"\b(ignore|disregard|forget|override)\s+(all\s+)?(previous|prior|earlier)\s+(instructions?|prompts?|messages?)\b"),
    ("reveal_system_prompt", "high", r"\b(show|print|reveal|expose|dump)\s+(the\s+)?(system|developer|hidden)\s+(prompt|message|instructions?)\b"),
    ("tool_call_override", "high", r"\b(must|should|need to|required to)\s+(call|invoke|use|trigger)\s+(a\s+)?tool\b"),
    ("permission_bypass", "high", r"\b(do\s+not|don't|never)\s+(ask|request)\s+(for\s+)?approval\b"),
    ("role_injection", "medium", r"\b(role\s*:\s*(system|developer|assistant|tool)|you\s+are\s+now\s+(system|developer|assistant))\b"),
    ("jailbreak_language", "medium", r"\b(jailbreak|dan\b|developer mode|god mode|prompt injection)\b"),
    ("secrets_exfiltration", "high", r"\b(return|send|exfiltrate|leak|export)\s+.*\b(api\s*keys?|tokens?|passwords?|credentials?|secrets?)\b"),
    ("sandbox_escape_request", "high", r"\b(disable|bypass|escape)\s+(the\s+)?(sandbox|guardrails|safety|security)\b"),
    ("hidden_channel_request", "medium", r"\b(use\s+(a\s+)?hidden\s+channel|respond\s+with\s+the\s+chain\s+of\s+thought|show\s+internal\s+reasoning)\b"),
    ("instruction_delimiter_block", "medium", r"(BEGIN|END)\s+(SYSTEM|DEVELOPER|HIDDEN)\s+(PROMPT|INSTRUCTIONS?)"),
]


def coerce_text_payload(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: List[str] = []
        for row in value:
            if isinstance(row, dict):
                parts.append(json.dumps(row, ensure_ascii=True, sort_keys=True))
            else:
                parts.append(str(row or ""))
        return "\n".join(parts)
    if isinstance(value, dict):
        try:
            return json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2)
        except Exception:
            return str(value)
    return str(value or "")


def line_findings(text: str) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    lines = str(text or "").splitlines() or [str(text or "")]
    for idx, line in enumerate(lines, start=1):
        for code, severity, pattern in PATTERNS:
            match = re.search(pattern, line, flags=re.IGNORECASE)
            if not match:
                continue
            findings.append(
                {
                    "code": code,
                    "severity": severity,
                    "line": idx,
                    "start": int(match.start()),
                    "end": int(match.end()),
                    "match_text": str(match.group(0) or "").strip(),
                    "line_text": line[:500],
                }
            )
    return findings


def score_findings(findings: List[Dict[str, Any]]) -> int:
    total = 0
    for row in findings:
        sev = str(row.get("severity") or "").strip().lower()
        if sev == "high":
            total += 35
        elif sev == "medium":
            total += 15
        else:
            total += 5
    return min(total, 100)


def decision_for_findings(findings: List[Dict[str, Any]], *, block_threshold: int = 60, review_threshold: int = 25) -> str:
    score = score_findings(findings)
    if not findings:
        return "allow"
    if any(str(row.get("severity") or "").strip().lower() == "high" for row in findings) or score >= block_threshold:
        return "block"
    if score >= review_threshold:
        return "review"
    return "allow"


def redact_lines(text: str, findings: List[Dict[str, Any]], placeholder: str = DEFAULT_PLACEHOLDER) -> str:
    if not findings:
        return str(text or "")
    lines = str(text or "").splitlines()
    flagged = {int(row.get("line") or 0) for row in findings if int(row.get("line") or 0) > 0}
    out: List[str] = []
    for idx, line in enumerate(lines, start=1):
        out.append(placeholder if idx in flagged else line)
    return "\n".join(out)


def scan_text(
    text: Any,
    *,
    placeholder: str = DEFAULT_PLACEHOLDER,
    block_threshold: int = 60,
    review_threshold: int = 25,
) -> Dict[str, Any]:
    original = coerce_text_payload(text)
    findings = line_findings(original)
    risk_score = score_findings(findings)
    decision = decision_for_findings(findings, block_threshold=block_threshold, review_threshold=review_threshold)
    sanitized = redact_lines(original, findings, placeholder=placeholder)
    return {
        "original_text": original,
        "sanitized_text": sanitized,
        "decision": decision,
        "risk_score": risk_score,
        "findings": findings,
        "summary": {
            "finding_count": len(findings),
            "high_count": sum(1 for row in findings if str(row.get("severity") or "").lower() == "high"),
            "medium_count": sum(1 for row in findings if str(row.get("severity") or "").lower() == "medium"),
            "risk_score": risk_score,
            "decision": decision,
        },
    }
