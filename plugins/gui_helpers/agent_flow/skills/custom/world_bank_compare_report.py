from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from ..external_data.world_bank import run as world_bank_run
except Exception:
    import importlib.util
    _P = Path(__file__).resolve().parents[1] / "external_data" / "world_bank.py"
    _S = importlib.util.spec_from_file_location("custom_world_bank_api", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    world_bank_run = _M.run


NAME = "custom.world_bank_compare_report"
PERMISSIONS = [NAME, "custom.*", "external_data.world_bank", "external_data.*", "web.request"]
_CREATED_AT = "2026-06-25T00:00:00Z"
_LAST_UPDATED = "2026-06-25T00:00:00Z"
_VERSION = "1.0"
_DEV_STATUS = "tested"

COUNTRY_CODES = {
    "indonesia": "IDN",
    "vietnam": "VNM",
    "mexico": "MEX",
    "united states": "USA",
    "usa": "USA",
    "euro area": "EMU",
    "china": "CHN",
}

COUNTRY_LABELS = {
    "IDN": "Indonesia",
    "VNM": "Vietnam",
    "MEX": "Mexico",
    "USA": "United States",
    "EMU": "Euro Area",
    "CHN": "China",
}

INDICATORS = {
    "inflation": ("FP.CPI.TOTL.ZG", "Inflation"),
    "gdp_growth": ("NY.GDP.MKTP.KD.ZG", "GDP Growth"),
    "unemployment": ("SL.UEM.TOTL.ZS", "Unemployment"),
}


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


def _detect_countries(request_text: str) -> List[str]:
    low = str(request_text or "").lower()
    found: List[str] = []
    for name, code in COUNTRY_CODES.items():
        if name in low and code not in found:
            found.append(code)
    return found or ["IDN", "VNM", "MEX"]


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _latest_record(records: Any) -> Dict[str, Any]:
    best_year = -1
    best_row: Dict[str, Any] = {}
    if not isinstance(records, list):
        return best_row
    for row in records:
        if not isinstance(row, dict):
            continue
        value = _safe_float(row.get("value"))
        if value is None:
            continue
        year_text = str(row.get("date") or "").strip()
        try:
            year = int(year_text)
        except Exception:
            continue
        if year > best_year:
            best_year = year
            best_row = row
    return best_row


def _fetch_indicator(ctx: Dict[str, Any], country_code: str, indicator_code: str, timeout: float) -> Tuple[Dict[str, Any], List[str]]:
    payload = world_bank_run(
        ctx or {},
        {
            "country": country_code,
            "indicator": indicator_code,
            "per_page": 120,
            "timeout": timeout,
        },
    )
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else {}
    warnings = [str(x or "").strip() for x in (payload.get("warnings") or []) if str(x or "").strip()] if isinstance(payload, dict) else []
    record = _latest_record(data.get("records"))
    return record, warnings


def _fmt_pct(value: Any) -> str:
    num = _safe_float(value)
    return f"{num:.2f}%" if num is not None else "Unavailable"


def _country_note(inflation: float | None, gdp_growth: float | None, unemployment: float | None) -> str:
    notes: List[str] = []
    if inflation is not None:
        if inflation <= 4.0:
            notes.append("inflation relatively contained")
        elif inflation >= 7.0:
            notes.append("inflation elevated")
    if gdp_growth is not None:
        if gdp_growth >= 5.0:
            notes.append("growth remains strong")
        elif gdp_growth <= 1.0:
            notes.append("growth is soft")
    if unemployment is not None:
        if unemployment <= 4.5:
            notes.append("labor market looks comparatively tight")
        elif unemployment >= 8.0:
            notes.append("labor market slack is notable")
    return "; ".join(notes[:3]) if notes else "context mixed"


def _stability_score(inflation: float | None, gdp_growth: float | None, unemployment: float | None) -> float:
    score = 0.0
    if inflation is not None:
        score += max(0.0, 8.0 - abs(inflation - 3.0))
    if gdp_growth is not None:
        score += max(0.0, 6.0 - abs(gdp_growth - 4.0))
    if unemployment is not None:
        score += max(0.0, 8.0 - unemployment)
    return score


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(params or {})
    request_text = _request_text(ctx or {}, params)
    timeout = float(params.get("timeout") or 8.0)
    countries = _detect_countries(request_text)
    rows: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for country_code in countries:
        row: Dict[str, Any] = {"country_code": country_code, "country": COUNTRY_LABELS.get(country_code, country_code)}
        latest_years: List[int] = []
        for key, (indicator_code, _label) in INDICATORS.items():
            record, warn = _fetch_indicator(ctx or {}, country_code, indicator_code, timeout)
            warnings.extend(warn)
            value = _safe_float(record.get("value"))
            year_text = str(record.get("date") or "").strip()
            row[f"{key}_value"] = value
            row[f"{key}_year"] = year_text
            row[key] = _fmt_pct(value)
            if year_text.isdigit():
                latest_years.append(int(year_text))
        row["note"] = _country_note(row.get("inflation_value"), row.get("gdp_growth_value"), row.get("unemployment_value"))
        row["stability_score"] = _stability_score(row.get("inflation_value"), row.get("gdp_growth_value"), row.get("unemployment_value"))
        row["latest_year"] = str(max(latest_years)) if latest_years else ""
        rows.append(row)

    ranked = sorted(rows, key=lambda item: item.get("stability_score") or 0.0, reverse=True)
    most_stable = ranked[0]["country"] if ranked else "Unavailable"
    table_lines = [
        "| Country | Inflation | GDP Growth | Unemployment | Context |",
        "|---|---:|---:|---:|---|",
    ]
    for row in rows:
        table_lines.append(
            f"| {row['country']} | {row['inflation']} ({row.get('inflation_year') or 'n/a'}) | {row['gdp_growth']} ({row.get('gdp_growth_year') or 'n/a'}) | {row['unemployment']} ({row.get('unemployment_year') or 'n/a'}) | {row['note']} |"
        )
    summary = (
        f"Based on the latest available World Bank series used here, **{most_stable}** currently looks the most stable overall because it combines the strongest balance of inflation, growth, and labor-market conditions across this comparison set."
        if ranked else
        "World Bank comparison could not rank the countries because no usable records were returned."
    )
    final_answer = (
        "## World Bank Comparison\n\n"
        "Latest available World Bank indicator snapshots for the requested economies.\n\n"
        + "\n".join(table_lines)
        + "\n\n**Short Summary**\n"
        + summary
    )
    if warnings:
        final_answer += "\n\nWarnings: " + "; ".join(warnings[:4])
    return {
        "ok": True,
        "summary": final_answer,
        "text": final_answer,
        "final_answer": final_answer,
        "data": {"rows": rows, "ranked": ranked[:3], "warnings": warnings},
        "warnings": warnings,
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "custom",
    "label": "World Bank Compare Report",
    "description": "Fetch latest World Bank macro indicators and return a reviewer-ready country comparison table.",
    "permissions": PERMISSIONS,
    "metadata": {
        "version": _VERSION,
        "created_at": _CREATED_AT,
        "last_updated": _LAST_UPDATED,
        "dev_status": _DEV_STATUS,
        "required_capabilities": ["web_research", "content_authoring"],
        "output_mode": "text",
    },
    "params_schema": {
        "type": "object",
        "properties": {
            "request_text": {"type": "string"},
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "text": {"type": "string"},
            "query": {"type": "string"},
            "timeout": {"type": "number"},
        },
        "additionalProperties": True,
    },
}

