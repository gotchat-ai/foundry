from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from collections import defaultdict
import re
from datetime import date as _date, datetime as _dt, timedelta as _td
from shared.io import iter_records
from shared.utils import coerce_scalar
NAME = "sheet.aggregate"
PERMISSIONS = ["filesystem.read", "spreadsheet.read", "spreadsheet.transform"]


def _resolve_file(params):
    return (
        params.get("file")
        or params.get("path")
        or params.get("file_path")
        or params.get("input_path")
    )


def _parse_date_like(v):
    if v is None:
        return None
    if isinstance(v, _dt):
        return v.date()
    if isinstance(v, _date):
        return v
    cv = coerce_scalar(v)
    # Excel serial date (1900 system): day 1 == 1899-12-31 with leap-bug offset;
    # common pragmatic conversion uses origin 1899-12-30.
    if isinstance(cv, (int, float)) and not isinstance(cv, bool):
        n = float(cv)
        if 20000 <= n <= 80000:
            try:
                return (_dt(1899, 12, 30) + _td(days=n)).date()
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


def aggregate_records(records, group_by=None, metrics=None, auto=False):
    rows = [dict(r) for r in records]
    if not rows: return {"records": [], "group_by": group_by or [], "metrics": metrics or []}
    columns = list(rows[0].keys())
    if auto and not group_by:
        for c in columns:
            vals = {str(r.get(c)) for r in rows[:1000] if r.get(c) is not None}
            if 1 < len(vals) <= min(50, max(2, len(rows)//2)):
                group_by = [c]; break
    group_by = group_by or []
    if auto and not metrics:
        metrics = []
        for c in columns:
            numeric = sum(1 for r in rows[:200] if isinstance(coerce_scalar(r.get(c)), (int, float)) and not isinstance(coerce_scalar(r.get(c)), bool))
            if numeric >= max(1, min(10, len(rows[:200])//2)):
                metrics += [{"column": c, "op": "sum", "as": f"sum_{c}"}, {"column": c, "op": "avg", "as": f"avg_{c}"}]; break
        metrics.append({"column": columns[0], "op": "count", "as": "count"})
    metrics = metrics or [{"column": columns[0], "op": "count", "as": "count"}]
    buckets = defaultdict(list)
    for r in rows:
        key = tuple(r.get(c) for c in group_by) if group_by else ("__all__",)
        buckets[key].append(r)
    out = []
    for key, items in buckets.items():
        rec = {}
        if group_by:
            for i, c in enumerate(group_by): rec[c] = key[i]
        else: rec["group"] = "all"
        for m in metrics:
            col, op, name = m.get("column"), (m.get("op") or "count").lower(), m.get("as") or f"{m.get('op')}_{m.get('column')}"
            values = [coerce_scalar(x.get(col)) for x in items]
            nums = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
            raw_vals = [x.get(col) for x in items]
            if op == "count": rec[name] = len(items)
            elif op == "sum": rec[name] = sum(nums)
            elif op in {"avg", "mean"}: rec[name] = sum(nums)/len(nums) if nums else None
            elif op in {"min", "max"}:
                parsed_dates = [d for d in (_parse_date_like(v) for v in raw_vals) if d is not None]
                # Prefer date result when the column appears date-like.
                if parsed_dates and (len(parsed_dates) >= max(1, int(len(raw_vals) * 0.4))):
                    best = min(parsed_dates) if op == "min" else max(parsed_dates)
                    rec[name] = best.isoformat()
                else:
                    rec[name] = min(nums) if op == "min" and nums else (max(nums) if op == "max" and nums else None)
            elif op in {"distinct", "count_distinct", "count_unique"}: rec[name] = len({str(v) for v in values if v is not None})
        out.append(rec)
    return {"records": out, "group_by": group_by, "metrics": metrics}


def _norm_col(name: str) -> str:
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def _resolve_group_column_name(rows, requested):
    if not rows or not requested:
        return None
    first = rows[0] if isinstance(rows[0], dict) else {}
    if not isinstance(first, dict):
        return None
    cols = list(first.keys())
    req = str(requested or "").strip()
    if not req:
        return None
    if req in first:
        return req
    norm_map = {_norm_col(c): c for c in cols}
    direct = norm_map.get(_norm_col(req))
    if direct:
        return direct
    rq = _norm_col(req)
    if rq:
        for k, v in norm_map.items():
            if k.startswith(rq) or rq.startswith(k):
                return v
    # Fuzzy token overlap fallback.
    req_tokens = [t for t in re.split(r"[^a-z0-9]+", req.lower()) if t]
    best_col = None
    best_score = 0.0
    for c in cols:
        toks = [t for t in re.split(r"[^a-z0-9]+", str(c).lower()) if t]
        score = 0.0
        for rt in req_tokens:
            for ct in toks:
                if rt == ct:
                    score += 2.5
                elif rt in ct or ct in rt:
                    score += 1.0
        if score > best_score:
            best_score = score
            best_col = c
    return best_col if best_score > 0 else None


def _resolve_metric_columns(records, metrics):
    if not records or not metrics:
        return metrics or []
    first = records[0] if isinstance(records[0], dict) else {}
    if not isinstance(first, dict):
        return metrics
    cols = list(first.keys())
    norm_map = {_norm_col(c): c for c in cols}

    def _tokenize(name: str) -> list[str]:
        s = str(name or "").lower()
        parts = re.split(r"[^a-z0-9]+", s)
        out = [p for p in parts if p]
        # include compact normalized token for substring-style matching
        compact = _norm_col(s)
        if compact and compact not in out:
            out.append(compact)
        return out

    def _fuzzy_scores(requested: str) -> list[tuple[str, float]]:
        req_norm = _norm_col(requested)
        if not req_norm:
            return []
        req_toks = _tokenize(requested)
        if not req_toks:
            req_toks = [req_norm]
        scored: list[tuple[str, float]] = []
        for original in cols:
            cand_norm = _norm_col(original)
            cand_toks = _tokenize(original)
            score = 0.0
            # strong normalized substring signals
            if req_norm == cand_norm:
                score += 10.0
            elif req_norm in cand_norm or cand_norm in req_norm:
                score += 5.0
            # token overlap / partial overlap
            for rt in req_toks:
                for ct in cand_toks:
                    if rt == ct:
                        score += 2.5
                    elif rt in ct or ct in rt:
                        score += 1.0
            # generic semantic token expansion (not tied to a specific dataset)
            token_groups = [
                {"qty", "quantity", "item", "items", "unit", "units", "sold", "count"},
                {"price", "retail", "amount", "total", "spend", "spending", "cost", "sales"},
                {"tax", "vat", "gst"},
            ]
            for g in token_groups:
                if any(t in g for t in req_toks) and any(t in g for t in cand_toks):
                    score += 1.5
            scored.append((original, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _fuzzy_best_match(requested: str) -> str | None:
        scored = _fuzzy_scores(requested)
        if not scored:
            return None
        best_col, best_score = scored[0]
        return best_col if best_score > 0 else None

    out = []
    for m in metrics:
        mm = dict(m or {})
        col = str(mm.get("column") or "").strip()
        if col and col not in first:
            # exact normalized match
            mapped = norm_map.get(_norm_col(col))
            # "customer" -> "customername" style prefix match
            if not mapped:
                nc = _norm_col(col)
                for k, v in norm_map.items():
                    if k.startswith(nc) or nc.startswith(k):
                        mapped = v
                        break
            if not mapped:
                mapped = _fuzzy_best_match(col)
            if mapped:
                mm["column"] = mapped
        out.append(mm)
    return out


def _numeric_column_sums(rows):
    if not rows:
        return {}
    cols = list(rows[0].keys()) if isinstance(rows[0], dict) else []
    sums = {}
    for c in cols:
        total = 0.0
        seen = 0
        for r in rows:
            v = coerce_scalar(r.get(c))
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                total += float(v)
                seen += 1
        if seen > 0:
            sums[c] = total
    return sums


def _repair_zero_sum_metrics(rows, metrics):
    if not rows or not metrics:
        return metrics
    col_sums = _numeric_column_sums(rows)
    if not col_sums:
        return metrics
    repaired = []
    for m in metrics:
        mm = dict(m or {})
        op = str(mm.get("op") or "").lower()
        col = str(mm.get("column") or "").strip()
        if op not in {"sum", "avg", "mean"} or not col:
            repaired.append(mm)
            continue
        current = col_sums.get(col, 0.0)
        # If requested sum-like metric maps to a zero-sum column while many other
        # numeric columns have non-zero sums, choose a better fuzzy candidate.
        if abs(float(current)) > 0.0:
            repaired.append(mm)
            continue
        # local fuzzy scorer with same logic as resolver
        req = _norm_col(col)
        req_toks = [t for t in re.split(r"[^a-z0-9]+", col.lower()) if t]
        if req and req not in req_toks:
            req_toks.append(req)
        best_alt = None
        best_score = -1.0
        for cand, csum in col_sums.items():
            if cand == col:
                continue
            cand_req = _norm_col(cand)
            cand_toks = [t for t in re.split(r"[^a-z0-9]+", cand.lower()) if t]
            if cand_req and cand_req not in cand_toks:
                cand_toks.append(cand_req)
            score = 0.0
            if req and (req == cand_req):
                score += 10.0
            elif req and (req in cand_req or cand_req in req):
                score += 5.0
            for rt in req_toks:
                for ct in cand_toks:
                    if rt == ct:
                        score += 2.5
                    elif rt in ct or ct in rt:
                        score += 1.0
            token_groups = [
                {"qty", "quantity", "item", "items", "unit", "units", "sold", "count"},
                {"price", "retail", "amount", "total", "spend", "spending", "cost", "sales"},
                {"tax", "vat", "gst"},
            ]
            for g in token_groups:
                if any(t in g for t in req_toks) and any(t in g for t in cand_toks):
                    score += 1.5
            if abs(float(csum)) > 0.0:
                score += 0.25
            if score > best_score:
                best_score = score
                best_alt = cand
        if best_alt and best_score > 0:
            mm["column"] = best_alt
        repaired.append(mm)
    return repaired


def _normalize_metrics(metrics):
    out = []
    for m in (metrics or []):
        if isinstance(m, str):
            s = m.strip()
            # Accept shorthand metric expressions often emitted by model nodes:
            #   "SUM(Total)", "MIN(Date)", "COUNT(DISTINCT Customer Name)"
            m_dist = re.match(r"^count\s*\(\s*distinct\s+(.+?)\s*\)$", s, flags=re.IGNORECASE)
            m_fn = re.match(r"^(sum|avg|mean|min|max|count)\s*\(\s*(.+?)\s*\)$", s, flags=re.IGNORECASE)
            if m_dist:
                col = str(m_dist.group(1)).strip()
                if col:
                    out.append({"column": col, "op": "count_distinct", "as": f"count_distinct_{col}"})
                continue
            if m_fn:
                fn = str(m_fn.group(1)).strip().lower()
                col = str(m_fn.group(2)).strip()
                op_map = {"mean": "avg"}
                op = op_map.get(fn, fn)
                if col:
                    out.append({"column": col, "op": op, "as": f"{op}_{col}"})
                continue
            continue
        if not isinstance(m, dict):
            continue
        mm = dict(m)
        op = str(
            mm.get("op")
            or mm.get("agg")
            or mm.get("operation")
            or mm.get("function")
            or mm.get("type")
            or mm.get("metric")
            or ""
        ).strip().lower()
        if op:
            op_map = {
                "count_unique": "count_distinct",
                "unique_count": "count_distinct",
                "distinct": "count_distinct",
                "count_distinct": "count_distinct",
                "count": "count",
                "sum": "sum",
                "avg": "avg",
                "mean": "avg",
                "min": "min",
                "max": "max",
            }
            mm["op"] = op_map.get(op, op)
        if "as" not in mm:
            if "alias" in mm:
                mm["as"] = mm.get("alias")
            elif "name" in mm:
                mm["as"] = mm.get("name")
        out.append(mm)
    return out


def _normalize_group_by(group_by):
    """
    Accepts either:
      group_by: ["Order Date", "Region"]
    or:
      group_by:
        - {column: "Order Date", op: "month", as: "order_month"}
        - {column: "Region"}
    Returns:
      - resolved group_by column names (list[str]) for aggregate_records
      - spec rows for derived/group transforms
    """
    out_cols = []
    specs = []
    gb_rows = group_by
    if isinstance(gb_rows, str):
        gb_rows = [gb_rows]
    elif not isinstance(gb_rows, list):
        gb_rows = []
    for raw in gb_rows:
        if isinstance(raw, str):
            c = raw.strip()
            if c:
                out_cols.append(c)
                specs.append({"column": c, "op": "", "as": c})
            continue
        if not isinstance(raw, dict):
            continue
        c = str(raw.get("column") or raw.get("name") or "").strip()
        if not c:
            continue
        op = str(
            raw.get("op")
            or raw.get("derive")
            or raw.get("agg")
            or raw.get("operation")
            or raw.get("function")
            or ""
        ).strip().lower()
        alias = str(raw.get("as") or raw.get("alias") or raw.get("name") or "").strip()
        if not alias:
            if op in {"week", "month", "year", "day", "date"}:
                alias = f"{c}_{op}"
            else:
                alias = c
        out_cols.append(alias)
        specs.append({"column": c, "op": op, "as": alias})
    return out_cols, specs


def _choose_date_like_column(rows):
    if not rows:
        return None
    first = rows[0] if isinstance(rows[0], dict) else {}
    if not isinstance(first, dict):
        return None
    cols = list(first.keys())
    # Prefer explicit date/time-like headers.
    for c in cols:
        if re.search(r"\b(date|time|timestamp|month|year)\b", str(c), flags=re.IGNORECASE):
            return c
    # Fallback: infer from sample values (including Excel serials).
    for c in cols:
        seen = 0
        good = 0
        for r in rows[:50]:
            if not isinstance(r, dict):
                continue
            v = r.get(c)
            if v is None or str(v).strip() == "":
                continue
            seen += 1
            if _parse_date_like(v) is not None:
                good += 1
        if seen > 0 and good >= max(1, int(seen * 0.5)):
            return c
    return None


def _resolve_group_specs_against_rows(rows, specs):
    if not specs:
        return specs
    date_col = _choose_date_like_column(rows)
    first = rows[0] if rows and isinstance(rows[0], dict) else {}
    cols = list(first.keys()) if isinstance(first, dict) else []
    resolved = []
    for s in specs:
        if not isinstance(s, dict):
            continue
        col = str(s.get("column") or "").strip()
        op = str(s.get("op") or "").strip().lower()
        alias = str(s.get("as") or "").strip()
        # Handle model shorthand: group_by: ["month"] / "month"
        if col.lower() in {"week", "month", "year", "day", "date"} and not op:
            if date_col:
                op = col.lower()
                col = str(date_col)
                if not alias:
                    alias = f"{col}_{op}"
        # For date-derived grouping, let the skill infer the real date column
        # when the model supplies semantic shorthand like "Date" but the sheet
        # header is "Order Date" or similar.
        if op in {"week", "month", "year", "day", "date"} and col and col not in cols and date_col:
            col = str(date_col)
        # Resolve plain group-by columns via exact/normalized/fuzzy matching.
        if op not in {"week", "month", "year", "day", "date"} and col and col not in cols:
            mapped = _resolve_group_column_name(rows, col)
            if mapped:
                col = mapped
        if not alias:
            alias = f"{col}_{op}" if op in {"week", "month", "year", "day", "date"} else col
        resolved.append({"column": col, "op": op, "as": alias})
    return resolved


def _apply_group_by_derivations(rows, specs):
    if not rows or not specs:
        return rows
    out = []
    for r in rows:
        row = dict(r)
        for s in specs:
            src = str(s.get("column") or "").strip()
            op = str(s.get("op") or "").strip().lower()
            alias = str(s.get("as") or src).strip()
            if not src or not alias:
                continue
            raw_v = row.get(src)
            if op in {"week", "month", "year", "day", "date"}:
                dv = _parse_date_like(raw_v)
                if dv is None:
                    row[alias] = None
                elif op == "week":
                    iso = dv.isocalendar()
                    row[alias] = f"{iso.year:04d}-W{iso.week:02d}"
                elif op == "month":
                    row[alias] = f"{dv.year:04d}-{dv.month:02d}"
                elif op == "year":
                    row[alias] = int(dv.year)
                elif op == "day":
                    row[alias] = dv.isoformat()
                else:  # date
                    row[alias] = dv.isoformat()
            else:
                row[alias] = raw_v
        out.append(row)
    return out


def _choose_fallback_group_column(rows, requested_name=None):
    """
    Choose a reasonable text-like grouping column when the requested group_by
    column is missing. Prefer non-empty, non-numeric columns with moderate
    cardinality over ID-like columns.
    """
    if not rows or not isinstance(rows[0], dict):
        return None
    cols = list(rows[0].keys())
    best_col = None
    best_score = -1.0
    req = str(requested_name or "").strip().lower()
    req_norm = _norm_col(req)
    req_toks = [t for t in re.split(r"[^a-z0-9]+", req) if t]
    for c in cols:
        vals = []
        numeric_like = 0
        for r in rows[:1000]:
            if not isinstance(r, dict):
                continue
            v = r.get(c)
            if v is None:
                continue
            s = str(v).strip()
            if not s:
                continue
            vals.append(s)
            cv = coerce_scalar(v)
            if isinstance(cv, (int, float)) and not isinstance(cv, bool):
                numeric_like += 1
        if not vals:
            continue
        non_empty = len(vals)
        unique = len(set(vals))
        unique_ratio = unique / max(1, non_empty)
        # Skip very numeric columns for category grouping.
        if numeric_like >= int(non_empty * 0.7):
            continue
        # Penalize obvious identifier-ish columns.
        name = str(c).lower()
        id_penalty = 0.0
        if any(tok in name for tok in ("id", "order no", "order_no", "number", "no")):
            id_penalty = 1.5
        # Penalize date/time columns unless request itself is explicitly date/time.
        date_penalty = 0.0
        name_is_date = bool(re.search(r"\b(date|time|timestamp|month|year|day)\b", name))
        req_is_date = bool(re.search(r"\b(date|time|timestamp|month|year|day)\b", req))
        if name_is_date and not req_is_date:
            date_penalty = 2.5
        # Reward semantic match against requested group column label.
        sem_bonus = 0.0
        if req_norm:
            cand_norm = _norm_col(name)
            if req_norm == cand_norm:
                sem_bonus += 3.0
            elif req_norm in cand_norm or cand_norm in req_norm:
                sem_bonus += 1.5
            cand_toks = [t for t in re.split(r"[^a-z0-9]+", name) if t]
            for rt in req_toks:
                for ct in cand_toks:
                    if rt == ct:
                        sem_bonus += 1.0
                    elif rt in ct or ct in rt:
                        sem_bonus += 0.4
        # Favor moderate cardinality and good fill rate.
        score = (1.0 - abs(unique_ratio - 0.45)) + (non_empty / max(1, min(len(rows), 1000))) + sem_bonus - id_penalty - date_penalty
        if score > best_score:
            best_score = score
            best_col = c
    return best_col


def _lift_group_ops_from_metrics(params):
    """
    Models sometimes emit date grouping as a metric:
      metrics: [{column: "Order Date", op: "month", as: "month"}, {column: "Total", op: "sum"}]
    Convert those grouping-like metric entries into group_by specs.
    """
    metrics = params.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        return
    keep = []
    lifted = []
    for m in metrics:
        if not isinstance(m, dict):
            keep.append(m)
            continue
        op = str(m.get("op") or m.get("agg") or m.get("operation") or m.get("function") or "").strip().lower()
        col = str(m.get("column") or "").strip()
        alias = str(m.get("as") or m.get("alias") or "").strip()
        if op in {"week", "month", "year", "day", "date"} and col:
            spec = {"column": col, "op": op}
            if alias:
                spec["as"] = alias
            lifted.append(spec)
        else:
            keep.append(m)
    if lifted:
        existing = params.get("group_by")
        if not isinstance(existing, list):
            existing = []
        params["group_by"] = list(existing) + lifted
        params["metrics"] = keep


def _normalize_aggregation_like(params):
    """
    Accept model-emitted variants:
      aggregate: [{column, function, alias}]
      aggregation: [{column, function, alias}]
      aggregations: [{column, operation|function, alias}]
    and map them into canonical params["metrics"].
    """
    if params.get("metrics"):
        return
    src = params.get("aggregate")
    if not isinstance(src, list):
        src = params.get("aggregation")
    if not isinstance(src, list):
        src = params.get("aggregations")
    if not isinstance(src, list):
        return
    mapped = []
    for item in src:
        if not isinstance(item, dict):
            continue
        col = str(item.get("column") or "").strip()
        op = str(
            item.get("op")
            or item.get("agg")
            or item.get("operation")
            or item.get("function")
            or item.get("type")
            or item.get("metric")
            or ""
        ).strip()
        alias = str(item.get("as") or item.get("alias") or item.get("name") or "").strip()
        if not col or not op:
            continue
        m = {"column": col, "op": op}
        if alias:
            m["as"] = alias
        mapped.append(m)
    if mapped:
        params["metrics"] = mapped


def _parse_query_metric(params):
    """
    Parse simple SQL-like query strings emitted by models, such as:
      COUNT(Customer)
      COUNT(DISTINCT Customer)
      SELECT COUNT(customer) FROM sheet
      SELECT COUNT(DISTINCT customer) FROM sheet
    Returns None if no parseable count expression is found.
    """
    query = str(params.get("query") or "").strip()
    if not query:
        return None
    q = query.lower()
    m_dist = re.search(r"count\s*\(\s*distinct\s+([a-zA-Z0-9_ \*]+)\s*\)", q, flags=re.IGNORECASE)
    m_cnt = re.search(r"count\s*\(\s*([a-zA-Z0-9_ \*]+)\s*\)", q, flags=re.IGNORECASE)
    if m_dist:
        col = m_dist.group(1).strip()
        return {"column": col, "op": "count_distinct", "as": f"count_distinct_{col}"}
    if m_cnt:
        col = m_cnt.group(1).strip()
        return {"column": col, "op": "count", "as": f"count_{col}"}
    return None


def run(ctx, params):
    _normalize_aggregation_like(params)
    _lift_group_ops_from_metrics(params)

    # Support shorthand metric keys often emitted by model nodes:
    #   {"sum": ["Sales"], "group_by": ["Month"]}
    #   {"avg": "Total (USD)"}
    #   {"count": "Customer Name"}
    if not params.get("metrics"):
        for op_key in ("sum", "avg", "mean", "min", "max", "count", "count_distinct", "distinct", "count_unique"):
            raw = params.get(op_key)
            if raw is None:
                continue
            cols: list[str] = []
            if isinstance(raw, str) and raw.strip():
                cols = [raw.strip()]
            elif isinstance(raw, list):
                cols = [str(v or "").strip() for v in raw if str(v or "").strip()]
            if not cols:
                continue
            op_map = {
                "count_unique": "count_distinct",
                "unique_count": "count_distinct",
                "distinct": "count_distinct",
                "count_distinct": "count_distinct",
                "count": "count",
                "sum": "sum",
                "avg": "avg",
                "mean": "avg",
                "min": "min",
                "max": "max",
            }
            mapped = op_map.get(op_key, op_key)
            params["metrics"] = [{"column": c, "op": mapped, "as": f"{mapped}_{c}"} for c in cols]
            break

    # Support model shorthand:
    #   {"agg_func": "sum", "column": "Total (USD)"}
    #   {"agg_func": ["sum"], "column": "Total (USD)"}
    #   {"agg_func": "sum", "columns": ["Total (USD)"]}
    if not params.get("metrics"):
        agg_func = params.get("agg_func")
        if isinstance(agg_func, list):
            agg_func = str(agg_func[0] or "").strip() if agg_func else ""
        agg_func = str(agg_func or "").strip().lower()
        agg_col = str(params.get("column") or "").strip()
        if not agg_col:
            cols = params.get("columns")
            if isinstance(cols, list) and cols:
                agg_col = str(cols[0] or "").strip()
        if agg_func and agg_col:
            op_map = {
                "count_unique": "count_distinct",
                "unique_count": "count_distinct",
                "distinct": "count_distinct",
                "count_distinct": "count_distinct",
                "count": "count",
                "sum": "sum",
                "avg": "avg",
                "mean": "avg",
                "min": "min",
                "max": "max",
            }
            mapped = op_map.get(agg_func, agg_func)
            params["metrics"] = [{"column": agg_col, "op": mapped, "as": f"{mapped}_{agg_col}"}]

    # Support shorthand parameter shapes often emitted by agent nodes:
    #   {"count_unique": "Customer Name"}
    #   {"count_distinct": "Customer Name"}
    #   {"distinct": "Customer Name"}
    if not params.get("metrics"):
        for key in ("count_unique", "count_distinct", "distinct", "unique_count"):
            v = params.get(key)
            if isinstance(v, str) and v.strip():
                col0 = v.strip()
                params["metrics"] = [{"column": col0, "op": "count_distinct", "as": f"count_distinct_{col0}"}]
                # Also mirror canonical fields to improve downstream diagnostics.
                params.setdefault("operation", "count_unique")
                params.setdefault("column", col0)
                break

    parsed_q = _parse_query_metric(params)
    if parsed_q and not params.get("metrics"):
        params["metrics"] = [parsed_q]

    operation = str(params.get("operation") or params.get("metric") or "").strip().lower()
    if not operation:
        operation = str(params.get("function") or "").strip().lower()
    column = str(params.get("column") or "").strip()
    unique_flag = bool(params.get("unique"))
    if operation == "count" and unique_flag:
        operation = "count_unique"
    if operation and column and not params.get("metrics"):
        op_map = {
            "count_unique": "count_distinct",
            "unique_count": "count_distinct",
            "distinct": "count_distinct",
            "count_distinct": "count_distinct",
            "count": "count",
            "sum": "sum",
            "avg": "avg",
            "mean": "avg",
            "min": "min",
            "max": "max",
        }
        mapped = op_map.get(operation, operation)
        params["metrics"] = [{"column": column, "op": mapped, "as": f"{mapped}_{column}"}]

    # Normalize shorthand group_by strings like "Month"/["Month"] to derived month grouping.
    # This lets model-emitted tool calls work without requiring explicit {column, derive}.
    gb = params.get("group_by")
    if isinstance(gb, str):
        gb = [gb]
    if isinstance(gb, list):
        norm_gb = []
        for item in gb:
            if isinstance(item, str):
                s = item.strip().lower()
                if s in {"week", "month", "year", "day", "date"}:
                    norm_gb.append({"column": s, "op": "", "as": s})
                else:
                    norm_gb.append(item)
            else:
                norm_gb.append(item)
        params["group_by"] = norm_gb

    records = params.get("records")
    if records is None:
        file = _resolve_file(params)
        if not file:
            return {"ok": False, "warnings": ["missing_file"], "records": [], "group_by": [], "metrics": []}
        records = iter_records(file, sheet=params.get("sheet"), limit=params.get("limit"))
    rows = [dict(r) for r in records]
    metrics = _normalize_metrics(params.get("metrics"))
    metrics = _resolve_metric_columns(rows, metrics)
    metrics = _repair_zero_sum_metrics(rows, metrics)
    group_by_cols, group_specs = _normalize_group_by(params.get("group_by"))
    group_specs = _resolve_group_specs_against_rows(rows, group_specs)
    missing_group_cols = [
        str(s.get("column") or "").strip()
        for s in group_specs
        if isinstance(s, dict)
        and str(s.get("column") or "").strip()
        and str(s.get("column") or "").strip() not in (list(rows[0].keys()) if rows and isinstance(rows[0], dict) else [])
    ]
    warnings = []
    if missing_group_cols:
        # When auto is enabled, do a best-effort fallback to a valid text
        # dimension instead of hard-failing.
        if bool(params.get("auto")) and rows:
            fallback = _choose_fallback_group_column(rows)
            if fallback:
                repaired = []
                for s in group_specs:
                    if not isinstance(s, dict):
                        continue
                    col = str(s.get("column") or "").strip()
                    op = str(s.get("op") or "").strip().lower()
                    alias = str(s.get("as") or "").strip()
                    if op in {"week", "month", "year", "day", "date"}:
                        repaired.append(s)
                        continue
                    if col in missing_group_cols:
                        req_col = col
                        preferred = _choose_fallback_group_column(rows, requested_name=req_col) or fallback
                        new_alias = alias if alias else str(fallback)
                        repaired.append({"column": str(preferred), "op": "", "as": new_alias})
                        warnings.append(f"group_by_fallback_used:{col}->{preferred}")
                    else:
                        repaired.append(s)
                group_specs = repaired
                missing_group_cols = [
                    str(s.get("column") or "").strip()
                    for s in group_specs
                    if isinstance(s, dict)
                    and str(s.get("column") or "").strip()
                    and str(s.get("column") or "").strip() not in (list(rows[0].keys()) if rows and isinstance(rows[0], dict) else [])
                ]
        if missing_group_cols:
            return {
                "ok": False,
                "warnings": [f"group_by_column_not_found:{c}" for c in missing_group_cols],
                "records": [],
                "group_by": group_by_cols,
                "metrics": metrics,
            }
    group_by_cols = [str(s.get("as") or "").strip() for s in group_specs if isinstance(s, dict) and str(s.get("as") or "").strip()]
    rows = _apply_group_by_derivations(rows, group_specs)
    result = aggregate_records(rows, group_by=group_by_cols, metrics=metrics, auto=bool(params.get("auto")))
    # Make month/date groupings deterministic for chart output.
    recs = result.get("records") if isinstance(result.get("records"), list) else []
    if recs and group_by_cols:
        primary = str(group_by_cols[0] or "").strip()
        if primary:
            def _sort_key(rec):
                v = rec.get(primary) if isinstance(rec, dict) else None
                s = str(v or "").strip()
                d = _parse_date_like(s)
                if d is not None:
                    return (0, d.isoformat())
                m = re.match(r"^(\d{4})-(\d{2})$", s)
                if m:
                    return (0, f"{m.group(1)}-{m.group(2)}-01")
                return (1, s.lower())
            recs.sort(key=_sort_key)
            result["records"] = recs
    out = {"ok": True, **result}
    if warnings:
        out["warnings"] = warnings
    # Emit explicit scalar when result is a single aggregate row+metric.
    recs = result.get("records") if isinstance(result.get("records"), list) else []
    mets = result.get("metrics") if isinstance(result.get("metrics"), list) else []
    if len(recs) == 1 and len(mets) == 1 and isinstance(recs[0], dict):
        m0 = mets[0] if isinstance(mets[0], dict) else {}
        key = str(m0.get("as") or f"{m0.get('op')}_{m0.get('column')}").strip()
        if key and key in recs[0]:
            out["value"] = recs[0].get(key)
            out["metric"] = str(m0.get("op") or "")
            out["column"] = str(m0.get("column") or "")
    return out


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}
