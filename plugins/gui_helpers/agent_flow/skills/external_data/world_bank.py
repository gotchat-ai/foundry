from __future__ import annotations

from typing import Any, Dict

try:
    from ._http import error_payload, get_json, int_param, text_param, url_with_query
except Exception:
    import importlib.util
    from pathlib import Path
    _P = Path(__file__).resolve().parent / "_http.py"
    _S = importlib.util.spec_from_file_location("external_data_http", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    error_payload = _M.error_payload
    get_json = _M.get_json
    int_param = _M.int_param
    text_param = _M.text_param
    url_with_query = _M.url_with_query


NAME = "external_data.world_bank"
PERMISSIONS = [NAME, "external_data.*", "web.request"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    country = text_param(params, "country", "country_code") or "all"
    indicator = text_param(params, "indicator", "indicator_code")
    if not indicator:
        return {"ok": False, "data": {}, "warnings": ["indicator_required"]}
    per_page = int_param(params, "per_page", int_param(params, "limit", 100, 1, 1000), 1, 20000)
    query = {"format": "json", "per_page": per_page}
    if text_param(params, "date"):
        query["date"] = text_param(params, "date")
    else:
        start = text_param(params, "start_year", "start")
        end = text_param(params, "end_year", "end")
        if start and end:
            query["date"] = f"{start}:{end}"
    url = url_with_query(f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}", query)
    try:
        row = get_json(url, params)
        payload = row.get("json") or []
        meta = payload[0] if isinstance(payload, list) and payload else {}
        records = payload[1] if isinstance(payload, list) and len(payload) > 1 and isinstance(payload[1], list) else []
        return {
            "ok": True,
            "data": {
                "source": "World Bank API v2",
                "url": url,
                "country": country,
                "indicator": indicator,
                "metadata": meta,
                "records": records,
            },
            "warnings": [],
        }
    except Exception as exc:
        return error_payload("World Bank", exc, {"url": url, "country": country, "indicator": indicator})


TOOL_SPEC = {
    "id": NAME,
    "category": "external_data",
    "label": "World Bank: Indicator Data",
    "description": "Fetch country or global time-series records from the World Bank API v2 by indicator code.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "country": {"type": "string", "description": "ISO2/ISO3 country code or 'all'."},
            "indicator": {"type": "string", "description": "World Bank indicator code, e.g. NY.GDP.MKTP.CD."},
            "start_year": {"type": "string"},
            "end_year": {"type": "string"},
            "date": {"type": "string", "description": "World Bank date expression, e.g. 2018:2024."},
            "per_page": {"type": "integer"},
            "limit": {"type": "integer"},
            "timeout": {"type": "number"},
        },
        "required": ["indicator"],
        "additionalProperties": True,
    },
}
