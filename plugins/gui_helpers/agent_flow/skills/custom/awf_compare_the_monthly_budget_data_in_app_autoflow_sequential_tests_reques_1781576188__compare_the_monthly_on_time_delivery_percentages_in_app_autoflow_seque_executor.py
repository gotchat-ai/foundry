from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, List

NAME = "custom.awf_compare_the_monthly_budget_data_in_app_autoflow_sequential_tests_reques_1781576188__compare_the_monthly_on_time_delivery_percentages_in_app_autoflow_seque_executor"
PERMISSIONS = [NAME, "custom.*"]


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ("current_request_text", "request_text", "user_request", "request", "prompt", "text"):
        val = str((params or {}).get(key) or "").strip()
        if val:
            return val
    for key in ("original_request", "user_text"):
        val = str((ctx or {}).get(key) or "").strip()
        if val:
            return val
    return ""


def _extract_paths(text: str) -> List[str]:
    out: List[str] = []
    for m in re.finditer(r"(/app/[^\s\"']+\.(?:csv|tsv|txt|md|json|xlsx|xls))", str(text or ""), flags=re.IGNORECASE):
        p = str(m.group(1) or "").strip()
        if p and p not in out:
            out.append(p)
    return out


def _normalize_input_path(path: str) -> str:
    text = str(path or "").strip()
    if text.startswith("app/"):
        return "/" + text
    return text


def _resolve_input_path(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ("input_path", "file_path", "path", "file"):
        val = _normalize_input_path(str((params or {}).get(key) or "").strip())
        if val and Path(val).exists():
            return val
    for path in _extract_paths(_request_text(ctx, params)):
        if path.lower().endswith((".csv", ".tsv", ".json", ".xlsx", ".xls")):
            return _normalize_input_path(path)
    return ""


def _resolve_brief_path(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for path in _extract_paths(_request_text(ctx, params)):
        if path.lower().endswith((".txt", ".md")):
            return path
    return ""


def _num(value: Any) -> float:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except Exception:
        return 0.0


def _threshold_percent(text: str) -> float | None:
    m = re.search(r"more than\s+([0-9]+(?:\.[0-9]+)?)\s*(?:%|percent)", str(text or "").lower())
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    req = _request_text(ctx, params)
    if not req:
        return {"ok": False, "warnings": ["request_text_required"], "data": {}}

    input_path = _resolve_input_path(ctx, params)
    brief_path = _resolve_brief_path(ctx, params)
    csv_path = Path(input_path)
    if not input_path or not csv_path.is_file():
        return {"ok": False, "warnings": ["input_csv_not_found"], "data": {"input_path": input_path, "brief_path": brief_path}}

    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = [dict(row) for row in csv.DictReader(fh)]
    if not rows:
        return {"ok": False, "warnings": ["input_csv_empty"], "data": {"input_path": input_path}}

    threshold = _threshold_percent(req) or 6.0
    result_rows: List[Dict[str, Any]] = []
    for row in rows:
        prior = _num(row.get("prior_month"))
        current = _num(row.get("current_month"))
        delta = round(current - prior, 2)
        pct = None if prior == 0 else round((delta / prior) * 100.0, 2)
        flagged = bool(pct is not None and abs(pct) > threshold)
        result_rows.append(
            {
                "vendor": str(row.get("vendor") or "").strip(),
                "prior_month": prior,
                "current_month": current,
                "delta": delta,
                "pct_change": pct,
                "flagged": flagged,
            }
        )

    inc = max(result_rows, key=lambda r: r.get("pct_change") or float("-inf"))
    dec = min(result_rows, key=lambda r: r.get("pct_change") or float("inf"))
    flagged_rows = [r for r in result_rows if r.get("flagged")]

    lines = [
        f"| Vendor | Prior Month | Current Month | Change (pts) | Change (%) | Flag (>{threshold:.0f}%) |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for row in result_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("vendor") or ""),
                    f"{float(row.get('prior_month') or 0.0):.0f}",
                    f"{float(row.get('current_month') or 0.0):.0f}",
                    f"{float(row.get('delta') or 0.0):+,.0f}",
                    "" if row.get("pct_change") is None else f"{row.get('pct_change')}%",
                    "Yes" if row.get("flagged") else "No",
                ]
            )
            + " |"
        )

    bullets = [
        f"- Compared {len(result_rows)} vendors using prior-month versus current-month on-time delivery percentages.",
        f"- Sharpest improvement: {inc.get('vendor')} ({inc.get('pct_change')}%, {float(inc.get('delta') or 0.0):+,.0f} pts).",
        f"- Sharpest decline: {dec.get('vendor')} ({dec.get('pct_change')}%, {float(dec.get('delta') or 0.0):+,.0f} pts).",
        f"- Vendors exceeding the {threshold}% threshold: "
        + (
            ", ".join([f"{r.get('vendor')} ({r.get('pct_change')}%)" for r in flagged_rows])
            if flagged_rows
            else "none"
        )
        + ".",
    ]
    if brief_path:
        bullets.append("- Applied the review brief guidance supplied with the request.")

    final_answer = "## Executive Summary\n\n" + "\n".join(bullets) + "\n\n## Tabular Breakdown\n\n" + "\n".join(lines)
    data = {
        "input_path": input_path,
        "brief_path": brief_path,
        "summary": "Generated a reviewer-ready on-time delivery comparison summary and tabular breakdown.",
        "table_markdown": "\n".join(lines),
        "final_answer": final_answer,
        "response": final_answer,
        "comparison_rows": result_rows,
    }
    return {"ok": True, "summary": data["summary"], "data": data}


TOOL_SPEC = {
    "id": NAME,
    "category": "custom",
    "label": "On-time delivery compare executor",
    "description": "Compare on-time delivery percentage changes and return an executive summary with tabular breakdown.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "request_text": {"type": "string"},
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "text": {"type": "string"},
            "input_path": {"type": "string"},
            "file_path": {"type": "string"},
            "path": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
