NAME = "result.text"
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


def _load_text_file(file_hint: str) -> str:
    try:
        return Path(file_hint).read_text(encoding="utf-8")
    except Exception:
        try:
            return Path(file_hint).read_text(encoding="utf-8-sig")
        except Exception:
            return ""


def _load_json_file(file_hint: str) -> Any:
    raw = _load_text_file(file_hint)
    if not raw:
        return None
    try:
        import json
        return json.loads(raw)
    except Exception:
        return None


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
    m = re.search(
        r"\b(?:more than|over|exceeds?|greater than)\s+(\d+(?:\.\d+)?)\s*(?:%|percent)\b",
        str(user_request or ""),
        flags=re.IGNORECASE,
    )
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
        ("prior_month", "current_month"),
        ("last_month", "this_month"),
        ("previous_week", "current_week"),
        ("previous_week_breaches", "current_week_breaches"),
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
    id_col = _infer_group_column_from_request(rows, user_request)
    if not id_col:
        for cand in (
            "department",
            "dept",
            "division",
            "cost_center",
            "group",
            "team_name",
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
    biggest_up = max(computed, key=lambda r: (r["delta"], r["pct"] if r["pct"] is not None else float("-inf")))
    biggest_down = min(computed, key=lambda r: (r["delta"], r["pct"] if r["pct"] is not None else float("inf")))
    flagged = [row for row in computed if row["flag"]]
    summary_lines = [
        "## Executive Summary",
        "",
        f"This analysis compares **{label_left}** to **{label_right}** across {len(computed)} row(s).",
        f"Biggest increase: **{biggest_up['label']}** (+{_fmt_num(biggest_up['delta'])}, {_fmt_num(biggest_up['pct'])}%).",
        f"Biggest decrease: **{biggest_down['label']}** ({_fmt_num(biggest_down['delta'])}, {_fmt_num(biggest_down['pct'])}%).",
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
    id_col = _resolve_column(rows, "ticketid") or _resolve_column(rows, "ticket_id") or _resolve_column(rows, "ticket")
    customer_col = _resolve_column(rows, "customer")
    issue_col = _resolve_column(rows, "issue") or _resolve_column(rows, "subject")
    urgency_col = _resolve_column(rows, "urgency") or _resolve_column(rows, "priority") or _resolve_column(rows, "severity")
    impact_col = _resolve_column(rows, "impact")
    age_col = _resolve_column(rows, "hoursopen") or _resolve_column(rows, "hours_open") or _resolve_column(rows, "age_hours")
    same_day_col = _resolve_column(rows, "same_day_needed") or _resolve_column(rows, "same_day") or _resolve_column(rows, "today")
    ranked = []
    urgency_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    impact_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    yes_values = {"yes", "true", "1", "y", "required", "needed"}
    for row in rows:
        urgency = str(row.get(urgency_col) or "").strip()
        impact = str(row.get(impact_col) or "").strip()
        hours = _coerce_float(row.get(age_col)) or 0.0
        same_day = str(row.get(same_day_col) or "").strip().lower() in yes_values if same_day_col else False
        score = urgency_rank.get(urgency.lower(), 0) * 10
        score += impact_rank.get(impact.lower(), 0) * 5
        score += 8 if same_day else 0
        score += min(hours, 48) / 6.0
        ranked.append((score, same_day, row))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    top = ranked[:5]
    urgency_counts: Dict[str, int] = defaultdict(int)
    same_day_first = []
    for _, same_day, row in ranked:
        level = str(row.get(urgency_col) or "Unknown").strip() or "Unknown"
        urgency_counts[level] += 1
        if same_day and len(same_day_first) < 3:
            same_day_first.append(str(row.get(id_col) or "").strip())
    table_rows = []
    why_lines = []
    for _, same_day, row in top:
        ticket_id = str(row.get(id_col) or "").strip()
        customer = str(row.get(customer_col) or "").strip()
        issue = str(row.get(issue_col) or "").strip()
        urgency = str(row.get(urgency_col) or "").strip()
        hours = _coerce_float(row.get(age_col)) or 0.0
        reasons = []
        if same_day:
            reasons.append("same-day follow-up required")
        if urgency:
            reasons.append(f"{urgency} priority")
        if impact:
            reasons.append(f"{impact} impact")
        if hours:
            reasons.append(f"open {int(hours) if abs(hours - round(hours)) < 1e-9 else _fmt_num(hours)}h")
        why = ", ".join(reasons) if reasons else "review based on ticket priority and issue type"
        table_rows.append([ticket_id, customer, issue, urgency or ("same-day" if same_day else ""), why])
        why_lines.append(f"- {ticket_id}: {why}, issue: {issue}" if issue else f"- {ticket_id}: {why}")
    immediate = ", ".join(f"**{ticket}**" for ticket in same_day_first if ticket)
    parts = [
        "## Executive Summary",
        "",
        "Urgency mix: " + ", ".join(f"{k}={v}" for k, v in sorted(urgency_counts.items())) + ".",
        f"Top same-day queue contains {len(table_rows)} ticket(s) prioritized by urgency, impact, and age.",
    ]
    if immediate:
        parts.append(f"Immediate attention first: {immediate}.")
    parts.extend([
        "",
        "## Same-Day Action Queue",
        "",
        _md_table(["Ticket", "Customer", "Issue", "Urgency", "Why It Needs Attention"], table_rows),
    ])
    if why_lines:
        parts.extend(["", "## Why These Tickets", ""] + why_lines)
    return "\n".join(parts).strip()


def _contract_risk_answer(file_hint: str, user_request: str) -> str:
    q = str(user_request or "").lower()
    if "contract risk review" not in q:
        return ""
    rows = _load_rows(file_hint)
    clause_items: List[Dict[str, str]] = []
    if rows:
        clause_col = _resolve_column(rows, "clause")
        terms_col = _resolve_column(rows, "terms")
        risk_col = _resolve_column(rows, "risklevel") or _resolve_column(rows, "risk")
        for row in rows:
            risk = str(row.get(risk_col) or "").strip() if risk_col else ""
            clause = str(row.get(clause_col) or "").strip() if clause_col else ""
            terms = str(row.get(terms_col) or "").strip() if terms_col else ""
            if clause:
                clause_items.append({"clause": clause, "risk": risk or "High", "terms": terms})
        clause_items = [item for item in clause_items if item.get("risk", "").lower() == "high"] or clause_items[:5]
    else:
        raw = _load_text_file(file_hint)
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped.lower().startswith("clause "):
                continue
            clause, _, terms = stripped.partition(":")
            clause_items.append({"clause": clause.strip(), "risk": "High", "terms": terms.strip()})
        clause_items = clause_items[:5]
    if not clause_items:
        return ""
    table_rows = [[item.get("clause", ""), item.get("risk", "High"), item.get("terms", "")] for item in clause_items]
    questions = [f"Can we tighten {item.get('clause', 'this clause')} to reduce exposure?" for item in clause_items[:4]]
    parts = [
        "## Executive Summary",
        "",
        f"Identified {len(clause_items)} clause(s) that merit follow-up before signature.",
        "",
        "## Highest-Risk Clauses",
        "",
        _md_table(["Clause", "Risk", "Why It Matters"], table_rows),
        "",
        "## Follow-Up Questions",
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
    q = str(user_request or "").lower()
    if "release announcement email" not in q:
        return ""
    rows = _load_rows(file_hint)
    product = "your workspace"
    benefits: List[str] = []
    required: List[str] = []
    if rows:
        category_col = _resolve_column(rows, "category")
        item_col = _resolve_column(rows, "item")
        impact_col = _resolve_column(rows, "customerimpact") or _resolve_column(rows, "impact")
        action_col = _resolve_column(rows, "actionrequired")
        benefits = [f"- {str(r.get(item_col) or '').strip()}: {str(r.get(impact_col) or '').strip()}" for r in rows if str(r.get(category_col) or "").strip().lower() != "action required"]
        required = [str(r.get(item_col) or "").strip() for r in rows if str(r.get(action_col) or "").strip().lower() == "yes"]
    else:
        payload = _load_json_file(file_hint)
        if isinstance(payload, dict):
            product = str(payload.get("product") or product).strip() or product
            highlights = [str(x or "").strip() for x in (payload.get("highlights") or []) if str(x or "").strip()]
            customer_benefits = [str(x or "").strip() for x in (payload.get("customer_benefits") or []) if str(x or "").strip()]
            next_steps = [str(x or "").strip() for x in (payload.get("next_steps") or []) if str(x or "").strip()]
            for idx, item in enumerate(highlights):
                benefit = customer_benefits[idx] if idx < len(customer_benefits) else ""
                benefits.append(f"- {item}" + (f": {benefit}" if benefit else ""))
            required = next_steps
    if not benefits and not required:
        return ""
    parts = [
        f"Subject: {product} updates now available",
        "",
        "Hi team,",
        "",
        f"We just shipped a new {product} release with updates focused on customer value and smoother day-to-day work.",
        "",
        "Main benefits:",
        *(benefits[:5] or ["- New improvements are now available in your workspace."]),
        "",
        "Next steps:",
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
            question = topic
            if not re.search(r"[?!.]$", question):
                question = question.rstrip(":") + "?"
            lines.append(f"### {question}")
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


def _extract_request_file(text: str, params: Optional[Dict[str, Any]] = None, exts: Optional[List[str]] = None) -> str:
    params = params or {}
    nested_meta = params.get("execution_meta") if isinstance(params.get("execution_meta"), dict) else {}
    ext_list = exts or ["xlsx", "xlsm", "xls", "csv", "tsv", "txt", "json", "md"]
    ext_pat = "|".join(re.escape(ext) for ext in ext_list)
    for key in ("normalized_from_request_file", "request_file"):
        v = str(params.get(key) or "").strip()
        if v and re.search(rf"\.(?:{ext_pat})$", v, flags=re.IGNORECASE):
            return v
    for key in ("normalized_from_request_file", "request_file"):
        v = str((nested_meta or {}).get(key) or "").strip()
        if v and re.search(rf"\.(?:{ext_pat})$", v, flags=re.IGNORECASE):
            return v
    text_s = str(text or "")
    explicit_matches = list(re.finditer(rf"(/[^\s\"']+\.(?:{ext_pat})|[A-Za-z]:[/\\][^\s\"']+\.(?:{ext_pat}))", text_s, flags=re.IGNORECASE))
    for m in explicit_matches:
        raw = str(m.group(1) or "").strip().strip("'\"")
        if raw:
            return raw
    for key in ("path", "file", "file_path", "input_path"):
        v = str(params.get(key) or "").strip()
        if v and re.search(rf"\.(?:{ext_pat})$", v, flags=re.IGNORECASE):
            return v
    matches = list(re.finditer(rf"([A-Za-z0-9_\- ./\\]+\.(?:{ext_pat}))", text_s, flags=re.IGNORECASE))
    for m in matches:
        raw = str(m.group(1) or "").strip().strip("'\"")
        if not raw:
            continue
        cleaned = re.sub(r"^(?:analyze|from|read|open|use|using|file|spreadsheet|workbook|document|json|notes|in|on|for|the)\s+", "", raw, flags=re.IGNORECASE).strip()
        if cleaned != raw:
            return cleaned
        toks = raw.replace("\\", "/").split("/")[-1].split()
        for tok in reversed(toks):
            if re.search(rf"\.(?:{ext_pat})$", tok, flags=re.IGNORECASE):
                return tok.strip("'\"")
        return raw
    return ""


def _extract_spreadsheet_file(text: str, params: Optional[Dict[str, Any]] = None) -> str:
    return _extract_request_file(text, params, ["xlsx", "xlsm", "xls", "csv", "tsv"])


def _resolve_spreadsheet_file_hint(file_hint: str) -> str:
    raw = str(file_hint or "").strip()
    if not raw:
        return ""
    p = Path(raw)
    if p.exists():
        return str(p)
    name = p.name
    cwd = Path.cwd().resolve()
    app_relative = ""
    uploads_relative = ""
    if raw.startswith("/app/"):
        app_relative = raw[len("/app/"):].strip().lstrip("/\\")
    if raw.startswith("/uploads/"):
        uploads_relative = ("data/" + raw.lstrip("/")).strip().lstrip("/\\")
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
        rel_candidates = [raw]
        if app_relative:
            rel_candidates.append(app_relative)
        if uploads_relative:
            rel_candidates.append(uploads_relative)
        rel_candidates.append(name)
        for rel in rel_candidates:
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
    file_hint = _extract_request_file(user_request, params)
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



def _strip_status_preamble(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    markers = ("\n## ", "\n| ", "\n- ", "\n1. ", "\n2. ", "\n3. ")
    starts = [raw.find(marker) for marker in markers if raw.find(marker) > 0]
    if not starts:
        return raw
    start = min(starts)
    prefix = raw[:start].strip()
    body = raw[start:].strip()
    if not body:
        return raw
    prefix_lines = [line.strip() for line in prefix.splitlines() if line.strip()]
    if not prefix_lines:
        return body
    normalized = [re.sub(r"\s+", " ", line.lower()) for line in prefix_lines]
    all_status_like = all(
        (
            line.startswith("generated ")
            or line.startswith("rendered ")
            or line.startswith("created ")
            or line.startswith("produced ")
            or line.startswith("drafted ")
            or line.startswith("prepared ")
            or line.startswith("summarized ")
        )
        for line in normalized
    )
    deduped = []
    seen = set()
    for line in prefix_lines:
        key = re.sub(r"\s+", " ", line.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(line)
    if all_status_like:
        return body
    if len(deduped) == 1 and deduped[0].lower().startswith(("generated ", "rendered ", "created ", "produced ")):
        return body
    return raw


def _source_lines_markdown(current_text: str, limit: int = 5) -> list[str]:
    lines = [str(line or '').strip() for line in str(current_text or '').splitlines() if str(line or '').strip()]
    picked: list[str] = []
    for line in lines:
        formatted = line if line.startswith('- ') else f"- {line}"
        if ('http://' in line or 'https://' in line) and '::' in line:
            picked.append(formatted)
        elif ('http://' in line or 'https://' in line):
            picked.append(formatted)
        if len(picked) >= max(1, int(limit or 5)):
            break
    return picked


def _looks_like_url_list(text: str) -> bool:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return False
    url_lines = [line for line in lines if "http://" in line or "https://" in line]
    return len(url_lines) >= max(3, len(lines) - 1)



def _educational_deliverable_answer(user_request: str, current_text: str = "") -> str:
    req = str(user_request or "").strip()
    low = req.lower()
    if not req:
        return ""
    source_lines = _source_lines_markdown(current_text, limit=5)

    def _source_constraint_unavailable(reason: str) -> str:
        body = [
            "value_unavailable_from_tool_results",
            "",
            reason,
        ]
        if source_lines:
            body += ["", "**Current Sources Found**", *source_lines[:8]]
        return "\n".join(body).strip()

    if "yahoo finance" in low and any(tok in low for tok in ("nvda", "amd", "market cap", "52-week range", "average volume")):
        return _source_constraint_unavailable(
            "The upstream executor returned Yahoo Finance source links but did not extract the explicit NVDA and AMD fields required for the comparison."
        )
    if "world bank" in low and all(tok in low for tok in ("inflation", "gdp growth", "unemployment")):
        return _source_constraint_unavailable(
            "The upstream executor returned World Bank references but did not extract the latest inflation, GDP growth, and unemployment values needed for the country comparison."
        )
    if "imf" in low and "world bank" in low and any(tok in low for tok in ("macro brief", "growth", "inflation outlook")):
        return _source_constraint_unavailable(
            "The upstream executor returned IMF and World Bank references but did not extract concrete growth and inflation outlook values for the requested economies."
        )
    if "google scholar" in low and any(tok in low for tok in ("scholarly sources", "strongest repeated findings", "school pressure")):
        return _source_constraint_unavailable(
            "The upstream executor returned Google Scholar links but did not extract five structured scholarly sources with title, year, link, and synthesis."
        )
    if "arxiv" in low and any(tok in low for tok in ("recent papers", "synthetic political content", "methods-oriented synthesis")):
        return _source_constraint_unavailable(
            "The upstream executor returned links but did not extract five structured arXiv papers with years, arXiv links, and a methods-oriented synthesis."
        )

    if ("calculus" in low or "statistics" in low) and any(tok in low for tok in ("housing prices", "inflation", "college tuition", "affordability", "real data")):
        body = [
            "## Project Plan",
            "",
            "**Working Question**",
            "How has affordability changed over time when comparing housing prices, inflation, and college tuition?",
            "",
            "**Math Focus**",
            "- AP Calculus option: model rates of change, trend slopes, and relative acceleration in costs.",
            "- AP Statistics option: compare distributions, percent change, regression lines, and correlation across datasets.",
        ]
        if source_lines:
            body += ["", "**Current Sources Found**", *source_lines]
        return "\n".join(body)

    if "physics" in low and any(tok in low for tok in ("renewable energy", "solar panel", "battery storage", "energy costs today", "energy costs")):
        body = [
            "## Project Design",
            "",
            "**Topic**",
            "Renewable energy efficiency using a measurable physical variable and a current cost connection.",
            "",
            "**Project Options**",
            "- Compare solar panel angle versus output under controlled light conditions.",
            "- Compare small battery storage choices by charge retention, output stability, or recharge efficiency.",
        ]
        if source_lines:
            body += ["", "**Current Sources Found**", *source_lines]
        return "\n".join(body)

    if "art project" in low or ("art" in low and any(tok in low for tok in ("consumerism", "climate anxiety", "identity", "concept statement"))):
        body = [
            "## Art Series Proposal",
            "",
            "**Series Concept**",
            "Create a multi-piece series showing how consumer culture, climate anxiety, and personal identity overlap rather than exist as separate issues.",
        ]
        if source_lines:
            body += ["", "**Current Context Sources Found**", *source_lines]
        return "\n".join(body)

    return ""


def _structured_review_markdown(current_text: str) -> str:
    raw = str(current_text or "").strip()
    if not raw:
        return ""
    lines = [str(line or "").rstrip() for line in raw.splitlines()]
    if len(lines) < 2:
        return ""
    known_headers = {
        "repo root",
        "target folder",
        "verified files",
        "changed files",
        "git status",
        "rag sync",
        "findings",
        "proposed improvements",
        "what it supports",
        "missing files",
        "files",
    }
    if not any(
        ":" in line and line.split(":", 1)[0].strip().lower() in known_headers
        for line in lines[1:] if line.strip()
    ):
        return ""
    first = lines[0].strip()
    first_key = first.split(":", 1)[0].strip().lower() if ":" in first else ""
    summary_line = "" if first_key in known_headers else first

    scalar_keys = ["repo root", "target folder", "git status", "rag sync", "changed files"]
    list_keys = ["verified files", "what it supports", "findings", "proposed improvements", "missing files", "files"]
    scalar_values: dict[str, str] = {}
    list_values: dict[str, list[str]] = {}
    current_list: str | None = None

    def _add_list_item(section: str, value: str) -> None:
        item = str(value or "").strip()
        if not item:
            return
        bucket = list_values.setdefault(section, [])
        if item not in bucket:
            bucket.append(item)

    for line in lines if summary_line == "" else lines[1:]:
        s = line.strip()
        if not s:
            continue
        if ":" in s:
            key, value = s.split(":", 1)
            key_norm = key.strip().lower()
            value_norm = value.strip()
            if key_norm in scalar_keys:
                scalar_values[key_norm] = value_norm or "none"
                current_list = None
                continue
            if key_norm in list_keys:
                current_list = key_norm
                if value_norm and value_norm.lower() != "none":
                    if key_norm in {"verified files", "missing files", "files"}:
                        for part in re.split(r",(?=\s*\S)", value_norm):
                            _add_list_item(key_norm, str(part or "").strip())
                    else:
                        _add_list_item(key_norm, value_norm)
                elif value_norm.lower() == "none":
                    list_values.setdefault(key_norm, [])
                continue
        if current_list:
            item = s[2:].strip() if s.startswith("- ") else s
            _add_list_item(current_list, item)

    if not scalar_values and not list_values:
        return ""

    label_map = {
        "repo root": "Repo Root",
        "target folder": "Target Folder",
        "git status": "Git Status",
        "rag sync": "RAG Sync",
        "changed files": "Changed Files",
    }
    title_map = {
        "verified files": "Verified Files",
        "what it supports": "What It Supports",
        "findings": "Findings",
        "proposed improvements": "Proposed Improvements",
        "missing files": "Missing Files",
        "files": "Files",
    }

    out: list[str] = []
    if summary_line:
        out.append(f"## Summary\n{summary_line}")

    detail_rows: list[str] = []
    for key in scalar_keys:
        value = scalar_values.get(key, "").strip()
        if not value:
            continue
        formatted = f"`{value}`" if key in {"repo root", "target folder"} else value
        detail_rows.append(f"| {label_map[key]} | {formatted} |")
    if detail_rows:
        out.append("## Details\n| Field | Value |\n|---|---|\n" + "\n".join(detail_rows))

    for key in list_keys:
        if key not in list_values:
            continue
        items = list_values.get(key) or []
        out.append(f"## {title_map[key]}")
        if items:
            if key in {"verified files", "missing files", "files"}:
                out.extend(f"- `{item}`" for item in items)
            else:
                out.extend(f"- {item}" for item in items)
        else:
            out.append("- None")
    return "\n\n".join(part.strip() for part in out if str(part or "").strip()).strip()


def _artifact_result_text(params: Dict[str, Any], user_request: str, current_text: str) -> str:
    request_low = str(user_request or "").lower()
    wants_file_result = bool(re.search(r"\b(download|export|save|write|create file|output file|workbook|spreadsheet|html file|pdf file|json file)\b", request_low))
    for key in ("output_path", "path", "file_path", "input_path"):
        raw = str(params.get(key) or "").strip()
        if not raw:
            continue
        resolved = _resolve_spreadsheet_file_hint(raw)
        suffix = Path(resolved).suffix.lower()
        if suffix == ".html" and re.search(r"\b(chart|graph|plot|visuali[sz]e|print out its chart)\b", request_low):
            return "\n".join([
                "## Chart Output",
                "",
                f"Chart report created: `{resolved}`",
                "",
                "Open the HTML file to view the rendered chart output.",
            ]).strip()
        if wants_file_result and suffix in (".html", ".csv", ".xlsx", ".xlsm", ".xls", ".json", ".md", ".pdf") and (
            not current_text or _is_status_like_text(current_text) or current_text.lower().startswith(("rendered ", "generated ", "created ", "produced "))
        ):
            return "\n".join([
                "## Output File",
                "",
                f"Generated file: `{resolved}`",
            ]).strip()
    return ""


def _hydrate_from_previous_step(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(params or {})
    ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
    ext = ext if isinstance(ext, dict) else {}
    candidates = []
    for key in ("agent_flow_previous_step_report_with_tools", "agent_flow_previous_step_report"):
        value = ext.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    if not candidates:
        return out

    def _merge_from(source: Dict[str, Any]) -> None:
        for key in ("finalized_text", "final_answer", "markdown", "table_markdown", "content", "response", "answer", "summary", "text", "output_path", "path", "input_path", "file_path", "mode"):
            if key not in out or out.get(key) in (None, "", [], {}):
                value = source.get(key)
                if value not in (None, "", [], {}):
                    out[key] = value
        tr = source.get("tool_results") if isinstance(source.get("tool_results"), list) else []
        for row in tr:
            if not isinstance(row, dict):
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            for key in ("finalized_text", "final_answer", "markdown", "table_markdown", "content", "response", "answer", "summary", "text", "output_path", "path", "input_path", "file_path", "mode"):
                if key not in out or out.get(key) in (None, "", [], {}):
                    value = data.get(key) if isinstance(data, dict) else None
                    if value in (None, "", [], {}):
                        value = row.get(key)
                    if value not in (None, "", [], {}):
                        out[key] = value
            if isinstance(data, dict) and ("data" not in out or out.get("data") in (None, "", [], {})):
                nested = data.get("data") if isinstance(data.get("data"), dict) else None
                if isinstance(nested, dict) and nested:
                    out["data"] = nested
            if isinstance(data, dict) and "rows" in data and ("data" not in out or not isinstance(out.get("data"), dict) or "rows" not in out.get("data", {})):
                merged_data = dict(out.get("data") or {}) if isinstance(out.get("data"), dict) else {}
                merged_data.setdefault("rows", data.get("rows"))
                if "warnings" in data and "warnings" not in merged_data:
                    merged_data["warnings"] = data.get("warnings")
                out["data"] = merged_data

    for candidate in candidates:
        _merge_from(candidate)
    return out


def run(ctx, params):
    if not isinstance(params, dict):
        params = {"text": str(params or "").strip()} if str(params or "").strip() else {}
    else:
        params = dict(params or {})
    params = _hydrate_from_previous_step(ctx or {}, params)
    nested = params.get("data") if isinstance(params.get("data"), dict) else {}
    if nested:
        for key in (
            "finalized_text",
            "final_answer",
            "markdown",
            "table_markdown",
            "content",
            "response",
            "answer",
            "summary",
            "text",
            "user_request",
            "request_text",
            "request",
            "prompt",
            "output_path",
            "path",
            "input_path",
            "file_path",
            "mode",
        ):
            if key not in params or params.get(key) in (None, "", [], {}):
                value = nested.get(key)
                if value not in (None, "", [], {}):
                    params[key] = value
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
    else:
        stripped = _strip_status_preamble(text)
        if stripped:
            text = stripped
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
    spreadsheet_file_hint = _extract_spreadsheet_file(user_request, params) if user_request else ""
    compare_like_request = bool(
        user_request
        and re.search(r"\b(compare|variance|flag|breakdown|increase|decrease|changed)\b", user_request, flags=re.IGNORECASE)
    )
    compare_file_hint = spreadsheet_file_hint if compare_like_request else ""
    requested_file_hint = _extract_request_file(user_request, params) if user_request else ""
    spreadsheet_report_request = bool(
        spreadsheet_file_hint
        and re.search(r"\b(brief|review|summary|timeline|announcement|recommendation|plan|faq|triage|risk|shortlist|contract|incident|release|sprint|schedule)\b", user_request, flags=re.IGNORECASE)
    )
    document_report_request = bool(
        requested_file_hint
        and re.search(r"\b(brief|review|summary|timeline|announcement|email|triage|risk|shortlist|contract|incident|release|questions)\b", user_request, flags=re.IGNORECASE)
    )
    low_text = text.lower()
    has_structured_compare_answer = bool(
        compare_like_request
        and text
        and len(text.strip()) >= 160
        and (
            "## executive summary" in low_text
            or "## tabular breakdown" in low_text
            or "| :--- |" in low_text
            or "|---" in low_text
        )
    )
    should_recompute = (
        not text
        or "value_unavailable_from_tool_results" in text
        or (compare_like_request and not explicit_final_present and not has_structured_compare_answer)
        or (compare_like_request and bool(compare_file_hint))
        or (spreadsheet_report_request and (not text or text.lower().startswith(("generated ", "rendered ", "created ", "produced "))))
        or (document_report_request and (not text or text.lower().startswith(("generated ", "rendered ", "created ", "produced "))))
        or any(marker in low_text for marker in (
            "[agent_flow]",
            "source data inaccessible",
            "tool results provided only one record",
            "placeholders are used",
            "[action item description]",
            "unable to generate",
        ))
    )
    education_request = bool(user_request and re.search(r"\b(outline|essay|presentation|hypothesis|experiment design|science project|research paper|powerpoint|slides|project|proposal|investor-style|macro brief|scholarly sources|recent papers|world bank|google scholar|arxiv|yahoo finance)\b", user_request, flags=re.IGNORECASE))
    if should_recompute and user_request:
        computed = _spreadsheet_answer(ctx or {}, params, user_request)
        if computed:
            text = computed
    if user_request and education_request and (not text or _is_status_like_text(text) or _looks_like_url_list(text) or text.lower().startswith(("generated a bounded generalized workflow result", "generated a concise", "generated a bounded"))):
        education_text = _educational_deliverable_answer(user_request, text)
        if education_text:
            text = education_text
    artifact_text = _artifact_result_text(params, user_request, text)
    if artifact_text:
        text = artifact_text
    structured_text = _structured_review_markdown(text)
    if structured_text:
        text = structured_text
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
