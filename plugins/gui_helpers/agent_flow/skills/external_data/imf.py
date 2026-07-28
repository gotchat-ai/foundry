from __future__ import annotations

from typing import Any, Dict, List

try:
    from ._http import error_payload, get_json, int_param, text_param
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


NAME = "external_data.imf"
PERMISSIONS = [NAME, "external_data.*", "web.request"]


def _join_codes(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(x).strip().upper() for x in value if str(x).strip())
    return str(value or "").strip().upper()


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    mode = str(params.get("mode") or "datamapper").strip().lower()
    base = "https://www.imf.org/external/datamapper/api/v1"
    if mode in {"indicators", "indicator_list"}:
        url = f"{base}/indicators"
    elif mode in {"countries", "country_list"}:
        url = f"{base}/countries"
    else:
        indicator = text_param(params, "indicator", "indicator_code")
        if not indicator:
            return {"ok": False, "data": {}, "warnings": ["indicator_required"]}
        countries = _join_codes(params.get("countries") or params.get("country") or params.get("country_code") or "")
        periods = _join_codes(params.get("periods") or params.get("period") or params.get("years") or "")
        parts: List[str] = [base, indicator.upper()]
        if countries:
            parts.append(countries)
        if periods:
            parts.append(periods)
        url = "/".join(parts)
    try:
        row = get_json(url, params)
        payload = row.get("json")
        limit = int_param(params, "limit", 500, 1, 10000)
        return {
            "ok": True,
            "data": {
                "source": "IMF DataMapper API",
                "url": url,
                "mode": mode,
                "payload": payload,
                "limit_hint": limit,
            },
            "warnings": [],
        }
    except Exception as exc:
        return error_payload("IMF DataMapper", exc, {"url": url, "mode": mode})


TOOL_SPEC = {
    "id": NAME,
    "category": "external_data",
    "label": "IMF: DataMapper Data",
    "description": "Fetch IMF DataMapper indicators, countries, or indicator time-series data.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["datamapper", "indicators", "countries"]},
            "indicator": {"type": "string", "description": "IMF DataMapper indicator code."},
            "country": {"type": "string"},
            "countries": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}]},
            "periods": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}]},
            "limit": {"type": "integer"},
            "timeout": {"type": "number"},
        },
        "additionalProperties": True,
    },
}
