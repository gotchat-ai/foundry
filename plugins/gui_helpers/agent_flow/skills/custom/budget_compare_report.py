from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

NAME = "custom.budget_compare_report"
PERMISSIONS = [NAME, "custom.*"]
_CREATED_AT = "2026-06-26T00:00:00Z"
_LAST_UPDATED = "2026-06-26T00:10:00Z"
_VERSION = "1.0"
_DEV_STATUS = "tested"

_FILE_HINT_RE = re.compile(r"((?:[A-Za-z]:[\\/][^\s\"']+|/(?:uploads|data|app)/[^\s\"']+)\.(?:csv|tsv))", re.IGNORECASE)
_MONTH_ALIASES = {
    "january": {"january", "jan", "jan amount", "january amount"},
    "february": {"february", "feb", "feb amount", "february amount"},
}


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ("request_text", "user_request", "request", "text", "prompt", "query"):
        value = str((params or {}).get(key) or "").strip()
        if value:
            return value
    for key in ("original_request", "user_text"):
        value = str((ctx or {}).get(key) or "").strip()
        if value:
            return value
    return ""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _map_path(raw: str) -> Path:
    token = str(raw or "").strip().strip("`\"'")
    token = token.replace("\\", "/")
    project_root = _project_root()
    if token.startswith("/uploads/"):
        return project_root / "data" / token.lstrip("/")
    if token.startswith("/data/"):
        return project_root / token.lstrip("/")
    if token.startswith("/app/"):
        return project_root / token.replace("/app/", "", 1)
    lower = token.lower()
    projects_match = re.search(r"/projects/[^/]+/(.+)$", lower)
    if re.match(r"^[a-z]:/", lower) and projects_match:
        suffix = token[len(token) - len(projects_match.group(1)) :]
        return project_root / suffix.replace("\\", "/")
    return Path(token)


def _target_file(request_text: str) -> Path | None:
    match = _FILE_HINT_RE.search(str(request_text or ""))
    if not match:
        return None
    candidate = _map_path(str(match.group(1) or ""))
    return candidate if candidate.is_file() else None


def _delimiter(path: Path) -> str:
    return "\t" if path.suffix.lower() == ".tsv" else ","


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _pick_month_columns(fieldnames: List[str]) -> Tuple[str | None, str | None]:
    normalized = {name: _normalize_header(name) for name in fieldnames}
    jan_col = None
    feb_col = None
    for name, low in normalized.items():
        if jan_col is None and low in _MONTH_ALIASES["january"]:
            jan_col = name
        if feb_col is None and low in _MONTH_ALIASES["february"]:
            feb_col = name
    if jan_col and feb_col:
        return jan_col, feb_col
    for name, low in normalized.items():
        if jan_col is None and "jan" in low:
            jan_col = name
        if feb_col is None and "feb" in low:
            feb_col = name
    return jan_col, feb_col


def _pick_dimension_columns(fieldnames: List[str], month_cols: Tuple[str | None, str | None]) -> List[str]:
    blocked = {col for col in month_cols if col}
    preferred = []
    for candidate in ("Department", "department", "Team", "team", "Owner", "owner", "Category", "category"):
        if candidate in fieldnames and candidate not in blocked:
            preferred.append(candidate)
    if preferred:
        return preferred[:2]
    out = [name for name in fieldnames if name not in blocked]
    return out[:2]


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", "").replace("$", "")
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _fmt_num(value: float) -> str:
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_text = _request_text(ctx or {}, params or {})
    path = _target_file(request_text)
    if path is None:
        return {"ok": False, "warnings": ["target_file_not_found"], "text": "Could not determine the target budget file from the request."}
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=_delimiter(path))
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    if not rows or not fieldnames:
        return {"ok": False, "warnings": ["empty_input"], "text": f"No rows were found in {path.name}."}
    jan_col, feb_col = _pick_month_columns(fieldnames)
    if not jan_col or not feb_col:
        return {"ok": False, "warnings": ["month_columns_not_found"], "text": f"Could not find January/February columns in {path.name}."}
    dims = _pick_dimension_columns(fieldnames, (jan_col, feb_col))
    threshold = 10.0
    enriched = []
    for row in rows:
        jan_val = _to_float(row.get(jan_col))
        feb_val = _to_float(row.get(feb_col))
        if jan_val is None or feb_val is None:
            continue
        change = feb_val - jan_val
        pct = 0.0 if jan_val == 0 else (change / jan_val) * 100.0
        enriched.append({
            "jan": jan_val,
            "feb": feb_val,
            "change": change,
            "pct": pct,
            "flag": abs(pct) > threshold,
            "dims": [str(row.get(col) or "").strip() for col in dims],
        })
    if not enriched:
        return {"ok": False, "warnings": ["numeric_rows_not_found"], "text": f"No numeric January/February rows were found in {path.name}."}
    header_dims = dims if dims else ["Row"]
    header = "| " + " | ".join(header_dims + [jan_col, feb_col, "Change", "Change (%)", "Flag (>10%)"]) + " |"
    sep = "|" + "|".join(["---"] * (len(header_dims) + 5)) + "|"
    lines = ["## Budget Comparison", "", header, sep]
    flagged = []
    biggest_up = max(enriched, key=lambda r: r["change"])
    biggest_down = min(enriched, key=lambda r: r["change"])
    for idx, record in enumerate(enriched, start=1):
        label_cells = record["dims"] if any(record["dims"]) else [f"Row {idx}"]
        while len(label_cells) < len(header_dims):
            label_cells.append("")
        if record["flag"]:
            flagged.append(record)
        change_text = f"{record['change']:+,.0f}" if float(record["change"]).is_integer() else f"{record['change']:+,.2f}"
        lines.append("| " + " | ".join(label_cells + [
            _fmt_num(record["jan"]),
            _fmt_num(record["feb"]),
            change_text,
            f"{record['pct']:+.2f}%",
            "Yes" if record["flag"] else "No",
        ]) + " |")
    summary_bits = [
        f"Compared `{jan_col}` vs `{feb_col}` across {len(enriched)} row(s).",
        f"Biggest increase: {' / '.join(biggest_up['dims']) or 'unlabeled row'} ({_fmt_num(biggest_up['change'])}, {biggest_up['pct']:+.2f}%).",
        f"Biggest decrease: {' / '.join(biggest_down['dims']) or 'unlabeled row'} ({_fmt_num(biggest_down['change'])}, {biggest_down['pct']:+.2f}%).",
    ]
    if flagged:
        summary_bits.append("Flagged over 10%: " + ", ".join((" / ".join(r["dims"]) or "unlabeled row") for r in flagged) + ".")
    else:
        summary_bits.append("No rows exceeded the 10% threshold.")
    final_answer = "\n".join(lines) + "\n\n**Short Summary**\n" + " ".join(summary_bits)
    return {
        "ok": True,
        "text": final_answer,
        "summary": final_answer,
        "final_answer": final_answer,
        "data": {
            "target_path": str(path),
            "jan_col": jan_col,
            "feb_col": feb_col,
            "rows": len(enriched),
            "flagged_rows": len(flagged),
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "custom",
    "label": "Budget Compare Report",
    "description": "Compare January and February values in a budget-style CSV/TSV and flag rows whose percentage change exceeds 10 percent.",
    "permissions": PERMISSIONS,
    "metadata": {
        "version": _VERSION,
        "created_at": _CREATED_AT,
        "last_updated": _LAST_UPDATED,
        "dev_status": _DEV_STATUS,
        "required_capabilities": ["document_io", "content_authoring"],
        "output_mode": "text",
    },
    "params_schema": {
        "type": "object",
        "properties": {
            "request_text": {"type": "string"},
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "text": {"type": "string"},
            "query": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
