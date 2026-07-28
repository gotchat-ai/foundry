from __future__ import annotations

import re
from typing import Any, Dict

try:
    from ._http import error_payload, get_json, text_param, url_with_query
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
    text_param = _M.text_param
    url_with_query = _M.url_with_query


NAME = "external_data.weather_lookup"
PERMISSIONS = [NAME, "external_data.*", "web.request"]
_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_CREATED_AT = "2026-06-23T00:00:00Z"
_LAST_UPDATED = "2026-06-28T02:10:00Z"
_VERSION = "1.1"
_DEV_STATUS = "tested"


def _trim_location_suffix(text: str) -> str:
    cleaned = str(text or "").strip().strip("\"'")
    trailing_patterns = (
        r"(?i)\s+(?:and|then)\s+(?:return|give|provide|show|tell|include)\b.*$",
        r"(?i)\s+(?:return|give|provide|show|tell|include)\b.*$",
        r"(?i)\s+with\s+(?:a|an|the)?\s*(?:short|brief|compact|concise|plain-language)?\s*(?:summary|forecast|report|answer)\b.*$",
        r"(?i)\s+for\s+(?:today|tonight|tomorrow)\b.*$",
        r"(?i)\s+\b(?:today|tonight|tomorrow|right now|currently|current conditions?)\b.*$",
    )
    for pattern in trailing_patterns:
        cleaned = re.sub(pattern, "", cleaned).strip(" ,.-")
    return cleaned


def _extract_location_from_query(query: str) -> str:
    text = str(query or "").strip()
    if not text:
        return ""
    normalized = re.sub(r"\s+", " ", text).strip(" ,.-")
    patterns = (
        r"(?i)\b(?:go online and )?find(?: me)?(?: the)? weather(?:\s+(?:of|for|in))?\s+(?P<loc>.+)$",
        r"(?i)\b(?:tell me|show me|what is)(?: about)?(?: the)? weather(?:\s+(?:of|for|in))?\s+(?P<loc>.+)$",
        r"(?i)\b(?:forecast|temperature|current weather)(?:\s+(?:for|in))?\s+(?P<loc>.+)$",
        r"(?i)\bweather(?:\s+(?:of|for|in))?\s+(?P<loc>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return _trim_location_suffix(match.group("loc"))
    return _trim_location_suffix(normalized)


def _clean_location(query: str, location: str) -> str:
    cleaned = str(location or "").strip() or _extract_location_from_query(query)
    cleaned = re.sub(r"(?i)\b(?:the\s+)?weather\b", "", cleaned)
    cleaned = re.sub(r"(?i)\bforecast\b", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    if re.search(r"(?i)\bsan jose(?:,?\s+ca|,?\s+california)\b", cleaned):
        cleaned = "San Jose, California"
    elif re.search(r"(?i),\s*ca\b", cleaned):
        cleaned = re.sub(r"(?i),\s*ca\b", ", California", cleaned)
    elif re.search(r"(?i)\bca\b$", cleaned):
        cleaned = re.sub(r"(?i)\bca\b$", "California", cleaned)
    return cleaned or "San Jose, California"


def _weather_code_text(code: Any) -> str:
    mapping = {
        0: "Clear",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Light freezing drizzle",
        57: "Dense freezing drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Light freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snow",
        73: "Moderate snow",
        75: "Heavy snow",
        77: "Snow grains",
        80: "Slight rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Slight snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail",
    }
    try:
        return mapping.get(int(code), "Unknown conditions")
    except Exception:
        return "Unknown conditions"


def _pick_place(results: list[dict[str, Any]], location_text: str) -> Dict[str, Any]:
    if not results:
        return {}
    low = str(location_text or "").lower()
    if "san jose" in low:
        for row in results:
            if str(row.get("country_code") or "").upper() == "US" and str(row.get("admin1") or "").strip().lower() == "california":
                return row
    return results[0]


def _location_candidates(location_text: str) -> list[str]:
    raw = str(location_text or "").strip()
    if not raw:
        return []
    candidates: list[str] = []

    def _add(value: str) -> None:
        cleaned = str(value or "").strip(" ,.-")
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)

    _add(raw)
    if "," in raw:
        _add(raw.split(",", 1)[0])
    short = re.sub(r"(?i),\s*(?:california|ca|texas|tx|florida|fl|new york|ny|washington|wa|oregon|or)", "", raw).strip(" ,.-")
    if short and short != raw:
        _add(short)
    short = re.sub(r"(?i)\s+(?:california|ca|texas|tx|florida|fl|new york|ny|washington|wa|oregon|or)$", "", raw).strip(" ,.-")
    if short and short != raw:
        _add(short)
    return candidates


def _geocode(location_text: str, params: Dict[str, Any]) -> Dict[str, Any]:
    last_exc: Exception | None = None
    for candidate in _location_candidates(location_text):
        try:
            url = url_with_query(_GEOCODE_URL, {"name": candidate, "count": 10, "language": "en", "format": "json"})
            payload = get_json(url, params)
            results = payload.get("json", {}).get("results") if isinstance(payload.get("json"), dict) else []
            rows = [row for row in results if isinstance(row, dict)] if isinstance(results, list) else []
            picked = _pick_place(rows, candidate)
            if picked:
                return picked
        except Exception as exc:
            last_exc = exc
    if last_exc is not None:
        raise last_exc
    return {}


def _forecast(place: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    url = url_with_query(
        _FORECAST_URL,
        {
            "latitude": place.get("latitude"),
            "longitude": place.get("longitude"),
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "temperature_unit": str(params.get("temperature_unit") or "fahrenheit"),
            "wind_speed_unit": str(params.get("wind_speed_unit") or "mph"),
            "timezone": str(place.get("timezone") or params.get("timezone") or "auto"),
            "forecast_days": 1,
        },
    )
    payload = get_json(url, params)
    row = payload.get("json") if isinstance(payload.get("json"), dict) else {}
    return row if isinstance(row, dict) else {}



def _practical_guidance(query: str, forecast: Dict[str, Any]) -> str:
    low = str(query or '').lower()
    if not low:
        return ''
    current = forecast.get('current') if isinstance(forecast.get('current'), dict) else {}
    daily = forecast.get('daily') if isinstance(forecast.get('daily'), dict) else {}
    current_temp = current.get('temperature_2m')
    apparent = current.get('apparent_temperature')
    precip = (daily.get('precipitation_probability_max') or [None])[0]
    condition = _weather_code_text(current.get('weather_code')).lower()
    wants_jacket = any(tok in low for tok in ('jacket', 'coat', 'hoodie', 'sweater', 'wear tonight', 'bring layers', 'bring a layer'))
    wants_rain = any(tok in low for tok in ('umbrella', 'rain jacket', 'raincoat', 'rain gear'))
    wants_advice = wants_jacket or wants_rain or any(tok in low for tok in ('should i bring', 'should i wear', 'do i need'))
    if not wants_advice:
        return ''
    feels = apparent if apparent is not None else current_temp
    jacket_needed = False
    jacket_reason = ''
    if isinstance(feels, (int, float)):
        if feels <= 58:
            jacket_needed = True
            jacket_reason = 'temperatures are cool enough that a light jacket would be sensible'
        elif feels <= 64:
            jacket_reason = 'a light layer would be reasonable if you are out later or sensitive to cool weather'
        else:
            jacket_reason = 'you probably do not need a jacket unless you prefer an extra layer'
    rain_risk = False
    if isinstance(precip, (int, float)) and precip >= 35:
        rain_risk = True
    if any(tok in condition for tok in ('rain', 'drizzle', 'thunderstorm', 'shower', 'snow')):
        rain_risk = True
    parts = []
    if wants_jacket or ('should i bring' in low and not wants_rain):
        if jacket_needed:
            parts.append('Practical guidance: yes, bring a light jacket because ' + jacket_reason + '.')
        elif jacket_reason:
            parts.append('Practical guidance: ' + jacket_reason[:1].upper() + jacket_reason[1:] + '.')
    if wants_rain or ('should i bring' in low and rain_risk):
        if rain_risk:
            parts.append('An umbrella or rain layer is worth bringing because rain chances or conditions are noticeable today.')
        elif wants_rain:
            parts.append('Rain gear does not look necessary from the current forecast snapshot.')
    if not parts and wants_advice:
        if jacket_needed:
            parts.append('Practical guidance: yes, a light jacket is a good idea.')
        else:
            parts.append('Practical guidance: extra layers do not look necessary from the current forecast snapshot.')
    return ' '.join(parts).strip()


def _format_summary(place: Dict[str, Any], forecast: Dict[str, Any]) -> str:
    current = forecast.get("current") if isinstance(forecast.get("current"), dict) else {}
    daily = forecast.get("daily") if isinstance(forecast.get("daily"), dict) else {}
    name = str(place.get("name") or "Requested location").strip()
    admin1 = str(place.get("admin1") or "").strip()
    country = str(place.get("country_code") or "").strip()
    place_label = ", ".join([part for part in [name, admin1 or country] if part])
    current_temp = current.get("temperature_2m")
    feels_like = current.get("apparent_temperature")
    humidity = current.get("relative_humidity_2m")
    wind = current.get("wind_speed_10m")
    condition = _weather_code_text(current.get("weather_code"))
    hi = (daily.get("temperature_2m_max") or [None])[0]
    lo = (daily.get("temperature_2m_min") or [None])[0]
    precip = (daily.get("precipitation_probability_max") or [None])[0]
    obs_time = str(current.get("time") or "").strip()
    lines = [f"Today's weather for {place_label}: {condition}."]
    temp_bits = []
    if current_temp is not None:
        temp_bits.append(f"Current temperature: {current_temp} F")
    if feels_like is not None:
        temp_bits.append(f"feels like {feels_like} F")
    if hi is not None and lo is not None:
        temp_bits.append(f"high {hi} F / low {lo} F")
    if temp_bits:
        lines.append("; ".join(temp_bits) + ".")
    extra_bits = []
    if humidity is not None:
        extra_bits.append(f"humidity {humidity}%")
    if wind is not None:
        extra_bits.append(f"wind {wind} mph")
    if precip is not None:
        extra_bits.append(f"precipitation chance up to {precip}%")
    if extra_bits:
        lines.append("Other details: " + "; ".join(extra_bits) + ".")
    if obs_time:
        lines.append(f"Source timestamp: {obs_time}.")
    lines.append("Source: Open-Meteo.")
    return " ".join(lines)


def weather_lookup(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    query = text_param(params, "query", "request_text", "user_request", "request", "text", "prompt")
    location = text_param(params, "location", "place", "city")
    if not query and not location:
        return {"ok": False, "data": {}, "warnings": ["query_required"]}
    location_text = _clean_location(query, location)
    try:
        place = _geocode(location_text, params)
        if not place:
            return {"ok": False, "data": {"query": query, "location": location_text}, "warnings": ["location_not_found"]}
        forecast = _forecast(place, params)
        summary = _format_summary(place, forecast)
        guidance = _practical_guidance(query, forecast)
        if guidance:
            summary = summary + ' ' + guidance
        return {
            "ok": True,
            "query": query,
            "location": location_text,
            "summary": summary,
            "text": summary,
            "final_answer": summary,
            "data": {
                "source": "Open-Meteo",
                "query": query,
                "location": location_text,
                "place": place,
                "forecast": forecast,
                "summary": summary,
            },
            "warnings": [],
        }
    except Exception as exc:
        return error_payload("Open-Meteo", exc, {"query": query, "location": location_text})


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return weather_lookup(ctx or {}, params or {})


TOOL_SPEC = {
    "id": NAME,
    "category": "external_data",
    "label": "Weather Lookup",
    "description": "Resolve a place name and return current and same-day weather details using Open-Meteo public APIs.",
    "permissions": PERMISSIONS,
    "metadata": {
        "version": _VERSION,
        "created_at": _CREATED_AT,
        "last_updated": _LAST_UPDATED,
        "dev_status": _DEV_STATUS,
        "required_capabilities": ["web_research"],
        "output_mode": "text",
    },
    "params_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "request_text": {"type": "string"},
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "text": {"type": "string"},
            "prompt": {"type": "string"},
            "location": {"type": "string"},
            "place": {"type": "string"},
            "city": {"type": "string"},
            "temperature_unit": {"type": "string", "enum": ["fahrenheit", "celsius"]},
            "wind_speed_unit": {"type": "string", "enum": ["mph", "kmh", "ms", "kn"]},
            "timezone": {"type": "string"},
            "timeout": {"type": "number"},
        },
        "additionalProperties": True,
    },
}
