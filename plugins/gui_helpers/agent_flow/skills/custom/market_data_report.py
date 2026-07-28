from __future__ import annotations

import csv
import json
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from ..external_data._http import get_text
except Exception:
    import importlib.util
    from pathlib import Path as _HttpPath
    _HP = _HttpPath(__file__).resolve().parents[1] / "external_data" / "_http.py"
    _HS = importlib.util.spec_from_file_location("custom_market_data_http", _HP)
    _HM = importlib.util.module_from_spec(_HS)
    assert _HS is not None and _HS.loader is not None
    _HS.loader.exec_module(_HM)
    get_text = _HM.get_text

try:
    from ..external_data.yahoo_finance import run as yahoo_finance_run
except Exception:
    import importlib.util
    _P = Path(__file__).resolve().parents[1] / "external_data" / "yahoo_finance.py"
    _S = importlib.util.spec_from_file_location("custom_market_data_yahoo_finance", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    yahoo_finance_run = _M.run

NAME = "custom.market_data_report"
PERMISSIONS = [NAME, "custom.*", "external_data.yahoo_finance", "external_data.*", "web.request"]
_CREATED_AT = "2026-06-24T00:00:00Z"
_LAST_UPDATED = "2026-06-28T19:28:00Z"
_VERSION = "1.5"
_DEV_STATUS = "tested"
FALLBACK_TICKERS = ["NVDA", "AMD", "MSFT", "AAPL", "GOOGL", "AMZN"]
COMPANY_TICKERS = {
    "nvidia": "NVDA",
    "advanced micro devices": "AMD",
    "amd": "AMD",
    "microsoft": "MSFT",
    "apple": "AAPL",
    "alphabet": "GOOGL",
    "google": "GOOGL",
    "intel": "INTC",
    "amazon": "AMZN",
    "meta": "META",
    "tesla": "TSLA",
}


def _safe_float(value: Any) -> float:
    try:
        if isinstance(value, dict):
            raw = value.get("raw")
            if raw is not None and raw != "":
                return float(raw)
            fmt = str(value.get("fmt") or "").replace(",", "").strip()
            if fmt:
                mult = 1.0
                upper = fmt.upper()
                if upper.endswith("T"):
                    mult = 1_000_000_000_000.0
                    fmt = fmt[:-1]
                elif upper.endswith("B"):
                    mult = 1_000_000_000.0
                    fmt = fmt[:-1]
                elif upper.endswith("M"):
                    mult = 1_000_000.0
                    fmt = fmt[:-1]
                elif upper.endswith("K"):
                    mult = 1_000.0
                    fmt = fmt[:-1]
                return float(fmt) * mult
        if value is None or value == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ("request_text", "user_request", "request", "text", "prompt", "query"):
        val = str((params or {}).get(key) or "").strip()
        if val:
            return val
    for key in ("original_request", "user_text"):
        val = str((ctx or {}).get(key) or "").strip()
        if val:
            return val
    return ""


def _extract_requested_symbols(request_text: str) -> List[str]:
    out: List[str] = []
    seen = set()
    text = str(request_text or "")
    low = text.lower()
    for sym in re.findall(r"\(([A-Z][A-Z0-9.\-]{0,9})\)", text):
        value = str(sym or "").strip().upper()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    for sym in re.findall(r"\b([A-Z]{2,5})\b", text):
        value = str(sym or "").strip().upper()
        if value and value not in seen and value not in {"USD", "ETF", "ETD", "API"}:
            seen.add(value)
            out.append(value)
    for name, ticker in COMPANY_TICKERS.items():
        if name in low and ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return out


def _quote_rows(ctx: Dict[str, Any], symbols: List[str], timeout: float) -> Tuple[Dict[str, Dict[str, Any]], List[str], Dict[str, Any]]:
    if not symbols:
        return {}, ["symbols_required"], {}
    payload = yahoo_finance_run(ctx or {}, {"mode": "quote", "symbols": ",".join(symbols), "timeout": timeout})
    data = payload.get("data") if isinstance(payload, dict) else {}
    warnings = [str(x or "").strip() for x in (payload.get("warnings") or []) if str(x or "").strip()] if isinstance(payload, dict) else []
    quote_rows = data.get("quotes") if isinstance(data, dict) and isinstance(data.get("quotes"), list) else []
    out: Dict[str, Dict[str, Any]] = {}
    for row in quote_rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").strip().upper()
        if sym:
            out[sym] = row
    source_meta = {
        "source": str(data.get("source") or "").strip(),
        "url": str(data.get("url") or "").strip(),
        "symbol_count": len(quote_rows),
    }
    low_source = source_meta["source"].lower()
    if low_source.endswith("quote page"):
        warnings.append("yahoo_finance_quote_page_fallback")
    if "chart api fallback" in low_source:
        warnings.append("yahoo_finance_chart_fallback")
    return out, warnings, source_meta


def _fmt_price(value: Any) -> str:
    num = _safe_float(value)
    return f"{num:,.2f}" if num else "Unavailable"


def _fmt_large(value: Any) -> str:
    num = _safe_float(value)
    if num <= 0:
        return "Unavailable"
    if num >= 1_000_000_000_000:
        return f"{num / 1_000_000_000_000:.2f}T"
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.2f}B"
    if num >= 1_000_000:
        return f"{num / 1_000_000:.2f}M"
    return f"{num:,.0f}"


def _range_text(row: Dict[str, Any]) -> str:
    direct = row.get("fiftyTwoWeekRange")
    if isinstance(direct, dict):
        raw = str(direct.get("raw") or direct.get("fmt") or "").strip()
        if raw:
            return raw
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    low = _safe_float(row.get("fiftyTwoWeekLow"))
    high = _safe_float(row.get("fiftyTwoWeekHigh"))
    if low > 0 and high > 0:
        return f"{low:,.2f} to {high:,.2f}"
    return "Unavailable"


def _range_bounds(row: Dict[str, Any]) -> Tuple[float, float]:
    return _safe_float(row.get("fiftyTwoWeekLow")), _safe_float(row.get("fiftyTwoWeekHigh"))


def _row_validation_notes(row: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    notes: List[str] = []
    warnings: List[str] = []
    symbol = str(row.get("symbol") or "").strip().upper() or "ticker"
    price = _safe_float(row.get("regularMarketPrice") or row.get("postMarketPrice") or row.get("preMarketPrice"))
    market_cap = _safe_float(row.get("marketCap"))
    shares_outstanding = _safe_float(row.get("sharesOutstanding") or row.get("impliedSharesOutstanding"))
    low, high = _range_bounds(row)
    if price > 0 and low > 0 and high > 0 and (price < low * 0.95 or price > high * 1.05):
        warnings.append(f"{symbol.lower()}_price_outside_reported_52_week_range")
    if price > 0 and market_cap > 0 and shares_outstanding > 0:
        implied_price = market_cap / shares_outstanding
        gap = abs(implied_price - price) / price if price else 0.0
        if gap <= 0.08:
            notes.append(f"{symbol} price and market cap are internally consistent with share count.")
        elif gap >= 0.25:
            warnings.append(f"{symbol.lower()}_price_market_cap_share_count_mismatch")
    return notes, warnings


def _validation_summary(raw_rows: List[Dict[str, Any]]) -> Tuple[str, List[str]]:
    notes: List[str] = []
    warnings: List[str] = []
    seen_notes = set()
    seen_warnings = set()
    for raw_row in raw_rows or []:
        if not isinstance(raw_row, dict):
            continue
        row_notes, row_warnings = _row_validation_notes(raw_row)
        for note in row_notes:
            if note not in seen_notes:
                seen_notes.add(note)
                notes.append(note)
        for warning in row_warnings:
            if warning not in seen_warnings:
                seen_warnings.add(warning)
                warnings.append(warning)
    for warning in list(warnings):
        low_warning = str(warning or '').lower()
        if ':price_reverted_to_chart_last_close' in low_warning:
            symbol = str(warning).split(':', 1)[0].upper()
            note = f"{symbol} fallback quote price disagreed with the chart series, so the price was reverted to the latest chart close."
            if note not in seen_notes:
                seen_notes.add(note)
                notes.append(note)
        elif ':price_outside_range_reverted_to_chart_last_close' in low_warning:
            symbol = str(warning).split(':', 1)[0].upper()
            note = f"{symbol} fallback quote price fell outside the reported 52-week range, so the price was reverted to the latest chart close."
            if note not in seen_notes:
                seen_notes.add(note)
                notes.append(note)
    return " ".join(notes).strip(), warnings


def _market_timestamp_text(row: Dict[str, Any]) -> str:
    stamp = _safe_float(row.get("regularMarketTime") or row.get("postMarketTime") or row.get("preMarketTime"))
    if stamp <= 0:
        return ""
    try:
        dt = datetime.fromtimestamp(int(stamp), tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return ""


def _should_keep_market_cap_without_quote_api(row: Dict[str, Any], market_cap_conf: str) -> bool:
    conf = str(market_cap_conf or '').strip().lower()
    if conf in {'estimated', 'cross_checked'}:
        return True
    market_cap = _safe_float(row.get('marketCap'))
    price = _safe_float(row.get('regularMarketPrice') or row.get('postMarketPrice') or row.get('preMarketPrice'))
    shares = _safe_float(row.get('sharesOutstanding') or row.get('impliedSharesOutstanding'))
    if market_cap <= 0 or price <= 0 or shares <= 0:
        return False
    implied_price = market_cap / shares if shares else 0.0
    if implied_price <= 0:
        return False
    gap = abs(implied_price - price) / price if price else 1.0
    return gap <= 0.12


def _apply_confidence_degradation(row: Dict[str, Any], warnings: List[str], *, fallback_snapshot: bool = False, quote_api_unauthorized: bool = False) -> Dict[str, Any]:
    out = dict(row or {})
    symbol = str(out.get('symbol') or '').strip().upper() or 'ticker'
    confidence = out.get('_field_confidence') if isinstance(out.get('_field_confidence'), dict) else {}
    price_conf = str(confidence.get('price') or '').strip().lower()
    volume_conf = str(confidence.get('averageVolume') or '').strip().lower()
    market_cap_conf = str(confidence.get('marketCap') or '').strip().lower()
    if fallback_snapshot and quote_api_unauthorized:
        if price_conf not in {'cross_checked', 'chart_only', 'corrected'}:
            out['regularMarketPrice'] = None
            out['postMarketPrice'] = None
            out['preMarketPrice'] = None
            warnings.append(f'{symbol}:price_unavailable_without_quote_api')
        if not (out.get('fiftyTwoWeekRange') or (_safe_float(out.get('fiftyTwoWeekLow')) > 0 and _safe_float(out.get('fiftyTwoWeekHigh')) > 0)):
            out['fiftyTwoWeekRange'] = None
            out['fiftyTwoWeekLow'] = None
            out['fiftyTwoWeekHigh'] = None
            warnings.append(f'{symbol}:range_unavailable_without_quote_api')
        if _should_keep_market_cap_without_quote_api(out, market_cap_conf):
            warnings.append(f'{symbol}:market_cap_snapshot_kept_without_quote_api')
        else:
            out['marketCap'] = None
            warnings.append(f'{symbol}:market_cap_unavailable_without_quote_api')
    elif price_conf == 'quote_page_only':
        out['regularMarketPrice'] = None
        warnings.append(f'{symbol}:price_low_confidence_unavailable')
    if volume_conf == 'quote_page_only':
        out['averageDailyVolume3Month'] = None
        out['averageDailyVolume10Day'] = None
        out['regularMarketVolume'] = None
        warnings.append(f'{symbol}:average_volume_low_confidence_unavailable')
    if (not quote_api_unauthorized) and market_cap_conf == 'quote_page_only':
        out['marketCap'] = None
        warnings.append(f'{symbol}:market_cap_low_confidence_unavailable')
    return out


def _confidence_notes(raw_rows: List[Dict[str, Any]]) -> str:
    notes: List[str] = []
    seen = set()
    for raw in raw_rows or []:
        if not isinstance(raw, dict):
            continue
        symbol = str(raw.get('symbol') or '').strip().upper() or 'ticker'
        conf = raw.get('_field_confidence') if isinstance(raw.get('_field_confidence'), dict) else {}
        price_conf = str(conf.get('price') or '').strip().lower()
        if price_conf == 'cross_checked':
            note = f'{symbol} fallback price was cross-checked between chart and quote-page sources.'
        elif price_conf == 'chart_only':
            note = f'{symbol} fallback price came only from the chart source.'
        elif price_conf == 'quote_page_only':
            note = f'{symbol} fallback price relied only on quote-page data and may be omitted when confidence is too low.'
        elif price_conf == 'corrected':
            note = f'{symbol} fallback price was corrected to the chart close because the fallback sources disagreed.'
        else:
            note = ''
        if note and note not in seen:
            seen.add(note)
            notes.append(note)
    return ' '.join(notes[:3]).strip()


def _has_quote_api_unauthorized(warnings: List[str]) -> bool:
    return any(str(w or '').strip().lower() == 'yahoo_finance_quote_api_unauthorized' for w in (warnings or []))


def _is_fallback_source(source_meta: Dict[str, Any], warnings: List[str]) -> bool:
    source = str((source_meta or {}).get("source") or "").strip().lower()
    if 'fallback' in source or 'quote page enrichment' in source or 'quote page' in source:
        return True
    return any('fallback' in str(w or '').lower() for w in (warnings or []))


def _requires_verified_current_price(request_text: str) -> bool:
    low = str(request_text or '').strip().lower()
    if not low:
        return False
    phrases = (
        'most current price',
        'current price',
        'latest price',
        'live price',
        'real-time price',
        'realtime price',
        'up-to-date price',
        'today price',
        "today's price",
    )
    return any(phrase in low for phrase in phrases)


def _display_price(value: Any, *, unverified: bool = False) -> str:
    base = _fmt_price(value)
    if base == 'Unavailable':
        return base
    return f"{base}*" if unverified else base


def _chart_close_reference(row: Dict[str, Any]) -> float:
    return _safe_float(row.get('chartLastClose') or row.get('regularMarketPreviousClose'))


def _display_price_payload(row: Dict[str, Any], warnings: List[str], *, fallback_snapshot: bool = False, quote_api_unauthorized: bool = False, require_verified_current_price: bool = False) -> Dict[str, Any]:
    symbol = str(row.get('symbol') or '').strip().upper() or 'ticker'
    live_price = _safe_float(row.get('regularMarketPrice') or row.get('postMarketPrice') or row.get('preMarketPrice'))
    chart_close = _chart_close_reference(row)
    price_conf = _field_confidence_text(row, 'price')
    if fallback_snapshot and quote_api_unauthorized:
        if live_price > 0 and price_conf in {'cross_checked', 'corrected'}:
            warnings.append(f'{symbol}:using_cross_checked_snapshot_price_without_quote_api')
            return {
                'value': live_price,
                'basis': 'current_snapshot',
                'label': 'latest Yahoo snapshot price',
                'unverified': True,
            }
        if chart_close > 0:
            if require_verified_current_price:
                warnings.append(f'{symbol}:verified_current_price_unavailable_using_chart_close_reference')
            else:
                warnings.append(f'{symbol}:using_chart_close_reference_without_quote_api')
            return {
                'value': chart_close,
                'basis': 'chart_close',
                'label': 'latest chart close',
                'unverified': True,
            }
        if require_verified_current_price:
            warnings.append(f'{symbol}:verified_current_price_required_but_unavailable')
            return {
                'value': 0.0,
                'basis': 'unavailable',
                'label': 'current price unavailable',
                'unverified': False,
            }
    return {
        'value': live_price,
        'basis': 'price',
        'label': 'current price' if live_price > 0 else 'price',
        'unverified': bool(fallback_snapshot),
    }


def _field_confidence_text(row: Dict[str, Any], field: str) -> str:
    conf = row.get('_field_confidence') if isinstance(row.get('_field_confidence'), dict) else {}
    if not conf and isinstance(row.get('field_confidence'), dict):
        conf = row.get('field_confidence')
    mapping = {
        'price': str(conf.get('price') or '').strip().lower(),
        'average_volume': str(conf.get('averageVolume') or '').strip().lower(),
        'market_cap': str(conf.get('marketCap') or '').strip().lower(),
    }
    return mapping.get(str(field or '').strip().lower(), '')


def _source_note(source_meta: Dict[str, Any], rows: List[Dict[str, Any]]) -> str:
    bits: List[str] = []
    source = str((source_meta or {}).get("source") or "").strip()
    if source:
        bits.append(f"Source: {source}.")
    times = [str(row.get("market_time") or "").strip() for row in rows if str(row.get("market_time") or "").strip()]
    if times:
        bits.append(f"Latest market timestamp in this snapshot: {times[0]}.")
    if "chart api + quote page enrichment" in source.lower():
        bits.append("Yahoo public quote API was unavailable during this request, so this response used Yahoo fallback snapshot sources and withheld any requested fields that could not be trusted for a safe investor-style comparison.")
    elif "chart api fallback" in source.lower():
        bits.append("Yahoo public quote API was unavailable during this request, so these values came from the Yahoo chart API snapshot rather than the main quote endpoint.")
    elif "quote page" in source.lower():
        bits.append("Yahoo public quote API was unavailable during this request, so these values came from the public quote-page fallback and should be treated as a live snapshot rather than a guaranteed audited feed.")
    return " ".join(bits).strip()


def _secondary_close_price(symbol: str, timeout: float) -> float:
    ticker = str(symbol or '').strip().lower()
    if not ticker:
        return 0.0
    urls = [
        f'https://stooq.com/q/l/?s={ticker}.us&i=d',
        f'https://stooq.com/q/l/?s={ticker}&i=d',
    ]
    for url in urls:
        try:
            row = get_text(url, {'timeout': max(1.0, min(float(timeout or 8.0), 6.0)), 'accept': 'text/csv,text/plain;q=0.9,*/*;q=0.8', 'user_agent': 'Mozilla/5.0'})
            text = str(row.get('text') or '').strip()
            if not text or text.lower().startswith('<!doctype html'):
                continue
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if len(lines) < 2:
                continue
            parts = [p.strip() for p in lines[1].split(',')]
            if len(parts) < 5:
                continue
            close_text = parts[4]
            value = _safe_float(close_text)
            if value > 0:
                return value
        except Exception:
            continue
    return 0.0


def _apply_secondary_sanity_checks(rows: List[Dict[str, Any]], warnings: List[str], *, timeout: float, fallback_snapshot: bool = False, quote_api_unauthorized: bool = False) -> None:
    if not fallback_snapshot or not quote_api_unauthorized:
        return
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get('symbol') or '').strip().upper()
        row['secondary_price_verified'] = False
        row['secondary_price_available'] = False
        reference_price = _safe_float(row.get('price')) or _safe_float(row.get('reference_price'))
        if not symbol or reference_price <= 0:
            continue
        secondary_close = _secondary_close_price(symbol, timeout)
        if secondary_close <= 0:
            warnings.append(f'{symbol}:secondary_source_verification_unavailable')
            continue
        row['secondary_price_available'] = True
        drift = abs(reference_price - secondary_close) / secondary_close if secondary_close else 0.0
        if drift >= 0.35:
            row['price'] = 0.0
            row['market_cap'] = 0.0
            row['fifty_two_week_range'] = 'Unavailable'
            warnings.append(f'{symbol}:secondary_source_snapshot_mismatch_withheld')
            continue
        row['secondary_price_verified'] = True


def _enforce_verified_compare_snapshot_rules(
    rows: List[Dict[str, Any]],
    warnings: List[str],
    *,
    require_verified_current_price: bool = False,
    fallback_snapshot: bool = False,
    quote_api_unauthorized: bool = False,
) -> None:
    if not (require_verified_current_price and fallback_snapshot and quote_api_unauthorized):
        return
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get('symbol') or '').strip().upper() or 'ticker'
        if bool(row.get('secondary_price_verified')):
            continue
        if _safe_float(row.get('price')) > 0:
            row['price'] = 0.0
            row['price_basis'] = 'unavailable'
            row['price_label'] = 'current price unavailable'
            row['price_unverified'] = False
            warnings.append(f'{symbol}:verified_current_price_required_but_unavailable')
        market_cap_conf = _field_confidence_text(row, 'market_cap')
        if market_cap_conf in {'quote_page_only', 'cross_checked'} and _safe_float(row.get('market_cap')) > 0:
            row['market_cap'] = 0.0
            warnings.append(f'{symbol}:comparison_fields_withheld_without_quote_api')


def _warnings_text(warnings: List[str]) -> str:
    parts: List[str] = []
    active_warnings = {str(w or '').lower() for w in (warnings or []) if str(w or '').strip()}
    for warning in warnings or []:
        low = str(warning or '').lower()
        if not low:
            continue
        if low == 'yahoo_finance_chart_fallback':
            parts.append('Yahoo public quote API was unavailable, so this answer relied on Yahoo chart and quote-page fallback sources and should be treated as a chart snapshot rather than a fully verified live quote feed.')
            continue
        if low == 'yahoo_finance_quote_api_unauthorized':
            parts.append('Yahoo public quote API returned unauthorized in this environment, so exact live quote verification was not available.')
            continue
        if low.endswith(':price_reverted_to_chart_last_close'):
            symbol = str(warning).split(':', 1)[0].upper()
            parts.append(f'{symbol} fallback quote price was corrected back to the latest chart close because the fallback sources disagreed.')
            continue
        if low.endswith(':price_outside_range_reverted_to_chart_last_close'):
            symbol = str(warning).split(':', 1)[0].upper()
            parts.append(f'{symbol} fallback quote price was corrected because it fell outside the reported 52-week range.')
            continue
        if low.endswith(':market_cap_estimated_from_shares'):
            symbol = str(warning).split(':', 1)[0].upper()
            parts.append(f'{symbol} market cap was estimated from shares outstanding and the latest available price because Yahoo fallback data omitted the field.')
            continue
        if low.endswith(':price_low_confidence_unavailable'):
            symbol = str(warning).split(':', 1)[0].upper()
            parts.append(f'{symbol} price was withheld because only a low-confidence quote-page fallback value was available.')
            continue
        if low.endswith(':average_volume_low_confidence_unavailable'):
            symbol = str(warning).split(':', 1)[0].upper()
            parts.append(f'{symbol} average volume was withheld because only a low-confidence quote-page fallback value was available.')
            continue
        if low.endswith(':market_cap_low_confidence_unavailable'):
            symbol = str(warning).split(':', 1)[0].upper()
            parts.append(f"{symbol} market cap was withheld because only a quote-page fallback value was available while Yahoo's main quote API was unavailable.")
            continue
        if low.endswith(':price_unavailable_without_quote_api'):
            symbol = str(warning).split(':', 1)[0].upper()
            parts.append(f"{symbol} price was withheld because Yahoo's main quote API was unavailable and fallback snapshot pricing could not be verified as a safe current quote.")
            continue
        if low.endswith(':market_cap_unavailable_without_quote_api'):
            symbol = str(warning).split(':', 1)[0].upper()
            parts.append(f"{symbol} market cap was withheld because Yahoo's main quote API was unavailable and fallback snapshot market-cap data could not be internally validated.")
            continue
        if low.endswith(':market_cap_snapshot_kept_without_quote_api'):
            symbol = str(warning).split(':', 1)[0].upper()
            if f"{symbol.lower()}:comparison_fields_withheld_without_quote_api" not in active_warnings and f"{symbol.lower()}:current_price_unverified_in_compare_withheld" not in active_warnings:
                parts.append(f"{symbol} market cap was kept from Yahoo fallback snapshot data because it remained internally consistent with the displayed price and share-count fields.")
            continue
        if low.endswith(':range_unavailable_without_quote_api'):
            symbol = str(warning).split(':', 1)[0].upper()
            parts.append(f"{symbol} 52-week range was withheld because Yahoo's main quote API was unavailable and fallback range values were not trusted as a safe investor-style comparison field.")
            continue
        if low.endswith(':secondary_source_snapshot_mismatch_withheld') or low.endswith(':secondary_source_price_mismatch_withheld'):
            symbol = str(warning).split(':', 1)[0].upper()
            parts.append(f'{symbol} fallback price, 52-week range, and market cap were withheld because Yahoo snapshot data disagreed sharply with a secondary public market source in this environment.')
            continue
        if low.endswith(':secondary_source_verification_unavailable'):
            symbol = str(warning).split(':', 1)[0].upper()
            parts.append(f'{symbol} fallback current-price verification could not be confirmed from a secondary public market source in this environment.')
            continue
        if low.endswith(':using_cross_checked_snapshot_price_without_quote_api'):
            symbol = str(warning).split(':', 1)[0].upper()
            if f"{symbol.lower()}:verified_current_price_required_but_unavailable" not in active_warnings and f"{symbol.lower()}:current_price_unverified_in_compare_withheld" not in active_warnings:
                parts.append(f"{symbol} price is shown from Yahoo fallback snapshot sources because the live quote API was unavailable; the value was cross-checked within Yahoo's public fallback sources but is still not a fully verified live quote.")
            continue
        if low.endswith(':current_price_unverified_in_compare_snapshot_used'):
            symbol = str(warning).split(':', 1)[0].upper()
            parts.append(f"{symbol} price is shown from the strongest available Yahoo fallback snapshot in this environment, so the displayed value should be treated as an unverified current-price reference rather than a fully confirmed live quote.")
            continue
        if low.endswith(':current_price_unverified_in_compare_withheld'):
            symbol = str(warning).split(':', 1)[0].upper()
            parts.append(f'{symbol} current price was withheld because the request required a current investor-style comparison and no safe latest snapshot price could be retained in this environment.')
            continue
        if low.endswith(':using_chart_close_reference_without_quote_api'):
            symbol = str(warning).split(':', 1)[0].upper()
            parts.append(f"{symbol} price is shown as the latest chart close reference because Yahoo's main quote API was unavailable, so a safe current quote could not be verified.")
            continue
        if low.endswith(':verified_current_price_required_but_unavailable'):
            symbol = str(warning).split(':', 1)[0].upper()
            parts.append(f"{symbol} current price was withheld because the request required a current price, but Yahoo's main quote API was unavailable in this environment.")
            continue
        if low.endswith(':comparison_fields_withheld_without_quote_api'):
            symbol = str(warning).split(':', 1)[0].upper()
            parts.append(f"{symbol} 52-week range and market cap were withheld because Yahoo's main quote API was unavailable and those comparison fields could not be independently verified in this environment.")
            continue
        if low.startswith('chart_quote_failed:'):
            symbol = str(warning).split(':', 2)[1].upper() if ':' in str(warning) else 'ticker'
            parts.append(f'Chart fallback retrieval failed for {symbol}.')
            continue
        if low.startswith('html_quote_failed:'):
            symbol = str(warning).split(':', 2)[1].upper() if ':' in str(warning) else 'ticker'
            parts.append(f'Quote-page fallback retrieval failed for {symbol}.')
            continue
        if low.startswith('quote_fallback_missing:'):
            symbol = str(warning).split(':', 1)[1].upper() if ':' in str(warning) else 'ticker'
            parts.append(f'No fallback quote data was available for {symbol}.')
            continue
    unique: List[str] = []
    seen = set()
    for part in parts:
        if part not in seen:
            seen.add(part)
            unique.append(part)
    return ' '.join(unique[:6]).strip()


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


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(params or {})
    request_text = _request_text(ctx or {}, params)
    timeout = float(params.get("timeout") or 8.0)
    top_n = max(2, min(int(params.get("top_n") or 10), 10))
    explicit_symbols = _extract_requested_symbols(request_text)
    compare_mode = len(explicit_symbols) >= 2 and bool(re.search(r"\b(compare|versus|vs\.?|comparison)\b", request_text, flags=re.IGNORECASE))
    require_verified_current_price = _requires_verified_current_price(request_text)
    symbols = explicit_symbols[:top_n] if explicit_symbols else FALLBACK_TICKERS[:top_n]
    quotes, warnings, source_meta = _quote_rows(ctx or {}, symbols, timeout)
    fallback_snapshot = _is_fallback_source(source_meta, warnings)
    quote_api_unauthorized = _has_quote_api_unauthorized(warnings)
    raw_rows: List[Dict[str, Any]] = []
    rows = []
    for symbol in symbols:
        row = _apply_confidence_degradation(
            quotes.get(symbol) or {},
            warnings,
            fallback_snapshot=fallback_snapshot,
            quote_api_unauthorized=quote_api_unauthorized,
        )
        raw_rows.append(row)
        price_payload = _display_price_payload(
            row,
            warnings,
            fallback_snapshot=fallback_snapshot,
            quote_api_unauthorized=quote_api_unauthorized,
            require_verified_current_price=require_verified_current_price,
        )
        rows.append({
            "symbol": symbol,
            "name": str(row.get("shortName") or row.get("longName") or symbol),
            "price": _safe_float(price_payload.get("value")),
            "price_basis": str(price_payload.get("basis") or "price"),
            "price_label": str(price_payload.get("label") or "price"),
            "price_unverified": bool(price_payload.get("unverified")),
            "reference_price": _chart_close_reference(row) or _safe_float(row.get("regularMarketPrice") or row.get("postMarketPrice") or row.get("preMarketPrice")),
            "fifty_two_week_range": _range_text(row),
            "market_cap": _safe_float(row.get("marketCap")),
            "average_volume": _safe_float(row.get("averageDailyVolume3Month") or row.get("averageDailyVolume10Day") or row.get("regularMarketVolume")),
            "market_time": _market_timestamp_text(row),
            "field_confidence": row.get("_field_confidence") if isinstance(row.get("_field_confidence"), dict) else {},
        })
    _apply_secondary_sanity_checks(rows, warnings, timeout=timeout, fallback_snapshot=fallback_snapshot, quote_api_unauthorized=quote_api_unauthorized)
    _enforce_verified_compare_snapshot_rules(
        rows,
        warnings,
        require_verified_current_price=require_verified_current_price,
        fallback_snapshot=fallback_snapshot,
        quote_api_unauthorized=quote_api_unauthorized,
    )
    if compare_mode and fallback_snapshot and quote_api_unauthorized and require_verified_current_price:
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get('symbol') or 'ticker').upper()
            if not bool(row.get('secondary_price_verified')):
                if _safe_float(row.get('price')) > 0:
                    warnings.append(f'{symbol}:current_price_unverified_in_compare_snapshot_used')
                else:
                    warnings.append(f'{symbol}:current_price_unverified_in_compare_withheld')
            if _safe_float(row.get('price')) <= 0:
                warnings.append(f"{symbol}:comparison_fields_still_partial_without_quote_api")
    validation_note, validation_warnings = _validation_summary(raw_rows)
    confidence_note = _confidence_notes(raw_rows)
    warnings.extend(validation_warnings)
    warning_text = _warnings_text(warnings)
    any_unverified_prices = any(bool(row.get('price_unverified')) and _safe_float(row.get('price')) > 0 for row in rows)
    any_snapshot_prices = any(str(row.get('price_basis') or '') == 'current_snapshot' for row in rows)
    if fallback_snapshot and quote_api_unauthorized:
        if any_unverified_prices and any_snapshot_prices:
            price_header = 'Yahoo Snapshot Price*'
        else:
            price_header = 'Latest Chart Close*' if any_unverified_prices else 'Current Price'
    elif fallback_snapshot:
        price_header = 'Yahoo Chart Snapshot Price*'
    else:
        price_header = 'Current Price'
    if compare_mode:
        table_lines = [
            f"| Ticker | {price_header} | 52-Week Range | Market Cap | Average Volume |",
            "|---|---:|---|---:|---:|",
        ]
        for row in rows[:2]:
            table_lines.append(
                f"| {row['symbol']} | {_display_price(row['price'], unverified=bool(row.get('price_unverified')))} | {row['fifty_two_week_range']} | {_fmt_large(row['market_cap'])} | {_fmt_large(row['average_volume'])} |"
            )
        strict_compare_withheld = bool(compare_mode and fallback_snapshot and quote_api_unauthorized and require_verified_current_price and all(_safe_float(row.get('price')) <= 0 for row in rows[:2]))
        summary_bits = []
        if fallback_snapshot and quote_api_unauthorized:
            if require_verified_current_price:
                if any_snapshot_prices:
                    summary_bits.append("Yahoo's main quote API was unavailable during this request, so exact live quote verification was not possible. This response uses the strongest available Yahoo fallback snapshot price where it could be retained safely and withholds only fields that still could not be trusted for a current investor-style comparison.")
                else:
                    summary_bits.append("Yahoo's main quote API was unavailable during this request, so exact live quote verification was not possible. This response shows the latest available Yahoo chart-close reference where it could be retained safely and withholds only fields that still could not be trusted for a current investor-style comparison.")
            else:
                summary_bits.append("Yahoo's main quote API was unavailable during this request, so exact live quote verification was not possible. This response uses the latest Yahoo fallback snapshot reference where available and withholds fields that could not be trusted for a safe investor-style comparison.")
        elif fallback_snapshot:
            summary_bits.append("Yahoo's main quote API was unavailable during this request, so exact live quote verification was not possible. This response used Yahoo fallback snapshot sources and withheld only fields that could not be trusted for a safe investor-style comparison.")
        usable_compare = len(rows) >= 2 and any((left := rows[0]).get(k) and (right := rows[1]).get(k) for k in ('market_cap', 'average_volume', 'price'))
        if usable_compare:
            left, right = rows[0], rows[1]
            if left.get("market_cap") and right.get("market_cap"):
                bigger = left if left["market_cap"] >= right["market_cap"] else right
                if fallback_snapshot:
                    summary_bits.append(f"In this fallback snapshot, {bigger['symbol']} appears larger by market cap.")
                else:
                    summary_bits.append(f"{bigger['symbol']} currently has the larger market cap.")
            if left.get("price") and right.get("price"):
                pricier = left if left["price"] >= right["price"] else right
                if fallback_snapshot and quote_api_unauthorized:
                    if any_snapshot_prices:
                        summary_bits.append(f"In this fallback snapshot view, {pricier['symbol']} has the higher displayed Yahoo snapshot price.")
                    else:
                        summary_bits.append(f"In this fallback view, {pricier['symbol']} has the higher latest chart-close reference price.")
                elif fallback_snapshot:
                    summary_bits.append(f"In this fallback snapshot, {pricier['symbol']} is trading at the higher share price.")
                else:
                    summary_bits.append(f"{pricier['symbol']} is trading at the higher share price.")
            if left.get("average_volume") and right.get("average_volume"):
                heavier = left if left["average_volume"] >= right["average_volume"] else right
                if fallback_snapshot:
                    summary_bits.append(f"In this fallback snapshot, {heavier['symbol']} appears to have the higher average volume.")
                else:
                    summary_bits.append(f"{heavier['symbol']} is trading with the higher average volume.")
        source_note = _source_note(source_meta, rows[:2])
        final_answer = (
            "## Investor Comparison\n\n"
            + "\n".join(table_lines)
            + "\n\n**Plain-Language Summary**\n"
            + " ".join(summary_bits or (["This comparison used Yahoo fallback snapshot sources and withheld any requested fields that could not be trusted for a safe investor-style comparison."] if fallback_snapshot else ["This comparison shows the requested current price, 52-week range, market cap, and average volume for the selected tickers."]))
            + ("\n\n**Source Context**\n" + source_note if source_note else "")
            + ("\n\n**Validation**\n" + validation_note if validation_note and not strict_compare_withheld else "")
            + ("\n\n**Confidence Signals**\n" + confidence_note if confidence_note and not strict_compare_withheld else "")
            + ("\n\n**Warnings**\n" + warning_text if warning_text else "")
            + ("\n\n**Confidence Note**\nThis comparison used Yahoo fallback sources because the main quote API was unavailable. Treat it as a safe-failure snapshot that may withhold requested fields rather than as an execution-grade quote feed." if fallback_snapshot else "")
            + ("\n\n*Prices marked with an asterisk came from fallback snapshot sources and were not verified against Yahoo's main quote API.*" if fallback_snapshot and any_unverified_prices else "")
        )
    else:
        if fallback_snapshot and quote_api_unauthorized:
            price_col = 'Latest Chart Close*' if any_unverified_prices else 'Current Price'
        elif fallback_snapshot:
            price_col = 'Yahoo Chart Snapshot Price*'
        else:
            price_col = 'Price'
        table_lines = [
            f"| Rank | Symbol | Name | {price_col} | 52-Week Range | Market Cap | Avg Volume |",
            "|---:|---|---|---:|---|---:|---:|",
        ]
        for idx, row in enumerate(rows, start=1):
            table_lines.append(
                f"| {idx} | {row['symbol']} | {str(row['name']).replace('|', '/')} | {_display_price(row['price'], unverified=bool(row.get('price_unverified')))} | {row['fifty_two_week_range']} | {_fmt_large(row['market_cap'])} | {_fmt_large(row['average_volume'])} |"
            )
        final_answer = "## Market Data\n\n" + "\n".join(table_lines)
        source_note = _source_note(source_meta, rows)
        if source_note:
            final_answer += "\n\n**Source Context**\n" + source_note
        if validation_note:
            final_answer += "\n\n**Validation**\n" + validation_note
        if confidence_note:
            final_answer += "\n\n**Confidence Signals**\n" + confidence_note
        if warning_text:
            final_answer += "\n\n**Warnings**\n" + warning_text
        if fallback_snapshot:
            final_answer += "\n\n**Confidence Note**\nThis market table used Yahoo fallback sources because the main quote API was unavailable. Treat it as a directional snapshot rather than a fully verified live feed."
            if any_unverified_prices:
                final_answer += "\n\n*Prices marked with an asterisk came from fallback snapshot sources and were not verified against Yahoo's main quote API.*"

    uploads = _uploads_dir(ctx or {})
    uploads.mkdir(parents=True, exist_ok=True)
    stem = "market_data_report_" + str(int(time.time()))
    work_dir = uploads / stem
    work_dir.mkdir(parents=True, exist_ok=True)
    summary_csv = work_dir / "summary.csv"
    summary_json = work_dir / "summary.json"
    report_md = work_dir / "report.md"
    with summary_csv.open("w", newline="", encoding="utf-8") as fh:
        csv_fields = ["symbol", "name", "price", "fifty_two_week_range", "market_cap", "average_volume", "market_time"]
        writer = csv.DictWriter(fh, fieldnames=csv_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in csv_fields})
    summary_json.write_text(json.dumps({"rows": rows, "warnings": warnings, "source_meta": source_meta}, ensure_ascii=True, indent=2), encoding="utf-8")
    report_md.write_text(final_answer + "\n", encoding="utf-8")
    zip_path = uploads / (stem + ".zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for artifact in (summary_csv, summary_json, report_md):
            zf.write(artifact, arcname=artifact.name)
    return {
        "ok": True,
        "summary": final_answer,
        "text": final_answer,
        "final_answer": final_answer,
        "output_path": str(zip_path).replace("\\", "/"),
        "report_path": str(report_md).replace("\\", "/"),
        "data": {"rows": rows, "warnings": warnings, "zip_path": str(zip_path).replace("\\", "/")},
        "warnings": warnings,
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "custom",
    "label": "Market Data Report",
    "description": "Fetch current Yahoo Finance quote data and return a structured market summary or ticker comparison.",
    "permissions": PERMISSIONS,
    "metadata": {
        "version": _VERSION,
        "created_at": _CREATED_AT,
        "last_updated": _LAST_UPDATED,
        "dev_status": _DEV_STATUS,
        "required_capabilities": ["market_data", "web_research"],
        "output_mode": "text_or_file",
    },
    "params_schema": {
        "type": "object",
        "properties": {
            "request_text": {"type": "string"},
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "text": {"type": "string"},
            "query": {"type": "string"},
            "top_n": {"type": "integer", "minimum": 1, "maximum": 10},
            "timeout": {"type": "number"},
            "output_mode": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
