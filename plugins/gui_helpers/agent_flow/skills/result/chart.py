NAME = "result.chart"
PERMISSIONS = ["result.emit"]


import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _coerce_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        try:
            return float(str(v).replace(",", "").strip())
        except Exception:
            return None


def _strip_custom_colors(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload or {})
    for k in ("colors", "palette", "theme", "backgroundColor", "borderColor"):
        out.pop(k, None)
    return out


def _intent_text(text: str) -> str:
    """Remove filenames so dataset names do not look like chart dimensions."""
    return re.sub(
        r"\b[\w./\\-]+\.(?:xlsx|xlsm|xls|csv|tsv)\b",
        " ",
        str(text or ""),
        flags=re.IGNORECASE,
    )


def _preferred_chart_kind(user_request: str = "", x_values: Optional[List[str]] = None) -> str:
    q = str(_intent_text(user_request) or "").lower()
    if re.search(r"\b(pie|donut|doughnut)\b", q):
        return "pie"
    if re.search(r"\bstacked\s+(bar|column)\b", q):
        return "stacked_bar"
    if "bar chart" in q or "bar graph" in q or "histogram" in q:
        return "bar"
    if "line chart" in q or "line graph" in q:
        return "line"
    if "area chart" in q or "area graph" in q:
        return "area"
    if "funnel" in q:
        return "funnel"
    if "heatmap" in q or "heat map" in q:
        return "heatmap"
    if "cohort" in q:
        return "cohort"
    if "waterfall" in q:
        return "waterfall"
    if "bullet chart" in q or "kpi chart" in q or "scorecard" in q:
        return "bullet"
    if isinstance(x_values, list) and x_values:
        joined = " ".join(str(v or "") for v in x_values[:8]).lower()
        if re.search(r"\b(20\d{2}-w\d{1,2}|20\d{2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|week|month|date|year)\b", joined):
            return "line"
    return "bar"


def _infer_group_spec(user_request: str) -> Dict[str, str]:
    q = str(_intent_text(user_request) or "").lower()
    category_hints = [
        (r"\b(countries|country|nation|nations)\b", "Country"),
        (r"\b(regions|region|territory|territories)\b", "Region"),
        (r"\b(states|state|province|provinces)\b", "State"),
        (r"\b(cities|city)\b", "City"),
        (r"\b(devices|device)\b", "Device"),
        (r"\b(models|model)\b", "Model"),
        (r"\b(products|product|items|item|sku|skus)\b", "Product"),
        (r"\b(categories|category|segment|segments)\b", "Category"),
        (r"\b(customers|customer|client|clients)\b", "Customer"),
        (r"\b(stores|store|branch|branches)\b", "Store"),
        (r"\b(salespersons|salesperson|sales reps|sales rep|rep|reps)\b", "Salesperson"),
        (r"\b(manufacturers|manufacturer|brand|brands)\b", "Brand"),
    ]
    category_requested = re.search(r"\b(pie|donut|doughnut|compare|comparing|comparison)\b.*\b(categories|category|segment|segments|brand|brands|device|devices|product|products|model|models|country|countries)\b", q)
    if category_requested:
        for pattern, column in category_hints:
            if re.search(pattern, q):
                return {"column": column, "op": "", "as": column.replace(" ", "_")}
    if re.search(r"\bby\s+(?:release\s+)?(month|monthly|week|weekly|year|yearly|date|day|daily)\b", q) or re.search(r"\brelease\s+(month|year|date)\b", q):
        group_op = _infer_group_op(user_request)
        group_alias = {
            "week": "Week",
            "month": "Month",
            "year": "Year",
            "date": "Date",
        }.get(group_op, "Month")
        return {"column": "Date", "op": group_op, "as": group_alias}
    for pattern, column in category_hints:
        if re.search(pattern, q):
            return {"column": column, "op": "", "as": column.replace(" ", "_")}
    group_op = _infer_group_op(user_request)
    group_alias = {
        "week": "Week",
        "month": "Month",
        "year": "Year",
        "date": "Order_Date",
    }.get(group_op, "Month")
    return {"column": "Order Date", "op": group_op, "as": group_alias}


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
        # The regex intentionally accepts spaces for filenames, but that can
        # also capture natural-language prefixes like "Analyze <file>.xlsx".
        # Prefer the shortest suffix that still looks like a spreadsheet path.
        cleaned = re.sub(
            r"^(?:analyze|from|read|open|use|using|file|spreadsheet|workbook|in|on|for|the)\s+",
            "",
            raw,
            flags=re.IGNORECASE,
        ).strip()
        if cleaned != raw:
            return cleaned
        parts = raw.replace("\\", "/").split("/")
        if parts:
            last = parts[-1].strip()
            if re.search(r"\.(?:xlsx|xlsm|xls|csv|tsv)$", last, flags=re.IGNORECASE):
                # If the final path segment has leading prose, keep the final
                # token ending in the extension unless the full segment exists.
                toks = last.split()
                for tok in reversed(toks):
                    if re.search(r"\.(?:xlsx|xlsm|xls|csv|tsv)$", tok, flags=re.IGNORECASE):
                        return tok.strip("'\"")
        return raw
    no_ext = re.search(
        r"\b([A-Za-z0-9][A-Za-z0-9_\- ./\\]{2,}?)\s+(?:spreadsheet|workbook|sheet|dataset)\b",
        text_s,
        flags=re.IGNORECASE,
    )
    if no_ext:
        raw = str(no_ext.group(1) or "").strip().strip("'\"")
        raw = re.sub(
            r"^(?:analyze|aggregate|from|read|open|use|using|file|spreadsheet|workbook|in|on|for|the)\s+",
            "",
            raw,
            flags=re.IGNORECASE,
        ).strip()
        # Keep the last token if the phrase accidentally captured prose.
        parts = raw.split()
        if parts:
            return parts[-1].strip("'\"")
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
    q = str(_intent_text(user_request) or "").lower()
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
    q = str(_intent_text(user_request) or "").lower()
    if re.search(r"\b(count|counts|number of|how many|frequency|distribution)\b", q):
        return {"column": "Column1", "op": "count", "as": "Count"}
    if re.search(r"\b(average|avg|mean)\b", q):
        if re.search(r"\b(price|sales|revenue|amount|spend|spending|cost|usd|value)\b", q):
            return {"column": "Price (USD)", "op": "avg", "as": "Average_Price"}
        return {"column": "Total (USD)", "op": "avg", "as": "Average_Value"}
    if re.search(r"\b(tax|vat|gst)\b", q):
        return {"column": "Tax (USD)", "op": "sum", "as": "Total_Tax"}
    if re.search(r"\b(item|items|quantity|qty|units|sold)\b", q):
        return {"column": "Units Sold", "op": "sum", "as": "Total_Items_Sold"}
    if re.search(r"\b(spend|spending|total amount|amount spent|cost)\b", q):
        return {"column": "Total (USD)", "op": "sum", "as": "Total_Spending"}
    if re.search(r"\b(sales|revenue|price|shares?|share)\b", q):
        return {"column": "Price (USD)", "op": "sum", "as": "Total_Sales"}
    return {"column": "Total (USD)", "op": "sum", "as": "Total_Spending"}


def _requested_limit(user_request: str) -> Optional[int]:
    m = re.search(r"\btop\s+(\d+)\b", str(_intent_text(user_request) or "").lower())
    if not m:
        return None
    try:
        return max(1, int(m.group(1)))
    except Exception:
        return None


def _sort_and_limit_records(records: List[Dict[str, Any]], metric_key: str, user_request: str) -> List[Dict[str, Any]]:
    if not records:
        return records
    q = str(_intent_text(user_request) or "").lower()
    should_sort = bool(re.search(r"\b(top|highest|largest|biggest|most|rank)\b", q))
    out = list(records)
    if metric_key and should_sort:
        out.sort(key=lambda r: _coerce_float(r.get(metric_key)) if isinstance(r, dict) and _coerce_float(r.get(metric_key)) is not None else float("-inf"), reverse=True)
    limit = _requested_limit(user_request)
    if limit:
        out = out[:limit]
    return out


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


def _norm_col(name: str) -> str:
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def _tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", str(text or "").lower()) if t]


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
        "product": ["product", "device", "item", "sku", "model"],
        "date": ["date", "release", "order", "created"],
        "metric": ["total", "sales", "revenue", "amount", "price", "cost", "usd", "value"],
    }
    req_tokens = _tokenize(req)
    if semantic and semantic in semantic_groups:
        req_tokens.extend(semantic_groups[semantic])
    best = ""
    best_score = -1.0
    for col in cols:
        col_norm = _norm_col(col)
        col_tokens = _tokenize(col)
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
        if semantic == "metric":
            numeric = sum(1 for r in rows[:100] if _coerce_float(r.get(col)) is not None)
            score += min(8, numeric / 10) if numeric else -6
            if "price" in str(col).lower() or "sales" in str(col).lower() or "revenue" in str(col).lower():
                score += 4
        if score > best_score:
            best = col
            best_score = score
    return best if best_score > 0 else ""


def _requested_dimension_values(rows: List[Dict[str, Any]], user_request: str) -> tuple[str, List[str]]:
    q = str(_intent_text(user_request) or "").lower()
    if not rows:
        return "", []
    cols = list(rows[0].keys())
    candidates: List[tuple[str, List[str]]] = []
    for col in cols:
        vals = []
        seen = set()
        for r in rows:
            val = str(r.get(col) or "").strip()
            if not val or val in seen:
                continue
            seen.add(val)
            if val.lower() in q:
                vals.append(val)
        if vals:
            candidates.append((col, vals))
    if not candidates:
        return "", []
    # Prefer country-like comparisons, then the column with the most explicit matches.
    candidates.sort(key=lambda item: (0 if re.search(r"country|origin|nation", item[0], re.I) else 1, -len(item[1])))
    col, vals = candidates[0]
    vals.sort(key=lambda v: q.find(v.lower()) if q.find(v.lower()) >= 0 else 10**9)
    return col, vals


def _chart_fences(charts: List[Dict[str, Any]]) -> str:
    parts = []
    for chart in charts:
        parts.append("```chart\n" + json.dumps(chart, ensure_ascii=False) + "\n```")
    return "\n\n".join(parts)


def _multi_chart_from_spreadsheet_request(ctx: Dict[str, Any], params: Dict[str, Any], user_request: str) -> Optional[Dict[str, Any]]:
    q = str(_intent_text(user_request) or "").lower()
    if not re.search(r"\b(two|three|multiple|separate|each|one for|other one|another)\b", q):
        return None
    file_hint = _extract_spreadsheet_file(user_request, params)
    if not file_hint:
        return None
    file_hint = _resolve_spreadsheet_file_hint(file_hint)
    rows = _load_rows(file_hint)
    if not rows:
        return None
    filter_col, targets = _requested_dimension_values(rows, user_request)
    if not filter_col or len(targets) < 2:
        return None
    metric_req = _infer_metric(user_request)
    metric_col = _resolve_column(rows, str(metric_req.get("column") or ""), semantic="metric")
    if not metric_col:
        return None
    x_col = _resolve_column(rows, "Device", semantic="product") or _resolve_column(rows, "Model", semantic="product") or _resolve_column(rows, "Brand", semantic="brand")
    if not x_col or x_col == filter_col:
        x_col = _resolve_column(rows, "Brand", semantic="brand")
    if not x_col or x_col == filter_col:
        return None
    chart_kind = _preferred_chart_kind(user_request)
    if chart_kind in {"pie", "line", "area", "stacked_bar"}:
        # Separate comparison charts over product rows are clearest as bars.
        chart_kind = "bar"
    charts: List[Dict[str, Any]] = []
    for target in targets:
        totals: Dict[str, float] = {}
        for r in rows:
            if str(r.get(filter_col) or "").strip().lower() != target.lower():
                continue
            label = str(r.get(x_col) or "").strip()
            val = _coerce_float(r.get(metric_col))
            if label and val is not None:
                totals[label] = totals.get(label, 0.0) + float(val)
        if not totals:
            continue
        ordered = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
        labels = [k for k, _v in ordered]
        values = [v for _k, v in ordered]
        chart = {
            "chart": chart_kind,
            "title": f"{target} {metric_col} by {x_col}",
            "x": labels,
            "categories": labels,
            "series": [{"name": metric_col, "y": values, "values": values}],
        }
        charts.append(_strip_custom_colors(chart))
    if len(charts) < 2:
        return None
    return {
        "chart": charts[0],
        "charts": charts,
        "content": _chart_fences(charts),
    }


def _chart_from_spreadsheet_request(ctx: Dict[str, Any], params: Dict[str, Any], user_request: str) -> Optional[Dict[str, Any]]:
    file_hint = _extract_spreadsheet_file(user_request, params)
    if not file_hint:
        return None
    file_hint = _resolve_spreadsheet_file_hint(file_hint)
    try:
        sheet_dir = Path(__file__).resolve().parent.parent / "sheet"
        sheet_dir_s = str(sheet_dir)
        if sheet_dir_s not in sys.path:
            sys.path.append(sheet_dir_s)
        import aggregate as sheet_aggregate  # type: ignore
    except Exception:
        return None

    group_spec = _infer_group_spec(user_request)
    metric = _infer_metric(user_request)
    agg_params = {
        "path": file_hint,
        "group_by": [group_spec],
        "metrics": [metric],
        "auto": True,
    }
    try:
        result = sheet_aggregate.run(ctx or {}, agg_params)
    except Exception:
        return None
    if not isinstance(result, dict) or result.get("ok") is False:
        return None
    records = result.get("records")
    if not isinstance(records, list) or not records:
        return None
    metric_key = str(metric.get("as") or "").strip()
    records = _sort_and_limit_records([r for r in records if isinstance(r, dict)], metric_key, user_request)
    return normalize_chart_payload({"records": records}, user_request=user_request)


def normalize_chart_payload(obj: Any, user_request: str = "") -> Optional[Dict[str, Any]]:
    # Accept JSON-ish string payloads (common model output shape).
    if isinstance(obj, str):
        s = obj.strip()
        if s:
            try:
                parsed = json.loads(s)
                obj = parsed
            except Exception:
                pass

    # Accept nested shape: {"chart": {"type":"line", ...}}.
    if isinstance(obj, dict) and isinstance(obj.get("chart"), dict):
        nested = dict(obj.get("chart") or {})
        if not nested.get("chart") and isinstance(nested.get("type"), str):
            nested["chart"] = str(nested.get("type") or "").strip().lower()
        if not nested.get("title") and obj.get("title"):
            nested["title"] = obj.get("title")
        obj = nested

    # Already chart-shaped payload.
    if isinstance(obj, dict) and str(obj.get("chart") or "").strip():
        p = _strip_custom_colors(dict(obj))
        if not p.get("chart"):
            p["chart"] = _preferred_chart_kind(user_request, p.get("x") if isinstance(p.get("x"), list) else None)
        chart_kind = str(p.get("chart") or "").strip().lower()
        if chart_kind in {"donut", "doughnut"}:
            chart_kind = "pie"
            p["chart"] = "pie"
        if chart_kind == "pie":
            data_rows = p.get("data") if isinstance(p.get("data"), list) else []
            norm_data = []
            for row in data_rows:
                if not isinstance(row, dict):
                    continue
                label = str(row.get("label") or row.get("name") or row.get("x") or "").strip()
                value = _coerce_float(row.get("value") if "value" in row else row.get("y"))
                if label and value is not None:
                    norm_data.append({"label": label, "value": value})
            if not norm_data:
                labels = p.get("labels") if isinstance(p.get("labels"), list) else p.get("x")
                labels = labels if isinstance(labels, list) else p.get("categories")
                series = p.get("series")
                values = None
                if isinstance(series, list) and series:
                    s0 = series[0] if isinstance(series[0], dict) else {}
                    values = s0.get("y") if isinstance(s0.get("y"), list) else s0.get("values")
                if not isinstance(values, list) and isinstance(p.get("values"), list):
                    values = p.get("values")
                if isinstance(labels, list) and isinstance(values, list):
                    for label, value_raw in zip(labels, values):
                        label_s = str(label or "").strip()
                        value = _coerce_float(value_raw)
                        if label_s and value is not None:
                            norm_data.append({"label": label_s, "value": value})
            if not norm_data:
                return None
            p["data"] = norm_data
            p["chart"] = "pie"
            return _strip_custom_colors(p)
        if chart_kind in {"line", "area", "bar", "stacked_bar"}:
            if not isinstance(p.get("x"), list):
                if isinstance(p.get("categories"), list):
                    p["x"] = list(p.get("categories") or [])
                elif isinstance(p.get("labels"), list):
                    p["x"] = list(p.get("labels") or [])
            series = p.get("series")
            if isinstance(series, dict):
                norm_series_from_map = []
                x_from_points: List[str] = []
                for name, spec in series.items():
                    if not isinstance(spec, dict):
                        continue
                    pts = spec.get("data")
                    if isinstance(pts, list):
                        point_rows = [pt for pt in pts if isinstance(pt, dict)]
                        yvals = [_coerce_float(pt.get("y")) for pt in point_rows]
                        yvals = [v for v in yvals if v is not None]
                        if yvals:
                            norm_series_from_map.append({"name": str(spec.get("label") or name or "value"), "y": yvals})
                            if not x_from_points:
                                xs0 = [str(pt.get("x") or "").strip() for pt in point_rows]
                                x_from_points = [x for x in xs0 if x]
                    else:
                        vals = spec.get("y") if isinstance(spec.get("y"), list) else spec.get("values")
                        if isinstance(vals, list):
                            yvals = [_coerce_float(v) for v in vals]
                            yvals = [v for v in yvals if v is not None]
                            if yvals:
                                norm_series_from_map.append({"name": str(spec.get("label") or name or "value"), "y": yvals})
                if norm_series_from_map:
                    p["series"] = norm_series_from_map
                    if not isinstance(p.get("x"), list) and x_from_points:
                        p["x"] = x_from_points
                    series = p.get("series")
            if isinstance(series, list):
                norm_series = []
                for s in series:
                    if not isinstance(s, dict):
                        continue
                    row = dict(s)
                    if not isinstance(row.get("y"), list) and isinstance(row.get("data"), list):
                        pts = [pt for pt in row.get("data") if isinstance(pt, dict)]
                        if pts:
                            yvals = [_coerce_float(pt.get("y")) for pt in pts]
                            yvals = [v for v in yvals if v is not None]
                            row["y"] = yvals
                            if not isinstance(p.get("x"), list):
                                xvals = [str(pt.get("x") or "").strip() for pt in pts]
                                xvals = [x for x in xvals if x]
                                if xvals:
                                    p["x"] = xvals
                    if not isinstance(row.get("y"), list) and isinstance(row.get("values"), list):
                        row["y"] = list(row.get("values") or [])
                    if not isinstance(row.get("y"), list):
                        continue
                    row["y"] = [v for v in row.get("y") if _coerce_float(v) is not None]
                    norm_series.append(row)
                p["series"] = norm_series
            else:
                p["series"] = []
        # Do not emit blank chart payloads.
        xs = p.get("x") if isinstance(p.get("x"), list) else []
        ss = p.get("series") if isinstance(p.get("series"), list) else []
        if not xs or not ss:
            return None
        has_y = False
        for s in ss:
            if isinstance(s, dict) and isinstance(s.get("y"), list) and len(s.get("y") or []) > 0:
                has_y = True
                break
        if not has_y:
            return None
        # Align all series lengths to x-axis to avoid renderer blanks.
        x_len = len(xs)
        aligned = []
        for s in ss:
            if not isinstance(s, dict):
                continue
            ys_raw = s.get("y") if isinstance(s.get("y"), list) else []
            ys_num = [_coerce_float(v) for v in ys_raw]
            ys = [v for v in ys_num if v is not None]
            if len(ys) < x_len:
                ys = ys + [None] * (x_len - len(ys))
            elif len(ys) > x_len:
                ys = ys[:x_len]
            aligned.append({"name": str(s.get("name") or "value"), "y": ys})
        if not aligned:
            return None
        p["series"] = aligned
        if chart_kind in {"bar", "stacked_bar"}:
            # charts_render's bar renderer consumes categories + series[].values,
            # while other chart paths consume x + series[].y. Emit both so the
            # result skill remains compatible with the plugin renderer.
            p.setdefault("categories", list(xs))
            p["series"] = [
                {
                    **s,
                    "values": list(s.get("y") or []),
                }
                for s in aligned
            ]
        return _strip_custom_colors(p)

    records = None
    if isinstance(obj, dict) and isinstance(obj.get("records"), list):
        records = obj.get("records")
    elif isinstance(obj, dict) and isinstance(obj.get("aggregate_records"), list):
        records = obj.get("aggregate_records")
    elif isinstance(obj, dict) and isinstance(obj.get("data"), dict) and isinstance(obj.get("data").get("records"), list):
        records = obj.get("data").get("records")
    elif isinstance(obj, dict) and isinstance(obj.get("data"), dict) and isinstance(obj.get("data").get("aggregate_records"), list):
        records = obj.get("data").get("aggregate_records")
    elif isinstance(obj, list):
        records = obj
    elif isinstance(obj, dict):
        if isinstance(obj.get("x"), list) and isinstance(obj.get("y"), list):
            xs = [str(v or "").strip() for v in (obj.get("x") or [])]
            ys = [_coerce_float(v) for v in (obj.get("y") or [])]
            points = [(xv, yv) for xv, yv in zip(xs, ys) if xv and yv is not None]
            if points:
                kind = _preferred_chart_kind(user_request, [p[0] for p in points])
                if kind == "pie":
                    return _strip_custom_colors({
                        "chart": "pie",
                        "title": str(obj.get("title") or "Result"),
                        "data": [{"label": p[0], "value": p[1]} for p in points],
                    })
                return _strip_custom_colors({
                    "chart": kind,
                    "title": str(obj.get("title") or "Result"),
                    "x": [p[0] for p in points],
                    "series": [{"name": str(obj.get("series_name") or "value"), "y": [p[1] for p in points]}],
                })
        if isinstance(obj.get("categories"), list) and isinstance(obj.get("series"), list):
            cats = [str(v or "").strip() for v in (obj.get("categories") or [])]
            out_series = []
            for s in obj.get("series") or []:
                if not isinstance(s, dict):
                    continue
                vals = s.get("y") if isinstance(s.get("y"), list) else s.get("values")
                if not isinstance(vals, list):
                    continue
                vals_n = [_coerce_float(v) for v in vals]
                vals_n = [v for v in vals_n if v is not None]
                out_series.append({"name": str(s.get("name") or "value"), "y": vals_n})
            if cats and out_series:
                kind = str(obj.get("chart") or "").strip().lower() or _preferred_chart_kind(user_request, cats)
                if kind in {"pie", "donut", "doughnut"}:
                    return _strip_custom_colors({
                        "chart": "pie",
                        "title": str(obj.get("title") or "Result"),
                        "data": [{"label": label, "value": value} for label, value in zip(cats, out_series[0].get("y") or [])],
                    })
                return _strip_custom_colors({
                    "chart": kind,
                    "title": str(obj.get("title") or "Result"),
                    "x": cats,
                    "series": out_series,
                })
    if not isinstance(records, list) or not records:
        return None
    sample = next((r for r in records if isinstance(r, dict)), None)
    if not isinstance(sample, dict):
        return None
    keys = list(sample.keys())
    if not keys:
        return None
    x_key = ""
    for cand in ("month", "Month", "date", "Date", "x", "label", "name"):
        if cand in sample:
            x_key = cand
            break
    if not x_key:
        x_key = keys[0]
    y_key = ""
    preferred_y = ["total_spending", "total", "sum", "value", "amount", "Total (USD)", "sum_Total (USD)"]
    for cand in preferred_y:
        if cand in sample:
            y_key = cand
            break
    if not y_key:
        for k in keys:
            if k == x_key:
                continue
            if _coerce_float(sample.get(k)) is not None:
                y_key = k
                break
    if not y_key:
        return None
    x_vals: List[str] = []
    y_vals: List[float] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        xv = str(r.get(x_key) or "").strip()
        yv = _coerce_float(r.get(y_key))
        if not xv or yv is None:
            continue
        x_vals.append(xv)
        y_vals.append(yv)
    if not x_vals or not y_vals:
        return None
    chart_kind = _preferred_chart_kind(user_request, x_vals)
    if chart_kind in {"pie", "donut", "doughnut"}:
        return _strip_custom_colors({
            "chart": "pie",
            "title": "Result",
            "data": [{"label": label, "value": value} for label, value in zip(x_vals, y_vals)],
        })
    series_row = {"name": y_key, "y": y_vals}
    if chart_kind in {"bar", "stacked_bar"}:
        series_row["values"] = list(y_vals)
    out_payload = {
        "chart": chart_kind,
        "title": "Result",
        "x": x_vals,
        "series": [series_row],
    }
    if chart_kind in {"bar", "stacked_bar"}:
        out_payload["categories"] = list(x_vals)
    return _strip_custom_colors(out_payload)


def run(ctx, params):
    params = params or {}
    payload = params.get("chart")
    if payload is None:
        payload = params.get("data")
    # Agent workflow models sometimes emit tagged tool calls with records/x/series
    # as top-level params instead of nesting them under chart/data. Treat that
    # shape as the chart payload so result.chart remains the schema boundary.
    if isinstance(params, dict) and isinstance(payload, str) and isinstance(params.get("records"), list):
        payload = params
    if payload is None and isinstance(params, dict):
        payload_keys = {"records", "aggregate_records", "x", "y", "series", "categories", "labels", "chart", "title"}
        if any(k in params for k in payload_keys):
            payload = params
    user_request = str(params.get("user_request") or "")
    multi = _multi_chart_from_spreadsheet_request(ctx or {}, params, user_request)
    if isinstance(multi, dict) and isinstance(multi.get("chart"), dict):
        return {
            "ok": True,
            "mode": "chart",
            "chart": multi.get("chart"),
            "charts": multi.get("charts") if isinstance(multi.get("charts"), list) else [multi.get("chart")],
            "content": str(multi.get("content") or ""),
            "data": {
                "mode": "chart",
                "chart": multi.get("chart"),
                "charts": multi.get("charts") if isinstance(multi.get("charts"), list) else [multi.get("chart")],
                "content": str(multi.get("content") or ""),
            },
        }
    normalized = normalize_chart_payload(payload, user_request=user_request)
    if not isinstance(normalized, dict):
        normalized = _chart_from_spreadsheet_request(ctx or {}, params, user_request)
    if not isinstance(normalized, dict):
        return {
            "ok": False,
            "mode": "chart",
            "warnings": ["value_unavailable_from_tool_results"],
            "chart": None,
            "data": {"mode": "chart", "chart": None},
        }
    return {
        "ok": True,
        "mode": "chart",
        "chart": normalized,
        "content": "```chart\n" + json.dumps(normalized, ensure_ascii=False) + "\n```",
        "data": {
            "mode": "chart",
            "chart": normalized,
            "content": "```chart\n" + json.dumps(normalized, ensure_ascii=False) + "\n```",
        },
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "result",
    "label": "Result: Chart",
    "description": (
        "Emit a normal assistant chart result outside Agent Jobs. The chart payload is normalized for the "
        "charts_render plugin. Supported chart values: pie, bar, stacked_bar, line, area, funnel, heatmap, "
        "cohort, waterfall, bullet. Preserve the chart type explicitly requested by the user. Renderer schemas: "
        "pie uses {chart:'pie', title, unit?, data:[{label,value}]}; bar/stacked_bar uses {chart, title, unit?, "
        "categories:[...], series:[{name, values:[...]}]}; line/area uses {chart, title, unit?, x:[...], "
        "series:[{name, y:[...]}]}; funnel uses stages/data [{label,value}]; heatmap/cohort uses x/y/values; "
        "waterfall uses start and steps; bullet uses actual, target, ranges."
    ),
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "chart": {},
            "data": {},
            "user_request": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
