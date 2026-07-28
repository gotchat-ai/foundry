from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from ..external_data.imf import run as imf_run
    from ..external_data.world_bank import run as world_bank_run
except Exception:
    import importlib.util
    _EP = Path(__file__).resolve().parents[1] / "external_data"
    _IS = importlib.util.spec_from_file_location("custom_imf_api", _EP / "imf.py")
    _IM = importlib.util.module_from_spec(_IS)
    assert _IS is not None and _IS.loader is not None
    _IS.loader.exec_module(_IM)
    imf_run = _IM.run
    _WS = importlib.util.spec_from_file_location("custom_world_bank_api", _EP / "world_bank.py")
    _WM = importlib.util.module_from_spec(_WS)
    assert _WS is not None and _WS.loader is not None
    _WS.loader.exec_module(_WM)
    world_bank_run = _WM.run


NAME = "custom.imf_world_bank_macro_brief"
PERMISSIONS = [NAME, "custom.*", "external_data.imf", "external_data.world_bank", "external_data.*", "web.request"]
_CREATED_AT = "2026-06-25T00:00:00Z"
_LAST_UPDATED = "2026-06-28T00:08:00Z"
_VERSION = "1.2"
_DEV_STATUS = "tested"

IMF_COUNTRIES = [
    (("USA",), "United States"),
    (("EURO", "EU", "EUQ"), "Euro Area"),
    (("CHN",), "China"),
]
WB_COUNTRIES = {"USA": "USA", "EURO": "EMU", "EU": "EMU", "EUQ": "EMU", "CHN": "CHN"}


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


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _latest_year_value(node: Any) -> Tuple[str, float | None]:
    if isinstance(node, dict):
        year_pairs: List[Tuple[int, float]] = []
        for key, value in node.items():
            if isinstance(value, dict):
                nested_year, nested_value = _latest_year_value(value)
                if nested_year and nested_value is not None:
                    try:
                        year_pairs.append((int(nested_year), nested_value))
                    except Exception:
                        pass
                continue
            try:
                year = int(str(key))
            except Exception:
                continue
            num = _safe_float(value)
            if num is not None:
                year_pairs.append((year, num))
        if year_pairs:
            current_year = datetime.utcnow().year
            preferred = [item for item in year_pairs if current_year <= item[0] <= (current_year + 1)]
            if preferred:
                year, num = sorted(preferred, key=lambda item: item[0])[0]
                return str(year), num
            recent = [item for item in year_pairs if item[0] <= current_year]
            if recent:
                year, num = sorted(recent, key=lambda item: item[0])[-1]
                return str(year), num
            year, num = sorted(year_pairs, key=lambda item: item[0])[0]
            return str(year), num
    return "", None


def _extract_imf_indicator(payload: Any, indicator_code: str, country_code: str) -> Tuple[str, float | None]:
    if isinstance(payload, dict):
        indicator_node = payload.get("values")
        if isinstance(indicator_node, dict):
            indicator_node = indicator_node.get(indicator_code) or indicator_node.get(indicator_code.upper()) or indicator_node
            if isinstance(indicator_node, dict):
                country_node = indicator_node.get(country_code) or indicator_node.get(country_code.upper())
                if country_node is not None:
                    return _latest_year_value(country_node)
        for value in payload.values():
            year, num = _extract_imf_indicator(value, indicator_code, country_code)
            if year:
                return year, num
    return "", None


def _latest_world_bank(ctx: Dict[str, Any], country_code: str, indicator_code: str, timeout: float) -> Tuple[str, float | None, List[str]]:
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
    records = data.get("records") if isinstance(data.get("records"), list) else []
    latest_year = ""
    latest_val = None
    for row in records:
        if not isinstance(row, dict):
            continue
        num = _safe_float(row.get("value"))
        if num is None:
            continue
        year = str(row.get("date") or "").strip()
        if year.isdigit() and year >= latest_year:
            latest_year = year
            latest_val = num
    return latest_year, latest_val, warnings


def _fmt_pct(value: float | None) -> str:
    return f"{value:.2f}%" if value is not None else "Unavailable"


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(params or {})
    request_text = _request_text(ctx or {}, params)
    timeout = float(params.get("timeout") or 8.0)
    imf_timeout = max(2.5, min(timeout, 4.0))
    warnings: List[str] = []
    imf_codes = []
    for codes, _label in IMF_COUNTRIES:
        for code in codes:
            if code not in imf_codes:
                imf_codes.append(code)

    growth_data: Any = {}
    inflation_data: Any = {}
    world_bank_results: Dict[tuple[str, str], Tuple[str, float | None, List[str]]] = {}

    with ThreadPoolExecutor(max_workers=8) as pool:
        future_map = {
            pool.submit(imf_run, ctx or {}, {"indicator": "NGDP_RPCH", "countries": imf_codes, "timeout": imf_timeout}): ("imf", "growth"),
            pool.submit(imf_run, ctx or {}, {"indicator": "PCPIPCH", "countries": imf_codes, "timeout": imf_timeout}): ("imf", "inflation"),
        }
        for _codes, _label in IMF_COUNTRIES:
            wb_code = WB_COUNTRIES[_codes[0]]
            future_map[pool.submit(_latest_world_bank, ctx or {}, wb_code, "NY.GDP.MKTP.KD.ZG", timeout)] = ("wb", wb_code, "growth")
            future_map[pool.submit(_latest_world_bank, ctx or {}, wb_code, "FP.CPI.TOTL.ZG", timeout)] = ("wb", wb_code, "inflation")
        for future in as_completed(future_map):
            meta = future_map[future]
            kind = meta[0]
            try:
                result = future.result()
            except Exception as exc:
                warnings.append(f"request_failed:{exc}")
                continue
            if kind == "imf":
                payload = result if isinstance(result, dict) else {}
                warnings.extend([str(x or "").strip() for x in (payload.get("warnings") or []) if str(x or "").strip()])
                payload_data = (payload.get("data") or {}).get("payload") if isinstance(payload, dict) else {}
                if meta[1] == "growth":
                    growth_data = payload_data
                else:
                    inflation_data = payload_data
            else:
                wb_code = meta[1]
                indicator_name = meta[2]
                world_bank_results[(wb_code, indicator_name)] = result if isinstance(result, tuple) else ("", None, ["world_bank_result_invalid"])

    lines = ["## Macro Brief", ""]
    rows: List[Dict[str, Any]] = []
    for imf_codes_for_row, label in IMF_COUNTRIES:
        imf_growth_year, imf_growth, chosen_growth_code = "", None, ""
        for candidate_code in imf_codes_for_row:
            imf_growth_year, imf_growth = _extract_imf_indicator(growth_data, "NGDP_RPCH", candidate_code)
            if imf_growth_year:
                chosen_growth_code = candidate_code
                break
        imf_infl_year, imf_infl, chosen_infl_code = "", None, ""
        for candidate_code in imf_codes_for_row:
            imf_infl_year, imf_infl = _extract_imf_indicator(inflation_data, "PCPIPCH", candidate_code)
            if imf_infl_year:
                chosen_infl_code = candidate_code
                break
        wb_lookup_code = chosen_growth_code or chosen_infl_code or imf_codes_for_row[0]
        wb_code = WB_COUNTRIES[wb_lookup_code]
        wb_growth_year, wb_growth, wb_growth_warn = world_bank_results.get((wb_code, "growth"), ("", None, ["world_bank_growth_missing"]))
        wb_infl_year, wb_infl, wb_infl_warn = world_bank_results.get((wb_code, "inflation"), ("", None, ["world_bank_inflation_missing"]))
        warnings.extend(wb_growth_warn)
        warnings.extend(wb_infl_warn)
        aligned_bits: List[str] = []
        if imf_growth is not None and wb_growth is not None:
            if abs(imf_growth - wb_growth) <= 1.75:
                aligned_bits.append("growth appears broadly aligned")
            else:
                aligned_bits.append("World Bank growth looks more contextual than directly aligned with the IMF outlook")
        if imf_infl is not None and wb_infl is not None:
            if abs(imf_infl - wb_infl) <= 2.0:
                aligned_bits.append("inflation direction appears aligned")
            else:
                aligned_bits.append("World Bank inflation is better read as recent context")
        if not aligned_bits:
            aligned_bits.append("source alignment is limited because one side returned partial data")
        rows.append(
            {
                "economy": label,
                "imf_growth": imf_growth,
                "imf_growth_year": imf_growth_year,
                "imf_inflation": imf_infl,
                "imf_inflation_year": imf_infl_year,
                "wb_growth": wb_growth,
                "wb_growth_year": wb_growth_year,
                "wb_inflation": wb_infl,
                "wb_inflation_year": wb_infl_year,
                "alignment": "; ".join(aligned_bits),
            }
        )
    table_lines = [
        "| Economy | IMF Growth Outlook | IMF Inflation Outlook | World Bank Growth Context | World Bank Inflation Context | Source Read |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        table_lines.append(
            f"| {row['economy']} | {_fmt_pct(row['imf_growth'])} ({row.get('imf_growth_year') or 'n/a'}) | {_fmt_pct(row['imf_inflation'])} ({row.get('imf_inflation_year') or 'n/a'}) | {_fmt_pct(row['wb_growth'])} ({row.get('wb_growth_year') or 'n/a'}) | {_fmt_pct(row['wb_inflation'])} ({row.get('wb_inflation_year') or 'n/a'}) | {row['alignment']} |"
        )
    lines.extend(table_lines)
    lines.extend(["", "**Alignment and Context**"])
    for row in rows:
        lines.append(f"- {row['economy']}: {row['alignment']}.")
    final_answer = "\n".join(lines)
    if any("request_failed:" in str(w or "") for w in warnings):
        final_answer += "\n\nNote: One or more official upstream datasets did not respond in time in this environment, so unavailable IMF fields should be treated as transport gaps rather than economic conclusions."
    if warnings:
        final_answer += "\n\nWarnings: " + "; ".join(warnings[:4])
    return {
        "ok": True,
        "summary": final_answer,
        "text": final_answer,
        "final_answer": final_answer,
        "data": {"rows": rows, "warnings": warnings, "request_text": request_text},
        "warnings": warnings,
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "custom",
    "label": "IMF and World Bank Macro Brief",
    "description": "Compare IMF macro outlook indicators with World Bank context and return a short macro brief.",
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

