from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List

NAME = "custom.file_chart_report"
PERMISSIONS = [NAME, "custom.*"]
_CREATED_AT = "2026-06-25T00:00:00Z"
_LAST_UPDATED = "2026-06-25T00:00:00Z"
_VERSION = "1.0"
_DEV_STATUS = "tested"

_FILE_RE = re.compile(r"((?:/app|/uploads|/data)/[^\s\"']+\.(?:json))", re.IGNORECASE)


def _uploads_dir(ctx: Dict[str, Any]) -> Path:
    app = (ctx or {}).get("app")
    uploads = None
    try:
        uploads = getattr(getattr(app, "state", None), "uploads_dir", None)
    except Exception:
        uploads = None
    if uploads:
        return Path(str(uploads))
    return Path(__file__).resolve().parents[5] / "data" / "uploads"


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


def _resolve_path(ctx: Dict[str, Any], request_text: str) -> Path | None:
    m = _FILE_RE.search(str(request_text or ""))
    if not m:
        return None
    raw = str(m.group(1) or "").strip()
    if raw.startswith("/uploads/"):
        return _uploads_dir(ctx) / Path(raw).name
    if raw.startswith("/data/"):
        return Path(__file__).resolve().parents[5] / raw.lstrip("/")
    return Path(raw)


def _extract_charts(payload: Any) -> List[Dict[str, Any]]:
    items = payload.get("charts") if isinstance(payload, dict) and isinstance(payload.get("charts"), list) else payload if isinstance(payload, list) else [payload]
    charts: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        simple_points = item.get("series") if isinstance(item.get("series"), list) else []
        if simple_points and all(isinstance(point, dict) and ("label" in point) and ("value" in point) for point in simple_points):
            charts.append({
                "title": str(item.get("title") or "Chart").strip() or "Chart",
                "type": str(item.get("chart") or item.get("type") or "bar").strip().lower() or "bar",
                "labels": [str(point.get("label") or "") for point in simple_points],
                "series": [{
                    "name": str(item.get("y_label") or item.get("title") or "Series 1").strip() or "Series 1",
                    "data": [point.get("value") for point in simple_points],
                }],
            })
            continue
        labels = item.get("labels") or item.get("x") or item.get("xValues") or item.get("categories") or []
        series_raw = item.get("series") if isinstance(item.get("series"), list) else []
        series: List[Dict[str, Any]] = []
        for idx, row in enumerate(series_raw):
            if not isinstance(row, dict):
                continue
            data = row.get("data") or row.get("y") or row.get("yValues") or []
            series.append({
                "name": str(row.get("name") or f"Series {idx + 1}").strip() or f"Series {idx + 1}",
                "data": list(data) if isinstance(data, list) else [],
            })
        if labels and series:
            charts.append({
                "title": str(item.get("title") or "Chart").strip() or "Chart",
                "type": str(item.get("chart") or item.get("type") or "line").strip().lower() or "line",
                "labels": [str(x) for x in labels],
                "series": series,
            })
    if charts:
        return charts
    return _infer_table_charts(payload)


def _safe_number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _infer_table_charts(payload: Any) -> List[Dict[str, Any]]:
    rows = payload if isinstance(payload, list) else []
    if not rows or not all(isinstance(row, dict) for row in rows[: min(len(rows), 12)]):
        return []
    sample_rows = rows[: min(len(rows), 40)]
    preferred_label_keys = ('idx', 'label', 'name', 'title', 'request', 'id')
    label_key = ''
    for key in preferred_label_keys:
        if any(str((row or {}).get(key) or '').strip() for row in sample_rows):
            label_key = key
            break
    if not label_key:
        for key in (rows[0].keys() if isinstance(rows[0], dict) else []):
            if any(isinstance((row or {}).get(key), str) and str((row or {}).get(key) or '').strip() for row in sample_rows):
                label_key = str(key)
                break
    labels = []
    for idx, row in enumerate(sample_rows, start=1):
        if label_key:
            raw = row.get(label_key)
            text_value = str(raw or '').strip()
            if label_key == 'request' and len(text_value) > 48:
                text_value = text_value[:45].rstrip() + '...'
            labels.append(text_value or f'Row {idx}')
        else:
            labels.append(f'Row {idx}')
    numeric_keys: List[str] = []
    blocked = {'tail', 'request', 'run_id', 'status'}
    first = rows[0] if isinstance(rows[0], dict) else {}
    for key in first.keys():
        if str(key or '') in blocked or str(key or '') == label_key:
            continue
        values = []
        valid = True
        for row in sample_rows:
            val = row.get(key)
            if isinstance(val, bool):
                values.append(1.0 if val else 0.0)
            elif isinstance(val, (int, float)):
                values.append(float(val))
            else:
                valid = False
                break
        if valid and values:
            numeric_keys.append(str(key))
    if not numeric_keys:
        return []
    chosen = numeric_keys[: min(len(numeric_keys), 6)]
    title = 'Structured Results Overview'
    return [{
        'title': title,
        'type': 'line' if len(sample_rows) > 2 else 'bar',
        'labels': labels,
        'series': [
            {
                'name': key.replace('_', ' ').title(),
                'data': [1.0 if row.get(key) is True else 0.0 if row.get(key) is False else float(row.get(key) or 0.0) for row in sample_rows],
            }
            for key in chosen
        ],
    }]


def _chart_text_summary(charts: List[Dict[str, Any]], limit: int = 3) -> List[str]:
    lines: List[str] = []
    for chart in charts[: max(1, int(limit or 3))]:
        title = str(chart.get("title") or "Chart").strip() or "Chart"
        labels = [str(x or "") for x in (chart.get("labels") or [])]
        series = chart.get("series") if isinstance(chart.get("series"), list) else []
        if not series:
            lines.append(f"- {title}: chart rendered.")
            continue
        first_series = series[0] if isinstance(series[0], dict) else {}
        series_name = str(first_series.get("name") or "Series 1").strip() or "Series 1"
        data = list(first_series.get("data") or []) if isinstance(first_series, dict) else []
        numeric = [_safe_number(v) for v in data]
        pairs = [(labels[idx] if idx < len(labels) else f"Point {idx + 1}", val) for idx, val in enumerate(numeric) if val is not None]
        if not pairs:
            lines.append(f"- {title}: {series_name} chart rendered.")
            continue
        start_label, start_val = pairs[0]
        end_label, end_val = pairs[-1]
        peak_label, peak_val = max(pairs, key=lambda item: item[1])
        direction = 'up' if end_val > start_val else 'down' if end_val < start_val else 'flat'
        lines.append(
            f"- {title}: {series_name} goes {direction} from {start_label} ({start_val:,.0f}) to {end_label} ({end_val:,.0f}); peak is {peak_label} ({peak_val:,.0f})."
        )
    return lines


def _html_document(title: str, charts: List[Dict[str, Any]]) -> str:
    charts_json = json.dumps(charts, ensure_ascii=False)
    template = """<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>__TITLE__</title>
  <script src=\"https://cdn.jsdelivr.net/npm/chart.js\"></script>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; background: #f6f8fb; color: #18212f; }
    .chart-card { background: #fff; border: 1px solid #dbe2ea; border-radius: 14px; padding: 16px; margin: 0 0 18px; }
    .chart-title { font-size: 18px; font-weight: 700; margin: 0 0 12px; }
    canvas { max-width: 100%; height: 320px !important; }
  </style>
</head>
<body>
  <h1>__TITLE__</h1>
  <div id=\"charts\"></div>
  <script>
    const charts = __CHARTS_JSON__;
    const host = document.getElementById('charts');
    charts.forEach((chart, idx) => {
      const card = document.createElement('div');
      card.className = 'chart-card';
      const heading = document.createElement('div');
      heading.className = 'chart-title';
      heading.textContent = chart.title || ('Chart ' + (idx + 1));
      const canvas = document.createElement('canvas');
      card.appendChild(heading);
      card.appendChild(canvas);
      host.appendChild(card);
      const colors = ['#2563eb', '#dc2626', '#059669', '#d97706'];
      const datasets = (chart.series || []).map((series, sidx) => ({
        label: series.name || ('Series ' + (sidx + 1)),
        data: Array.isArray(series.data) ? series.data : [],
        borderColor: colors[sidx % colors.length],
        backgroundColor: colors[sidx % colors.length] + '33',
        tension: 0.25,
        fill: false,
      }));
      new Chart(canvas.getContext('2d'), {
        type: chart.type || 'line',
        data: { labels: Array.isArray(chart.labels) ? chart.labels : [], datasets },
        options: { responsive: true, maintainAspectRatio: false }
      });
    });
  </script>
</body>
</html>
"""
    return template.replace("__TITLE__", title).replace("__CHARTS_JSON__", charts_json)


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_text = _request_text(ctx or {}, params or {})
    source_path = _resolve_path(ctx or {}, request_text)
    if source_path is None or not source_path.is_file():
        return {"ok": False, "warnings": ["input_json_not_found"], "data": {"input_path": str(source_path or "")}}
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    charts = _extract_charts(payload)
    if not charts:
        return {"ok": False, "warnings": ["chart_payload_not_detected"], "data": {"input_path": str(source_path)}}
    uploads = _uploads_dir(ctx or {})
    uploads.mkdir(parents=True, exist_ok=True)
    out_path = uploads / f"{source_path.stem}_{int(time.time())}.html"
    relative_output = f"/uploads/{out_path.name}"
    title = str(payload.get("title") if isinstance(payload, dict) else "" or source_path.stem.replace("_", " ").title()).strip() or "Chart Output"
    out_path.write_text(_html_document(title, charts), encoding="utf-8")
    chart_titles = ", ".join(chart.get("title") or "Chart" for chart in charts[:4])
    chart_lines = _chart_text_summary(charts, limit=3)
    summary_parts = [
        f"Rendered {len(charts)} chart(s) from {source_path.name}: {chart_titles}.",
        *chart_lines,
        f"HTML chart report saved to {relative_output}.",
    ]
    summary = "\n".join(part for part in summary_parts if str(part or "").strip())
    return {
        "ok": True,
        "summary": summary,
        "text": summary,
        "final_answer": summary,
        "data": {"input_path": str(source_path), "output_path": str(out_path), "relative_output_path": relative_output, "chart_count": len(charts), "charts": charts},
        "warnings": [],
        "files": [str(out_path), relative_output],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "custom",
    "label": "File Chart Report",
    "description": "Read a JSON chart payload and render it into an HTML chart report.",
    "permissions": PERMISSIONS,
    "metadata": {
        "version": _VERSION,
        "created_at": _CREATED_AT,
        "last_updated": _LAST_UPDATED,
        "dev_status": _DEV_STATUS,
        "required_capabilities": ["document_io", "chart_output"],
        "output_mode": "file",
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
