from __future__ import annotations

import csv
import json
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List

NAME = 'custom.awf_go_to_finance_yahoo_com_and_pick_the_top_trending_10_stocks_you_can_sea__market_data_report'
PERMISSIONS = ['custom.awf_go_to_finance_yahoo_com_and_pick_the_top_trending_10_stocks_you_can_sea__market_data_report', 'custom.*']
TRENDING_URL = 'https://query1.finance.yahoo.com/v1/finance/trending/US'
QUOTE_URL = 'https://query1.finance.yahoo.com/v7/finance/quote'
SPARK_URL = 'https://query1.finance.yahoo.com/v7/finance/spark'
FALLBACK_TICKERS = ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'META', 'TSLA', 'AMD', 'AVGO', 'GOOGL', 'NFLX']

def _uploads_dir(ctx: Dict[str, Any]) -> Path:
    app = (ctx or {}).get('app')
    data_dir = getattr(getattr(app, 'state', None), 'data_dir', None) if app is not None else None
    root = Path(str(data_dir or './data')).resolve() / 'uploads'
    root.mkdir(parents=True, exist_ok=True)
    return root

def _json_get(url: str, timeout: float) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}, method='GET')
    with urllib.request.urlopen(req, timeout=max(3.0, min(float(timeout or 10.0), 15.0))) as resp:
        raw = resp.read().decode('utf-8', 'ignore')
    row = json.loads(raw)
    return row if isinstance(row, dict) else {}

def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        try:
            return float(str(v).replace(',', '').strip())
        except Exception:
            return 0.0

def _fetch_trending(top_n: int, timeout: float) -> List[str]:
    try:
        payload = _json_get(TRENDING_URL, timeout)
        quotes = (((payload.get('finance') or {}).get('result') or [{}])[0].get('quotes') or [])
        tickers = []
        for row in quotes:
            if not isinstance(row, dict):
                continue
            sym = str(row.get('symbol') or '').strip().upper()
            if sym and sym not in tickers:
                tickers.append(sym)
            if len(tickers) >= top_n:
                break
        return tickers or FALLBACK_TICKERS[:top_n]
    except Exception:
        return FALLBACK_TICKERS[:top_n]

def _fetch_quotes(symbols: List[str], timeout: float) -> Dict[str, Dict[str, Any]]:
    if not symbols:
        return {}
    try:
        url = QUOTE_URL + '?' + urllib.parse.urlencode({'symbols': ','.join(symbols)})
        payload = _json_get(url, timeout)
        out = {}
        for row in ((payload.get('quoteResponse') or {}).get('result') or []):
            if not isinstance(row, dict):
                continue
            sym = str(row.get('symbol') or '').strip().upper()
            if sym:
                out[sym] = row
        return out
    except Exception:
        return {}

def _fetch_spark(symbol: str, rng: str, interval: str, timeout: float) -> Dict[str, Any]:
    try:
        url = SPARK_URL + '?' + urllib.parse.urlencode({'symbols': symbol, 'range': rng, 'interval': interval, 'includePrePost': 'false'})
        payload = _json_get(url, timeout)
        result = (payload.get('spark') or {}).get('result') or []
        row = result[0] if result and isinstance(result[0], dict) else {}
        response = row.get('response') if isinstance(row.get('response'), list) and row.get('response') else []
        return response[0] if response and isinstance(response[0], dict) else {}
    except Exception:
        return {}

def _chart_payload(symbol: str, title: str, spark: Dict[str, Any]) -> Dict[str, Any]:
    timestamps = spark.get('timestamp') if isinstance(spark.get('timestamp'), list) else []
    indicators = (((spark.get('indicators') or {}).get('quote') or [{}])[0] if isinstance((spark.get('indicators') or {}).get('quote'), list) else {})
    closes = indicators.get('close') if isinstance(indicators.get('close'), list) else []
    x_vals = []
    y_vals = []
    for ts, val in zip(timestamps, closes):
        if ts is None or val is None:
            continue
        try:
            x_vals.append(time.strftime('%Y-%m-%d %H:%M', time.localtime(int(ts))))
        except Exception:
            x_vals.append(str(ts))
        y_vals.append(_safe_float(val))
    return {
        'symbol': symbol,
        'title': title,
        'chart': 'line',
        'xValues': x_vals,
        'series': [{'name': symbol, 'data': y_vals}],
    }

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(params or {})
    top_n = max(3, min(int(params.get('top_n') or 10), 10))
    timeout = float(params.get('timeout') or 8.0)
    region = str(params.get('region') or 'US').strip().upper() or 'US'
    symbols = _fetch_trending(top_n, timeout)
    quotes = _fetch_quotes(symbols, timeout)
    uploads = _uploads_dir(ctx)
    stem = 'market_data_report_' + str(int(time.time()))
    work_dir = uploads / stem
    work_dir.mkdir(parents=True, exist_ok=True)
    summary_csv = work_dir / 'summary.csv'
    summary_json = work_dir / 'summary.json'
    day_json = work_dir / 'day_charts.json'
    week_json = work_dir / 'week_charts.json'
    rows = []
    day_charts = []
    week_charts = []
    for symbol in symbols[:top_n]:
        quote = quotes.get(symbol, {})
        spark_day = _fetch_spark(symbol, '1d', '15m', timeout)
        spark_week = _fetch_spark(symbol, '5d', '1d', timeout)
        regular = _safe_float(quote.get('regularMarketPrice'))
        previous = _safe_float(quote.get('regularMarketPreviousClose'))
        day_change = ((regular - previous) / previous * 100.0) if previous else 0.0
        week_points = _chart_payload(symbol, f'{symbol} - 1 Week', spark_week).get('series')[0].get('data') if spark_week else []
        week_start = week_points[0] if week_points else regular
        week_end = week_points[-1] if week_points else regular
        week_change = ((week_end - week_start) / week_start * 100.0) if week_start else 0.0
        volume = _safe_float(quote.get('regularMarketVolume'))
        momentum_score = round(day_change * 0.45 + week_change * 0.45 + min(volume / 1000000.0, 10.0) * 0.1, 3)
        sell_pressure_proxy = round(max(0.0, -day_change) + max(0.0, -week_change), 3)
        row = {
            'symbol': symbol,
            'name': str(quote.get('shortName') or quote.get('longName') or symbol),
            'region': region,
            'price': regular,
            'day_change_pct': round(day_change, 3),
            'week_change_pct': round(week_change, 3),
            'volume': int(volume) if volume else 0,
            'momentum_score': momentum_score,
            'sell_pressure_proxy': sell_pressure_proxy,
        }
        rows.append(row)
        day_charts.append(_chart_payload(symbol, f'{symbol} - 1 Day', spark_day))
        week_charts.append(_chart_payload(symbol, f'{symbol} - 1 Week', spark_week))
    rows.sort(key=lambda r: (r.get('momentum_score') or 0.0), reverse=True)
    with summary_csv.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=['symbol', 'name', 'region', 'price', 'day_change_pct', 'week_change_pct', 'volume', 'momentum_score', 'sell_pressure_proxy'])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    summary_json.write_text(json.dumps({'rows': rows}, ensure_ascii=True, indent=2), encoding='utf-8')
    day_json.write_text(json.dumps({'charts': day_charts}, ensure_ascii=True, indent=2), encoding='utf-8')
    week_json.write_text(json.dumps({'charts': week_charts}, ensure_ascii=True, indent=2), encoding='utf-8')
    report_md = work_dir / 'report.md'
    top_line = rows[0] if rows else {}
    report_md.write_text(
        '# Market Data Report\n\n'
        + f"Generated for region {region}.\n\n"
        + (f"Top momentum symbol: {top_line.get('symbol', 'N/A')} ({top_line.get('momentum_score', 0)})\n" if top_line else 'No symbols available.\n'),
        encoding='utf-8'
    )
    table_lines = ['| Rank | Symbol | Name | Price | Day % | Week % | Volume |', '|---:|---|---|---:|---:|---:|---:|']
    for idx, row in enumerate(rows, start=1):
        table_lines.append(
            f"| {idx} | {row.get('symbol', '')} | {str(row.get('name', '')).replace('|', '/')} | {row.get('price', 0)} | {row.get('day_change_pct', 0)} | {row.get('week_change_pct', 0)} | {row.get('volume', 0)} |"
        )
    table_markdown = '\n'.join(table_lines)
    summary_lines = [f"Top {len(rows)} stocks for region {region}:"]
    for idx, row in enumerate(rows[: min(len(rows), top_n)], start=1):
        summary_lines.append(
            f"{idx}. {row.get('symbol', '')} - {row.get('name', '')}: price {row.get('price', 0)}, day {row.get('day_change_pct', 0)}%, week {row.get('week_change_pct', 0)}%"
        )
    final_answer = '\n'.join(summary_lines) + '\n\n' + table_markdown
    zip_path = uploads / (stem + '.zip')
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for path in [summary_csv, summary_json, day_json, week_json, report_md]:
            if path.is_file():
                zf.write(path, arcname=path.name)
    return {
        'ok': True,
        'output_path': str(zip_path),
        'bundle_files': [str(summary_csv), str(summary_json), str(day_json), str(week_json), str(report_md)],
        'summary': final_answer,
        'text': final_answer,
        'response': final_answer,
        'final_answer': final_answer,
        'table_markdown': table_markdown,
        'rows': rows,
        'day_charts': day_charts,
        'week_charts': week_charts,
        'data': {
            'output_path': str(zip_path),
            'bundle_files': [str(summary_csv), str(summary_json), str(day_json), str(week_json), str(report_md)],
            'rows': rows,
            'day_charts': day_charts,
            'week_charts': week_charts,
        },
        'warnings': [] if rows else ['no_market_rows'],
    }


TOOL_SPEC = {'id': 'custom.awf_go_to_finance_yahoo_com_and_pick_the_top_trending_10_stocks_you_can_sea__market_data_report', 'category': 'custom', 'label': 'Market Data Report', 'description': 'Fetch trending market symbols, gather day/week market evidence, compute bounded momentum metrics, and write a downloadable report bundle.', 'permissions': ['custom.awf_go_to_finance_yahoo_com_and_pick_the_top_trending_10_stocks_you_can_sea__market_data_report', 'custom.*'], 'params_schema': {'type': 'object', 'properties': {'region': {'type': 'string'}, 'top_n': {'type': 'integer'}, 'timeout': {'type': 'number'}}, 'additionalProperties': True}}
