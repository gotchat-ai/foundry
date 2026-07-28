from collections import Counter, defaultdict
from shared.utils import coerce_scalar

def infer_type(values):
    non_empty = [v for v in values if v is not None and str(v).strip() != ""]
    if not non_empty:
        return "empty"
    nums = ints = bools = 0
    for v in non_empty:
        cv = coerce_scalar(v)
        if isinstance(cv, bool): bools += 1
        elif isinstance(cv, int): ints += 1; nums += 1
        elif isinstance(cv, float): nums += 1
    n = len(non_empty)
    if bools / n > 0.9: return "boolean"
    if ints / n > 0.9: return "integer"
    if nums / n > 0.9: return "numeric"
    return "text"

def profile_records(records, max_rows=None):
    rows = 0
    columns, seen_columns = [], set()
    stats = defaultdict(lambda: {"missing": 0, "non_empty": 0, "samples": [], "unique": set(), "min": None, "max": None})
    row_keys = Counter()
    duplicate_count = 0
    for rec in records:
        rows += 1
        for k in rec.keys():
            if k not in seen_columns:
                columns.append(k); seen_columns.add(k)
        key = tuple((k, rec.get(k)) for k in sorted(rec.keys()))
        row_keys[key] += 1
        if row_keys[key] > 1: duplicate_count += 1
        for col in columns:
            val = rec.get(col)
            s = stats[col]
            if val is None or str(val).strip() == "":
                s["missing"] += 1
            else:
                s["non_empty"] += 1
                if len(s["samples"]) < 5: s["samples"].append(val)
                if len(s["unique"]) < 1000: s["unique"].add(str(val))
                cv = coerce_scalar(val)
                if isinstance(cv, (int, float)) and not isinstance(cv, bool):
                    s["min"] = cv if s["min"] is None else min(s["min"], cv)
                    s["max"] = cv if s["max"] is None else max(s["max"], cv)
        if max_rows and rows >= max_rows:
            break
    return {
        "rows_profiled": rows,
        "columns": [{"name": c, "type": infer_type(stats[c]["samples"]), "missing": stats[c]["missing"], "non_empty": stats[c]["non_empty"], "unique_sample_count": len(stats[c]["unique"]), "min": stats[c]["min"], "max": stats[c]["max"], "samples": stats[c]["samples"]} for c in columns],
        "duplicate_rows_sample_count": duplicate_count,
    }
