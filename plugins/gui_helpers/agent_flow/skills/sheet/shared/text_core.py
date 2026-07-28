import csv, io, json, re

def parse_structured_text(text: str, columns=None, delimiter=None):
    text = text or ""
    if not text.strip():
        return []
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            if obj and isinstance(obj[0], dict): return obj
            if columns: return [dict(zip(columns, row if isinstance(row, list) else [row])) for row in obj]
        if isinstance(obj, dict): return [obj]
    except Exception:
        pass
    sample = text[:4096]
    delim = delimiter
    if not delim:
        try:
            delim = csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
        except Exception:
            delim = "," if "," in sample else None
    if delim:
        reader = csv.reader(io.StringIO(text), delimiter=delim)
        rows = [r for r in reader if any(str(c).strip() for c in r)]
        if not rows: return []
        if columns:
            headers, data_rows = columns, rows
        else:
            headers = [c.strip() or f"Column{i+1}" for i, c in enumerate(rows[0])]
            data_rows = rows[1:]
        return [{headers[i] if i < len(headers) else f"Column{i+1}": row[i] if i < len(row) else None for i in range(max(len(headers), len(row)))} for row in data_rows]
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line: continue
        pairs = re.findall(r"([A-Za-z][A-Za-z0-9 _-]{1,30})\s*[:=]\s*([^,;]+)", line)
        records.append({k.strip(): v.strip() for k, v in pairs} if pairs else {"Text": line})
    return records
