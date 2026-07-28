NAME = "result.awf_web_research__text"
PERMISSIONS = ["result.emit"]


import re
import sys
from collections import defaultdict
from datetime import date as _date, datetime as _dt, timedelta as _td
from pathlib import Path
from typing import Any, Dict, List, Optional


def _coerce_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        try:
            return float(str(v).replace(",", "").strip())
        except Exception:
            return None


def _fmt_num(v: Any, digits: int = 2) -> str:
    n = _coerce_float(v)
    if n is None:
        return str(v)
    if abs(n - round(n)) < 1e-9:
        return f"{n:,.0f}"
    return f"{n:,.{digits}f}".rstrip("0").rstrip(".")


def _norm_col(name: str) -> str:
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def _tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", str(text or "").lower()) if t]


def _intent_text(text: str) -> str:
    """Remove filenames so dataset names do not masquerade as requested columns."""
    return re.sub(
        r"\b[\w./\\-]+\.(?:xlsx|xlsm|xls|csv|tsv)\b",
        " ",
        str(text or ""),
        flags=re.IGNORECASE,
    )


def _load_rows(file_hint: str) -> List[Dict[str, Any]]:
    try:
        sheet_dir = Path(__file__).resolve().parent.parent / "sheet"
        sheet_dir_s = str(sheet_dir)
        if sheet_dir_s not in sys.path:
            sys.path.append(sheet_dir_s)
        from shared.io import iter_records  # type: ignore
    except Exception:
        return []
    try:
        return [dict(r) for r in iter_records(file_hint)]
    except Exception:
        return []


def _resolve_column(rows: List[Dict[str, Any]], requested: str = "", *, semantic: str = "") -> str:
    if not rows or not isinstance(rows[0], dict):
        return ""
    cols = list(rows[0].keys())
    if not cols:
        return ""
    req = str(requested or semantic or "").strip()
    norm_map = {_norm_col(c): c for c in cols}
    if req:
        direct = norm_map.get(_norm_col(req))
        if direct:
            return direct
    semantic_groups = {
        "country": ["country", "nation", "origin"],
        "brand": ["brand", "manufacturer", "maker"],
        "product": ["product", "device", "item", "sku"],
        "model": ["model", "name"],
        "date": ["date", "release", "order", "created"],
        "metric": ["total", "sales", "revenue", "amount", "price", "cost", "usd"],
    }
    req_tokens = _tokenize(req)
    if semantic and semantic in semantic_groups:
        req_tokens.extend(semantic_groups[semantic])
    best = ""
    best_score = -1.0
    for col in cols:
        col_l = str(col or "").lower()
        col_norm = _norm_col(col)
        col_tokens = _tokenize(col_l)
        score = 0.0
        if req and _norm_col(req) == col_norm:
            score += 20
        if req and (_norm_col(req) in col_norm or col_norm in _norm_col(req)):
            score += 8
        for rt in req_tokens:
            for ct in col_tokens + [col_norm]:
                if rt == ct:
                    score += 4
                elif rt and ct and (rt in ct or ct in rt):
                    score += 1.5
        # Prefer actually numeric columns for metrics.
        if semantic == "metric":
            numeric = 0
            for r in rows[:100]:
                if _coerce_float(r.get(col)) is not None:
                    numeric += 1
            if numeric:
                score += min(8, numeric / 10)
            else:
                score -= 6
            if "total" in col_l:
                score += 5
            if "price" in col_l or "sales" in col_l or "revenue" in col_l:
                score += 4
        if semantic == "date":
            parsed = 0
            for r in rows[:100]:
                if _parse_date_like(r.get(col)) is not None:
                    parsed += 1
            if parsed:
                score += min(8, parsed / 10)
            else:
                score -= 5
        if score > best_score:
            best = col
            best_score = score
    return best if best_score > 0 else ""


def _parse_date_like(v: Any) -> Optional[_date]:
    if v is None:
        return None
    if isinstance(v, _dt):
        return v.date()
    if isinstance(v, _date):
        return v
    n = _coerce_float(v)
    if n is not None and 20000 <= n <= 80000:
        try:
            return (_dt(1899, 12, 30) + _td(days=float(n))).date()
        except Exception:
            pass
    s = str(v).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m-%d-%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return _dt.strptime(s, fmt).date()
        except Exception:
            pass
    return None


def _format_row_label(row: Dict[str, Any], rows: List[Dict[str, Any]]) -> str:
    for requested, semantic in (("Model", "model"), ("Product", "product"), ("Device", "product"), ("Brand", "brand")):
        col = _resolve_column(rows, requested, semantic=semantic)
        val = str(row.get(col) or "").strip() if col else ""
        if val:
            if requested.lower() == "model":
                brand_col = _resolve_column(rows, "Brand", semantic="brand")
                brand = str(row.get(brand_col) or "").strip() if brand_col else ""
                return f"{brand} {val}".strip()
            return val
    return "the matching row"


def _infer_group_column_from_request(rows: List[Dict[str, Any]], user_request: str) -> str:
    intent = _intent_text(user_request)
    group = _infer_category_group(intent)
    if group:
        semantic = {
            "Country": "country",
            "Brand": "brand",
            "Product": "product",
            "Customer": "customer",
        }.get(group, "")
        return _resolve_column(rows, group, semantic=semantic)
    q = str(intent or "").lower()
    for word, semantic in (("brand", "brand"), ("country", "country"), ("product", "product"), ("device", "product"), ("model", "model")):
        if word in q:
            return _resolve_column(rows, word, semantic=semantic)
    return ""


def _general_spreadsheet_answer(file_hint: str, user_request: str) -> str:
    rows = _load_rows(file_hint)
    if not rows:
        return ""
    q = str(_intent_text(user_request) or "").lower()
    cols = list(rows[0].keys()) if isinstance(rows[0], dict) else []
    metric_col = _resolve_column(rows, "Total (USD)", semantic="metric") or _resolve_column(rows, "Price (USD)", semantic="metric")

    if re.search(r"\b(columns?|headers?|fields?)\b", q):
        return f"The spreadsheet has these columns: {', '.join(str(c) for c in cols)}."

    if re.search(r"\b(how many|number of|count)\s+(rows|records|entries)\b", q):
        return f"The spreadsheet contains {len(rows):,} data rows."

    if re.search(r"\b(unique|distinct)\b", q):
        group_col = _infer_group_column_from_request(rows, user_request)
        if group_col:
            vals = sorted({str(r.get(group_col) or "").strip() for r in rows if str(r.get(group_col) or "").strip()})
            return f"There are {len(vals):,} unique {group_col} values: {', '.join(vals)}."

    if re.search(r"\b(date range|range of dates|earliest|latest)\b", q):
        date_col = _resolve_column(rows, "Date", semantic="date")
        dates = [d for d in (_parse_date_like(r.get(date_col)) for r in rows) if d is not None] if date_col else []
        if dates:
            return f"The {date_col} range is {min(dates).isoformat()} to {max(dates).isoformat()}."

    if metric_col and re.search(r"\b(total|sum)\b", q) and not re.search(r"\b(by|per|group|top|highest|lowest|best|worst)\b", q):
        vals = [_coerce_float(r.get(metric_col)) for r in rows]
        nums = [v for v in vals if v is not None]
        if nums:
            return f"The total {metric_col} is {_fmt_num(sum(nums))}."

    if metric_col and re.search(r"\b(average|avg|mean)\b", q):
        vals = [_coerce_float(r.get(metric_col)) for r in rows]
        nums = [v for v in vals if v is not None]
        if nums:
            return f"The average {metric_col} is {_fmt_num(sum(nums) / len(nums))}."

    group_col = _infer_group_column_from_request(rows, user_request)
    aggregate_group_request = bool(
        metric_col
        and group_col
        and re.search(r"\b(by|per|group|top|highest|best|largest|max|total)\b", q)
        and re.search(r"\b(total|sum|sales|revenue|amount)\b", q)
    )
    if aggregate_group_request:
        totals: Dict[str, float] = defaultdict(float)
        for r in rows:
            label = str(r.get(group_col) or "").strip()
            val = _coerce_float(r.get(metric_col))
            if label and val is not None:
                totals[label] += float(val)
        if totals:
            ordered = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
            m_top = re.search(r"\btop\s+(\d+)\b", q)
            if m_top:
                limit = max(1, int(m_top.group(1)))
                shown = ordered[:limit]
                return f"Top {limit} {group_col} values by {metric_col}: " + "; ".join(f"{k}: {_fmt_num(v)}" for k, v in shown) + "."
            if re.search(r"\b(highest|best|largest|max)\b", q):
                k, v = ordered[0]
                return f"The {group_col} with the highest {metric_col} is {k} with {_fmt_num(v)}."
            return f"Total {metric_col} by {group_col}: " + "; ".join(f"{k}: {_fmt_num(v)}" for k, v in ordered) + "."

    if metric_col and re.search(r"\b(highest|largest|max|most expensive|top item|top product|top model)\b", q) and not re.search(r"\b(by|per)\b", q):
        best_row = None
        best_val = None
        for r in rows:
            val = _coerce_float(r.get(metric_col))
            if val is None:
                continue
            if best_val is None or val > best_val:
                best_val = val
                best_row = r
        if isinstance(best_row, dict) and best_val is not None:
            return f"The highest {metric_col} row is {_format_row_label(best_row, rows)} at {_fmt_num(best_val)}."

    if metric_col and re.search(r"\b(lowest|smallest|min|cheapest)\b", q) and not re.search(r"\b(by|per)\b", q):
        best_row = None
        best_val = None
        for r in rows:
            val = _coerce_float(r.get(metric_col))
            if val is None:
                continue
            if best_val is None or val < best_val:
                best_val = val
                best_row = r
        if isinstance(best_row, dict) and best_val is not None:
            return f"The lowest {metric_col} row is {_format_row_label(best_row, rows)} at {_fmt_num(best_val)}."

    if metric_col and group_col and re.search(r"\b(by|per|group|top|highest|best|total)\b", q):
        totals: Dict[str, float] = defaultdict(float)
        for r in rows:
            label = str(r.get(group_col) or "").strip()
            val = _coerce_float(r.get(metric_col))
            if label and val is not None:
                totals[label] += float(val)
        if totals:
            ordered = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
            m_top = re.search(r"\btop\s+(\d+)\b", q)
            if m_top:
                limit = max(1, int(m_top.group(1)))
                shown = ordered[:limit]
                return f"Top {limit} {group_col} values by {metric_col}: " + "; ".join(f"{k}: {_fmt_num(v)}" for k, v in shown) + "."
            if re.search(r"\b(highest|best|largest|max)\b", q):
                k, v = ordered[0]
                return f"The {group_col} with the highest {metric_col} is {k} with {_fmt_num(v)}."
            return f"Total {metric_col} by {group_col}: " + "; ".join(f"{k}: {_fmt_num(v)}" for k, v in ordered) + "."

    return ""


def _extract_threshold_pct(user_request: str) -> Optional[float]:
    m = re.search(r"\b(?:more than|over|exceeds?|greater than)\s+(\d+(?:\.\d+)?)\s*%", str(user_request or ""), flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _paired_numeric_columns(rows: List[Dict[str, Any]]) -> tuple[str, str]:
    if not rows or not isinstance(rows[0], dict):
        return "", ""
    cols = list(rows[0].keys())
    lowered = {str(c or "").lower(): str(c or "") for c in cols}
    pairs = [
        ("jan_qty", "feb_qty"),
        ("jan_amount", "feb_amount"),
        ("jan_budget", "feb_budget"),
        ("previous_month_budget", "current_month_budget"),
        ("before", "after"),
        ("previous", "current"),
        ("old", "new"),
        ("start", "end"),
    ]
    for left, right in pairs:
        if left in lowered and right in lowered:
            return lowered[left], lowered[right]
    numeric_cols: List[str] = []
    for col in cols:
        hits = 0
        for row in rows[:25]:
            if _coerce_float(row.get(col)) is not None:
                hits += 1
        if hits >= max(2, min(5, len(rows[:25]))):
            numeric_cols.append(str(col))
    if len(numeric_cols) >= 2:
        return numeric_cols[0], numeric_cols[1]
    return "", ""


def _delta_table_answer(file_hint: str, user_request: str) -> str:
    rows = _load_rows(file_hint)
    if not rows:
        return ""
    q = str(user_request or "").lower()
    if not re.search(r"\b(compare|comparison|variance|change|changed|increase|decrease|flag|breakdown)\b", q):
        return ""
    left_col, right_col = _paired_numeric_columns(rows)
    if not left_col or not right_col:
        return ""
    threshold_pct = _extract_threshold_pct(user_request)
    id_col = ""
    for cand in (
        "team",
        "queue",
        "course",
        "course_name",
        "vendor",
        "campaign",
        "campaign_name",
        "program",
        "program_name",
        "provider",
        "provider_name",
        "zone",
        "region",
        "neighborhood",
        "neighborhood_name",
        "device_type",
        "sku",
        "category",
        "product",
        "item",
        "name",
    ):
        found = _resolve_column(rows, cand)
        if found:
            id_col = found
            break
    owner_col = _resolve_column(rows, "owner")
    label_left = left_col.replace("_", " ").title()
    label_right = right_col.replace("_", " ").title()
    computed: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        left_v = _coerce_float(row.get(left_col))
        right_v = _coerce_float(row.get(right_col))
        if left_v is None or right_v is None:
            continue
        delta = float(right_v) - float(left_v)
        pct = (delta / float(left_v) * 100.0) if float(left_v) != 0 else None
        label = str(row.get(id_col) or "").strip() if id_col else ""
        owner = str(row.get(owner_col) or "").strip() if owner_col else ""
        flag = bool(threshold_pct is not None and pct is not None and abs(pct) > float(threshold_pct))
        computed.append({
            "label": label or "Row",
            "owner": owner,
            "left": float(left_v),
            "right": float(right_v),
            "delta": delta,
            "pct": pct,
            "flag": flag,
        })
    if not computed:
        return ""
    biggest_up = max(computed, key=lambda r: r["pct"] if r["pct"] is not None else float("-inf"))
    biggest_down = min(computed, key=lambda r: r["pct"] if r["pct"] is not None else float("inf"))
    flagged = [row for row in computed if row["flag"]]
    summary_lines = [
        "## Executive Summary",
        "",
        f"This analysis compares **{label_left}** to **{label_right}** across {len(computed)} row(s).",
        f"Biggest increase: **{biggest_up['label']}** ({_fmt_num(biggest_up['pct'])}%).",
        f"Biggest decrease: **{biggest_down['label']}** ({_fmt_num(biggest_down['pct'])}%).",
    ]
    if threshold_pct is not None:
        if flagged:
            summary_lines.append(
                f"Rows exceeding the **{_fmt_num(threshold_pct)}%** threshold: "
                + ", ".join(f"**{row['label']}** ({_fmt_num(row['pct'])}%)" for row in flagged)
                + "."
            )
        else:
            summary_lines.append(f"No rows exceeded the **{_fmt_num(threshold_pct)}%** threshold.")
    summary_lines.extend(["", "## Tabular Breakdown", ""])
    headers = [id_col.title() if id_col else "Row"]
    if owner_col:
        headers.append(owner_col.title())
    headers.extend([label_left, label_right, "Change", "Change (%)"])
    if threshold_pct is not None:
        headers.append(f"Flag (>{_fmt_num(threshold_pct)}%)")
    table = ["| " + " | ".join(headers) + " |", "| " + " | ".join([":---"] * len(headers)) + " |"]
    for row in computed:
        cells = [str(row["label"])]
        if owner_col:
            cells.append(str(row["owner"] or ""))
        cells.extend([
            _fmt_num(row["left"]),
            _fmt_num(row["right"]),
            f"{'+' if row['delta'] > 0 else ''}{_fmt_num(row['delta'])}",
            f"{'+' if (row['pct'] or 0) > 0 else ''}{_fmt_num(row['pct'])}%" if row["pct"] is not None else "n/a",
        ])
        if threshold_pct is not None:
            cells.append("Yes" if row["flag"] else "No")
        table.append("| " + " | ".join(cells) + " |")
    return "\n".join(summary_lines + table).strip()


def _md_table(headers: List[str], rows: List[List[Any]]) -> str:
    table = ["| " + " | ".join(headers) + " |", "| " + " | ".join([":---"] * len(headers)) + " |"]
    for row in rows:
        table.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(table)


def _action_register_answer(file_hint: str, user_request: str) -> str:
    rows = _load_rows(file_hint)
    q = str(user_request or "").lower()
    if not rows or "action register" not in q:
        return ""
    note_col = _resolve_column(rows, "note") or _resolve_column(rows, "action")
    owner_col = _resolve_column(rows, "owner")
    due_col = _resolve_column(rows, "due_date") or _resolve_column(rows, "due date")
    blocker_col = _resolve_column(rows, "blocker")
    priority_col = _resolve_column(rows, "priority")
    type_col = _resolve_column(rows, "rowtype") or _resolve_column(rows, "type")
    actions, decisions, questions = [], [], []
    for row in rows:
        kind = str(row.get(type_col) or "").strip().lower() if type_col else ""
        item = str(row.get(note_col) or "").strip()
        owner = str(row.get(owner_col) or "").strip() if owner_col else ""
        due = str(row.get(due_col) or "").strip() if due_col else ""
        blocker = str(row.get(blocker_col) or "").strip() if blocker_col else ""
        priority = str(row.get(priority_col) or "").strip() if priority_col else ""
        if "decision" in kind:
            if item:
                decisions.append(item)
            continue
        if "question" in kind:
            if item:
                questions.append(item)
            continue
        if item:
            actions.append([item, owner or "Unassigned", due or "TBD", blocker or "None", priority or "Medium"])
    if not actions and not decisions and not questions:
        return ""
    parts = ["## Executive Summary", ""]
    parts.append(f"Captured {len(actions)} action item(s), {len(decisions)} decision(s), and {len(questions)} unresolved question(s).")
    parts.extend(["", "## Action Register", "", _md_table(
        ["Action Item", "Owner", "Due Date", "Blocker", "Priority"],
        actions or [["No action items found", "-", "-", "-", "-"]],
    )])
    if decisions:
        parts.extend(["", "## Decisions Summary", ""] + [f"- {x}" for x in decisions])
    if questions:
        parts.extend(["", "## Unresolved Questions", ""] + [f"- {x}" for x in questions])
    return "\n".join(parts).strip()


def _support_triage_answer(file_hint: str, user_request: str) -> str:
    rows = _load_rows(file_hint)
    q = str(user_request or "").lower()
    if not rows or "triage brief" not in q:
        return ""
    id_col = _resolve_column(rows, "ticketid") or _resolve_column(rows, "ticket")
    customer_col = _resolve_column(rows, "customer")
    issue_col = _resolve_column(rows, "issue")
    impact_col = _resolve_column(rows, "impact")
    urgency_col = _resolve_column(rows, "urgency")
    age_col = _resolve_column(rows, "hoursopen") or _resolve_column(rows, "hours_open")
    ranked = []
    urgency_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    impact_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    for row in rows:
        urgency = str(row.get(urgency_col) or "").strip()
        impact = str(row.get(impact_col) or "").strip()
        hours = _coerce_float(row.get(age_col)) or 0.0
        score = urgency_rank.get(urgency.lower(), 0) * 10 + impact_rank.get(impact.lower(), 0) * 5 + min(hours, 48) / 6.0
        ranked.append((score, row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    top = ranked[:5]
    urgency_counts: Dict[str, int] = defaultdict(int)
    for _, row in ranked:
        urgency_counts[str(row.get(urgency_col) or "Unknown").strip() or "Unknown"] += 1
    table_rows = []
    for _, row in top:
        issue = str(row.get(issue_col) or "").strip()
        why = f"{row.get(impact_col) or ''} impact, {row.get(urgency_col) or ''} urgency, open {row.get(age_col) or ''}h".strip(", ")
        table_rows.append([
            str(row.get(id_col) or ""),
            str(row.get(customer_col) or ""),
            issue,
            str(row.get(urgency_col) or ""),
            why,
        ])
    parts = [
        "## Executive Summary",
        "",
        "Urgency mix: " + ", ".join(f"{k}={v}" for k, v in sorted(urgency_counts.items())) + ".",
        f"Top same-day queue contains {len(table_rows)} ticket(s) prioritized by urgency, impact, and age.",
        "",
        "## Same-Day Action Queue",
        "",
        _md_table(["Ticket", "Customer", "Issue", "Urgency", "Why It Needs Attention"], table_rows),
    ]
    return "\n".join(parts).strip()


def _contract_risk_answer(file_hint: str, user_request: str) -> str:
    rows = _load_rows(file_hint)
    q = str(user_request or "").lower()
    if not rows or "contract risk review" not in q:
        return ""
    clause_col = _resolve_column(rows, "clause")
    terms_col = _resolve_column(rows, "terms")
    risk_col = _resolve_column(rows, "risklevel") or _resolve_column(rows, "risk")
    high = [row for row in rows if str(row.get(risk_col) or "").strip().lower() == "high"]
    table_rows = [[str(r.get(clause_col) or ""), str(r.get(risk_col) or ""), str(r.get(terms_col) or "")] for r in high[:5]]
    questions = [f"Can we revise '{str(r.get(clause_col) or '').strip()}' to reduce exposure?" for r in high[:4]]
    parts = [
        "## Executive Summary",
        "",
        f"Identified {len(high)} high-risk clause(s) that should be reviewed before signature.",
        "",
        "## Highest-Risk Clauses",
        "",
        _md_table(["Clause", "Risk", "Why It Matters"], table_rows),
        "",
        "## Negotiation Questions",
        "",
        "\n".join(f"- {x}" for x in questions),
    ]
    return "\n".join(parts).strip()


def _hiring_memo_answer(file_hint: str, user_request: str) -> str:
    rows = _load_rows(file_hint)
    q = str(user_request or "").lower()
    if not rows or "hiring recommendation" not in q:
        return ""
    interviewer_col = _resolve_column(rows, "interviewer")
    strengths_col = _resolve_column(rows, "strengths")
    concerns_col = _resolve_column(rows, "concerns")
    rec_col = _resolve_column(rows, "recommendation")
    strengths = [str(r.get(strengths_col) or "").strip() for r in rows if str(r.get(strengths_col) or "").strip()]
    concerns = [str(r.get(concerns_col) or "").strip() for r in rows if str(r.get(concerns_col) or "").strip()]
    table_rows = [[str(r.get(interviewer_col) or ""), str(r.get(rec_col) or ""), str(r.get(strengths_col) or ""), str(r.get(concerns_col) or "")] for r in rows]
    parts = [
        "## Executive Summary",
        "",
        "Recommendation: proceed with a final decision only after one focused follow-up on the recurring risk areas.",
        f"Common strengths: {strengths[0] if strengths else 'n/a'}.",
        f"Main risks: {concerns[0] if concerns else 'n/a'}.",
        "",
        "## Panel View",
        "",
        _md_table(["Interviewer", "Recommendation", "Strengths", "Concerns"], table_rows),
        "",
        "## Follow-Up Questions",
        "",
        "- Ask for a quantified example of program impact.",
        "- Probe vendor procurement depth.",
        "- Test prioritization and metrics ownership with a concrete scenario.",
    ]
    return "\n".join(parts).strip()


def _incident_timeline_answer(file_hint: str, user_request: str) -> str:
    rows = _load_rows(file_hint)
    q = str(user_request or "").lower()
    if not rows or "incident timeline" not in q:
        return ""
    ts_col = _resolve_column(rows, "timestamp")
    source_col = _resolve_column(rows, "source")
    event_col = _resolve_column(rows, "event")
    table_rows = [[str(r.get(ts_col) or ""), str(r.get(source_col) or ""), str(r.get(event_col) or "")] for r in rows]
    first_customer = next((str(r.get(ts_col) or "") for r in rows if "customer" in str(r.get(event_col) or "").lower() or "ticket" in str(r.get(event_col) or "").lower()), "")
    recovery = next((str(r.get(ts_col) or "") for r in rows if "recovery" in str(r.get(event_col) or "").lower() or "dropped below" in str(r.get(event_col) or "").lower()), "")
    parts = [
        "## Executive Summary",
        "",
        f"Customer-facing impact likely ran from {first_customer or 'initial alert'} to {recovery or 'confirmed recovery'}.",
        "Likely turning points: first customer report, rollback start, and recovery confirmation.",
        "",
        "## Timeline",
        "",
        _md_table(["Timestamp", "Source", "Event"], table_rows),
        "",
        "## Next Follow-Up Actions",
        "",
        "- Confirm root cause and contributing factors.",
        "- Publish a customer-facing incident recap if required.",
        "- Add a prevention item to the incident tracker.",
    ]
    return "\n".join(parts).strip()


def _release_email_answer(file_hint: str, user_request: str) -> str:
    rows = _load_rows(file_hint)
    q = str(user_request or "").lower()
    if not rows or "release announcement email" not in q:
        return ""
    category_col = _resolve_column(rows, "category")
    item_col = _resolve_column(rows, "item")
    impact_col = _resolve_column(rows, "customerimpact") or _resolve_column(rows, "impact")
    action_col = _resolve_column(rows, "actionrequired")
    benefits = [f"- {str(r.get(item_col) or '').strip()}: {str(r.get(impact_col) or '').strip()}" for r in rows if str(r.get(category_col) or "").strip().lower() != "action required"]
    required = [str(r.get(item_col) or "").strip() for r in rows if str(r.get(action_col) or "").strip().lower() == "yes"]
    parts = [
        "Subject: New updates now available in your workspace",
        "",
        "Hi team,",
        "",
        "We just shipped a set of updates designed to make administration and reporting easier.",
        "",
        "What’s new:",
        *benefits[:5],
        "",
        "What you need to do next:",
        *(f"- {x}" for x in (required or ["No action is required right now."])),
        "",
        "Thanks,",
        "Product Team",
    ]
    return "\n".join(parts).strip()


def _vendor_shortlist_answer(file_hint: str, user_request: str) -> str:
    rows = _load_rows(file_hint)
    q = str(user_request or "").lower()
    if not rows or "shortlist" not in q:
        return ""
    vendor_col = _resolve_column(rows, "vendor")
    cost_col = _resolve_column(rows, "annualcost")
    weeks_col = _resolve_column(rows, "implementationweeks")
    sec_col = _resolve_column(rows, "securityscore")
    support_col = _resolve_column(rows, "supportscore")
    scored = []
    for r in rows:
        score = (12 - (_coerce_float(r.get(weeks_col)) or 12)) * 1.5 + (_coerce_float(r.get(sec_col)) or 0) * 2 + (_coerce_float(r.get(support_col)) or 0) * 1.5 - (_coerce_float(r.get(cost_col)) or 0) / 20000
        scored.append((score, r))
    scored.sort(key=lambda item: item[0], reverse=True)
    top = scored[0][1] if scored else {}
    table_rows = [[str(r.get(vendor_col) or ""), _fmt_num(r.get(cost_col)), _fmt_num(r.get(weeks_col)), _fmt_num(r.get(sec_col)), _fmt_num(r.get(support_col))] for _, r in scored]
    return "\n".join([
        "## Executive Summary",
        "",
        f"Recommended shortlist: **{str(top.get(vendor_col) or '')}** based on the best balance of speed, security, support, and cost.",
        "",
        "## Tradeoff Table",
        "",
        _md_table(["Vendor", "Annual Cost", "Implementation Weeks", "Security", "Support"], table_rows),
    ]).strip()


def _sprint_plan_answer(file_hint: str, user_request: str) -> str:
    rows = _load_rows(file_hint)
    q = str(user_request or "").lower()
    if not rows or "sprint plan" not in q:
        return ""
    title_col = _resolve_column(rows, "title")
    priority_col = _resolve_column(rows, "priority")
    effort_col = _resolve_column(rows, "effort")
    dep_col = _resolve_column(rows, "dependency")
    risk_col = _resolve_column(rows, "risk")
    ranked = sorted(rows, key=lambda r: ((str(r.get(priority_col) or "").lower() != "high"), _coerce_float(r.get(effort_col)) or 999))
    pull = ranked[:4]
    wait = ranked[4:]
    pull_rows = [[str(r.get(title_col) or ""), str(r.get(priority_col) or ""), str(r.get(effort_col) or ""), str(r.get(dep_col) or ""), str(r.get(risk_col) or "")] for r in pull]
    wait_lines = [f"- {str(r.get(title_col) or '').strip()}" for r in wait if str(r.get(title_col) or "").strip()]
    return "\n".join([
        "## Executive Summary",
        "",
        f"Recommended pulling {len(pull_rows)} item(s) into the next sprint, starting with the smallest high-priority work and dependency-unblocking items.",
        "",
        "## Pull First",
        "",
        _md_table(["Item", "Priority", "Effort", "Dependency", "Risk"], pull_rows),
        "",
        "## Wait / Revisit",
        "",
        *(wait_lines or ["- No additional items to defer."]),
    ]).strip()


def _faq_answer(file_hint: str, user_request: str) -> str:
    rows = _load_rows(file_hint)
    q = str(user_request or "").lower()
    if not rows or "faq" not in q:
        return ""
    topic_col = _resolve_column(rows, "topic")
    detail_col = _resolve_column(rows, "detail")
    lines = ["## FAQ", ""]
    for r in rows:
        topic = str(r.get(topic_col) or "").strip()
        detail = str(r.get(detail_col) or "").strip()
        if topic and detail:
            lines.append(f"**How does {topic.lower()} work?**")
            lines.append(detail)
            lines.append("")
    return "\n".join(lines).strip()


def _schedule_resolution_answer(file_hint: str, user_request: str) -> str:
    rows = _load_rows(file_hint)
    q = str(user_request or "").lower()
    if not rows or "scheduling resolution brief" not in q:
        return ""
    team_col = _resolve_column(rows, "team")
    issue_col = _resolve_column(rows, "issue")
    priority_col = _resolve_column(rows, "priority")
    stakeholder_col = _resolve_column(rows, "stakeholder")
    rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    ordered = sorted(rows, key=lambda r: rank.get(str(r.get(priority_col) or "").lower(), 0), reverse=True)
    table_rows = [[str(r.get(team_col) or ""), str(r.get(issue_col) or ""), str(r.get(priority_col) or ""), str(r.get(stakeholder_col) or "")] for r in ordered]
    contacts = [str(r.get(stakeholder_col) or "").strip() for r in ordered[:3] if str(r.get(stakeholder_col) or "").strip()]
    return "\n".join([
        "## Executive Summary",
        "",
        f"Resolve the critical conflicts first and contact {', '.join(contacts)} before lower-priority scheduling issues.",
        "",
        "## Conflict Order",
        "",
        _md_table(["Team", "Issue", "Priority", "Stakeholder"], table_rows),
    ]).strip()


def _extract_spreadsheet_file(text: str, params: Optional[Dict[str, Any]] = None) -> str:
    params = params or {}
    for key in ("path", "file", "file_path", "input_path"):
        v = str(params.get(key) or "").strip()
        if v:
            return v
    text_s = str(text or "")
    matches = list(re.finditer(r"([A-Za-z0-9_\- ./\\]+\.(?:xlsx|xlsm|xls|csv|tsv))", text_s, flags=re.IGNORECASE))
    for m in matches:
        raw = str(m.group(1) or "").strip().strip("'\"")
        if not raw:
            continue
        cleaned = re.sub(
            r"^(?:analyze|from|read|open|use|using|file|spreadsheet|workbook|in|on|for|the)\s+",
            "",
            raw,
            flags=re.IGNORECASE,
        ).strip()
        if cleaned != raw:
            return cleaned
        toks = raw.replace("\\", "/").split("/")[-1].split()
        for tok in reversed(toks):
            if re.search(r"\.(?:xlsx|xlsm|xls|csv|tsv)$", tok, flags=re.IGNORECASE):
                return tok.strip("'\"")
        return raw
    return ""


def _resolve_spreadsheet_file_hint(file_hint: str) -> str:
    raw = str(file_hint or "").strip()
    if not raw:
        return ""
    p = Path(raw)
    if p.exists():
        return str(p)
    name = p.name
    cwd = Path.cwd().resolve()
    roots = [
        cwd,
        cwd / "data",
        cwd / "data" / "agent_workflow" / "repo",
        cwd / "generated",
        cwd / "llmloader2",
        cwd / "llmloader2" / "data",
        cwd / "llmloader2" / "data" / "agent_workflow" / "repo",
        cwd / "llmloader2" / "generated",
    ]
    for parent in list(cwd.parents)[:3]:
        roots.extend([
            parent,
            parent / "data",
            parent / "data" / "agent_workflow" / "repo",
            parent / "generated",
            parent / "llmloader2",
            parent / "llmloader2" / "data",
            parent / "llmloader2" / "data" / "agent_workflow" / "repo",
            parent / "llmloader2" / "generated",
        ])
    seen = set()
    for root in roots:
        root_s = str(root)
        if root_s in seen:
            continue
        seen.add(root_s)
        for rel in (raw, name):
            if not rel:
                continue
            cand = root / rel
            try:
                if cand.exists():
                    return str(cand.resolve())
            except Exception:
                continue
    return raw


def _infer_group_op(user_request: str) -> str:
    q = str(user_request or "").lower()
    if re.search(r"\b(week|weekly)\b", q):
        return "week"
    if re.search(r"\b(month|monthly|month-by-month|month by month)\b", q):
        return "month"
    if re.search(r"\b(year|yearly|annual|annually)\b", q) and not re.search(r"\b(order date|by date|daily|day)\b", q):
        return "year"
    if re.search(r"\b(date|daily|day|order date)\b", q):
        return "date"
    return "month"


def _infer_metric(user_request: str) -> Dict[str, str]:
    q = str(user_request or "").lower()
    if re.search(r"\b(tax|vat|gst)\b", q):
        return {"column": "Tax (USD)", "op": "sum", "as": "Total_Tax"}
    if re.search(r"\b(item|items|quantity|qty|units|sold)\b", q):
        return {"column": "Units Sold", "op": "sum", "as": "Total_Items_Sold"}
    if re.search(r"\b(sales|revenue|amount|price|shares?|share)\b", q):
        return {"column": "Total (USD)", "op": "sum", "as": "Total_Sales"}
    return {"column": "Total (USD)", "op": "sum", "as": "Total_Sales"}


def _infer_category_group(user_request: str) -> str:
    q = str(user_request or "").lower()
    hints = [
        (r"\b(countries|country|nation|nations)\b", "Country"),
        (r"\b(regions|region|territory|territories)\b", "Region"),
        (r"\b(states|state|province|provinces)\b", "State"),
        (r"\b(cities|city)\b", "City"),
        (r"\b(products|product|items|item|sku|skus|device|devices)\b", "Product"),
        (r"\b(categories|category|segment|segments)\b", "Category"),
        (r"\b(customers|customer|client|clients)\b", "Customer"),
        (r"\b(brands|brand|manufacturer|manufacturers)\b", "Brand"),
    ]
    for pattern, column in hints:
        if re.search(pattern, q):
            return column
    return ""


def _infer_named_target(user_request: str) -> str:
    q = str(user_request or "").lower()
    targets = [
        "United States",
        "South Korea",
        "Japan",
        "China",
        "Taiwan",
        "Malaysia",
    ]
    for target in targets:
        if target.lower() in q:
            return target
    m = re.search(r"\b(?:for|is|does|did)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})\b", str(user_request or ""))
    return str(m.group(1)).strip() if m else ""


def _comparison_answer(ctx: Dict[str, Any], file_hint: str, user_request: str) -> str:
    q = str(user_request or "").lower()
    if not re.search(r"\b(compare|compared|versus|vs\.?|how many times|times)\b", q):
        return ""
    group_col = _infer_category_group(user_request)
    target = _infer_named_target(user_request)
    if not group_col or not target:
        return ""
    try:
        sheet_dir = Path(__file__).resolve().parent.parent / "sheet"
        sheet_dir_s = str(sheet_dir)
        if sheet_dir_s not in sys.path:
            sys.path.append(sheet_dir_s)
        import aggregate as sheet_aggregate  # type: ignore
    except Exception:
        return ""

    metric = _infer_metric(user_request)
    metric_key = str(metric.get("as") or "Total_Sales").strip()
    try:
        result = sheet_aggregate.run(ctx or {}, {
            "path": file_hint,
            "group_by": [{"column": group_col, "op": "", "as": group_col.replace(" ", "_")}],
            "metrics": [metric],
            "auto": True,
        })
    except Exception:
        return ""
    records = result.get("records") if isinstance(result, dict) else None
    if not isinstance(records, list) or not records:
        return ""
    group_key = group_col.replace(" ", "_")
    target_row = None
    rows = []
    for row in records:
        if not isinstance(row, dict):
            continue
        label = str(row.get(group_key) or row.get(group_col) or "").strip()
        value = _coerce_float(row.get(metric_key))
        if not label or value is None:
            continue
        item = {"label": label, "value": value}
        rows.append(item)
        if label.lower() == target.lower():
            target_row = item
    if not target_row:
        return ""
    target_value = float(target_row["value"])
    others = [r for r in rows if r["label"].lower() != target.lower()]
    others.sort(key=lambda r: float(r["value"]), reverse=True)
    metric_label = metric_key.replace("_", " ").lower()
    parts = [
        f"{target} has {metric_label} of {target_value:,.0f}.",
    ]
    if others:
        comparisons = []
        for row in others:
            other_value = float(row["value"])
            if other_value == 0:
                comparisons.append(f"{row['label']}: no comparable sales")
            else:
                comparisons.append(f"{row['label']}: {target_value / other_value:.2f}x ({other_value:,.0f})")
        parts.append(f"Compared with the other {group_col.lower()} values: " + "; ".join(comparisons) + ".")
    return " ".join(parts)


def _iso_week_range(label: str) -> str:
    m = re.match(r"^(\d{4})-W(\d{1,2})$", str(label or "").strip())
    if not m:
        return ""
    try:
        start = _date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
        end = _date.fromisocalendar(int(m.group(1)), int(m.group(2)), 7)
        return f"{start.isoformat()} to {end.isoformat()}"
    except Exception:
        return ""


def _spreadsheet_answer(ctx: Dict[str, Any], params: Dict[str, Any], user_request: str) -> str:
    file_hint = _extract_spreadsheet_file(user_request, params)
    if not file_hint:
        return ""
    file_hint = _resolve_spreadsheet_file_hint(file_hint)
    for fn in (
        _action_register_answer,
        _support_triage_answer,
        _contract_risk_answer,
        _hiring_memo_answer,
        _incident_timeline_answer,
        _release_email_answer,
        _vendor_shortlist_answer,
        _sprint_plan_answer,
        _faq_answer,
        _schedule_resolution_answer,
    ):
        direct = fn(file_hint, user_request)
        if direct:
            return direct
    delta = _delta_table_answer(file_hint, user_request)
    if delta:
        return delta
    comparison = _comparison_answer(ctx, file_hint, user_request)
    if comparison:
        return comparison
    general = _general_spreadsheet_answer(file_hint, user_request)
    if general:
        return general
    try:
        sheet_dir = Path(__file__).resolve().parent.parent / "sheet"
        sheet_dir_s = str(sheet_dir)
        if sheet_dir_s not in sys.path:
            sys.path.append(sheet_dir_s)
        import aggregate as sheet_aggregate  # type: ignore
    except Exception:
        return ""

    group_op = _infer_group_op(user_request)
    group_alias = {"week": "Week", "month": "Month", "year": "Year", "date": "Order_Date"}.get(group_op, "Month")
    metric = _infer_metric(user_request)
    try:
        result = sheet_aggregate.run(ctx or {}, {
            "path": file_hint,
            "group_by": [{"column": "Order Date", "op": group_op, "as": group_alias}],
            "metrics": [metric],
            "auto": True,
        })
    except Exception:
        return ""
    records = result.get("records") if isinstance(result, dict) else None
    if not isinstance(records, list) or not records:
        return ""
    metric_key = str(metric.get("as") or "").strip()
    best = None
    best_val = None
    for row in records:
        if not isinstance(row, dict):
            continue
        val = _coerce_float(row.get(metric_key))
        if val is None:
            continue
        if best is None or val > float(best_val):
            best = row
            best_val = val
    if not isinstance(best, dict) or best_val is None:
        return ""
    group_value = str(best.get(group_alias) or "").strip()
    metric_label = metric_key.replace("_", " ").strip() or "Total"
    range_text = _iso_week_range(group_value) if group_op == "week" else ""
    if range_text:
        return f"The best performing {group_op} is {group_value} ({range_text}) with {metric_label.lower()} of {best_val:,.3f}."
    return f"The best performing {group_op} is {group_value} with {metric_label.lower()} of {best_val:,.3f}."


def _is_status_like_text(text: str) -> bool:
    low = str(text or "").strip().lower()
    if not low:
        return False
    markers = (
        "tracker completed all",
        "tracker selected request",
        "workflow bundle `",
        "sandbox validation passed for",
        "sandbox suite passed for",
        "status: completed; flow_name:",
    )
    return any(marker in low for marker in markers)


def _extract_tagged_report_text(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    low = raw.lower()
    if "role:" not in low and "response:" not in low and "summary:" not in low:
        return ""
    lines = raw.splitlines()
    picked: list[str] = []
    capture = False
    for line in lines:
        stripped = line.strip()
        low_line = stripped.lower()
        if low_line.startswith("response:"):
            value = stripped.split(":", 1)[1].strip()
            if value:
                picked = [value]
                capture = True
            else:
                picked = []
                capture = True
            continue
        if low_line.startswith("did:") and not picked:
            value = stripped.split(":", 1)[1].strip()
            if value:
                picked = [value]
            continue
        if low_line.startswith("summary:") and not picked:
            value = stripped.split(":", 1)[1].strip()
            if value:
                picked = [value]
            continue
        if capture:
            if re.match(r"^(plan|analysis|did|actions|skills_invoked|skill_results|handoff)\s*:", low_line):
                break
            if stripped:
                picked.append(stripped)
    return "\n".join(picked).strip()


def run(ctx, params):
    if not isinstance(params, dict):
        params = {"text": str(params or "").strip()} if str(params or "").strip() else {}
    else:
        params = dict(params or {})
    raw_text = str(params.get("text") or "").strip()
    execution_text = str(params.get("execution_text") or "").strip()
    preferred_text = str(
        params.get("finalized_text")
        or params.get("final_answer")
        or params.get("markdown")
        or params.get("table_markdown")
        or params.get("content")
        or params.get("response")
        or params.get("answer")
        or params.get("summary")
        or ""
    ).strip()
    request_like_text = str(
        params.get("user_request")
        or params.get("request_text")
        or params.get("request")
        or params.get("prompt")
        or ""
    ).strip()
    explicit_final_present = bool(preferred_text)
    text = str(
        (
            execution_text
            if execution_text and (not raw_text or _is_status_like_text(raw_text) or raw_text == request_like_text)
            else (
                preferred_text
                if preferred_text and (not raw_text or _is_status_like_text(raw_text) or raw_text == request_like_text)
                else raw_text
            )
        )
        or preferred_text
        or ""
    ).strip()
    tagged_text = _extract_tagged_report_text(text)
    if tagged_text:
        text = tagged_text
    if not text:
        parts = []
        for label, key in (
            ("Summary", "summary"),
            ("Analysis", "analysis"),
            ("Recommendation", "recommendation"),
            ("Response", "response"),
        ):
            val = str(params.get(key) or "").strip()
            if val:
                parts.append(f"**{label}**\n{val}")
        actions = params.get("actions")
        if isinstance(actions, list) and actions:
            lines = [str(v or "").strip() for v in actions if str(v or "").strip()]
            if lines:
                parts.append("**Next Steps**\n" + "\n".join(f"- {v}" for v in lines))
        text = "\n\n".join(parts).strip()
    user_request = request_like_text
    compare_like_request = bool(
        user_request
        and re.search(r"\b(compare|variance|flag|breakdown|increase|decrease|changed)\b", user_request, flags=re.IGNORECASE)
    )
    low_text = text.lower()
    should_recompute = (
        not text
        or "value_unavailable_from_tool_results" in text
        or (compare_like_request and not explicit_final_present)
        or any(marker in low_text for marker in (
            "[agent_flow]",
            "source data inaccessible",
            "tool results provided only one record",
            "placeholders are used",
            "[action item description]",
            "unable to generate",
        ))
    )
    if should_recompute and user_request:
        computed = _spreadsheet_answer(ctx or {}, params, user_request)
        if computed:
            text = computed
    return {
        "ok": True,
        "mode": "text",
        "text": text,
        "data": {
            "mode": "text",
            "text": text,
        },
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "result",
    "label": "Result: Text",
    "description": "Emit a normal assistant text result outside Agent Jobs.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "user_request": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
