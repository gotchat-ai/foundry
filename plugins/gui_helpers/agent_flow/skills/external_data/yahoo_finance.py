from __future__ import annotations

import json
import re
from html import unescape
from typing import Any, Dict, List

try:
    from ._http import error_payload, get_json, get_text, int_param, text_param, url_with_query
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
    get_text = _M.get_text
    int_param = _M.int_param
    text_param = _M.text_param
    url_with_query = _M.url_with_query


NAME = "external_data.yahoo_finance"
PERMISSIONS = [NAME, "external_data.*", "web.request"]
QUOTE_HEADERS = {
    "Origin": "https://finance.yahoo.com",
    "Referer": "https://finance.yahoo.com/",
}


def _merge_source_tags(*values: Any) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        if isinstance(value, str):
            items = [value]
        elif isinstance(value, (list, tuple, set)):
            items = [str(x or '').strip() for x in value]
        else:
            items = []
        for item in items:
            tag = str(item or '').strip()
            if tag and tag not in seen:
                seen.add(tag)
                out.append(tag)
    return out


def _mark_field_source(row: Dict[str, Any], field: str, source: str) -> None:
    fields = row.get('_field_sources') if isinstance(row.get('_field_sources'), dict) else {}
    current = _merge_source_tags(fields.get(field), source)
    fields[field] = current
    row['_field_sources'] = fields
    row['_source_components'] = _merge_source_tags(row.get('_source_components'), source)


def _symbol_list(params: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    for key in ("symbols", "symbol_list", "tickers"):
        raw = params.get(key)
        if isinstance(raw, list):
            for item in raw:
                text = str(item or "").strip().upper()
                if text:
                    values.append(text)
        elif raw is not None:
            for item in re.split(r"[\s,;]+", str(raw or "").strip()):
                text = str(item or "").strip().upper()
                if text:
                    values.append(text)
    for key in ("symbol", "ticker"):
        text = str(params.get(key) or "").strip().upper()
        if text:
            values.append(text)
    out: List[str] = []
    seen = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _chart(params: Dict[str, Any]) -> Dict[str, Any]:
    symbol = text_param(params, "symbol", "ticker").upper()
    if not symbol:
        return {"ok": False, "data": {}, "warnings": ["symbol_required"]}
    interval = str(params.get("interval") or "1d").strip()
    range_value = str(params.get("range") or params.get("period") or "1mo").strip()
    include_events = str(params.get("include_events") or "div,splits").strip()
    url = url_with_query(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        {"interval": interval, "range": range_value, "events": include_events},
    )
    row = get_json(url, params, headers=QUOTE_HEADERS)
    payload = row.get("json") or {}
    result = (((payload.get("chart") or {}).get("result") or []) + [{}])[0]
    quote = (((result.get("indicators") or {}).get("quote") or []) + [{}])[0]
    timestamps = result.get("timestamp") or []
    prices: List[Dict[str, Any]] = []
    for idx, ts in enumerate(timestamps):
        prices.append({
            "timestamp": ts,
            "open": (quote.get("open") or [None] * len(timestamps))[idx] if idx < len(quote.get("open") or []) else None,
            "high": (quote.get("high") or [None] * len(timestamps))[idx] if idx < len(quote.get("high") or []) else None,
            "low": (quote.get("low") or [None] * len(timestamps))[idx] if idx < len(quote.get("low") or []) else None,
            "close": (quote.get("close") or [None] * len(timestamps))[idx] if idx < len(quote.get("close") or []) else None,
            "volume": (quote.get("volume") or [None] * len(timestamps))[idx] if idx < len(quote.get("volume") or []) else None,
        })
    limit = int_param(params, "limit", 60, 1, 1000)
    meta = result.get("meta") or {}
    return {
        "ok": True,
        "data": {
            "source": "Yahoo Finance chart API",
            "url": url,
            "symbol": symbol,
            "currency": meta.get("currency"),
            "exchange": meta.get("exchangeName"),
            "instrument_type": meta.get("instrumentType"),
            "regular_market_price": meta.get("regularMarketPrice"),
            "regular_market_time": meta.get("regularMarketTime"),
            "prices": prices[-limit:],
            "truncated": len(prices) > limit,
            "raw_meta": meta,
        },
        "warnings": [],
    }


def _search(params: Dict[str, Any]) -> Dict[str, Any]:
    query = text_param(params, "query", "q", "symbol", "ticker")
    if not query:
        return {"ok": False, "data": {}, "warnings": ["query_required"]}
    limit = int_param(params, "limit", 10, 1, 50)
    url = url_with_query("https://query2.finance.yahoo.com/v1/finance/search", {"q": query, "quotesCount": limit, "newsCount": 0})
    row = get_json(url, params, headers=QUOTE_HEADERS)
    payload = row.get("json") or {}
    quotes = payload.get("quotes") if isinstance(payload.get("quotes"), list) else []
    return {
        "ok": True,
        "data": {"source": "Yahoo Finance search API", "url": url, "query": query, "quotes": quotes[:limit]},
        "warnings": [],
    }


def _avg_recent_volume(points: List[Dict[str, Any]], trading_days: int = 63) -> float | None:
    vols: List[float] = []
    for row in reversed(points or []):
        vol = row.get('volume') if isinstance(row, dict) else None
        try:
            num = float(vol)
        except Exception:
            num = 0.0
        if num > 0:
            vols.append(num)
        if len(vols) >= max(1, int(trading_days or 63)):
            break
    if not vols:
        return None
    return sum(vols) / float(len(vols))


def _last_non_null_close(points: List[Dict[str, Any]]) -> float | None:
    for row in reversed(points or []):
        try:
            close_value = float((row or {}).get('close'))
        except Exception:
            close_value = 0.0
        if close_value > 0:
            return close_value
    return None


def _coerce_number(value: Any) -> float | None:
    if isinstance(value, dict):
        raw = value.get('raw')
        if raw not in (None, ''):
            return _coerce_number(raw)
        fmt = value.get('fmt')
        if fmt not in (None, ''):
            return _coerce_number(fmt)
        return None
    if value in (None, ''):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    parsed = _parse_compact_number(str(value or '').strip())
    if parsed is not None:
        return parsed
    try:
        return float(str(value or '').replace(',', '').strip())
    except Exception:
        return None


def _normalize_fallback_quote(item: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(item or {})
    integrity_warnings: List[str] = [str(x or '').strip() for x in (out.get('_integrity_warnings') or []) if str(x or '').strip()]
    symbol = str(out.get('symbol') or '').strip().upper() or 'ticker'
    chart_last_close = _coerce_number(out.get('chartLastClose'))
    current_price = _coerce_number(out.get('regularMarketPrice') or out.get('postMarketPrice') or out.get('preMarketPrice'))
    range_low = _coerce_number(out.get('fiftyTwoWeekLow')) or 0.0
    range_high = _coerce_number(out.get('fiftyTwoWeekHigh')) or 0.0
    if current_price and chart_last_close and chart_last_close > 0:
        drift = abs(current_price - chart_last_close) / chart_last_close if chart_last_close else 0.0
        if drift >= 0.35:
            out['regularMarketPrice'] = {'raw': chart_last_close, 'fmt': f'{chart_last_close:.2f}'}
            integrity_warnings.append(f'{symbol}:price_reverted_to_chart_last_close')
            current_price = chart_last_close
    if current_price and range_low > 0 and range_high > 0 and (current_price < range_low * 0.95 or current_price > range_high * 1.05):
        if chart_last_close and range_low * 0.95 <= chart_last_close <= range_high * 1.05:
            out['regularMarketPrice'] = {'raw': chart_last_close, 'fmt': f'{chart_last_close:.2f}'}
            integrity_warnings.append(f'{symbol}:price_outside_range_reverted_to_chart_last_close')
            current_price = chart_last_close
    if not out.get('marketCap'):
        shares_outstanding = _coerce_number(out.get('sharesOutstanding') or out.get('impliedSharesOutstanding'))
        price_for_cap = _coerce_number(out.get('regularMarketPrice') or out.get('postMarketPrice') or out.get('preMarketPrice'))
        if shares_outstanding and price_for_cap:
            estimated_market_cap = shares_outstanding * price_for_cap
            out['marketCap'] = {'raw': estimated_market_cap, 'fmt': f'{estimated_market_cap:,.0f}'}
            integrity_warnings.append(f'{symbol}:market_cap_estimated_from_shares')
            _mark_field_source(out, 'marketCap', 'estimated_from_shares')
    field_sources = out.get('_field_sources') if isinstance(out.get('_field_sources'), dict) else {}
    price_sources = set(_merge_source_tags(field_sources.get('regularMarketPrice'), field_sources.get('postMarketPrice'), field_sources.get('preMarketPrice'), field_sources.get('chartLastClose')))
    average_volume_sources = set(_merge_source_tags(field_sources.get('averageDailyVolume3Month'), field_sources.get('averageDailyVolume10Day'), field_sources.get('regularMarketVolume')))
    market_cap_sources = set(_merge_source_tags(field_sources.get('marketCap')))
    field_confidence: Dict[str, str] = {}
    if any(tag in price_sources for tag in ('chart_api', 'quote_page')):
        if any(flag in integrity_warnings for flag in (f'{symbol}:price_reverted_to_chart_last_close', f'{symbol}:price_outside_range_reverted_to_chart_last_close')):
            field_confidence['price'] = 'corrected'
        elif {'chart_api', 'quote_page'} <= price_sources:
            field_confidence['price'] = 'cross_checked'
        elif 'chart_api' in price_sources:
            field_confidence['price'] = 'chart_only'
        else:
            field_confidence['price'] = 'quote_page_only'
    if market_cap_sources:
        if 'estimated_from_shares' in market_cap_sources:
            field_confidence['marketCap'] = 'estimated'
        elif {'chart_api', 'quote_page'} <= market_cap_sources:
            field_confidence['marketCap'] = 'cross_checked'
        elif 'quote_page' in market_cap_sources:
            field_confidence['marketCap'] = 'quote_page_only'
        else:
            field_confidence['marketCap'] = 'chart_only'
    if average_volume_sources:
        if {'chart_api', 'quote_page'} <= average_volume_sources:
            field_confidence['averageVolume'] = 'cross_checked'
        elif 'chart_api' in average_volume_sources:
            field_confidence['averageVolume'] = 'chart_only'
        else:
            field_confidence['averageVolume'] = 'quote_page_only'
    if field_confidence:
        out['_field_confidence'] = field_confidence
    if integrity_warnings:
        out['_integrity_warnings'] = integrity_warnings
    return out


def _quote_from_chart(symbol: str, params: Dict[str, Any]) -> Dict[str, Any] | None:
    payload = _chart({**params, 'symbol': symbol, 'range': '1y', 'interval': '1d', 'limit': 260})
    data = payload.get('data') if isinstance(payload, dict) else {}
    meta = data.get('raw_meta') if isinstance(data, dict) else {}
    if not isinstance(meta, dict) or not meta:
        return None
    prices = data.get('prices') if isinstance(data.get('prices'), list) else []
    avg_recent = _avg_recent_volume(prices, trading_days=63)
    chart_last_close = _last_non_null_close(prices)
    out: Dict[str, Any] = {
        'symbol': symbol,
        'shortName': meta.get('shortName') or meta.get('longName') or symbol,
        'longName': meta.get('longName') or meta.get('shortName') or symbol,
        'regularMarketPrice': meta.get('regularMarketPrice') if meta.get('regularMarketPrice') not in (None, '') else chart_last_close,
        'regularMarketTime': meta.get('regularMarketTime'),
        'regularMarketPreviousClose': meta.get('previousClose'),
        'fiftyTwoWeekLow': meta.get('fiftyTwoWeekLow'),
        'fiftyTwoWeekHigh': meta.get('fiftyTwoWeekHigh'),
        'regularMarketVolume': meta.get('regularMarketVolume'),
        'chartLastClose': chart_last_close,
        '_source_components': ['chart_api'],
        '_field_sources': {
            'regularMarketPrice': ['chart_api'],
            'regularMarketTime': ['chart_api'],
            'regularMarketPreviousClose': ['chart_api'],
            'fiftyTwoWeekLow': ['chart_api'],
            'fiftyTwoWeekHigh': ['chart_api'],
            'regularMarketVolume': ['chart_api'],
            'chartLastClose': ['chart_api'],
        },
    }
    if avg_recent:
        out['averageDailyVolume3Month'] = {'raw': avg_recent, 'fmt': f'{avg_recent:,.0f}'}
        _mark_field_source(out, 'averageDailyVolume3Month', 'chart_api')
    if out.get('fiftyTwoWeekLow') and out.get('fiftyTwoWeekHigh'):
        out['fiftyTwoWeekRange'] = {
            'raw': f"{out['fiftyTwoWeekLow']} - {out['fiftyTwoWeekHigh']}",
            'fmt': f"{float(out['fiftyTwoWeekLow']):.2f} - {float(out['fiftyTwoWeekHigh']):.2f}",
        }
        _mark_field_source(out, 'fiftyTwoWeekRange', 'chart_api')
    return out


def _merge_quote_rows(primary: Dict[str, Any] | None, secondary: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not isinstance(primary, dict) and not isinstance(secondary, dict):
        return None
    if not isinstance(primary, dict):
        return dict(secondary or {})
    out = dict(primary)
    preferred_from_secondary = {
        'regularMarketPrice', 'postMarketPrice', 'preMarketPrice', 'marketCap', 'regularMarketVolume',
        'averageDailyVolume3Month', 'averageDailyVolume10Day',
        'regularMarketChange', 'postMarketChange'
    }
    if isinstance(secondary, dict):
        for key, value in secondary.items():
            if key in {'_field_sources', '_source_components'}:
                continue
            if key in preferred_from_secondary and value not in (None, '', 0, {}, []):
                out[key] = value
                continue
            if key not in out or out.get(key) in (None, '', 0, {}, []):
                out[key] = value
    out['_source_components'] = _merge_source_tags((primary or {}).get('_source_components'), (secondary or {}).get('_source_components'))
    merged_field_sources: Dict[str, Any] = {}
    for field_sources in ((primary or {}).get('_field_sources'), (secondary or {}).get('_field_sources')):
        if not isinstance(field_sources, dict):
            continue
        for field, tags in field_sources.items():
            merged_field_sources[field] = _merge_source_tags(merged_field_sources.get(field), tags)
    if merged_field_sources:
        out['_field_sources'] = merged_field_sources
    return out


def _summary_value_from_html(html: str, label: str) -> str:
    if not html or not label:
        return ""
    pattern = re.compile(re.escape(label) + r'.{0,300}?<fin-streamer[^>]*data-value="([^"]+)"', re.IGNORECASE | re.DOTALL)
    match = pattern.search(html)
    return str(match.group(1) or "").strip() if match else ""


def _parse_compact_number(value: str) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    mult = 1.0
    upper = text.upper()
    if upper.endswith("T"):
        mult = 1_000_000_000_000.0
        text = text[:-1]
    elif upper.endswith("B"):
        mult = 1_000_000_000.0
        text = text[:-1]
    elif upper.endswith("M"):
        mult = 1_000_000.0
        text = text[:-1]
    elif upper.endswith("K"):
        mult = 1_000.0
        text = text[:-1]
    try:
        return float(text) * mult
    except Exception:
        return None


def _visible_quote_page_values(html: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    patterns = {
        'regularMarketPrice': r'data-testid="qsp-price">\s*([0-9][0-9,]*\.?[0-9]*)',
        'postMarketPrice': r'data-testid="qsp-post-price">\s*([0-9][0-9,]*\.?[0-9]*)',
        'regularMarketChange': r'data-testid="qsp-price-change">\s*([+\-]?[0-9][0-9,]*\.?[0-9]*)',
        'postMarketChange': r'data-testid="qsp-post-price-change">\s*([+\-]?[0-9][0-9,]*\.?[0-9]*)',
    }
    for key, pat in patterns.items():
        m = re.search(pat, html, re.IGNORECASE)
        if not m:
            continue
        raw = _parse_compact_number(str(m.group(1) or ''))
        if raw is not None:
            out[key] = {'raw': raw, 'fmt': str(m.group(1) or '').strip()}
    return out


def _augment_quote_from_summary_html(item: Dict[str, Any], html: str) -> Dict[str, Any]:
    out = dict(item or {})
    out['_source_components'] = _merge_source_tags(out.get('_source_components'), 'quote_page')
    out['_field_sources'] = dict(out.get('_field_sources') or {})
    for field in (
        'regularMarketPrice', 'postMarketPrice', 'preMarketPrice', 'regularMarketChange', 'postMarketChange',
        'regularMarketVolume', 'averageDailyVolume3Month', 'averageDailyVolume10Day', 'marketCap',
        'fiftyTwoWeekRange', 'fiftyTwoWeekLow', 'fiftyTwoWeekHigh', 'regularMarketTime',
        'sharesOutstanding', 'impliedSharesOutstanding',
    ):
        if out.get(field) not in (None, '', {}, []):
            _mark_field_source(out, field, 'quote_page')
    avg_volume = _summary_value_from_html(html, "Avg. Volume")
    if avg_volume and not out.get("averageDailyVolume3Month"):
        raw = _parse_compact_number(avg_volume)
        out["averageDailyVolume3Month"] = {"raw": raw if raw is not None else avg_volume, "fmt": avg_volume}
        _mark_field_source(out, 'averageDailyVolume3Month', 'quote_page')
    market_cap = _summary_value_from_html(html, "Market Cap (intraday)")
    if market_cap and not out.get("marketCap"):
        raw = _parse_compact_number(market_cap)
        out["marketCap"] = {"raw": raw if raw is not None else market_cap, "fmt": market_cap}
        _mark_field_source(out, 'marketCap', 'quote_page')
    fifty_two_range = _summary_value_from_html(html, "52 Week Range")
    if fifty_two_range and not out.get("fiftyTwoWeekRange"):
        out["fiftyTwoWeekRange"] = {"raw": fifty_two_range, "fmt": fifty_two_range}
        _mark_field_source(out, 'fiftyTwoWeekRange', 'quote_page')
    regular_volume = _summary_value_from_html(html, "Volume")
    if regular_volume and not out.get("regularMarketVolume"):
        raw = _parse_compact_number(regular_volume)
        out["regularMarketVolume"] = {"raw": raw if raw is not None else regular_volume, "fmt": regular_volume}
        _mark_field_source(out, 'regularMarketVolume', 'quote_page')
    visible = _visible_quote_page_values(html)
    for key, value in visible.items():
        if value:
            out[key] = value
            _mark_field_source(out, key, 'quote_page')
    return out


def _quote_from_html(symbol: str, params: Dict[str, Any]) -> Dict[str, Any] | None:
    page_url = f"https://finance.yahoo.com/quote/{symbol}"
    row = get_text(page_url, params={**params, "accept": "text/html,*/*", "user_agent": "Mozilla/5.0"}, headers=QUOTE_HEADERS)
    html = str(row.get("text") or "")
    if not html:
        return None
    pattern = re.compile(r'<script type="application/json"[^>]*data-url="([^"]+)"[^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL)
    for match in pattern.finditer(html):
        data_url = unescape(str(match.group(1) or ""))
        blob = unescape(str(match.group(2) or "").strip())
        if not blob or "/v7/finance/quote" not in data_url:
            continue
        try:
            outer = json.loads(blob)
        except Exception:
            continue
        body = outer.get("body") if isinstance(outer, dict) else None
        if not isinstance(body, str) or not body.strip():
            continue
        try:
            inner = json.loads(body)
        except Exception:
            continue
        results = ((inner.get("quoteResponse") or {}).get("result") or []) if isinstance(inner, dict) else []
        for item in results:
            if isinstance(item, dict) and str(item.get("symbol") or "").strip().upper() == symbol:
                return _augment_quote_from_summary_html(item, html)
    return None


def _quote(params: Dict[str, Any]) -> Dict[str, Any]:
    symbols = _symbol_list(params)
    if not symbols:
        query = text_param(params, "query", "q")
        if query:
            lookup = _search({**params, "query": query, "limit": max(1, min(int_param(params, "limit", 5, 1, 25), 25))})
            quotes = (((lookup.get("data") or {}).get("quotes")) or []) if isinstance(lookup, dict) else []
            seen = set()
            symbols = []
            for row in quotes:
                sym = str((row or {}).get("symbol") or "").strip().upper()
                if sym and sym not in seen:
                    seen.add(sym)
                    symbols.append(sym)
        if not symbols:
            return {"ok": False, "data": {}, "warnings": ["symbols_required"]}
    encoded = ",".join(symbols)
    urls = [
        url_with_query("https://query1.finance.yahoo.com/v7/finance/quote", {"symbols": encoded}),
        url_with_query("https://query2.finance.yahoo.com/v7/finance/quote", {"symbols": encoded}),
    ]
    api_timeout = max(1.0, min(float(params.get("timeout") or 8.0), 2.0))
    html_timeout = max(1.0, min(float(params.get("timeout") or 8.0), 2.5))
    last_exc: Exception | None = None
    quote_api_unauthorized = False
    api_params = dict(params or {})
    api_params["timeout"] = api_timeout
    for url in urls:
        try:
            row = get_json(url, api_params, headers=QUOTE_HEADERS)
            payload = row.get("json") or {}
            results = ((payload.get("quoteResponse") or {}).get("result") or [])
            if isinstance(results, list) and results:
                by_symbol = {}
                normalized = []
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    sym = str(item.get("symbol") or "").strip().upper()
                    if not sym:
                        continue
                    by_symbol[sym] = item
                    normalized.append(item)
                if normalized:
                    return {
                        "ok": True,
                        "data": {
                            "source": "Yahoo Finance quote API",
                            "url": url,
                            "symbols": symbols,
                            "quotes": normalized,
                            "by_symbol": by_symbol,
                        },
                        "warnings": [],
                    }
        except Exception as exc:
            last_exc = exc
            if getattr(exc, "code", None) == 401:
                quote_api_unauthorized = True
    chart_quotes: List[Dict[str, Any]] = []
    fallback_warnings: List[str] = []
    used_html_enrichment = False
    for symbol in symbols:
        chart_item = None
        html_item = None
        try:
            chart_item = _quote_from_chart(symbol, {**params, "timeout": api_timeout})
        except Exception as exc:
            fallback_warnings.append(f"chart_quote_failed:{symbol}:{exc}")
        try:
            html_item = _quote_from_html(symbol, {**params, "timeout": html_timeout})
        except Exception as exc:
            fallback_warnings.append(f"html_quote_failed:{symbol}:{exc}")
        merged = _merge_quote_rows(chart_item, html_item)
        if isinstance(merged, dict):
            merged = _normalize_fallback_quote(merged)
            if isinstance(html_item, dict):
                used_html_enrichment = True
            for warning in (merged.get('_integrity_warnings') or []):
                warning_text = str(warning or '').strip()
                if warning_text:
                    fallback_warnings.append(warning_text)
            chart_quotes.append(merged)
        else:
            fallback_warnings.append(f"quote_fallback_missing:{symbol}")
    if chart_quotes:
        by_symbol = {}
        for item in chart_quotes:
            sym = str(item.get("symbol") or "").strip().upper()
            if sym:
                by_symbol[sym] = item
        source_name = "Yahoo Finance chart API fallback"
        source_url = "https://query1.finance.yahoo.com/v8/finance/chart"
        if used_html_enrichment:
            source_name = "Yahoo Finance chart API + quote page enrichment"
            source_url = "https://query1.finance.yahoo.com/v8/finance/chart + https://finance.yahoo.com/quote"
        warnings = ["yahoo_finance_chart_fallback", *(["yahoo_finance_quote_api_unauthorized"] if quote_api_unauthorized else []), *fallback_warnings]
        return {
            "ok": True,
            "data": {
                "source": source_name,
                "url": source_url,
                "symbols": symbols,
                "quotes": chart_quotes,
                "by_symbol": by_symbol,
            },
            "warnings": warnings,
        }
    return error_payload("Yahoo Finance", last_exc or RuntimeError("quote_lookup_failed"), {"mode": "quote", "symbols": symbols})


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    mode = str(params.get("mode") or "chart").strip().lower()
    try:
        if mode == "search":
            return _search(params)
        if mode == "quote":
            return _quote(params)
        return _chart(params)
    except Exception as exc:
        return error_payload("Yahoo Finance", exc, {"mode": mode})


TOOL_SPEC = {
    "id": NAME,
    "category": "external_data",
    "label": "Yahoo Finance: Quote/Search",
    "description": "Fetch stock/ETF/crypto chart data, quote snapshots, or symbol search results from Yahoo Finance public endpoints.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["chart", "search", "quote"]},
            "symbol": {"type": "string"},
            "ticker": {"type": "string"},
            "symbols": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
            "symbol_list": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
            "tickers": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
            "query": {"type": "string"},
            "range": {"type": "string"},
            "interval": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
            "timeout": {"type": "number"},
        },
        "additionalProperties": True,
    },
}
