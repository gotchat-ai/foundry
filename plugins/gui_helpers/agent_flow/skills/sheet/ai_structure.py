from pathlib import Path as _Path
import os as _os
import re as _re
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from shared.text_core import parse_structured_text
from shared.io import iter_records, write_records
import inspect as _inspect
import asyncio as _asyncio
NAME = "sheet.ai_structure"
PERMISSIONS = ["ai_router.execute", "spreadsheet.transform", "filesystem.write", "spreadsheet.write"]


def _candidate_roots(ctx=None):
    roots = []
    app = (ctx or {}).get("app") if isinstance(ctx, dict) else None
    for raw in (
        getattr(getattr(app, "state", None), "data_dir", None),
        getattr(getattr(app, "state", None), "workdir", None),
        _os.getcwd(),
    ):
        if raw:
            roots.append(_Path(str(raw)).resolve())
    for base in list(roots):
        roots.extend([
            base / "agent_workflow" / "repo",
            base / "data",
            base / "data" / "agent_workflow" / "repo",
            base / "generated",
        ])
    cwd = _Path(_os.getcwd()).resolve()
    for parent in [cwd, *list(cwd.parents)[:4]]:
        roots.extend([
            parent,
            parent / "data",
            parent / "data" / "agent_workflow" / "repo",
            parent / "llmloader2" / "data" / "agent_workflow" / "repo",
            parent / "generated",
        ])
    seen = set()
    out = []
    for root in roots:
        try:
            r = root.resolve()
        except Exception:
            continue
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _resolve_path(raw, ctx=None, aliases=None):
    text = str(raw or "").strip().strip("'\"")
    if not text:
        return None
    p = _Path(text)
    names = [p.name]
    for alias in aliases or []:
        a = str(alias or "").strip()
        if a and a not in names:
            names.append(a)
    candidates = [p] if p.is_absolute() else []
    for root in _candidate_roots(ctx):
        candidates.append(root / text)
        for name in names:
            candidates.append(root / name)
    for cand in candidates:
        try:
            r = cand.resolve()
            if r.is_file():
                return r
        except Exception:
            continue
    for root in _candidate_roots(ctx):
        if not root.exists():
            continue
        for name in names:
            try:
                for hit in root.rglob(name):
                    if hit.is_file():
                        return hit.resolve()
            except Exception:
                continue
    return None


def _read_text_input(ctx, params):
    text = str(params.get("text") or "")
    path_raw = (
        params.get("text_file")
        or params.get("text_path")
        or params.get("input_text_file")
        or params.get("input_path")
    )
    if path_raw:
        p = _resolve_path(path_raw, ctx, aliases=["25_callers.txt"] if str(path_raw).lower().endswith("25_calls.txt") else None)
        if p:
            return p.read_text(encoding="utf-8-sig", errors="replace"), str(p)
    if text.strip():
        return text, ""
    # Last-resort convenience for common workflow wording.
    for name in ("25_calls.txt", "25_callers.txt"):
        p = _resolve_path(name, ctx, aliases=["25_callers.txt", "25_calls.txt"])
        if p:
            return p.read_text(encoding="utf-8-sig", errors="replace"), str(p)
    return "", ""


def _schema_from_file(ctx, params):
    file_raw = params.get("file") or params.get("schema_file") or params.get("workbook") or params.get("spreadsheet")
    if not file_raw:
        return []
    p = _resolve_path(file_raw, ctx)
    if not p:
        return []
    try:
        rows = list(iter_records(str(p), sheet=params.get("sheet"), limit=1))
    except Exception:
        rows = []
    if rows and isinstance(rows[0], dict):
        return [k for k in rows[0].keys() if str(k or "").strip() and not str(k).lower().startswith("column")]
    return []


def _normalize_columns(params, inferred):
    cols = params.get("columns") or params.get("schema") or _columns_from_model_context(params) or inferred or []
    if isinstance(cols, str):
        parts = _re.split(r"[,|\n]", cols)
        cols = [p.strip() for p in parts if p.strip()]
    if isinstance(cols, dict):
        cols = list(cols.keys())
    return [str(c).strip() for c in (cols or []) if str(c).strip()]


def _columns_from_model_context(params):
    for key in ("header_analysis", "field_map", "column_mapping", "schema_analysis", "context"):
        raw = params.get(key)
        if not raw:
            continue
        obj = raw
        if isinstance(raw, str):
            try:
                import json as _json
                obj = _json.loads(raw)
            except Exception:
                obj = raw
        if isinstance(obj, dict):
            for col_key in ("columns", "target_columns", "output_columns", "schema_columns", "profile_columns"):
                cols = obj.get(col_key)
                if isinstance(cols, list) and cols:
                    return cols
            fields = obj.get("fields") or obj.get("mappings") or obj.get("field_map")
            if isinstance(fields, list):
                cols = []
                for item in fields:
                    if isinstance(item, dict):
                        val = item.get("target") or item.get("column") or item.get("name") or item.get("output")
                        if val:
                            cols.append(val)
                    elif item:
                        cols.append(item)
                if cols:
                    return cols
            if isinstance(fields, dict) and fields:
                return list(fields.keys())
        if isinstance(obj, list) and obj:
            return obj
    return []


def _model_context_objects(params):
    out = []
    for key in ("header_analysis", "field_map", "column_mapping", "schema_analysis", "context"):
        raw = params.get(key)
        if not raw:
            continue
        obj = raw
        if isinstance(raw, str):
            try:
                import json as _json
                obj = _json.loads(raw)
            except Exception:
                obj = raw
        if isinstance(obj, dict):
            out.append(obj)
            for nested_key in ("header_analysis", "schema_analysis", "mapping", "field_map"):
                nested = obj.get(nested_key)
                if isinstance(nested, dict):
                    out.append(nested)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict):
                    out.append(item)
    return out


def _filters_from_model_context(params):
    filters = []
    for obj in _model_context_objects(params):
        raw_filters = obj.get("filters") or obj.get("where") or obj.get("criteria")
        if isinstance(raw_filters, dict):
            raw_filters = [raw_filters]
        if isinstance(raw_filters, list):
            for item in raw_filters:
                if isinstance(item, dict):
                    filters.append(item)
    return filters


def _clean_text(text):
    return (
        str(text or "")
        .replace("Ã¢â‚¬â„¢", "'")
        .replace("â€™", "'")
        .replace("�", "'")
        .replace("Ã¢â‚¬Å“", '"')
        .replace("Ã¢â‚¬Â", '"')
    )


def _norm_name(name):
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def _field_kind(name):
    norm = _norm_name(name)
    if norm in {"callernumber", "number", "id", "rowid"} or ("caller" in norm and "number" in norm):
        return "block_number"
    if norm in {"name", "fullname", "customer", "customername", "caller"} or norm.endswith("name"):
        return "name"
    if "age" in norm:
        return "age"
    if "gender" in norm or norm == "sex":
        return "gender"
    if "bmi" in norm:
        return "bmi"
    if "child" in norm or "kid" in norm or "depend" in norm:
        return "children"
    if "smok" in norm:
        return "smoking"
    if ("month" in norm or "monthly" in norm) and any(x in norm for x in ("pay", "price", "cost", "premium", "amount", "usd", "fee")):
        return "money_monthly"
    if any(x in norm for x in ("price", "cost", "premium", "amount", "payment", "usd", "fee")):
        return "money_annual"
    if "location" in norm or "city" in norm or "state" in norm or "region" in norm:
        return "location"
    if "source" in norm or "transcript" in norm or "text" in norm or "note" in norm:
        return "source_text"
    return "unknown"


def _number_value(raw):
    word_num = {
        "zero": 0,
        "no": 0,
        "none": 0,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    text = str(raw or "").strip().lower()
    if text.isdigit():
        return int(text)
    return word_num.get(text, raw)


def _money_number(match):
    if not match:
        return None
    val = float(str(match.group(1)).replace(",", ""))
    return int(val) if val.is_integer() else val


def _extract_by_kind(kind, block):
    body = block.get("body", "")
    if kind == "block_number":
        return block.get("number")
    if kind == "name":
        return block.get("title") or block.get("name")
    if kind == "age":
        m = _re.search(r"\b(\d{1,3})\s+years?\s+old\b|\bage\s*(?:is|:)?\s*(\d{1,3})\b", body, _re.IGNORECASE)
        return int(m.group(1) or m.group(2)) if m else None
    if kind == "gender":
        m = _re.search(r"\b(male|female|nonbinary|non-binary|other)\b", body, _re.IGNORECASE)
        return m.group(1).replace("-", " ").title().replace(" ", "-") if m else None
    if kind == "bmi":
        m = _re.search(r"\bbmi\s*(?:is|:)?\s*([0-9]+(?:\.[0-9]+)?)\b", body, _re.IGNORECASE)
        return float(m.group(1)) if m else None
    if kind == "children":
        m = _re.search(r"\b(?:have|has|with)\s+(no|none|zero|one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+(?:kids?|children|child|dependents?)\b", body, _re.IGNORECASE)
        return _number_value(m.group(1)) if m else None
    if kind == "smoking":
        m = _re.search(r"\b(non[- ]?smoker|nonsmoker|smoker|don.?t smoke|do not smoke|never smoke|not a smoker)\b", body, _re.IGNORECASE)
        if not m:
            return None
        raw = m.group(1).lower()
        return "Non-Smoker" if "non" in raw or "don" in raw or "do not" in raw or "never" in raw or "not a" in raw else "Smoker"
    if kind == "money_monthly":
        m = _re.search(r"\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:a month|monthly|per month)\b", body, _re.IGNORECASE)
        return _money_number(m)
    if kind == "money_annual":
        annual = _re.search(r"\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:a year|annually|annual|per year)\b", body, _re.IGNORECASE)
        if annual:
            return _money_number(annual)
        monthly = _re.search(r"\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:a month|monthly|per month)\b", body, _re.IGNORECASE)
        monthly_val = _money_number(monthly)
        if monthly_val is None:
            return None
        annual_val = float(monthly_val) * 12
        return int(annual_val) if annual_val.is_integer() else annual_val
    if kind == "location":
        m = _re.search(r"\b(?:live in|from|located in|location is)\s+([A-Z][A-Za-z .'-]+?)(?:[,.]|$)", body)
        return m.group(1).strip() if m else None
    if kind == "source_text":
        return f"Caller Number {block.get('number')}: {body}" if block.get("number") is not None else body
    return None


def _default_columns_for_blocks():
    return [
        "Caller Number",
        "Name",
        "Age",
        "Gender",
        "BMI",
        "Children",
        "Smoking Status",
        "Monthly Payment (USD)",
        "Insurance Price (USD)",
        "Source Text",
    ]


def _parse_numbered_blocks(text, columns=None):
    records = []
    s = _clean_text(text)
    pattern = _re.compile(
        r"(?:\*\*)?\s*(?P<num>\d+)\.\s*(?:(?P<label>Caller|Customer|Person|Patient|Member|Client)\s*:\s*)?(?P<title>[^*\r\n]+?)(?:\*\*)?\s*[\r\n]+(?P<body>.*?)(?=\n\s*(?:\*\*)?\s*\d+\.\s*(?:Caller|Customer|Person|Patient|Member|Client)?\s*:|\Z)",
        _re.IGNORECASE | _re.DOTALL,
    )
    target_columns = columns or _default_columns_for_blocks()
    for m in pattern.finditer(s):
        body = " ".join(str(m.group("body") or "").split()).strip().strip('"')
        title = str(m.group("title") or "").strip().strip(":").strip()
        block = {"number": int(m.group("num")), "label": str(m.group("label") or "").strip(), "title": title, "body": body}
        rec = {col: _extract_by_kind(_field_kind(col), block) for col in target_columns}
        if any(v is not None and v != "" for v in rec.values()):
            records.append(rec)
    return records


def _project_record(rec, columns):
    if not columns:
        return rec
    out = {}
    source_by_kind = {}
    for key in rec:
        source_by_kind.setdefault(_field_kind(key), key)
    for col in columns:
        if col in rec:
            out[col] = rec.get(col)
            continue
        src = source_by_kind.get(_field_kind(col))
        out[col] = rec.get(src) if src else None
    return out


def _record_value_by_kind(rec, kind):
    if not isinstance(rec, dict):
        return None
    for key, val in rec.items():
        if _field_kind(key) == kind:
            return val
    return None


def _number_or_none(value):
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except Exception:
        return None


def _matches_numeric_goal(value, goal, nouns):
    num = _number_or_none(value)
    if num is None:
        return True
    noun_pattern = "|".join(_re.escape(n) for n in nouns)
    over = _re.search(rf"\b(?:{noun_pattern})\b[^.\n]*\b(?:over|above|greater than|more than|>=?)\s*(\d+(?:\.\d+)?)", goal)
    if not over:
        over = _re.search(rf"\b(?:over|above|greater than|more than|>=?)\s*(\d+(?:\.\d+)?)\s*(?:{noun_pattern})\b", goal)
    if over and num <= float(over.group(1)):
        return False
    under = _re.search(rf"\b(?:{noun_pattern})\b[^.\n]*\b(?:under|below|less than|younger than|<=?)\s*(\d+(?:\.\d+)?)", goal)
    if not under:
        under = _re.search(rf"\b(?:under|below|less than|younger than|<=?)\s*(\d+(?:\.\d+)?)\s*(?:{noun_pattern})\b", goal)
    if under and num >= float(under.group(1)):
        return False
    between = _re.search(rf"\b(?:{noun_pattern})\b[^.\n]*\bbetween\s*(\d+(?:\.\d+)?)\s*(?:and|-)\s*(\d+(?:\.\d+)?)", goal)
    if between:
        lo = float(between.group(1))
        hi = float(between.group(2))
        if not (lo <= num <= hi):
            return False
    return True


def _value_for_filter(rec, flt):
    if not isinstance(rec, dict) or not isinstance(flt, dict):
        return None
    for key in ("column", "field", "target", "name"):
        col = flt.get(key)
        if col and str(col) in rec:
            return rec.get(str(col))
    kind = flt.get("kind") or flt.get("semantic") or flt.get("field_kind")
    if kind:
        return _record_value_by_kind(rec, str(kind))
    col = flt.get("column") or flt.get("field") or flt.get("target") or flt.get("name")
    if col:
        wanted = _field_kind(col)
        if wanted != "unknown":
            return _record_value_by_kind(rec, wanted)
        norm = _norm_name(col)
        for key, val in rec.items():
            if _norm_name(key) == norm:
                return val
    return None


def _coerce_for_compare(value):
    num = _number_or_none(value)
    if num is not None:
        return num
    return str(value or "").strip().lower()


def _filter_matches(rec, flt):
    if not isinstance(flt, dict):
        return True
    op = str(flt.get("op") or flt.get("operator") or flt.get("condition") or "eq").strip().lower()
    expected = flt.get("value")
    if expected is None and "values" in flt:
        expected = flt.get("values")
    actual = _value_for_filter(rec, flt)
    if op in {"exists", "not_empty", "present"}:
        return actual not in (None, "")
    if op in {"missing", "empty", "is_empty"}:
        return actual in (None, "")
    if isinstance(expected, (list, tuple)) and op in {"in", "one_of", "eq", "equals"}:
        actual_s = str(actual or "").strip().lower()
        return any(actual_s == str(v or "").strip().lower() for v in expected)
    if op in {"contains", "includes"}:
        return str(expected or "").strip().lower() in str(actual or "").strip().lower()
    if op in {"not_contains", "excludes"}:
        return str(expected or "").strip().lower() not in str(actual or "").strip().lower()
    if op in {"neq", "ne", "not", "not_eq", "!="}:
        return _coerce_for_compare(actual) != _coerce_for_compare(expected)
    if op in {"gt", ">", "after", "above", "over", "greater_than"}:
        a = _number_or_none(actual)
        b = _number_or_none(expected)
        return True if a is None or b is None else a > b
    if op in {"gte", ">=", "at_least", "min"}:
        a = _number_or_none(actual)
        b = _number_or_none(expected)
        return True if a is None or b is None else a >= b
    if op in {"lt", "<", "before", "below", "under", "less_than"}:
        a = _number_or_none(actual)
        b = _number_or_none(expected)
        return True if a is None or b is None else a < b
    if op in {"lte", "<=", "at_most", "max"}:
        a = _number_or_none(actual)
        b = _number_or_none(expected)
        return True if a is None or b is None else a <= b
    if op in {"between", "range"}:
        vals = expected if isinstance(expected, (list, tuple)) else [flt.get("min"), flt.get("max")]
        if len(vals) < 2:
            return True
        a = _number_or_none(actual)
        lo = _number_or_none(vals[0])
        hi = _number_or_none(vals[1])
        return True if a is None or lo is None or hi is None else lo <= a <= hi
    return _coerce_for_compare(actual) == _coerce_for_compare(expected)


def _apply_model_filters(records, filters):
    out = list(records or [])
    for flt in filters or []:
        out = [r for r in out if _filter_matches(r, flt)]
    return out

def _apply_goal(records, params):
    goal = " ".join(
        str(params.get(k) or "")
        for k in ("goal", "request", "user_request", "instruction", "instructions", "query")
    ).lower()
    out = list(records or [])
    if not goal:
        return out, None
    if _re.search(r"\b(non[- ]?smokers?|nonsmokers?)\s+only\b|\bonly\s+(?:the\s+)?non[- ]?smokers?\b|\b(?:list|extract|include|show)\s+(?:only\s+)?(?:the\s+)?non[- ]?smokers?\b", goal):
        out = [r for r in out if "non" in str(r.get("Smoking Status") or r.get("Smoker") or "").strip().lower()]
    elif _re.search(r"\bonly\s+(?:the\s+)?smokers?\b|\bsmokers?\s+only\b|\b(?:list|extract|include|show)\s+(?:only\s+)?(?:the\s+)?smokers?\b", goal):
        out = [r for r in out if str(r.get("Smoking Status") or r.get("Smoker") or "").strip().lower() == "smoker"]
    if _re.search(r"\b(?:female|women)\b", goal) and not _re.search(r"\bmale\b", goal):
        out = [r for r in out if str(_record_value_by_kind(r, "gender") or "").strip().lower().startswith("female")]
    elif _re.search(r"\b(?:male|men)\b", goal):
        out = [r for r in out if str(_record_value_by_kind(r, "gender") or "").strip().lower().startswith("male")]
    if _re.search(r"\b(?:no|zero|without)\s+(?:children|kids|dependents)\b", goal):
        out = [r for r in out if (_number_or_none(_record_value_by_kind(r, "children")) or 0) == 0]
    elif _re.search(r"\b(?:with|has|have)\s+(?:children|kids|dependents)\b", goal):
        out = [r for r in out if (_number_or_none(_record_value_by_kind(r, "children")) or 0) > 0]
    out = [r for r in out if _matches_numeric_goal(_record_value_by_kind(r, "age"), goal, ["age", "ages", "years old", "year old"])]
    out = [r for r in out if _matches_numeric_goal(_record_value_by_kind(r, "bmi"), goal, ["bmi"])]
    out = [r for r in out if _matches_numeric_goal(_record_value_by_kind(r, "money_monthly"), goal, ["monthly", "month", "payment", "premium"])]
    out = [r for r in out if _matches_numeric_goal(_record_value_by_kind(r, "money_annual"), goal, ["annual", "yearly", "insurance price", "price"])]
    # Convenient projection for common natural-language requests when columns
    # were not supplied explicitly.
    if not (params.get("columns") or params.get("schema")):
        wants_name = "name" in goal or "caller" in goal
        wants_age = "age" in goal or "years old" in goal
        wants_gender = "gender" in goal or "male" in goal or "female" in goal
        wants_bmi = "bmi" in goal
        wants_children = "child" in goal or "kid" in goal or "dependent" in goal
        wants_smoking = "smok" in goal
        wants_monthly = "monthly" in goal or "month" in goal
        wants_annual = "annual" in goal or "insurance price" in goal or "year" in goal
        wants_source = "source" in goal or "transcript" in goal or "quote" in goal
        cols = []
        if wants_name:
            cols.append("Name")
        if wants_age:
            cols.append("Age")
        if wants_gender:
            cols.append("Gender")
        if wants_bmi:
            cols.append("BMI")
        if wants_children:
            cols.append("Children")
        if wants_smoking:
            cols.append("Smoking Status")
        if wants_monthly:
            cols.append("Monthly Payment (USD)")
        if wants_annual:
            cols.append("Insurance Price (USD)")
        if wants_source:
            cols.append("Source Text")
        if cols:
            out = [_project_record(r, cols) for r in out]
            return out, cols
    return out, None


def _find_router(ctx):
    if isinstance(ctx, dict): return ctx.get("ai_router")
    if hasattr(ctx, "ai_router"): return getattr(ctx, "ai_router")
    if hasattr(ctx, "app") and hasattr(ctx.app, "state") and hasattr(ctx.app.state, "ai_router"): return ctx.app.state.ai_router
    return None
def run(ctx, params):
    params = params or {}
    text, text_source = _read_text_input(ctx, params)
    inferred_columns = _schema_from_file(ctx, params)
    columns = _normalize_columns(params, inferred_columns)
    router = _find_router(ctx)
    ai_error = None
    if router and hasattr(router, "execute") and params.get("use_ai", True):
        prompt = "Convert the following text into a JSON array of flat spreadsheet records. Return JSON only. No markdown."
        if columns: prompt += f" Target columns: {columns}."
        if inferred_columns: prompt += f" Reference spreadsheet columns: {inferred_columns}."
        prompt += "\n\nTEXT:\n" + text
        try:
            result = router.execute(route=params.get("route", "spreadsheet_structure"), prompt=prompt, context=params.get("context") or {}, options=params.get("options") or {})
            if _inspect.isawaitable(result):
                try:
                    _asyncio.get_running_loop()
                    raise RuntimeError("async_ai_router_execute_requires_async_skill_runtime")
                except RuntimeError as loop_exc:
                    if str(loop_exc) == "async_ai_router_execute_requires_async_skill_runtime":
                        raise
                    result = _asyncio.run(result)
            raw = result.get("text") if isinstance(result, dict) else str(result)
            records, source = parse_structured_text(raw, columns=columns), "ai_router"
        except Exception as e:
            records, source, ai_error = [], "deterministic_fallback", str(e)
    else:
        records, source = [], "deterministic"
    if not records:
        records = _parse_numbered_blocks(text, columns=columns or None)
        if records:
            source = "numbered_block_parser" if source == "deterministic" else f"{source}:numbered_block_parser"
    if not records:
        records = parse_structured_text(text, columns=columns)
        if source == "deterministic_fallback" and not ai_error:
            ai_error = "ai_router_returned_no_records"
    model_filters = _filters_from_model_context(params)
    if model_filters:
        records = _apply_model_filters(records, model_filters)
    else:
        records, goal_columns = _apply_goal(records, params)
        if goal_columns and not columns:
            columns = goal_columns
    if columns and records:
        records = [_project_record(r, columns) for r in records]
    out = {
        "ok": True,
        "records": records,
        "rows": len(records),
        "source": source,
        "columns": columns or (list(records[0].keys()) if records else []),
        "text_source": text_source,
        "schema_columns": inferred_columns,
    }
    if model_filters:
        out["filters"] = model_filters
    if ai_error: out["ai_error"] = ai_error
    output = params.get("output")
    if output:
        try:
            out["export"] = write_records(records, output, sheet_name=params.get("sheet_name") or "Structured", columns=columns or None)
            out["output"] = out["export"].get("output") if isinstance(out.get("export"), dict) else output
        except Exception as exc:
            fallback = str(output)
            if _Path(fallback).suffix.lower() in {".xlsx", ".xlsm"}:
                fallback = str(_Path(fallback).with_suffix(".csv"))
                out["export"] = write_records(records, fallback, sheet_name=params.get("sheet_name") or "Structured", columns=columns or None)
                out["output"] = out["export"].get("output") if isinstance(out.get("export"), dict) else fallback
                out["export_fallback_reason"] = str(exc)
            else:
                raise
    return out


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Convert free-form text into flat spreadsheet records, optionally using a reference workbook/schema and exporting the result.",
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}
