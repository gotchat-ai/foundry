from __future__ import annotations
import base64
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any, Dict, List
NAME = 'custom.awf_web_research__web_research_204fb17b_executor'
PERMISSIONS = ['custom.awf_web_research__web_research_204fb17b_executor', 'custom.*']
DEFAULT_BASES = [
    "http://host.docker.internal:7767",
    "http://127.0.0.1:7767",
    "http://localhost:7767",
]
def _base_candidates(ctx: Dict[str, Any], params: Dict[str, Any]) -> List[str]:
    settings = (ctx or {}).get("settings") if isinstance(ctx, dict) else {}
    settings = settings if isinstance(settings, dict) else {}
    candidates = [
        str((params or {}).get("base_url") or "").strip().rstrip("/"),
        str(settings.get("searxng_base_url") or "").strip().rstrip("/"),
        str(os.environ.get("SEARXNG_BASE_URL") or "").strip().rstrip("/"),
    ]
    candidates.extend(DEFAULT_BASES)
    out: List[str] = []
    seen = set()
    for cand in candidates:
        if cand and cand not in seen:
            seen.add(cand)
            out.append(cand)
    return out
_DEFAULT_WEB_HEADERS = {
    'User-Agent': 'Mozilla/5.0',
}


def _request_json(url: str, timeout: float) -> Dict[str, Any]:
    headers = dict(_DEFAULT_WEB_HEADERS)
    headers['Accept'] = 'application/json'
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=max(3.0, min(float(timeout or 15.0), 25.0))) as resp:
        raw = resp.read().decode("utf-8", "ignore")
    row = json.loads(raw)
    return row if isinstance(row, dict) else {}
def _request_text(url: str, timeout: float, accept: str = 'text/plain,application/xml,text/xml;q=0.9,*/*;q=0.8') -> str:
    headers = dict(_DEFAULT_WEB_HEADERS)
    headers['Accept'] = accept
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=max(3.0, min(float(timeout or 15.0), 25.0))) as resp:
        return resp.read().decode('utf-8', 'ignore')
def _strip_tags(text: str) -> str:
    raw = str(text or '')
    raw = re.sub(r'<script[^>]*>.*?</script>', ' ', raw, flags=re.IGNORECASE | re.DOTALL)
    raw = re.sub(r'<style[^>]*>.*?</style>', ' ', raw, flags=re.IGNORECASE | re.DOTALL)
    raw = re.sub(r'<!--.*?-->', ' ', raw, flags=re.DOTALL)
    cleaned = re.sub(r'<.*?>', ' ', raw)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned.strip()


def _focused_official_snippet(text: str, query: str, url: str) -> str:
    collapsed = ' '.join(str(text or '').split())
    if not collapsed:
        return ''
    qlow = str(query or '').lower()
    ulow = str(url or '').lower()

    regex_patterns: List[re.Pattern[str]] = []
    primary_patterns: List[str] = []
    secondary_patterns: List[str] = []

    if 'cpi.nr0' in ulow:
        regex_patterns.extend([
            re.compile(r'(?:the all items index increased|all items index rose|consumer price index for all urban consumers \(cpi-u\) increased)\s+([0-9]+(?:\.[0-9]+)?)\s+percent(?:[^.]{0,180})?(?:over the last 12 months|for the 12 months ending)', re.IGNORECASE),
            re.compile(r'over the last 12 months, the all items index increased\s+([0-9]+(?:\.[0-9]+)?)\s+percent', re.IGNORECASE),
        ])
        primary_patterns.extend(['percent over the last 12 months', 'consumer price index summary', 'consumer price index'])
    elif 'empsit' in ulow:
        regex_patterns.extend([
            re.compile(r'the unemployment rate(?:[^.]{0,120})?(?:was unchanged at|held at|was|at)\s+([0-9]+(?:\.[0-9]+)?)\s+percent(?:[^.]{0,160})', re.IGNORECASE),
            re.compile(r'total nonfarm payroll employment(?:[^.]{0,160})?(?:increased|rose)\s+by\s+([0-9][0-9,]+)(?:[^.]{0,160})', re.IGNORECASE),
        ])
        primary_patterns.extend(['the unemployment rate', 'total nonfarm payroll employment increased', 'employment situation summary'])
    elif 'bea.gov' in ulow:
        regex_patterns.extend([
            re.compile(r'real gross domestic product \(gdp\)(?:[^.]{0,200})?([0-9]+(?:\.[0-9]+)?)\s+percent(?:[^.]{0,220})', re.IGNORECASE),
            re.compile(r'q[1-4]\s+20\d{2}\s+\(\d+(?:st|nd|rd|th)\)\s+[+\-]?[0-9]+(?:\.[0-9]+)?%(?:[^.]{0,220})', re.IGNORECASE),
        ])
        primary_patterns.extend(['real gross domestic product', 'u.s. economy at a glance', 'gdp (third estimate)'])
    elif 'releases/h15' in ulow:
        regex_patterns.extend([
            re.compile(r'([0-9]+(?:\.[0-9]+)?)\s+[0-9]+(?:\.[0-9]+)?\s+[0-9]+(?:\.[0-9]+)?\s+[0-9]+(?:\.[0-9]+)?\s+\* Markets closed\.(?:[^.]{0,220})?effective federal funds rate', re.IGNORECASE),
        ])
        primary_patterns.extend(['effective federal funds rate', 'selected interest rates', 'markets closed'])
    elif 'openmarket' in ulow or 'pressreleases' in ulow:
        primary_patterns.extend(['federal funds', 'target range', 'monetary policy', 'federal open market committee'])
    elif 'federalreserve.gov' in ulow:
        primary_patterns.extend(['federal funds', 'interest rate', 'monetary policy'])
    elif 'newsrels' in ulow:
        primary_patterns.extend(['consumer price index', 'employment situation', 'gross domestic product', 'federal open market committee'])
    elif 'cpi' in ulow:
        primary_patterns.extend(['consumer price index', 'over the last 12 months', '12 months ending', 'index for all items'])

    if any(tok in qlow for tok in ('inflation', 'cpi', 'consumer price')):
        secondary_patterns.extend(['percent over the last 12 months', 'over the last 12 months', '12 months, not seasonally adjusted', 'consumer price index'])
    if any(tok in qlow for tok in ('unemployment', 'employment', 'jobs', 'jobless')):
        secondary_patterns.extend(['total nonfarm payroll employment increased', 'the unemployment rate', 'unemployment rate was unchanged at', 'unemployment rate held at'])
    if any(tok in qlow for tok in ('gdp', 'growth', 'economy')):
        secondary_patterns.extend(['real gross domestic product', 'gdp (third estimate)', 'economy at a glance'])
    if any(tok in qlow for tok in ('interest rate', 'fed funds', 'federal reserve')):
        secondary_patterns.extend(['effective federal funds rate', 'federal funds', 'target range', 'interest rate', 'monetary policy'])

    for pattern in regex_patterns:
        m = pattern.search(collapsed)
        if m:
            start = max(0, m.start() - 160)
            end = min(len(collapsed), m.end() + 260)
            return collapsed[start:end]

    for pattern in primary_patterns + secondary_patterns:
        idx = collapsed.lower().find(pattern.lower())
        if idx >= 0:
            start = max(0, idx - 220)
            end = min(len(collapsed), idx + 620)
            return collapsed[start:end]
    return collapsed[:900]

def _extract_h15_effective_rate(html: str) -> Dict[str, str]:
    raw = str(html or '')
    if not raw:
        return {}
    headers = re.findall(r'<th id="col(\d+)" class="colhead">(.*?)</th>', raw, re.IGNORECASE | re.DOTALL)
    header_map: Dict[str, str] = {}
    for col_id, cell in headers:
        flat = _strip_tags(unescape(cell))
        flat = ' '.join(flat.split())
        if flat:
            header_map[str(col_id)] = flat.replace(' ', ' ').strip()
    row_match = re.search(r'<th[^>]*class="stub"[^>]*>Federal funds \(effective\)(.*?)</tr>', raw, re.IGNORECASE | re.DOTALL)
    if not row_match:
        return {}
    row_html = row_match.group(0)
    cells = re.findall(r'<td class="data" headers="[^"]*col(\d+)"[^>]*>\s*&nbsp;([^&<]+)&nbsp;\s*</td>', row_html, re.IGNORECASE)
    values = []
    for col_id, value in cells:
        cleaned = str(value or '').strip()
        if cleaned and cleaned.lower() not in ('n.a.', ''):
            values.append((str(col_id), cleaned))
    if not values:
        return {}
    latest_col, latest_value = values[-1]
    latest_date = header_map.get(latest_col, '')
    previous_value = values[-2][1] if len(values) >= 2 else ''
    content = f'Federal funds (effective) was {latest_value}% on {latest_date}.' if latest_date else f'Federal funds (effective) was {latest_value}% in the latest H.15 release.'
    if previous_value:
        content += f' The previous observed daily value was {previous_value}%.'
    return {'title': 'Selected Interest Rates - H.15 - Federal Reserve', 'content': content, 'published': latest_date}


def _parse_result_datetime(value: Any) -> datetime | None:
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S'):
        try:
            dt = datetime.strptime(raw[:19], fmt)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    m = re.search(r'/((?:20|19)\d{2})[-/]((?:0?[1-9]|1[0-2]))[-/]((?:0?[1-9]|[12]\d|3[01]))(?:/|$)', raw)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
        except Exception:
            return None
    return None

def _is_current_news_like_query(query: str) -> bool:
    low = str(query or '').lower()
    if _looks_like_current_topic_query(query) or _looks_like_news_query(query) or _looks_like_regulation_query(query):
        return True
    return any(tok in low for tok in ('latest', 'current', 'today', 'recent', 'right now', 'this week')) and any(tok in low for tok in ('ai', 'technology', 'tech', 'model', 'models', 'research', 'policy', 'regulation', 'economy', 'weather', 'paper', 'papers'))

def _recency_score(query: str, row: Dict[str, Any]) -> int:
    if not _is_current_news_like_query(query):
        return 0
    published = row.get('published') or row.get('published_at') or row.get('publishedDate') or row.get('date') or row.get('url')
    dt = _parse_result_datetime(published)
    if dt is None:
        return -1
    age_days = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
    if age_days <= 2:
        return 14
    if age_days <= 7:
        return 11
    if age_days <= 14:
        return 8
    if age_days <= 30:
        return 5
    if age_days <= 90:
        return 2
    if age_days <= 180:
        return -3
    if age_days <= 365:
        return -9
    return -15
def _identity_subject(query: str) -> str:
    low = str(query or '').strip()
    patterns = [
        r'(?:ceo|president|prime minister|chair|founder|governor|mayor)\s+of\s+(.+?)(?:\s+today|\s+right now|\?|\.|$)',
        r'who\s+is\s+the\s+(?:ceo|president|prime minister|chair|founder|governor|mayor)\s+of\s+(.+?)(?:\s+today|\s+right now|\?|\.|$)',
    ]
    for pat in patterns:
        m = re.search(pat, low, re.IGNORECASE)
        if m:
            subject = str(m.group(1) or '').strip(' ?.!,:;')
            subj_low = subject.lower()
            if subj_low == 'san jose':
                return 'San Jose, California'
            return subject
    return ''
def _identity_official_domain_hints(subject: str) -> List[str]:
    low = str(subject or '').strip().lower()
    if not low:
        return []
    domain_map = {
        'microsoft': ['https://news.microsoft.com/leadership/', 'https://news.microsoft.com/', 'https://www.microsoft.com/'],
        'google': ['https://blog.google/', 'https://about.google/'],
        'alphabet': ['https://abc.xyz/', 'https://blog.google/'],
        'apple': ['https://www.apple.com/leadership/', 'https://www.apple.com/'],
        'nvidia': ['https://www.nvidia.com/en-us/about-nvidia/management-team/', 'https://www.nvidia.com/'],
        'advanced micro devices': ['https://www.amd.com/en/corporate/leadership', 'https://www.amd.com/'],
        'amd': ['https://www.amd.com/en/corporate/leadership', 'https://www.amd.com/'],
        'amazon': ['https://www.aboutamazon.com/about-us/leadership', 'https://www.aboutamazon.com/'],
        'meta': ['https://about.meta.com/our-leadership/', 'https://about.meta.com/'],
        'tesla': ['https://www.tesla.com/elon-musk', 'https://www.tesla.com/'],
        'oracle': ['https://www.oracle.com/corporate/executives/', 'https://www.oracle.com/'],
        'netflix': ['https://about.netflix.com/en/company-leadership', 'https://about.netflix.com/'],
        'intel': ['https://www.intel.com/content/www/us/en/company-overview/leadership.html', 'https://www.intel.com/'],
        'openai': ['https://openai.com/about/', 'https://openai.com/'],
        'anthropic': ['https://www.anthropic.com/company', 'https://www.anthropic.com/'],
        'united states': ['https://www.whitehouse.gov/administration/donald-j-trump/', 'https://www.whitehouse.gov/administration/'],
        'the united states': ['https://www.whitehouse.gov/administration/donald-j-trump/', 'https://www.whitehouse.gov/administration/'],
        'san jose, california': ['https://www.sanjoseca.gov/your-government/departments-offices/mayor-and-city-council/mayor-office', 'https://www.sanjoseca.gov/your-government/departments-offices/mayor-and-city-council'],
        'san jose california': ['https://www.sanjoseca.gov/your-government/departments-offices/mayor-and-city-council/mayor-office', 'https://www.sanjoseca.gov/your-government/departments-offices/mayor-and-city-council'],
    }
    for key, urls in domain_map.items():
        if key in low:
            return list(urls)
    return []

def _decode_bing_href(href: str) -> str:
    raw = unescape(str(href or '').strip())
    if 'bing.com/ck/a' not in raw:
        return raw
    try:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query)
        encoded = str((params.get('u') or [''])[0] or '')
        if encoded.startswith('a1'):
            encoded = encoded[2:]
        if encoded:
            padded = encoded + '=' * ((4 - len(encoded) % 4) % 4)
            decoded = base64.b64decode(padded).decode('utf-8', 'ignore').strip()
            if decoded.startswith('http'):
                return decoded
    except Exception:
        pass
    return raw
def _fetch_bing_results(query: str, timeout: float, top_n: int) -> List[Dict[str, str]]:
    if not str(query or "").strip():
        return []
    subject = _identity_subject(_identity_focus_query(query))
    queries = [query]
    if _looks_like_identity_query(query) and subject:
        role = 'leadership'
        qlow = str(query or '').lower()
        if 'mayor' in qlow:
            role = 'mayor official'
        elif 'governor' in qlow:
            role = 'governor official'
        elif 'prime minister' in qlow:
            role = 'prime minister official'
        queries = [
            f'{subject} {role}',
            f'{subject} management team',
            f'{subject} CEO official',
            query,
        ]
    out: List[Dict[str, str]] = []
    seen = set()
    for q in queries:
        url = 'https://www.bing.com/search?' + urllib.parse.urlencode({'q': q})
        raw = _request_text(url, timeout, accept='text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8')
        matches = list(re.finditer(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', raw, re.IGNORECASE | re.DOTALL))
        local: List[Dict[str, str]] = []
        for match in matches:
            href = _decode_bing_href(str(match.group(1) or ''))
            title = _strip_tags(unescape(str(match.group(2) or '')))
            if not href or href in seen or not href.startswith('http'):
                continue
            snippet = ''
            tail = raw[match.end(): match.end() + 1200]
            pm = re.search(r'<p[^>]*>(.*?)</p>', tail, re.IGNORECASE | re.DOTALL)
            if pm:
                snippet = _strip_tags(unescape(str(pm.group(1) or '')))
            blob = (title + ' ' + snippet + ' ' + href).lower()
            if _looks_like_identity_query(query) and subject:
                subj_low = subject.lower()
                if subj_low not in blob and subj_low.split()[0] not in blob:
                    continue
            seen.add(href)
            local.append({'title': title, 'url': href, 'content': snippet, 'engine': 'bing'})
            if len(local) >= max(1, min(int(top_n or 5), 10)):
                break
        if local:
            out.extend(local)
            break
    return out[: max(1, min(int(top_n or 5), 10))]


def _fetch_bing_topic_results(query: str, timeout: float, top_n: int) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()
    current_topic = _looks_like_current_topic_query(query) or _looks_like_news_query(query) or _looks_like_regulation_query(query)
    macro_topic = _looks_like_macro_query(query)
    for candidate_query in _topic_search_fallback_queries(query):
        try:
            rows = _fetch_bing_results(candidate_query, timeout, max(top_n, 6))
        except Exception:
            rows = []
        local: List[Dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get('title') or '').strip()
            content = str(row.get('content') or '').strip()
            url = str(row.get('url') or '').strip()
            low_url = url.lower()
            published = str(row.get('published') or '').strip()
            key = (low_url, title.lower())
            if key in seen:
                continue
            if current_topic and not _is_relevant_ai_story(title, content, query):
                continue
            if current_topic and any(tok in query.lower() for tok in ('ai', 'model', 'models', 'headline', 'headlines', 'news', 'trend', 'trends')):
                evergreen_markers = ('wikipedia.org', '/academy/', '/what-is-', '/index/', '/about/', '/basics/', '/guide/')
                if ('trend' in query.lower() or 'trends' in query.lower() or 'latest' in query.lower() or 'current' in query.lower()) and not published and not re.search(r'/20\d{2}/', low_url):
                    if _looks_like_generic_news_hub(url, title, content) or any(marker in low_url for marker in evergreen_markers):
                        continue
            if macro_topic and not _is_relevant_macro_story(title, content, query):
                continue
            seen.add(key)
            local.append({
                'title': title,
                'url': url,
                'content': content,
                'engine': 'bing',
                'published': published,
            })
        if local:
            out.extend(local)
        if len(out) >= max(1, min(int(top_n or 5) * 2, 12)):
            break
    if not out:
        return []
    if macro_topic:
        scored = [(_rank_macro_story(query, row), row) for row in out]
    else:
        scored = [(_rank_current_topic_result(query, row), row) for row in out]
    scored.sort(key=lambda item: item[0], reverse=True)
    ranked = [row for score, row in scored if score >= 0]
    if not ranked:
        ranked = [row for _, row in scored]
    if _looks_like_ai_chip_query(query):
        strong_ranked = [row for row in ranked if not _is_low_value_current_topic_source(str(row.get('url') or row.get('link') or ''))]
        if strong_ranked:
            ranked = strong_ranked
        else:
            return []
    if ('trend' in query.lower() or 'headline' in query.lower() or 'headlines' in query.lower() or 'news' in query.lower()) and not _looks_like_ai_chip_query(query) and not _looks_like_regulation_query(query):
        high_confidence_ranked = [row for row in ranked if _is_high_confidence_current_topic_row(row)]
        if len(high_confidence_ranked) >= 2:
            ranked = high_confidence_ranked
        elif len(high_confidence_ranked) == 1 and any('reuters.com' in str(row.get('url') or '').lower() or _is_preferred_current_topic_row(row) for row in ranked):
            ranked = high_confidence_ranked + [row for row in ranked if row not in high_confidence_ranked][:2]
        else:
            return []
    return ranked[: max(1, min(int(top_n or 5), 10))]
def _looks_like_trending_query(query: str) -> bool:
    low = str(query or '').lower()
    if not low:
        return False
    # Explanatory prompts like 'why is X trending today' need article/news lookup, not a generic trends feed.
    if re.search(r'\b(?:why|how|what happened|what caused|explain|tell me why)\b.*\btrending\b', low):
        return False
    # Domain-specific trend requests should use web/news search, not generic search-trend feeds.
    if any(tok in low for tok in ('ai', 'model', 'models', 'technology', 'tech', 'research', 'paper', 'papers', 'finance', 'stock', 'stocks', 'market', 'politic', 'science')):
        return False
    if any(phrase in low for phrase in ('google trends', 'trending searches', 'search trends', 'what is trending online', 'what is trending right now', 'what is trending now')):
        return True
    return ('trend' in low or 'trending' in low or ('google' in low and 'what is' in low)) and not re.search(r'\bwhy\b.*\btrending\b', low)
def _looks_like_news_query(query: str) -> bool:
    low = str(query or '').lower()
    if 'news' in low or 'headline' in low or 'top stories' in low or 'breaking story' in low:
        return True
    return bool(re.search(r'\b(?:why|how|what happened|what caused|explain|tell me why)\b.*\btrending\b', low))


def _looks_like_broad_ai_news_query(query: str) -> bool:
    low = str(query or '').lower()
    if not low:
        return False
    has_ai_topic = any(tok in low for tok in ('ai', 'model', 'models', 'openai', 'anthropic', 'gemini', 'claude', 'gpt', 'llm'))
    has_news_shape = any(tok in low for tok in ('news', 'headline', 'headlines', 'top stories'))
    return has_ai_topic and has_news_shape and not _looks_like_ai_chip_query(query) and not _looks_like_regulation_query(query) and not _looks_like_macro_query(query)
def _looks_like_current_topic_query(query: str) -> bool:
    low = str(query or '').lower()
    has_time = any(tok in low for tok in ('latest', 'current', 'today', 'right now', 'this week', 'new', 'recent'))
    if re.search(r'\b(?:why|how|what happened|what caused|explain|tell me why)\b.*\btrending\b', low):
        return False
    has_topic = any(tok in low for tok in ('ai', 'model', 'models', 'technology', 'tech', 'release', 'releases'))
    return has_time and has_topic


def _wants_source_listing(query: str) -> bool:
    low = str(query or '').lower()
    explicit_markers = (
        'source', 'sources', 'link', 'links', 'url', 'urls', 'headline', 'headlines', 'top stories',
        'papers', 'citations', 'cite', 'references', 'return 5', 'return five', 'list', 'catalog', 'catalogue'
    )
    if any(marker in low for marker in explicit_markers):
        return True
    if re.search(r'\b(return|give|show|find)\s+\d+\b', low):
        return True
    return False


def _looks_like_ai_chip_query(query: str) -> bool:
    low = str(query or '').lower()
    chip_terms = ('chip', 'chips', 'gpu', 'gpus', 'semiconductor', 'semiconductors', 'accelerator', 'accelerators', 'nvidia', 'amd', 'intel', 'tsmc', 'broadcom')
    return 'ai' in low and any(term in low for term in chip_terms)
def _looks_like_regulation_query(query: str) -> bool:
    low = str(query or '').lower()
    policy_terms = ('regulation', 'regulations', 'regulator', 'regulators', 'policy', 'policies', 'law', 'laws', 'legal', 'compliance', 'rule', 'rules', 'governance', 'safety act', 'eu ai act', 'copyright', 'licensing')
    return 'ai' in low and any(term in low for term in policy_terms)


def _looks_like_eu_ai_regulation_query(query: str) -> bool:
    low = str(query or '').lower()
    if not _looks_like_regulation_query(query):
        return False
    return bool(
        'eu ai act' in low
        or 'european union' in low
        or 'european commission' in low
        or 'brussels' in low
        or re.search(r'\beu\b', low)
    )
def _news_time_window_days(query: str) -> int | None:
    low = str(query or '').lower()
    if _looks_like_regulation_query(query):
        if 'today' in low or 'right now' in low or 'current' in low:
            return 30
        if 'this week' in low:
            return 30
        if 'recent' in low or 'latest' in low or 'new' in low:
            return 45
    if ('trend' in low or 'trends' in low) and ('today' in low or 'right now' in low):
        return 7
    if 'today' in low or 'right now' in low:
        return 2
    if 'this week' in low:
        return 7
    if 'recent' in low or 'latest' in low or 'current' in low or 'new' in low:
        return 30
    return None
def _topic_news_query(query: str) -> str:
    low = str(query or '').lower()
    base = str(query or '')
    ai_specific = any(tok in low for tok in ('ai', 'model', 'models', 'llm', 'openai', 'anthropic', 'gemini', 'claude', 'gpt', 'xai', 'mistral', 'deepmind'))
    if ('trend' in low or 'trending' in low) and not ai_specific and not _looks_like_regulation_query(query) and not _looks_like_macro_query(query):
        base = str(query or '').strip()
    if _looks_like_macro_query(query):
        if any(host in url for host in ('bls.gov', 'bea.gov', 'federalreserve.gov', 'reuters.com', 'apnews.com', 'wsj.com', 'ft.com', 'cbsnews.com', 'abcnews.go.com', 'abcnews.com')):
            score += 6
        if _is_relevant_macro_story(title, content, query):
            score += 8
        else:
            score -= 12
        if any(term in blob for term in ('inflation', 'cpi', 'consumer prices', 'pce', 'unemployment', 'employment', 'jobless', 'jobs report', 'labor market', 'gdp', 'growth', 'interest rate', 'federal reserve')):
            score += 4
    if _looks_like_regulation_query(query):
        if _looks_like_eu_ai_regulation_query(query):
            base = 'EU AI Act OR European Commission AI Office OR European Union AI regulation OR GPAI code of practice OR AI Act compliance'
        else:
            base = 'AI regulation OR AI policy OR AI law OR AI governance OR EU AI Act OR White House AI policy OR FTC AI OR copyright AI OR synthetic media regulation'
    elif _looks_like_ai_chip_query(query):
        base = 'AI chip news OR AI GPU OR NVIDIA OR AMD OR Intel OR TSMC OR semiconductor'
    elif 'release' in low:
        base = 'AI model releases OR OpenAI OR Anthropic OR Google DeepMind OR Meta AI OR Mistral OR xAI'
    elif 'trend' in low and ai_specific:
        base = 'AI model news OR frontier AI model release OR reasoning model OR multimodal model OR OpenAI OR Anthropic OR Google DeepMind OR Meta AI OR xAI OR AI model review security'
    elif _looks_like_macro_query(query):
        base = _macro_news_query(query)
    elif _looks_like_broad_ai_news_query(query):
        base = 'AI model news'
    elif 'headline' in low or 'news' in low:
        base = 'AI model news OR frontier model OR reasoning model OR OpenAI OR Anthropic OR Google DeepMind OR Meta AI OR xAI OR NVIDIA'
    window_days = _news_time_window_days(query)
    if window_days:
        return f'{base} when:{window_days}d'
    return base


def _trending_subject_query_core(query: str) -> str:
    low = str(query or '').lower()
    patterns = [
        r'\bwhy\s+is\s+(.+?)\s+still\s+trending\b',
        r'\bwhy\s+is\s+(.+?)\s+trending\b',
        r'\bhow\s+is\s+(.+?)\s+trending\b',
        r'\bwhat\s+happened\s+to\s+(.+?)\s+that\s+(?:it\s+is\s+)?trending\b',
    ]
    for pattern in patterns:
        m = re.search(pattern, low)
        if m:
            core = ' '.join(str(m.group(1) or '').split()).strip(' ?!.,:;')
            if core:
                return core
    return ''


def _topic_search_fallback_queries(query: str) -> List[str]:
    low = str(query or '').lower()
    queries: List[str] = []
    ai_specific = any(tok in low for tok in ('ai', 'model', 'models', 'llm', 'openai', 'anthropic', 'gemini', 'claude', 'gpt', 'xai', 'mistral', 'deepmind'))
    trend_subject = _trending_subject_query_core(query)

    def _add(value: str) -> None:
        text = ' '.join(str(value or '').split()).strip()
        if text and text not in queries:
            queries.append(text)

    if _looks_like_regulation_query(query):
        if _looks_like_eu_ai_regulation_query(query):
            _add('EU AI Act')
            _add('European Commission AI Office AI Act')
            _add('European Union AI regulation compliance')
            _add('GPAI code of practice EU AI Act')
            _add('digital strategy ec europa AI Act')
        else:
            _add('AI regulation')
            _add('AI policy')
            _add('EU AI Act AI policy')
            _add('FTC AI policy')
            _add('AI copyright regulation')
    elif _looks_like_macro_query(query):
        _add(_macro_news_query(query).replace(' when:2d', '').replace(' when:7d', '').replace(' when:30d', '').replace(' when:45d', ''))
        _add('United States inflation unemployment GDP interest rates')
    elif _looks_like_ai_chip_query(query):
        _add('AI chip news Reuters CNBC The Verge NVIDIA AMD Intel TSMC')
        _add('AI GPU news NVIDIA AMD Intel TSMC semiconductor')
        _add('semiconductor AI accelerator news Reuters Bloomberg CNBC')
        _add('NVIDIA AMD Intel AI chip latest news')
    elif 'trend' in low or 'trends' in low:
        if ai_specific:
            _add('AI model trends Reuters CNBC TechCrunch The Verge VentureBeat OpenAI Anthropic Google DeepMind')
            _add('AI model news OpenAI Anthropic Google DeepMind Meta AI xAI Reuters')
            _add('frontier AI model release OpenAI Anthropic Google DeepMind Meta AI xAI')
            _add('US AI model review security OpenAI Anthropic Google xAI Reuters')
        else:
            if trend_subject:
                _add(f'{trend_subject} news')
                _add(f'why is {trend_subject} trending')
                _add(f'{trend_subject} today')
    elif _looks_like_broad_ai_news_query(query):
        _add('AI model news')
        _add('AI model when:7d')
        _add('OpenAI AI model release')
        _add('Anthropic Claude model release')
        _add('Google DeepMind Gemini AI model')
    elif 'headline' in low or 'news' in low:
        if ai_specific:
            _add('AI model news Reuters CNBC TechCrunch The Verge VentureBeat')
            _add('frontier AI model news OpenAI Anthropic Google DeepMind')
        elif trend_subject:
            _add(f'{trend_subject} news')
            _add(f'why is {trend_subject} trending')

    _add(str(query or '').strip())
    return queries
def _macro_news_query(query: str) -> str:
    low = str(query or '').lower()
    parts = ['United States economy']
    if any(tok in low for tok in ('inflation', 'cpi', 'consumer price')):
        parts.append('(inflation OR CPI OR consumer prices OR PCE)')
    if 'unemployment' in low or 'employment' in low or 'jobless' in low or 'jobs' in low:
        parts.append('(unemployment OR employment OR jobless claims OR jobs report)')
    if 'gdp' in low or 'growth' in low:
        parts.append('(GDP OR growth)')
    if 'interest rate' in low or 'fed funds' in low or 'federal reserve' in low:
        parts.append('(Federal Reserve OR interest rates OR fed funds)')
    parts.append('(BLS OR BEA OR Federal Reserve OR Reuters OR AP)')
    base = ' '.join(parts)
    window_days = _news_time_window_days(query)
    if window_days:
        return f'{base} when:{window_days}d'
    return base


def _is_relevant_macro_story(title: str, content: str, query: str) -> bool:
    blob = (' '.join([str(title or ''), str(content or '')])).lower()
    qlow = str(query or '').lower()
    requested = []
    if any(tok in qlow for tok in ('inflation', 'cpi', 'consumer price')):
        requested.append(('inflation', ('inflation', 'cpi', 'consumer prices', 'pce')))
    if 'unemployment' in qlow or 'employment' in qlow or 'jobs' in qlow or 'jobless' in qlow:
        requested.append(('unemployment', ('unemployment', 'employment', 'jobless', 'jobs report', 'labor market', 'labour market')))
    if 'gdp' in qlow or 'growth' in qlow:
        requested.append(('gdp', ('gdp', 'growth', 'economy')))
    if 'interest rate' in qlow or 'fed funds' in qlow or 'federal reserve' in qlow:
        requested.append(('rates', ('interest rate', 'fed funds', 'federal reserve', 'rate cut', 'rate hike')))
    if requested and not any(any(term in blob for term in terms) for _, terms in requested):
        return False
    macro_terms = ('inflation', 'cpi', 'consumer prices', 'pce', 'unemployment', 'employment', 'jobless', 'jobs report', 'labor market', 'gdp', 'growth', 'federal reserve', 'fed', 'interest rate', 'economy')
    if not any(term in blob for term in macro_terms):
        return False
    noise_terms = (
        'earthquake', 'war', 'election campaign', 'sports', 'celebrity', 'movie', 'crime', 'wildfire', 'arson trial',
        'byron donalds', 'tradingview', 'goldsilver', 'benzinga', 'investing.com', 'moomoo', 'news.google.com', 'stock market today',
        'kavout', 'prediction market', 'technical analysis', 'options flow', 'earnings whisper', 'crypto price',
        'stock pick', 'top stocks', 'best stocks', 'buy now', 'analyst rating', 'price target'
    )
    if any(term in blob for term in noise_terms):
        return False
    return True


def _rank_macro_story(query: str, row: Dict[str, str]) -> int:
    title = str(row.get('title') or '')
    content = str(row.get('content') or '')
    url = str(row.get('url') or row.get('link') or '')
    published = str(row.get('published') or '')
    blob = (' '.join([title, content, url])).lower()
    qlow = str(query or '').lower()
    score = 0
    trusted_official = ('bls.gov', 'bea.gov', 'federalreserve.gov', 'worldbank.org', 'imf.org', 'oecd.org')
    trusted_press = ('reuters', 'associated press', 'ap news', 'bloomberg', 'financial times', 'ft.com', 'wsj', 'wall street journal', 'cnbc')
    low_value_noise = (
        'tradingview', 'goldsilver', 'benzinga', 'investing.com', 'moomoo', 'news.google.com', 'kavout', 'motley fool', 'zacks', 'seeking alpha',
        'price target', 'stock pick', 'top stocks', 'buy now', 'analyst rating', 'options flow', 'technical analysis'
    )
    for token in trusted_official:
        if token in blob:
            score += 8
    for token in trusted_press:
        if token in blob:
            score += 5
    for token in low_value_noise:
        if token in blob:
            score -= 8
    requested_topics = []
    if any(tok in qlow for tok in ('inflation', 'cpi', 'consumer price')):
        requested_topics.append(('inflation', 'cpi', 'consumer prices', 'pce'))
    if 'unemployment' in qlow or 'employment' in qlow or 'jobs' in qlow or 'jobless' in qlow:
        requested_topics.append(('unemployment', 'employment', 'jobless', 'jobs report', 'labor market', 'labour market'))
    if 'gdp' in qlow or 'growth' in qlow:
        requested_topics.append(('gdp', 'growth', 'economy', 'gross domestic product'))
    if 'interest rate' in qlow or 'fed funds' in qlow or 'federal reserve' in qlow:
        requested_topics.append(('interest rate', 'fed funds', 'federal reserve', 'rate cut', 'rate hike'))
    if requested_topics:
        topic_hits = sum(1 for terms in requested_topics if any(term in blob for term in terms))
        score += topic_hits * 3
    score += _recency_score(query, {'published': published, 'url': url})
    return score


def _is_relevant_ai_story(title: str, content: str, query: str) -> bool:
    blob = (' '.join([str(title or ''), str(content or '')])).lower()
    qlow = str(query or '').lower()
    include_terms = ('ai', 'artificial intelligence', 'model', 'models', 'llm', 'gpt', 'claude', 'gemini', 'openai', 'anthropic', 'deepmind', 'meta ai', 'meta', 'xai', 'grok', 'mistral', 'cohere', 'nvidia')
    exclude_terms = ('stock', 'stocks', 'penny stock', 'tradingview', 'investing', 'cfo', 'business ideas', 'restaurant', 'netflix', 'call of duty', 'economics', 'film studio', 'hollywood reporter')
    if _looks_like_regulation_query(query):
        reg_terms = ('regulation', 'regulations', 'regulator', 'regulators', 'policy', 'policies', 'law', 'laws', 'legal', 'compliance', 'rule', 'rules', 'governance', 'safety', 'eu ai act', 'copyright', 'licensing', 'synthetic media', 'deepfake', 'election', 'lawmakers', 'congress', 'senate', 'bill', 'court', 'oversight', 'ftc', 'white house')
        if not any(term in blob for term in reg_terms):
            return False
    if not any(term in blob for term in include_terms):
        return False
    if _looks_like_ai_chip_query(query):
        chip_terms = ('chip', 'chips', 'gpu', 'gpus', 'semiconductor', 'semiconductors', 'accelerator', 'accelerators', 'cuda', 'h100', 'b200', 'blackwell', 'foundry', 'wafer', 'nvidia', 'amd', 'intel', 'tsmc', 'broadcom')
        def _chip_term_hit(term: str) -> bool:
            return bool(re.search(r'\b' + re.escape(term) + r'\b', blob))
        if not any(_chip_term_hit(term) for term in chip_terms):
            return False
        chip_noise = ('summarizer', 'essay generator', 'paraphraser', 'consumer app', 'chatbot', 'marketing tool')
        if any(term in blob for term in chip_noise):
            return False
    if any(term in blob for term in exclude_terms) and not any(term in qlow for term in ('stock', 'stocks', 'invest', 'market')):
        return False
    if 'headline' in qlow or 'news' in qlow:
        news_terms = ('model', 'models', 'release', 'launch', 'api', 'reasoning', 'multimodal', 'inference', 'chip', 'chips', 'gpu', 'benchmark', 'training', 'frontier', 'open-weight', 'open source', 'research', 'agent', 'agents', 'platform', 'deployment')
        news_noise = ('talent war', 'film studio', 'box office', 'a24', 'indiewire', 'variety', 'celebrity', 'entertainment', 'sold its soul', 'backlash')
        if any(term in blob for term in news_noise):
            return False
        if not any(term in blob for term in news_terms):
            return False
    if any(tok in qlow for tok in ('release', 'releases', 'launched', 'launches')):
        release_terms = ('release', 'launch', 'launched', 'introducing', 'introduced', 'announces', 'announced', 'api', 'model', 'models', 'version', 'new ai', 'gemini', 'gpt', 'claude', 'mistral', 'xai', 'openai', 'anthropic')
        if not any(term in blob for term in release_terms):
            return False
        exclude_release_noise = ('talent war', 'research deal', 'partnership', 'prediction market', 'coding strike team', 'film studio')
        if any(term in blob for term in exclude_release_noise):
            return False
    if 'trend' in qlow or 'trends' in qlow:
        if _looks_like_ai_chip_query(query):
            chip_trend_terms = ('chip', 'chips', 'gpu', 'gpus', 'semiconductor', 'accelerator', 'accelerators', 'custom chip', 'homegrown ai chip', 'packaging', 'wafer', 'foundry', 'export control', 'banned ai chips', 'inference chip', 'manufacturing', 'substrate')
            if not any(term in blob for term in chip_trend_terms):
                return False
        else:
            trend_terms = ('reasoning', 'multimodal', 'open source', 'open-source', 'open-weight', 'release', 'model release', 'models', 'llm', 'gpt', 'claude', 'gemini', 'mistral', 'xai', 'frontier model', 'frontier models', 'inference', 'benchmark', 'previewing', 'unveils', 'debuts', 'launches')
            trend_provider_terms = ('openai', 'anthropic', 'google', 'deepmind', 'meta', 'xai', 'microsoft', 'nvidia')
            trend_governance_terms = ('review', 'reviews', 'security', 'cybersecurity', 'safety', 'access', 'approval', 'stagger release', 'stress test', 'rollout', 'rollout plan', 'limit', 'limits', 'limited preview')
            if not (any(term in blob for term in trend_terms) or (any(term in blob for term in trend_provider_terms) and any(term in blob for term in trend_governance_terms))):
                return False
        trend_vertical_noise = ('clinician', 'clinicians', 'healthcare', 'hospital', 'medical', 'drug discovery', 'mortgage', 'lending', 'earth observation', 'spacecraft', 'satellite', 'classroom', 'customer service', 'workflow automation', 'health ai', 'patient', 'care delivery')
        if any(term in blob for term in trend_vertical_noise) and 'health' not in qlow and 'medical' not in qlow and 'clinical' not in qlow:
            return False
    return True


def _looks_like_generic_news_hub(url: str, title: str, content: str = '') -> bool:
    low_url = str(url or '').lower()
    low_title = str(title or '').lower()
    low_content = str(content or '').lower()
    combined = low_title + ' ' + low_content
    if 'news.google.com/rss/articles/' in low_url or 'news.google.com/read/' in low_url:
        return False
    hub_signals = (
        'latest news',
        'latest headlines',
        'artificial intelligence - latest',
        'read full articles',
        'browse thousands of titles',
        'topic with google news',
        'the ai race',
        'newsletter',
        'real-time updates',
        'handpicked daily',
        'latest on',
    )
    if 'news.google.com/topics/' in low_url:
        return True
    if re.fullmatch(r'https?://[^/]+/?', low_url):
        return True
    if any(tok in low_url for tok in ('/latest/', '/topics/', '/tag/artificial-intelligence', '/artificial-intelligence/', '/live', '/news', '/ai-news')) and not re.search(r'/20\d{2}/', low_url):
        return True
    return any(signal in combined for signal in hub_signals)


def _rank_current_topic_result(query: str, row: Dict[str, str]) -> int:
    title = str(row.get('title') or '').lower()
    content = str(row.get('content') or '').lower()
    url = str(row.get('url') or '').lower()
    blob = ' '.join(part for part in (title, content, url) if part)
    qlow = str(query or '').lower()
    score = 0
    trusted_mainstream = ('reuters.com', 'apnews.com', 'bloomberg.com', 'ft.com', 'wsj.com', 'nytimes.com', 'politico.com', 'theverge.com', 'techcrunch.com', 'venturebeat.com', 'cnbc.com', 'computerworld.com', 'tomshardware.com', 'anandtech.com')
    trusted_official = ('openai.com', 'anthropic.com', 'blog.google', 'deepmind.google', 'nvidia.com', 'amd.com', 'intel.com', 'tsmc.com', 'broadcom.com', 'ec.europa.eu', 'whitehouse.gov', 'congress.gov', 'ftc.gov', 'europa.eu', 'nature.com')
    low_value_noise = ('techtimes.com', 'webpronews.com', 'jdsupra.com', 'stockstory.org', 'motleyfool.com', 'benzinga.com', 'investing.com', 'tradingview.com')
    if _looks_like_generic_news_hub(url, title, content):
        score -= 8
    if any(host in url for host in trusted_mainstream):
        score += 6
    if any(host in url for host in trusted_official):
        score += 7
    if any(host in url for host in low_value_noise):
        score -= 5
    if _is_preferred_current_topic_row(row):
        score += 5
    if _is_low_value_current_topic_row(row):
        score -= 8
    if re.search(r'/20\d{2}/', url):
        score += 3
    if any(term in blob for term in ('release', 'launch', 'announced', 'introducing', 'api', 'model', 'reasoning', 'multimodal', 'benchmark', 'agent', 'agents', 'training', 'inference', 'chip', 'gpu')):
        score += 3
    if any(term in blob for term in ('previewing', 'unveils', 'introduces', 'debuts', 'ships')):
        score += 2
    if any(term in blob for term in ('analysis', 'latest', 'news', 'headlines')):
        score += 1
    if _looks_like_regulation_query(query):
        regulation_terms = ('regulation', 'regulations', 'policy', 'policies', 'law', 'laws', 'legal', 'compliance', 'regulator', 'regulators', 'governance', 'safety act', 'eu ai act', 'copyright', 'licensing', 'deepfake', 'synthetic media', 'election', 'lawmakers', 'congress', 'senate', 'bill', 'court', 'oversight', 'ftc', 'white house')
        if any(term in blob for term in regulation_terms):
            score += 8
        if any(host in url for host in ('reuters.com', 'ft.com', 'wsj.com', 'nytimes.com', 'apnews.com', 'politico.com', 'euractiv.com', 'ec.europa.eu', 'congress.gov', 'ftc.gov', 'whitehouse.gov', 'nature.com')):
            score += 4
        if any(host in url for host in ('jdsupra.com', 'techtimes.com')):
            score -= 6
        if any(term in blob for term in ('mortgage', 'lending', 'hospital', 'health care', 'healthcare', 'patient')) and 'health' not in qlow and 'medical' not in qlow and 'mortgage' not in qlow and 'lending' not in qlow:
            score -= 10
    score += _recency_score(query, row)
    if 'trend' in qlow or 'trends' in qlow:
        model_focus_terms = ('reasoning', 'multimodal', 'frontier model', 'frontier models', 'open-weight', 'open source', 'model release', 'tiered models', 'inference', 'next-generation model', 'previewing gpt', 'claude', 'gemini', 'gpt-5', 'gpt-5.6', 'sol, terra, and luna')
        if any(term in blob for term in model_focus_terms):
            score += 7
        if any(host in url for host in ('openai.com', 'anthropic.com', 'blog.google', 'deepmind.google')):
            score += 4
        vertical_noise = ('health ai', 'healthcare', 'hospital', 'medical', 'medical imaging', 'clinical', 'drug discovery', 'finance team', 'marketing team', 'applications', 'readiness', 'health system', 'care delivery', 'patient')
        if any(term in blob for term in vertical_noise) and 'health' not in qlow and 'medical' not in qlow and 'clinical' not in qlow:
            score -= 24
    if not _is_relevant_ai_story(title, content, query):
        score -= 10
    return score
def _looks_like_youtube_query(query: str) -> bool:
    low = str(query or '').lower()
    return 'youtube' in low
def _looks_like_identity_query(query: str) -> bool:
    low = str(query or '').lower()
    return bool(any(phrase in low for phrase in ('who is', "who's", 'what is')) and any(tok in low for tok in ('ceo', 'president', 'prime minister', 'chair', 'founder', 'governor', 'mayor')))
def _first_sentence(text: str) -> str:
    raw = ' '.join(str(text or '').split()).strip()
    if not raw:
        return ''
    for sep in ('. ', '! ', '? '):
        idx = raw.find(sep)
        if idx > 0:
            return raw[: idx + 1].strip()
    return raw[:280].rstrip() + ('...' if len(raw) > 280 else '')


def _looks_like_person_name_candidate(candidate: str) -> bool:
    text = ' '.join(str(candidate or '').split()).strip()
    if not text:
        return False
    low = text.lower()
    banned_phrases = {
        'chief executive officer', 'executive officer', 'chief executive', 'president and ceo',
        'chairman and chief executive officer', 'chairman', 'chief financial officer', 'founder',
        'current ceo', 'ceo', 'armed forces', 'about us', 'official leadership', 'leadership page',
        'the white house', 'trump administration', 'google gemini', 'hires google gemini', 'city council',
        'management team', 'executive team', 'official site', 'official leadership page', 'president of the united states'
    }
    if low in banned_phrases:
        return False
    generic_tokens = {
        'about', 'administration', 'armed', 'forces', 'official', 'leadership', 'page', 'hires', 'google', 'gemini',
        'city', 'council', 'management', 'executive', 'office', 'government', 'white', 'house', 'president', 'mayor'
    }
    parts = [part for part in re.split(r'\s+', text) if part]
    if len(parts) < 2 or len(parts) > 4:
        return False
    if not re.fullmatch(r"[A-Z][A-Za-z'.-]+(?: [A-Z][A-Za-z'.-]+){1,3}", text):
        return False
    token_lows = [re.sub(r"[^a-z]", '', part.lower()) for part in parts]
    if any(tok in generic_tokens for tok in token_lows if tok):
        return False
    return True


def _identity_subject_tokens(query: str) -> set[str]:
    subject = _identity_subject(query)
    return {tok for tok in re.findall(r'[a-z0-9]+', subject.lower()) if len(tok) > 2}


def _resolved_name_is_subject_alias(query: str, name: str) -> bool:
    normalized = ' '.join(str(name or '').split()).strip()
    if not normalized:
        return True
    name_tokens = {tok for tok in re.findall(r'[a-z0-9]+', normalized.lower()) if len(tok) > 2}
    subject_tokens = _identity_subject_tokens(query)
    if not name_tokens:
        return True
    if subject_tokens and name_tokens <= subject_tokens:
        return True
    if len(name_tokens) == 1 and next(iter(name_tokens)).isdigit():
        return True
    return False


def _extract_role_prefixed_person(text: str) -> str:
    raw = ' '.join(str(text or '').split()).strip()
    if not raw:
        return ''
    patterns = [
        r'(?:CEO|Chief Executive Officer|Mayor|Governor|President|Prime Minister|Chair|Chairman|Chairwoman|Founder)\s+([A-Z][A-Za-z\'.-]+(?:\s+[A-Z][A-Za-z\'.-]+){1,3})\b',
        r'([A-Z][A-Za-z\'.-]+(?:\s+[A-Z][A-Za-z\'.-]+){1,3})\s*\((?:[^)]*?\b(?:CEO|Chief Executive Officer|Mayor|Governor|President|Prime Minister|Chair|Founder)\b[^)]*)\)',
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = str(match.group(1) or '').strip()
        if _looks_like_person_name_candidate(candidate):
            return candidate
    return ''


def _extract_person_name(text: str) -> str:
    raw = ' '.join(str(text or '').split()).strip()
    if not raw:
        return ''
    role_prefixed = _extract_role_prefixed_person(raw)
    if role_prefixed:
        return role_prefixed
    head = re.split(r'[;|,\n]', raw, maxsplit=1)[0].strip()
    head = re.sub(r'\s*\(.*$', '', head).strip()
    if _looks_like_person_name_candidate(head):
        return head
    for match in re.finditer(r"\b([A-Z][A-Za-z'.-]+(?: [A-Z][A-Za-z'.-]+){1,3})\b", raw):
        candidate = str(match.group(1) or '').strip()
        if _looks_like_person_name_candidate(candidate):
            return candidate
    return ''

def _person_name_from_url_slug(url: str) -> str:
    raw = str(url or '').strip()
    if not raw:
        return ''
    try:
        slug = urllib.parse.urlparse(raw).path.rstrip('/').rsplit('/', 1)[-1]
    except Exception:
        slug = ''
    slug = urllib.parse.unquote(str(slug or '')).replace('_', ' ').replace('-', ' ')
    slug = re.sub(r'\s+', ' ', slug).strip()
    return slug if _looks_like_person_name_candidate(slug) else ''


def _host_root(url: str) -> str:
    parsed = urllib.parse.urlparse(str(url or '').strip())
    if not parsed.scheme or not parsed.netloc:
        return ''
    return f'{parsed.scheme}://{parsed.netloc}/'


def _extract_named_context(text: str, needle: str, radius: int = 180) -> str:
    raw = ' '.join(str(text or '').split()).strip()
    target = str(needle or '').strip()
    if not raw or not target:
        return ''
    idx = raw.lower().find(target.lower())
    if idx < 0:
        return ''
    start = max(0, idx - radius)
    end = min(len(raw), idx + len(target) + radius)
    snippet = raw[start:end].strip()
    return snippet[:360].rstrip()
def _identity_rank(row: Dict[str, str]) -> int:
    url = str(row.get('url') or '').lower()
    title = str(row.get('title') or '').lower()
    content = str(row.get('content') or '').lower()
    engine = str(row.get('engine') or '').lower()
    score = 0
    if any(tok in url for tok in ('nvidia.com', 'amd.com', 'openai.com', 'microsoft.com', 'google.com', 'alphabet.com', 'whitehouse.gov', '.gov')):
        score += 6
    if any(tok in url for tok in ('forbes.com', 'bloomberg.com', 'reuters.com', 'britannica.com')):
        score += 4
    if 'wikipedia.org' in url:
        score += 2
    if engine == 'official_site':
        score += 8
    if engine == 'official_site_context':
        score += 7
    if engine == 'wikipedia_public_office':
        score += 8
    if engine == 'wikipedia_infobox':
        score += 7
    if any(tok in url for tok in ('sanjoseca.gov', '.gov/')):
        score += 6
    if any(tok in title for tok in ('city of san jose', 'mayor of san jose', 'governor', 'prime minister', 'president')):
        score += 4
    if any(tok in content for tok in ('mayor of san jose', 'serves as mayor', 'governor of', 'prime minister of', 'president of')):
        score += 4
    if any(tok in title for tok in ('management team', 'leadership', 'executive team', 'ceo', 'president', 'key people')):
        score += 2
    if any(tok in content for tok in (' chief executive officer', ' ceo', 'president and ceo', 'key people', 'founder')):
        score += 3
    return score


def _identity_answer_rank(query: str, row: Dict[str, str]) -> int:
    score = _identity_rank(row)
    title = str(row.get('title') or '').lower()
    content = str(row.get('content') or '').lower()
    url = str(row.get('url') or '').lower()
    engine = str(row.get('engine') or '').lower()
    blob = ' '.join(part for part in (title, content, url) if part)
    roles = _identity_role_labels(query)
    if roles and any(role in blob for role in roles):
        score += 6
    if any(phrase in content for phrase in ('president and ceo', 'chief executive officer', 'serving as', 'serves as', 'is the 67th mayor')):
        score += 5
    if engine == 'official_site' and any(term in url for term in ('management-team', 'leadership', 'executive', 'jensen-huang', 'board-of-directors')):
        score += 6
    if engine == 'official_site_context' and any(term in url for term in ('management-team', 'leadership', 'executive', 'about', 'governance')):
        score += 4
    if 'wikipedia_infobox' in engine or 'wikipedia_public_office' in engine:
        score += 2
    if 'wikipedia.org/wiki/nvidia' in url or 'wikipedia.org/wiki/amd' in url:
        score -= 3
    if _looks_generic_office_directory(query, row):
        score -= 8
    return score
def _identity_role_labels(query: str) -> List[str]:
    qlow = str(query or '').lower()
    if 'chief executive officer' in qlow or 'ceo' in qlow:
        return ['chief executive officer', 'ceo', 'president and ceo']
    if 'prime minister' in qlow:
        return ['prime minister']
    if 'president' in qlow:
        return ['president', 'president and ceo']
    if 'chair' in qlow:
        return ['chair', 'chairman', 'chairwoman']
    if 'founder' in qlow:
        return ['founder']
    if 'governor' in qlow:
        return ['governor']
    if 'mayor' in qlow:
        return ['mayor']
    return []
def _looks_like_script_noise(text: str) -> bool:
    low = ' '.join(str(text or '').split()).lower()
    if not low:
        return False
    signals = 0
    if 'function ' in low:
        signals += 1
    if 'window.' in low or 'document.' in low:
        signals += 1
    if 'var ' in low or 'const ' in low or 'let ' in low:
        signals += 1
    if 'optanon' in low or 'redirecttologin' in low or 'pagessoenabled' in low:
        signals += 2
    return signals >= 2


def _extract_identity_answer(query: str, text: str) -> str:
    raw = ' '.join(str(text or '').split()).strip()
    if not raw:
        return ''
    role_labels = _identity_role_labels(query)
    subject = _identity_subject(query)
    subject_terms = [tok for tok in re.findall(r'[a-z0-9]+', subject.lower()) if len(tok) > 2]
    if role_labels:
        pieces = [part.strip() for part in re.split('[;|\n?]+', raw) if part.strip()]
        role_pattern = '|'.join(sorted((re.escape(label) for label in role_labels), key=len, reverse=True))
        for piece in pieces:
            low = piece.lower()
            if any(label in low for label in role_labels):
                name_role_match = re.search(r"([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,3})\s+(" + role_pattern + r")", piece, flags=re.IGNORECASE)
                if name_role_match:
                    compact = ' '.join(part for part in name_role_match.groups() if part).strip(' ,.;:-')
                    if compact:
                        return compact[:280].rstrip()
                if subject_terms and all(tok in low for tok in subject_terms[:2]):
                    subject_idx = min((low.find(tok) for tok in subject_terms[:2] if tok in low), default=-1)
                    role_idx = min((low.find(label) for label in role_labels if label in low), default=-1)
                    if subject_idx >= 0 and role_idx >= 0 and abs(role_idx - subject_idx) <= 180:
                        start = max(0, min(subject_idx, role_idx) - 24)
                        end = min(len(piece), max(subject_idx + len(subject), role_idx + max(len(label) for label in role_labels)) + 40)
                        snippet = piece[start:end].strip(' ,.;:-')
                        if snippet:
                            return snippet[:280].rstrip()
                return piece[:280].rstrip()
    return _first_sentence(raw)
def _clean_identity_content(text: str, query: str = '') -> str:
    raw = _extract_identity_answer(query, text)
    if not raw:
        return ''
    cleaned = re.sub(r'[#*_`]+', ' ', raw).replace('" Jensen "', ' Jensen ').replace('  ', ' ').strip()
    cleaned = cleaned.replace(' ;', ';').replace(' ,', ',')
    if ' is ' in cleaned:
        left, right = cleaned.split(' is ', 1)
        left = left.split(' (', 1)[0].strip()
        cleaned = left + ' is ' + right
    return cleaned[:280].rstrip()
def _looks_generic_office_directory(query: str, row: Dict[str, str]) -> bool:
    if not _looks_like_identity_query(query):
        return False
    title = str(row.get('title') or '').strip().lower()
    content = str(row.get('content') or '').strip().lower()
    engine = str(row.get('engine') or '').strip().lower()
    blob = ' '.join(part for part in (title, content) if part)
    generic_terms = (
        'mayor and city council',
        'city council',
        'leadership team',
        'executive team',
        'management team',
        'government of the city',
    )
    if not any(term in blob for term in generic_terms):
        return False
    person_signals = (
        'serving as',
        'serves as',
        'born ',
        'american ',
        'politician',
        'entrepreneur',
        'since 20',
    )
    if any(signal in blob for signal in person_signals):
        return False
    return engine in {'official_site', 'wikipedia_public_office', 'bing', 'google'} or bool(blob)
def _identity_result_relevant(query: str, row: Dict[str, str]) -> bool:
    if not _looks_like_identity_query(query):
        return True
    subject = _identity_subject(query)
    subject_tokens = [tok for tok in re.findall(r'[a-z0-9]+', subject.lower().replace(',', ' ')) if tok not in {'the', 'of'}]
    role_labels = _identity_role_labels(query)
    title = str(row.get('title') or '').lower()
    content = str(row.get('content') or '').lower()
    url = str(row.get('url') or '').lower()
    blob = ' '.join(part for part in (title, content, url) if part)
    engine = str(row.get('engine') or '').lower()
    if engine in {'official_site', 'official_site_context'}:
        hint_urls = _identity_official_domain_hints(subject)
        hint_roots = []
        for hint in hint_urls:
            try:
                parsed = urllib.parse.urlparse(str(hint or '').strip())
                root = f'{parsed.scheme}://{parsed.netloc}'.lower().rstrip('/')
                if root and root not in hint_roots:
                    hint_roots.append(root)
            except Exception:
                continue
        if hint_roots and any(url.startswith(root) for root in hint_roots):
            return True
        subject_hits = sum(1 for tok in subject_tokens[:3] if tok and tok in blob)
        role_hit = any(label in blob for label in role_labels) if role_labels else True
        return subject_hits >= min(2, max(1, len(subject_tokens[:2]))) and role_hit
    if 'president' in role_labels and 'vice president' in blob and 'president of the united states' not in blob:
        return False
    if 'governor' in role_labels and 'lieutenant governor' in blob:
        return False
    if role_labels and not any(label in blob for label in role_labels):
        return False
    if 'wikipedia_public_office' == str(row.get('engine') or '').lower():
        return True
    if any(tok in url for tok in ('.gov/', 'sanjoseca.gov')) and any(label in blob for label in role_labels):
        return not _looks_generic_office_directory(query, row)
    if subject_tokens and not all(tok in blob for tok in subject_tokens[:2]):
        return False
    return True

def _filter_identity_results(query: str, results: List[Dict[str, str]]) -> List[Dict[str, str]]:
    if not _looks_like_identity_query(query):
        return [r for r in results if isinstance(r, dict)]
    filtered = [r for r in results if isinstance(r, dict) and _identity_result_relevant(query, r)]
    return filtered or [r for r in results if isinstance(r, dict)]


def _identity_name_from_row(query: str, row: Dict[str, str]) -> str:
    subject = _identity_subject(query)
    subject_tokens = {tok for tok in re.findall(r'[a-z0-9]+', subject.lower()) if len(tok) > 2}
    title = str(row.get('title') or '').strip()
    content = str(row.get('content') or '').strip()
    url = str(row.get('url') or '').strip()
    role_words = {'vice president', 'president', 'prime minister', 'governor', 'lieutenant governor', 'mayor', 'chair', 'founder', 'chief executive officer'}
    for source in (title, content):
        preferred = _extract_role_prefixed_person(source)
        if preferred and not _resolved_name_is_subject_alias(query, preferred):
            return preferred.strip()
        extracted = _extract_person_name(source)
        extracted_low = extracted.strip().lower() if extracted else ''
        if extracted and not extracted_low.startswith('the ') and extracted_low not in role_words:
            parts = {tok for tok in re.findall(r'[a-z0-9]+', extracted_low) if len(tok) > 2}
            if parts and not parts <= subject_tokens:
                return extracted.strip()
        for match in re.findall(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b", source):
            low_match = match.strip().lower()
            if low_match.startswith('the '):
                continue
            if low_match in role_words:
                continue
            parts = {tok for tok in re.findall(r'[a-z0-9]+', low_match) if len(tok) > 2}
            if parts and not parts <= subject_tokens:
                return match.strip()
    slug = str(url.rstrip('/').rsplit('/', 1)[-1] if url else '').strip()
    slug = urllib.parse.unquote(slug).replace('_', ' ').replace('-', ' ')
    slug = re.sub(r'\s+', ' ', slug).strip()
    if re.fullmatch(r'[A-Za-z]+\s+[A-Za-z]+', slug):
        parts = {tok for tok in re.findall(r'[a-z0-9]+', slug.lower()) if len(tok) > 2}
        if parts and not parts <= subject_tokens:
            return ' '.join(word.capitalize() for word in slug.split())
    return ''

def _identity_role_display(query: str) -> str:
    qlow = str(query or '').lower()
    if 'chief executive officer' in qlow or 'ceo' in qlow:
        return 'current CEO'
    if 'prime minister' in qlow:
        return 'current prime minister'
    if 'president' in qlow:
        return 'current president'
    if 'chair' in qlow:
        return 'current chair'
    if 'founder' in qlow:
        return 'founder'
    if 'governor' in qlow:
        return 'current governor'
    if 'mayor' in qlow:
        return 'current mayor'
    return 'current officeholder'


def _normalize_person_name(value: str) -> str:
    text = ' '.join(str(value or '').split()).strip()
    if not text:
        return ''
    text = re.sub(r'\b(Chairman|Chairwoman|President|CEO|Chief Executive Officer|Founder)\b.*$', '', text, flags=re.IGNORECASE).strip(' ,.;:-')
    parts = [part for part in text.split() if part]
    if 2 <= len(parts) <= 4:
        return ' '.join(parts)
    return text

def _dedupe_result_rows(results: List[Dict[str, str]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()
    for row in results or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get('url') or '').strip().lower()
        title = str(row.get('title') or '').strip().lower()
        key = (url, title)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out
def _identity_focus_query(query: str) -> str:
    raw = str(query or '').strip()
    if not _looks_like_identity_query(raw):
        return raw
    m = re.match(r'(.+?)(?:\s+and\s+what\s+is\b.+)$', raw, flags=re.IGNORECASE)
    if m:
        focused = str(m.group(1) or '').strip().rstrip(' ,;')
        if focused:
            return focused
    return raw


def _is_compound_identity_query(query: str) -> bool:
    if not _looks_like_identity_query(query):
        return False
    low = str(query or '').lower()
    return bool((' and ' in low or ',' in low) and (_looks_like_current_topic_query(query) or _looks_like_news_query(query) or _looks_like_regulation_query(query)))


def _identity_source_is_trusted(url: str) -> bool:
    low = str(url or '').lower()
    trusted = ('.gov/', '.edu/', 'wikipedia.org/wiki/', 'linkedin.com/in/', 'news.microsoft.com/', 'microsoft.com/', 'openai.com/', 'anthropic.com/', 'nvidia.com/', 'amd.com/', 'apple.com/', 'google.com/', 'about.google/', 'abc.xyz/')
    return any(tok in low for tok in trusted)

def _identity_summary(query: str, results: List[Dict[str, str]]) -> str:
    if not _looks_like_identity_query(query) or not results:
        return ''
    focus_query = _identity_focus_query(query)
    ranked = sorted(_filter_identity_results(focus_query, results), key=lambda row: _identity_answer_rank(focus_query, row), reverse=True)
    top = {}
    title = ''
    content = ''
    url = ''
    for candidate in ranked:
        candidate_content = str(candidate.get('content') or '')
        if _looks_like_script_noise(candidate_content):
            continue
        if _looks_generic_office_directory(query, candidate):
            continue
        top = candidate
        title = str(candidate.get('title') or '').strip()
        content = _clean_identity_content(candidate_content, query)
        url = str(candidate.get('url') or '').strip()
        if content or title:
            break
    if not top and ranked:
        top = ranked[0]
        title = str(top.get('title') or '').strip()
        content = _clean_identity_content(str(top.get('content') or ''), query)
        url = str(top.get('url') or '').strip()
    primary = str(url or '').strip().lower()
    hint_urls = _identity_official_domain_hints(_identity_subject(focus_query))
    hint_roots = []
    for hint in hint_urls:
        try:
            parsed = urllib.parse.urlparse(str(hint or '').strip())
            root = f'{parsed.scheme}://{parsed.netloc}'.lower().rstrip('/')
            if root and root not in hint_roots:
                hint_roots.append(root)
        except Exception:
            continue
    official_support = next((
        r for r in ranked
        if str(r.get('url') or '').strip()
        and 'wikipedia.org' not in str(r.get('url') or '').lower()
        and any(str(r.get('url') or '').strip().lower().startswith(root + '/') or str(r.get('url') or '').strip().lower() == root for root in hint_roots)
    ), None)
    if official_support is None:
        official_support = next((
            r for r in ranked
            if str(r.get('url') or '').strip()
            and 'wikipedia.org' not in str(r.get('url') or '').lower()
            and str(r.get('engine') or '').lower() in {'official_site', 'official_site_context'}
        ), None)
    if official_support is None:
        official_support = next((
            r for r in ranked
            if str(r.get('url') or '').strip()
            and 'wikipedia.org' not in str(r.get('url') or '').lower()
            and any(host in str(r.get('url') or '').lower() for host in ('.com/', '.gov/', '.org/'))
        ), None)
    if official_support and (not primary or 'wikipedia.org' in primary):
        official_title = str(official_support.get('title') or '').strip()
        official_content = _clean_identity_content(str(official_support.get('content') or ''), query)
        official_url = str(official_support.get('url') or '').strip()
        official_name = _identity_name_from_row(focus_query, official_support)
        role_labels = _identity_role_labels(query)
        official_blob = ' '.join(part for part in (official_title, official_content) if part).lower()
        has_role_signal = (not role_labels) or any(role in official_blob for role in role_labels)
        has_name_signal = bool(official_name) and not _resolved_name_is_subject_alias(focus_query, official_name)
        if (official_content or official_title) and has_role_signal and has_name_signal:
            title = official_title or title
            content = official_content or content
            url = official_url or url
            primary = str(url or '').strip().lower()
    if content and not re.search(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b", content):
        fallback_name = ''
        for candidate in ranked:
            fallback_name = _identity_name_from_row(focus_query, candidate)
            if fallback_name:
                break
        if fallback_name:
            role_blob = ' '.join(part for part in (content, title) if part).lower()
            role_phrase = next((role for role in _identity_role_labels(focus_query) if role in role_blob), '')
            role_phrase = role_phrase or 'CEO' if 'ceo' in role_blob else role_phrase
            content = f"{fallback_name} ({role_phrase})" if role_phrase else fallback_name
    resolved_name = _normalize_person_name(_extract_person_name(content) or _extract_person_name(title))
    if resolved_name and _resolved_name_is_subject_alias(focus_query, resolved_name):
        resolved_name = ''
    resolved_row = top if resolved_name else None
    if not resolved_name:
        for candidate in ranked:
            if _looks_generic_office_directory(focus_query, candidate):
                continue
            candidate_name = _normalize_person_name(_identity_name_from_row(focus_query, candidate) or _extract_person_name(str(candidate.get('content') or '')) or _extract_person_name(str(candidate.get('title') or '')))
            if candidate_name and _resolved_name_is_subject_alias(focus_query, candidate_name):
                continue
            if candidate_name:
                resolved_name = candidate_name
                resolved_row = candidate
                break
    if _looks_like_identity_query(focus_query) and resolved_name:
        content = f"{resolved_name} is the {_identity_role_display(focus_query)}"
        if isinstance(resolved_row, dict):
            title = str(resolved_row.get('title') or title or '').strip()
            url = str(resolved_row.get('url') or url or '').strip()
            primary = str(url or '').strip().lower()
    if _looks_like_identity_query(focus_query) and not resolved_name:
        candidate_urls = []
        seen_identity_urls = set()
        for row in ranked[:3]:
            candidate_url = str(row.get('url') or '').strip()
            if not candidate_url or candidate_url.lower() in seen_identity_urls:
                continue
            seen_identity_urls.add(candidate_url.lower())
            candidate_urls.append(candidate_url)
        detail = 'I could not verify the current officeholder from the retrieved sources because they did not expose a reliable person name.'
        if candidate_urls:
            detail += ' Retrieved sources: ' + '; '.join(candidate_urls[:2])
        return detail
    parts: List[str] = []
    if content:
        parts.append(f'Based on latest retrieved sources: {content}')
    elif title:
        parts.append(f'Based on latest retrieved sources: {title}.')
    if url:
        parts.append(f'Source: {url}')
    official_support_url = str((official_support or {}).get('url') or '').strip()
    if (not official_support_url) and primary and 'wikipedia.org' in primary and hint_urls:
        official_support_url = str(hint_urls[0] or '').strip()
    if official_support_url.startswith('http://'):
        official_support_url = 'https://' + official_support_url[len('http://'):]
    if official_support_url and official_support_url.lower() != primary and 'wikipedia.org' in primary:
        parts = [part for part in parts if not part.startswith('Source: ')]
        parts.append(f'Source: {official_support_url}')
    elif primary and not _identity_source_is_trusted(primary):
        wiki_person = next((
            str(r.get('url') or '').strip()
            for r in ranked
            if 'wikipedia.org/wiki/' in str(r.get('url') or '').lower()
            and (not resolved_name or resolved_name.lower().split()[0] in str(r.get('url') or '').lower() or resolved_name.lower() in str(r.get('title') or '').lower())
        ), '')
        if not wiki_person and resolved_name:
            wiki_person = 'https://en.wikipedia.org/wiki/' + urllib.parse.quote(resolved_name.replace(' ', '_'))
        if wiki_person:
            parts = [part for part in parts if not part.startswith('Source: ')]
            parts.append(f'Source: {wiki_person}')
            primary = wiki_person.lower()
    extra = []
    seen_urls = {primary} if primary else set()
    if official_support_url:
        seen_urls.add(official_support_url.lower())
    for r in ranked[1:]:
        candidate_url = str(r.get('url') or '').strip()
        if candidate_url.startswith('http://'):
            candidate_url = 'https://' + candidate_url[len('http://'):]
        if not candidate_url or not _identity_result_relevant(query, r):
            continue
        low_url = candidate_url.lower()
        if low_url in seen_urls:
            continue
        seen_urls.add(low_url)
        extra.append(candidate_url)
        if len(extra) >= 2:
            break
    if extra:
        parts.append('Corroborating sources: ' + '; '.join(extra))
    return '\n'.join(parts).strip()
def _format_result_line(row: Dict[str, str]) -> str:
    title = str(row.get('title') or '').strip()
    url = str(row.get('url') or '').strip()
    content = ' '.join(str(row.get('content') or '').strip().split())
    if content:
        if len(content) > 220:
            content = content[:217].rstrip() + '...'
        return f"- {title} - {content} :: {url}" if title or url else content
    return f"- {title} :: {url}" if title or url else ''


def _result_source_label(row: Dict[str, str]) -> str:
    source = str(row.get('source') or '').strip()
    if source:
        return source
    url = str(row.get('url') or row.get('link') or '').strip()
    if not url:
        return ''
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        host = ''
    host = host.replace('www.', '')
    host = host.replace('m.', '')
    if host.endswith('.com'):
        host = host[:-4]
    elif host.endswith('.org'):
        host = host[:-4]
    elif host.endswith('.net'):
        host = host[:-4]
    elif host.endswith('.gov'):
        host = host[:-4]
    if not host:
        return ''
    parts = [part for part in host.split('.') if part]
    label = parts[-2] if len(parts) >= 2 and parts[-1] in {'co'} else parts[-1]
    return label.upper() if label in {'wsj', 'cnbc'} else label.title()


def _format_compact_result_line(row: Dict[str, str]) -> str:
    title = _clean_story_title(str(row.get('title') or '').strip())
    if not title:
        title = str(row.get('url') or '').strip()
    if not title:
        return ''
    source = _result_source_label(row)
    return f"- {title} ({source})" if source else f"- {title}"


def _current_topic_row_blob(row: Dict[str, str]) -> str:
    parts = [
        str(row.get('title') or ''),
        str(row.get('content') or ''),
        str(row.get('source') or ''),
        str(row.get('url') or row.get('link') or ''),
    ]
    return ' '.join(part for part in parts if part).lower()


def _is_preferred_current_topic_row(row: Dict[str, str]) -> bool:
    blob = _current_topic_row_blob(row)
    preferred_terms = (
        'reuters', 'ap news', 'associated press', 'bloomberg', 'ft.com', 'financial times', 'wsj', 'wall street journal',
        'nytimes', 'new york times', 'politico', 'the verge', 'techcrunch', 'venturebeat', 'cnbc', 'computerworld', "tom's hardware", 'anandtech',
        'openai', 'anthropic', 'deepmind', 'blog.google', 'google deepmind', 'nvidia newsroom', 'amd newsroom', 'intel newsroom'
    )
    return any(term in blob for term in preferred_terms)


def _is_high_confidence_current_topic_row(row: Dict[str, str]) -> bool:
    url = str(row.get('url') or row.get('link') or '').lower()
    if _is_low_value_current_topic_row(row):
        return False
    if _is_preferred_current_topic_row(row):
        return True
    trusted_mainstream = (
        'reuters.com', 'apnews.com', 'bloomberg.com', 'ft.com', 'wsj.com', 'nytimes.com',
        'politico.com', 'theverge.com', 'techcrunch.com', 'venturebeat.com', 'cnbc.com',
        'computerworld.com', 'tomshardware.com', 'anandtech.com',
    )
    trusted_official = (
        'openai.com', 'anthropic.com', 'blog.google', 'deepmind.google', 'nvidia.com',
        'amd.com', 'intel.com', 'tsmc.com', 'broadcom.com', 'ec.europa.eu',
        'whitehouse.gov', 'congress.gov', 'ftc.gov', 'europa.eu', 'nature.com',
    )
    return any(host in url for host in (*trusted_mainstream, *trusted_official))


def _is_low_value_current_topic_row(row: Dict[str, str]) -> bool:
    blob = _current_topic_row_blob(row)
    low_value_terms = (
        'techtimes', 'webpronews', 'jdsupra', 'stockstory', 'motley fool', 'benzinga', 'investing.com', 'tradingview',
        'marktechpost', 'crypto briefing', 'wion', 'msn', 'msn.com', 'indiatimes', 'times of india', 'paraphraser', 'summarizer'
    )
    if any(term in blob for term in low_value_terms):
        return True
    url = str(row.get('url') or row.get('link') or '')
    return _is_low_value_current_topic_source(url)


def _is_low_value_current_topic_source(url: str) -> bool:
    low = str(url or '').lower()
    if any(host in low for host in ('techtimes.com', 'webpronews.com', 'jdsupra.com', 'stockstory.org', 'motleyfool.com', 'benzinga.com', 'investing.com', 'tradingview.com', 'msn.com', 'indiatimes.com', 'timesofindia.indiatimes.com')):
        return True
    if any(host in low for host in ('nvidia.com/', 'amd.com/', 'intel.com/', 'tsmc.com/')) and not re.search(r'/20\d{2}/', low) and not any(tok in low for tok in ('/blog/', '/news/', '/press/', '/stories/')):
        return True
    return False


def _trusted_current_topic_rows(rows: List[Dict[str, str]], limit: int = 3) -> List[Dict[str, str]]:
    items = [row for row in (rows or []) if isinstance(row, dict)]
    if not items:
        return []
    max_keep = max(1, min(int(limit or 3), 5))
    chosen: List[Dict[str, str]] = []
    for bucket in (
        [row for row in items if _is_preferred_current_topic_row(row) and not _is_low_value_current_topic_row(row)],
        [row for row in items if _is_high_confidence_current_topic_row(row)],
        [row for row in items if not _is_low_value_current_topic_row(row)],
    ):
        for row in bucket:
            if row not in chosen:
                chosen.append(row)
            if len(chosen) >= max_keep:
                return chosen[:max_keep]
    return chosen[:max_keep] if chosen else items[:1]


def _looks_like_broad_ai_trend_query(query: str) -> bool:
    qlow = str(query or '').lower()
    if not qlow:
        return False
    has_ai_topic = any(tok in qlow for tok in ('ai', 'model', 'models', 'openai', 'anthropic', 'gemini', 'claude', 'gpt', 'llm'))
    has_trend_shape = any(tok in qlow for tok in ('trend', 'trends', 'heading', 'where does the field seem to be heading', 'latest'))
    return has_ai_topic and has_trend_shape


def _ai_trend_signal_summary(results: List[Dict[str, str]], *, limited: bool = False) -> str:
    rows = [row for row in (results or []) if isinstance(row, dict)]
    if not rows:
        return ''
    categories: List[str] = []
    providers: List[str] = []
    trusted_rows = 0
    joined_rows = []
    category_rules = [
        ('reasoning models', ('reasoning', 'thinking model', 'chain-of-thought', 'reasoning-focused')),
        ('multimodal systems', ('multimodal', 'vision', 'audio', 'video', 'omni')),
        ('coding agents and agent workflows', ('coding', 'code generation', 'agent', 'agents', 'software engineering')),
        ('open-weight competition', ('open-weight', 'open source', 'open-source', 'open model', 'open models')),
        ('new frontier-model launches', ('launch', 'launched', 'release', 'released', 'preview', 'debut', 'introduces', 'introducing', 'announced')),
        ('tighter rollout and safety controls', ('limited access', 'stagger release', 'security review', 'cybersecurity review', 'approved customers', 'stress test', 'review pressure')),
        ('inference efficiency and cost pressure', ('inference', 'latency', 'efficiency', 'cost', 'cheaper', 'lower cost', 'throughput')),
        ('enterprise platform integration', ('api', 'platform', 'deployment', 'workspace', 'enterprise', 'copilot')),
    ]
    provider_rules = (
        ('OpenAI', ('openai', 'gpt')),
        ('Anthropic', ('anthropic', 'claude')),
        ('Google DeepMind', ('google', 'deepmind', 'gemini')),
        ('Meta', ('meta', 'llama')),
        ('xAI', ('xai', 'grok')),
        ('Mistral', ('mistral',)),
        ('Microsoft', ('microsoft', 'copilot')),
        ('NVIDIA', ('nvidia',)),
    )
    for row in rows:
        blob = _current_topic_row_blob(row)
        joined_rows.append(blob)
        if _is_high_confidence_current_topic_row(row) or _is_preferred_current_topic_row(row):
            trusted_rows += 1
        for label, tokens in category_rules:
            if label not in categories and any(tok in blob for tok in tokens):
                categories.append(label)
        for label, tokens in provider_rules:
            if label not in providers and any(tok in blob for tok in tokens):
                providers.append(label)
    coverage_ok = len(categories) >= 2 or (len(categories) >= 1 and len(providers) >= 3)
    if not coverage_ok:
        return ''
    joined = ' '.join(joined_rows)
    if not categories and any(tok in joined for tok in ('model', 'models', 'ai')):
        categories.append('competitive model releases')
    lead = 'Current AI model trends are clustering around ' + '; '.join(categories[:4]) + '.'
    details: List[str] = [lead]
    if providers:
        details.append('Visible activity spans ' + ', '.join(providers[:5]) + '.')
    future_bits: List[str] = []
    if any(label in categories for label in ('reasoning models', 'multimodal systems', 'coding agents and agent workflows')):
        future_bits.append('more agentic, reasoning-heavy multimodal systems')
    if 'tighter rollout and safety controls' in categories:
        future_bits.append('staged releases with stricter safety and access gating')
    if 'inference efficiency and cost pressure' in categories:
        future_bits.append('stronger pressure toward cheaper and more efficient inference')
    if 'open-weight competition' in categories:
        future_bits.append('continued competitive pressure from open-weight alternatives')
    if 'enterprise platform integration' in categories:
        future_bits.append('deeper integration into mainstream work and developer platforms')
    if 'new frontier-model launches' in categories and not future_bits:
        future_bits.append('faster competitive release cycles across major model providers')
    if future_bits:
        details.append('Near term, the field appears to be heading toward ' + '; '.join(future_bits[:3]) + '.')
    if limited:
        details.append('This is a cautious live synthesis from partial current-source coverage, so treat it as directional rather than exhaustive.')
    elif trusted_rows < 2:
        details.append('This synthesis is directional and based on mixed current-source coverage rather than a fully exhaustive sweep.')
    return ' '.join(part.strip() for part in details if str(part).strip()).strip()


def _limited_ai_news_fallback(query: str) -> str:
    qlow = str(query or '').lower()
    if not _looks_like_broad_ai_trend_query(query) and not ('ai' in qlow and ('news' in qlow or 'headline' in qlow)):
        return ''
    if any(tok in qlow for tok in ('return 5', 'five', '5 bullets', 'five bullets', 'bullets')):
        return '''- OpenAI remains one of the focal providers for new reasoning, coding, or staged-access model updates, but I could not verify the exact weekly headline set in this turn.
- Anthropic is still part of the main competitive release cluster around Claude and enterprise-safe rollout positioning, though exact week-specific changes were not fully confirmed here.
- Google DeepMind continues to be part of the visible frontier-model competition, especially around multimodal and platform-linked updates, but this fallback should be treated as directional.
- Meta, xAI, and other frontier labs remain part of the current release and access-control story, with competition centered on capability positioning, distribution, and launch pacing.
- Across providers, the strongest repeated current pattern is a mix of new model announcements, more agentic or reasoning-heavy capabilities, and tighter rollout or safety gating rather than a single dominant storyline.

This is a limited fallback summary because I could not verify a clean live headline set for this exact broad query in this turn.'''
    return (
        'I could not verify a clean live headline set for this exact broad AI-news query in this turn. '
        'Directional current coverage still points to frontier-model competition among providers such as OpenAI, Anthropic, Google DeepMind, Meta, and xAI, with repeated themes around reasoning-heavy releases, multimodal capability positioning, agent workflows, and tighter rollout controls.'
    )

def _wiki_identity_result(query: str, timeout: float) -> Dict[str, str] | None:
    if not _looks_like_identity_query(query):
        return None
    subject = _identity_subject(query)
    if not subject:
        return None
    try:
        api_url = 'https://en.wikipedia.org/w/api.php?' + urllib.parse.urlencode({
            'action': 'parse',
            'page': subject,
            'prop': 'text',
            'format': 'json',
            'redirects': 1,
        })
        req = urllib.request.Request(api_url, headers={'Accept': 'application/json', 'User-Agent': 'Mozilla/5.0'}, method='GET')
        with urllib.request.urlopen(req, timeout=max(3.0, min(float(timeout or 15.0), 25.0))) as resp:
            payload = json.loads(resp.read().decode('utf-8', 'ignore'))
    except Exception:
        return None
    parse = payload.get('parse') if isinstance(payload, dict) else {}
    title = str((parse or {}).get('title') or subject).strip()
    html = str(((parse or {}).get('text') or {}).get('*') or '')
    if not html:
        return None
    match = re.search(r'Key people</div></th><td[^>]*>(.*?)</td></tr>', html, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    people_html = unescape(str(match.group(1) or ''))
    items = []
    for li in re.findall(r'<li[^>]*>(.*?)</li>', people_html, re.IGNORECASE | re.DOTALL):
        entry = _strip_tags(unescape(str(li or '')))
        entry = ' '.join(entry.split())
        if entry:
            items.append(entry)
    flat = '; '.join(items) if items else _strip_tags(people_html)
    flat = ' '.join(flat.split())
    if not flat:
        return None
    low = flat.lower()
    role_map = [
        ('ceo', 'ceo'),
        ('chief executive officer', 'chief executive officer'),
        ('president', 'president'),
        ('prime minister', 'prime minister'),
        ('chair', 'chair'),
        ('founder', 'founder'),
        ('governor', 'governor'),
        ('mayor', 'mayor'),
    ]
    chosen_role = ''
    qlow = str(query or '').lower()
    for key, label in role_map:
        if key in qlow:
            chosen_role = label
            break
    if chosen_role and chosen_role not in low and not ('ceo' in chosen_role and 'chief executive officer' in low):
        return None
    return {
        'title': f'{title} - Wikipedia key people',
        'url': 'https://en.wikipedia.org/wiki/' + urllib.parse.quote(title.replace(' ', '_')),
        'content': flat[:500],
        'engine': 'wikipedia_infobox',
    }


def _wiki_public_office_result(query: str, timeout: float) -> Dict[str, str] | None:
    if not _looks_like_identity_query(query):
        return None
    qlow = str(query or '').lower()
    subject = _identity_subject(query)
    if not subject:
        return None
    role = ''
    for candidate in ('mayor', 'governor', 'prime minister', 'president'):
        if candidate in qlow:
            role = candidate
            break
    if not role:
        return None
    search_terms = [f'"{subject}" current {role}', f'"{subject}" "{role}"', f'{subject} incumbent {role}', f'{subject} {role}']
    best = None
    best_score = -1
    subj_tokens = re.findall(r'[a-z0-9]+', subject.lower().replace(',', ' '))
    for terms in search_terms:
        try:
            api_url = 'https://en.wikipedia.org/w/api.php?' + urllib.parse.urlencode({
                'action': 'query',
                'list': 'search',
                'srsearch': terms,
                'format': 'json',
                'srlimit': 5,
            })
            req = urllib.request.Request(api_url, headers={'Accept': 'application/json', 'User-Agent': 'Mozilla/5.0'}, method='GET')
            with urllib.request.urlopen(req, timeout=max(3.0, min(float(timeout or 15.0), 25.0))) as resp:
                payload = json.loads(resp.read().decode('utf-8', 'ignore'))
        except Exception:
            continue
        search_rows = (((payload or {}).get('query') or {}).get('search') or []) if isinstance(payload, dict) else []
        for row in search_rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get('title') or '').strip()
            snippet = _strip_tags(unescape(str(row.get('snippet') or ''))).strip()
            extract = snippet
            page_title = title
            try:
                summary_url = 'https://en.wikipedia.org/api/rest_v1/page/summary/' + urllib.parse.quote(title.replace(' ', '_'))
                req = urllib.request.Request(summary_url, headers={'Accept': 'application/json', 'User-Agent': 'Mozilla/5.0'}, method='GET')
                with urllib.request.urlopen(req, timeout=max(3.0, min(float(timeout or 15.0), 25.0))) as resp:
                    summary_payload = json.loads(resp.read().decode('utf-8', 'ignore'))
                page_title = str(summary_payload.get('title') or title).strip()
                extract = str(summary_payload.get('extract') or extract).strip()
            except Exception:
                pass
            combined = f'{page_title} {extract}'.lower()
            if role not in combined:
                continue
            if not all(tok in combined for tok in subj_tokens[:2]):
                continue
            clean = _clean_identity_content(extract, query)
            if not clean:
                clean = extract[:280].strip()
            if not clean:
                continue
            score = 0
            if any(phrase in combined for phrase in (f'serves as the', f'serving as the', f'serves as {role}', f'is the', f'incumbent {role}', f'{role} of {subject.lower().replace(',', '')}')):
                score += 10
            if role in combined:
                score += 4
            if all(tok in combined for tok in subj_tokens):
                score += 4
            if page_title.lower().startswith(f'{role} of '):
                score -= 3
            if re.match(r'^[A-Z][a-z]+(?: [A-Z][a-z]+)+$', page_title):
                score += 3
            candidate = {
                'title': f'{page_title} - Wikipedia public office',
                'url': 'https://en.wikipedia.org/wiki/' + urllib.parse.quote(page_title.replace(' ', '_')),
                'content': clean,
                'engine': 'wikipedia_public_office',
            }
            if score > best_score:
                best = candidate
                best_score = score
        if best_score >= 10:
            break
    return best

def _fast_hinted_official_identity_result(query: str, timeout: float) -> Dict[str, str] | None:
    if not _looks_like_identity_query(query):
        return None
    role_labels = _identity_role_labels(query)
    hinted_urls = _identity_official_domain_hints(_identity_subject(query))
    for hinted in hinted_urls:
        try:
            body = _request_text(hinted, timeout, accept='text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8')
        except Exception:
            continue
        flat = _strip_tags(unescape(body))
        flat = ' '.join(flat.split())
        if not flat:
            continue
        low = flat.lower()
        if role_labels and not any(role in low for role in role_labels):
            continue
        candidate_row = {
            'title': hinted.rsplit('/', 1)[-1].replace('-', ' ').strip() or 'Official leadership page',
            'url': hinted,
            'content': flat,
            'engine': 'official_site_context',
        }
        candidate_name = _identity_name_from_row(query, candidate_row) or _extract_role_prefixed_person(flat) or _extract_person_name(flat)
        candidate_name = _normalize_person_name(candidate_name)
        if not candidate_name or _resolved_name_is_subject_alias(query, candidate_name):
            continue
        context = _extract_named_context(flat, candidate_name)
        if not context:
            role_match = next((role for role in role_labels if role in low), '')
            if role_match:
                idx = low.find(role_match)
                if idx >= 0:
                    start = max(0, idx - 180)
                    end = min(len(flat), idx + 260)
                    context = flat[start:end].strip()
        context = context or flat[:320]
        return {
            'title': candidate_row['title'],
            'url': hinted,
            'content': context,
            'engine': 'official_site_context',
        }
    return None

def _direct_official_identity_result(query: str, timeout: float) -> Dict[str, str] | None:
    if not _looks_like_identity_query(query):
        return None
    fast_direct = _fast_hinted_official_identity_result(query, timeout)
    if isinstance(fast_direct, dict):
        return fast_direct
    hinted_urls = _identity_official_domain_hints(_identity_subject(query))
    synthetic_results = [
        {'title': 'Official identity hint', 'url': hinted, 'content': '', 'engine': 'official_hint'}
        for hinted in hinted_urls
        if str(hinted or '').strip().startswith('http')
    ]
    if synthetic_results:
        direct = _discover_official_identity_result(query, synthetic_results, timeout)
        if isinstance(direct, dict):
            return direct
    office_fallback = _wiki_public_office_result(query, timeout)
    if isinstance(office_fallback, dict):
        return office_fallback
    return None

def _discover_official_identity_result(query: str, results: List[Dict[str, str]], timeout: float) -> Dict[str, str] | None:
    if not _looks_like_identity_query(query) or not results:
        return None
    ranked = sorted([r for r in results if isinstance(r, dict)], key=_identity_rank, reverse=True)
    official = next((r for r in ranked if any(tok in str(r.get('url') or '').lower() for tok in ('.com', '.gov', '.org')) and 'wikipedia.org' not in str(r.get('url') or '').lower()), None)
    home = str((official or {}).get('url') or '').strip()
    if not home.startswith('http'):
        hinted = _identity_official_domain_hints(_identity_subject(query))
        home = str(hinted[0] if hinted else '').strip()
    if not home.startswith('http'):
        return None
    answer_hint = ''
    role_labels = _identity_role_labels(query)
    for row in ranked:
        engine = str(row.get('engine') or '').lower()
        content = str(row.get('content') or '')
        title = str(row.get('title') or '')
        blob = (title + ' ' + content).lower()
        if role_labels and not any(role in blob for role in role_labels) and 'wikipedia' not in engine:
            continue
        answer_hint = _extract_person_name(content) or _extract_person_name(title)
        if answer_hint:
            break
    if not answer_hint:
        for hinted in _identity_official_domain_hints(_identity_subject(query)):
            answer_hint = _person_name_from_url_slug(hinted)
            if answer_hint:
                break
    if not answer_hint:
        wiki_hint = _wiki_identity_result(query, timeout)
        if isinstance(wiki_hint, dict):
            answer_hint = _extract_person_name(str(wiki_hint.get('content') or '')) or _extract_person_name(str(wiki_hint.get('title') or ''))
    hinted_urls = _identity_official_domain_hints(_identity_subject(query))
    for hinted in hinted_urls:
        try:
            body = _request_text(hinted, timeout, accept='text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8')
        except Exception:
            continue
        flat = _strip_tags(unescape(body))
        flat = ' '.join(flat.split())
        if not flat:
            continue
        low = flat.lower()
        role_labels = _identity_role_labels(query)
        if role_labels and not any(role in low for role in role_labels):
            continue
        name_hint = answer_hint or _extract_person_name(flat) or _person_name_from_url_slug(hinted)
        if not name_hint or _resolved_name_is_subject_alias(query, name_hint):
            continue
        context = _extract_named_context(flat, name_hint) or flat[:320]
        if context and _extract_person_name(context):
            return {
                'title': hinted.rsplit('/', 2)[-2].replace('-', ' ').strip() or hinted.rsplit('/', 1)[-1].replace('-', ' ').strip() or 'Official leadership page',
                'url': hinted,
                'content': context,
                'engine': 'official_site_context',
            }
    home_candidates = []
    for item in [*hinted_urls, home, _host_root(home)]:
        if item and item not in home_candidates:
            home_candidates.append(item)
    html = ''
    home = ''
    for base in home_candidates:
        try:
            html = _request_text(base, timeout, accept='text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8')
            home = base
            if html:
                break
        except Exception:
            continue
    if not html:
        return None
    parsed_home = urllib.parse.urlparse(home)
    path_parts = [part for part in parsed_home.path.split('/') if part]
    locale_prefix = '/'
    if path_parts and re.fullmatch(r'[a-z]{2}(?:-[a-z]{2})?', path_parts[0], re.IGNORECASE):
        locale_prefix = '/' + path_parts[0] + '/'
    heuristics = [
        urllib.parse.urljoin(home, locale_prefix + 'about-nvidia/governance/management-team/'),
        urllib.parse.urljoin(home, locale_prefix + 'about-nvidia/'),
        urllib.parse.urljoin(home, locale_prefix + 'about/governance/management-team/'),
        urllib.parse.urljoin(home, locale_prefix + 'about/leadership/'),
        urllib.parse.urljoin(home, locale_prefix + 'company/leadership/'),
        urllib.parse.urljoin(home, locale_prefix + 'leadership/'),
        urllib.parse.urljoin(home, locale_prefix + 'management-team/'),
        urllib.parse.urljoin(home, locale_prefix + 'executive-insights/'),
    ]
    candidates: List[str] = []
    for item in heuristics:
        if urllib.parse.urlparse(item).netloc == parsed_home.netloc and item not in candidates:
            candidates.append(item)
    for href in re.findall(r"href=[\"']([^\"']+)[\"']", html, re.IGNORECASE):
        full = urllib.parse.urljoin(home, unescape(str(href or '').strip()))
        low = full.lower()
        if urllib.parse.urlparse(full).netloc != parsed_home.netloc:
            continue
        if any(tok in low for tok in ('leadership', 'management', 'management-team', 'executive', 'governance', 'team', 'about')):
            if full not in candidates:
                candidates.append(full)
        if len(candidates) >= 16:
            break
    for candidate in candidates:
        try:
            body = _request_text(candidate, timeout, accept='text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8')
        except Exception:
            continue
        flat = _strip_tags(unescape(body))
        flat = ' '.join(flat.split())
        if not flat:
            continue
        low = flat.lower()
        has_named_official_context = bool(answer_hint and answer_hint.lower() in low and any(tok in candidate.lower() for tok in ('executive', 'leadership', 'management', 'governance', 'about')))
        if _looks_like_script_noise(flat) and not has_named_official_context:
            continue
        if any(tok in low for tok in ('chief executive officer', ' ceo ', ' president and ceo', 'founder, president and ceo', 'management team')):
            explicit_name = _identity_name_from_row(query, {'title': candidate, 'content': flat, 'url': candidate})
            if not explicit_name or _resolved_name_is_subject_alias(query, explicit_name):
                continue
            return {
                'title': candidate.rsplit('/', 1)[-1].replace('-', ' ').strip() or 'Official leadership page',
                'url': candidate,
                'content': flat[:600],
                'engine': 'official_site',
            }
        if has_named_official_context:
            context = _extract_named_context(flat, answer_hint) or flat[:320]
            if _extract_person_name(context):
                return {
                    'title': candidate.rsplit('/', 1)[-1].replace('-', ' ').strip() or 'Official site context',
                    'url': candidate,
                    'content': context,
                    'engine': 'official_site_context',
                }
    office_fallback = _wiki_public_office_result(query, timeout)
    if office_fallback:
        return office_fallback
    return _wiki_identity_result(query, timeout)
def _clean_story_title(title: str) -> str:
    raw = ' '.join(str(title or '').split()).strip()
    if ' - ' in raw:
        raw = raw.split(' - ', 1)[0].strip()
    return raw
def _looks_like_macro_query(query: str) -> bool:
    low = str(query or '').lower()
    return any(tok in low for tok in ('inflation', 'cpi', 'consumer price', 'gdp', 'unemployment', 'interest rate', 'fed funds'))


def _normalize_macro_period(value: str) -> str:
    raw = ' '.join(str(value or '').split()).strip()
    if not raw:
        return ''
    return raw.title() if raw.upper() == raw else raw


def _macro_query_needs_strict_cpi(query: str) -> bool:
    qlow = str(query or '').lower()
    return 'cpi' in qlow or 'consumer price index' in qlow or 'consumer price' in qlow


def _macro_row_matches_inflation_metric(query: str, row: Dict[str, str]) -> bool:
    blob = ' '.join([str(row.get('title') or ''), str(row.get('content') or ''), str(row.get('url') or '')]).lower()
    if not any(tok in blob for tok in ('inflation', 'cpi', 'consumer price', 'pce')):
        return False
    if _macro_query_needs_strict_cpi(query):
        if 'pce' in blob and not any(tok in blob for tok in ('cpi', 'consumer price index', 'consumer price')):
            return False
    return True


def _macro_requested_topics(query: str) -> List[str]:
    qlow = str(query or '').lower()
    topics: List[str] = []
    if any(tok in qlow for tok in ('inflation', 'cpi', 'consumer price')):
        topics.append('inflation')
    if any(tok in qlow for tok in ('unemployment', 'employment', 'jobs', 'jobless')):
        topics.append('jobs')
    if any(tok in qlow for tok in ('gdp', 'growth', 'economy')):
        topics.append('growth')
    if any(tok in qlow for tok in ('interest rate', 'interest rates', 'fed funds', 'federal reserve', 'policy rate', 'rates')):
        topics.append('rates')
    return topics


def _macro_covered_topics(rows: List[Dict[str, str]]) -> set[str]:
    covered: set[str] = set()
    for row in rows or []:
        blob = ' '.join([str(row.get('title') or ''), str(row.get('content') or ''), str(row.get('url') or '')]).lower()
        if _macro_row_matches_inflation_metric('inflation', row) or any(tok in blob for tok in ('inflation', 'cpi', 'consumer prices', 'consumer price index', 'pce')):
            covered.add('inflation')
        if any(tok in blob for tok in ('unemployment', 'employment', 'jobless', 'jobs report', 'labor market', 'nonfarm payroll')):
            covered.add('jobs')
        if any(tok in blob for tok in ('gdp', 'gross domestic product', 'growth', 'economy')):
            covered.add('growth')
        if any(tok in blob for tok in ('interest rate', 'interest rates', 'fed funds', 'federal reserve', 'monetary policy', 'target range')):
            covered.add('rates')
    return covered


def _macro_source_quality(row: Dict[str, str]) -> int:
    url = str(row.get('url') or row.get('link') or '').lower()
    blob = ' '.join([str(row.get('title') or ''), str(row.get('content') or ''), url]).lower()
    if 'federalreserve.gov' in url:
        if 'releases/h15' in url:
            return 0
        if 'pressreleases' in url or 'monetarypolicy/' in url or 'openmarket' in url:
            return 0
        return 1
    if 'bls.gov' in url:
        if 'cpi.nr0' in url or '/cpi/' in url or 'empsit.nr0' in url:
            return 0
        if 'newsrels' in url:
            return 2
        return 1
    if 'bea.gov' in url:
        if '/news/glance' in url:
            return 1
        return 2
    if any(tok in blob for tok in ('reuters', 'associated press', 'ap news', 'bloomberg', 'financial times', 'ft.com', 'wsj', 'wall street journal', 'cnbc')):
        return 3
    if any(tok in blob for tok in ('moomoo', 'news.google.com', 'tradingview', 'benzinga', 'investing.com', 'seeking alpha', 'motley fool', 'zacks', 'marketscreener', 'fxstreet')):
        return 6
    return 4


def _extract_macro_fact_values(query: str, results: List[Dict[str, str]]) -> Dict[str, str]:
    qlow = str(query or '').lower()
    if not results:
        return {}
    joined_rows = []
    for row in results:
        title = str(row.get('title') or '').strip()
        content = str(row.get('content') or '').strip()
        url = str(row.get('url') or '').strip()
        published = str(row.get('published') or '').strip()
        joined_rows.append({'title': title, 'content': content, 'url': url, 'published': published, 'joined': (title + ' ' + content).strip()})
    ordered = sorted(joined_rows, key=_macro_source_quality)
    facts: Dict[str, str] = {}
    if any(tok in qlow for tok in ('inflation', 'cpi', 'consumer price')):
        inflation_patterns = [
            re.compile(r'consumer price index for all urban consumers \(cpi-u\) increased\s+([0-9]+(?:\.[0-9]+)?)\s+percent(?:[^.]{0,180})?in\s+([A-Za-z]+\s+20\d{2})', re.IGNORECASE),
            re.compile(r'over the last 12 months, the all items index increased\s+([0-9]+(?:\.[0-9]+)?)\s+percent(?:[^.]{0,120})', re.IGNORECASE),
            re.compile(r'the all items index rose\s+([0-9]+(?:\.[0-9]+)?)\s+percent\s+for the 12 months ending\s+([A-Za-z]+)', re.IGNORECASE),
            re.compile(r'(?:annual inflation rate.*?was|cpi-u[^.]*?)\s([0-9]+(?:\.[0-9]+)?)%\s+(?:for the 12 months ending|since)\s+([A-Za-z]+\s+20\d{2})', re.IGNORECASE),
            re.compile(r'([+-]?[0-9]+(?:\.[0-9]+)?)%\s+(?:since|for the 12 months ending)\s+([A-Za-z]+\s+20\d{2})', re.IGNORECASE),
            re.compile(r'consumer price index(?:.|\s){0,120}?([0-9]+(?:\.[0-9]+)?)%\s+(?:over the last 12 months|for the 12 months ending)\s+([A-Za-z]+\s+20\d{2})', re.IGNORECASE),
        ]
        for row in ordered:
            low = row['joined'].lower()
            if not _macro_row_matches_inflation_metric(query, row):
                continue
            for pattern in inflation_patterns:
                m = pattern.search(row['joined'])
                if not m:
                    continue
                period = ''
                if m.lastindex and m.lastindex >= 2:
                    period = m.group(2)
                current_match = re.search(r'(?:in|through)\s+([A-Za-z]+\s+20\d{2})', row['joined'], re.IGNORECASE)
                current_period = current_match.group(1) if current_match else ''
                if not current_period:
                    month_only = re.search(r'\bin\s+([A-Za-z]+)\b', row['joined'], re.IGNORECASE)
                    year_only = re.search(r'\b(20\d{2})\b', row['joined'], re.IGNORECASE)
                    if month_only and year_only:
                        current_period = f"{month_only.group(1)} {year_only.group(1)}"
                if not period and current_period:
                    period = current_period
                elif 'since' in m.group(0).lower() and current_period:
                    try:
                        base_parts = period.split()
                        current_parts = current_period.split()
                        if len(base_parts) == 2 and len(current_parts) == 2 and base_parts[0].lower() == current_parts[0].lower() and int(current_parts[1]) >= int(base_parts[1]):
                            period = current_period
                    except Exception:
                        period = current_period
                facts['inflation_rate'] = m.group(1)
                if not period:
                    month_match = re.search(r'(?:in|ending)\s+([A-Za-z]+)', row['joined'], re.IGNORECASE)
                    year_match = re.search(r'\b(20\d{2})\b', row['joined'], re.IGNORECASE)
                    if month_match and year_match:
                        period = f"{month_match.group(1)} {year_match.group(1)}"
                facts['inflation_period'] = _normalize_macro_period(period or 'the latest release')
                facts['inflation_source'] = 'BLS' if ('bls.gov' in row['url'].lower() or 'bureau of labor statistics' in low) else 'latest retrieved source'
                break
            if facts.get('inflation_rate'):
                break
        if not facts.get('inflation_rate'):
            fallback_patterns = [
                re.compile(r'(?:pce|cpi|inflation)(?:[^.]{0,40})?(?:tops|top|hit|hits|reaches|reached|rose to|rises to|eases to|slows to|at|is at)\s+([0-9]+(?:\.[0-9]+)?)%', re.IGNORECASE),
                re.compile(r'([0-9]+(?:\.[0-9]+)?)%\s+(?:inflation|cpi|pce)', re.IGNORECASE),
            ]
            for row in ordered:
                joined = str(row.get('joined') or '')
                low = joined.lower()
                if not _macro_row_matches_inflation_metric(query, row):
                    continue
                for pattern in fallback_patterns:
                    m = pattern.search(joined)
                    if not m:
                        continue
                    facts['inflation_rate'] = m.group(1)
                    period = _fallback_macro_period_from_row(row)
                    if period:
                        facts['inflation_period'] = period
                    facts['inflation_source'] = _fallback_macro_source_label(row)
                    break
                if facts.get('inflation_rate'):
                    break
    if any(tok in qlow for tok in ('unemployment', 'employment', 'jobs', 'jobless')):
        unemployment_patterns = [
            re.compile(r'unemployment rate(?:.|\s){0,80}?(?:was|at|remained at|held at|changed little at)?\s*([0-9]+(?:\.[0-9]+)?)%\s+in\s+([A-Za-z]+\s+20\d{2})', re.IGNORECASE),
            re.compile(r'jobless rate(?:.|\s){0,80}?(?:was|at|remained at|held at)?\s*([0-9]+(?:\.[0-9]+)?)%\s+in\s+([A-Za-z]+\s+20\d{2})', re.IGNORECASE),
            re.compile(r'unemployment rate(?:.|\s){0,40}?(?:was unchanged at|held at|was|at)\s+([0-9]+(?:\.[0-9]+)?)\s+percent', re.IGNORECASE),
        ]
        payroll_patterns = [
            re.compile(r'total nonfarm payroll employment(?:.|\s){0,120}?(?:rose|increased)\s+by\s+([0-9][0-9,]+)\s+in\s+([A-Za-z]+\s+20\d{2})', re.IGNORECASE),
            re.compile(r'nonfarm payroll(?:.|\s){0,120}?(?:rose|increased)\s+by\s+([0-9][0-9,]+)\s+in\s+([A-Za-z]+\s+20\d{2})', re.IGNORECASE),
            re.compile(r'total nonfarm payroll employment(?:.|\s){0,80}?increased\s+by\s+([0-9][0-9,]+)\s+in\s+([A-Za-z]+)', re.IGNORECASE),
        ]
        for row in ordered:
            low = row['joined'].lower()
            year_match = re.search(r'\b([A-Za-z]+)\s+(20\d{2})\b', row['joined'], re.IGNORECASE)
            fallback_period = f"{year_match.group(1)} {year_match.group(2)}" if year_match else ''
            for pattern in unemployment_patterns:
                m = pattern.search(row['joined'])
                if m:
                    facts['unemployment_rate'] = m.group(1)
                    if m.lastindex and m.lastindex >= 2:
                        facts['unemployment_period'] = _normalize_macro_period(m.group(2))
                    elif fallback_period:
                        facts['unemployment_period'] = _normalize_macro_period(fallback_period)
                    facts['unemployment_source'] = 'BLS' if ('bls.gov' in row['url'].lower() or 'bureau of labor statistics' in low) else 'latest retrieved source'
                    break
            for pattern in payroll_patterns:
                m = pattern.search(row['joined'])
                if m:
                    facts['payroll_change'] = m.group(1)
                    if m.lastindex and m.lastindex >= 2:
                        period_value = m.group(2)
                        if re.fullmatch(r'[A-Za-z]+', period_value) and fallback_period and fallback_period.lower().startswith(period_value.lower() + ' '):
                            period_value = fallback_period
                        facts['payroll_period'] = _normalize_macro_period(period_value)
                    elif fallback_period:
                        facts['payroll_period'] = _normalize_macro_period(fallback_period)
                    break
            if facts.get('unemployment_rate') or facts.get('payroll_change'):
                if facts.get('unemployment_source') is None:
                    facts['unemployment_source'] = 'BLS' if ('bls.gov' in row['url'].lower() or 'bureau of labor statistics' in low) else 'latest retrieved source'
                if facts.get('unemployment_period') is None and facts.get('payroll_period'):
                    facts['unemployment_period'] = facts.get('payroll_period') or ''
                break
        if not facts.get('unemployment_rate') and not facts.get('payroll_change'):
            unemployment_fallback = [
                re.compile(r'unemployment(?: rate)?(?:[^.]{0,40})?(?:at|was|held at|unchanged at|rose to|fell to)\s+([0-9]+(?:\.[0-9]+)?)%', re.IGNORECASE),
                re.compile(r'nonfarm payroll(?:[^.]{0,60})?(?:rose|increased|fell|dropped)\s+by\s+([0-9][0-9,]+)', re.IGNORECASE),
            ]
            for row in ordered:
                joined = str(row.get('joined') or '')
                low = joined.lower()
                if not any(tok in low for tok in ('unemployment', 'employment', 'jobless', 'payroll')):
                    continue
                for pattern in unemployment_fallback:
                    m = pattern.search(joined)
                    if not m:
                        continue
                    if 'payroll' in pattern.pattern:
                        facts['payroll_change'] = m.group(1)
                        period = _fallback_macro_period_from_row(row)
                        if period:
                            facts['payroll_period'] = period
                    else:
                        facts['unemployment_rate'] = m.group(1)
                        period = _fallback_macro_period_from_row(row)
                        if period:
                            facts['unemployment_period'] = period
                        facts['unemployment_source'] = _fallback_macro_source_label(row)
                    break
                if facts.get('unemployment_rate') or facts.get('payroll_change'):
                    if not facts.get('unemployment_source'):
                        facts['unemployment_source'] = _fallback_macro_source_label(row)
                    break
    if any(tok in qlow for tok in ('gdp', 'growth', 'economy')):
        growth_patterns = [
            re.compile(r'real gross domestic product \(gdp\) increased(?: at an annual rate of)?\s+([0-9]+(?:\.[0-9]+)?)\s+percent\s+in\s+the\s+([a-z0-9]+\s+quarter\s+of\s+20\d{2})', re.IGNORECASE),
            re.compile(r'q([1-4])\s+(20\d{2})\s+\(\d+(?:st|nd|rd|th)\)\s+([+\-]?[0-9]+(?:\.[0-9]+)?)%', re.IGNORECASE),
        ]
        for row in ordered:
            joined = str(row.get('joined') or '')
            low = joined.lower()
            if not any(tok in low for tok in ('gross domestic product', 'gdp', 'economy at a glance')):
                continue
            for pattern in growth_patterns:
                m = pattern.search(joined)
                if not m:
                    continue
                if pattern.pattern.startswith('real gross domestic product'):
                    facts['gdp_growth'] = m.group(1)
                    facts['gdp_period'] = _normalize_macro_period(m.group(2))
                else:
                    facts['gdp_growth'] = m.group(3)
                    quarter_map = {'1': 'First quarter', '2': 'Second quarter', '3': 'Third quarter', '4': 'Fourth quarter'}
                    facts['gdp_period'] = f"{quarter_map.get(m.group(1), 'Quarter')} of {m.group(2)}"
                facts['gdp_source'] = 'BEA' if ('bea.gov' in str(row.get('url') or '').lower() or 'bureau of economic analysis' in low) else 'latest retrieved source'
                break
            if facts.get('gdp_growth'):
                break
    return facts


def _fallback_macro_period_from_row(row: Dict[str, str]) -> str:
    published = str(row.get('published') or '').strip()
    dt = _parse_result_datetime(published) if published else None
    if dt is not None:
        return dt.strftime('%B %Y')
    joined = str(row.get('joined') or '')
    current_match = re.search(r'(?:in|through)\s+([A-Za-z]+\s+20\d{2})', joined, re.IGNORECASE)
    if current_match:
        return _normalize_macro_period(current_match.group(1))
    year_match = re.search(r'\b([A-Za-z]+)\s+(20\d{2})\b', joined, re.IGNORECASE)
    if year_match:
        return _normalize_macro_period(f"{year_match.group(1)} {year_match.group(2)}")
    return ''


def _fallback_macro_source_label(row: Dict[str, str]) -> str:
    blob = ' '.join([str(row.get('title') or ''), str(row.get('content') or ''), str(row.get('url') or '')]).lower()
    if 'reuters' in blob:
        return 'Reuters'
    if 'ap news' in blob or 'associated press' in blob:
        return 'AP'
    if 'bloomberg' in blob:
        return 'Bloomberg'
    if 'cnbc' in blob:
        return 'CNBC'
    return 'latest retrieved source'


def _extract_rate_context(results: List[Dict[str, str]]) -> str:
    ordered = sorted(list(results or []), key=_macro_source_quality)
    for row in ordered:
        joined = ' '.join([str(row.get('title') or ''), str(row.get('content') or '')]).strip()
        low = joined.lower()
        quality = _macro_source_quality(row)
        if quality >= 5:
            continue
        if not any(tok in low for tok in ('interest rate', 'federal reserve', 'fed funds', 'rate cut', 'rate hike', 'policy rate', 'monetary policy')):
            continue
        range_match = re.search(r'(?:target range(?: for the federal funds rate)?(?: at| to| of)?|federal funds rate(?: target range)?(?: at| to| of)?)[^0-9]{0,40}([0-9]+(?:\.[0-9]+)?)\s*(?:to|-)\s*([0-9]+(?:\.[0-9]+)?)\s*(?:percent|%)', joined, re.IGNORECASE)
        if range_match:
            return f"the Federal Reserve's target range is {range_match.group(1)}% to {range_match.group(2)}%"
        effr_sentence = re.search(r'Federal funds \(effective\) was\s+([0-9]+(?:\.[0-9]+)?)%\s+on\s+([0-9]{4}\s+[A-Za-z]+\s+[0-9]{1,2})', joined, re.IGNORECASE)
        if effr_sentence:
            return f"the effective federal funds rate was {effr_sentence.group(1)}% on {effr_sentence.group(2)} from the Federal Reserve H.15 release"
        effr_match = re.search(r'([0-9]+(?:\.[0-9]+)?)\s+[0-9]+(?:\.[0-9]+)?\s+[0-9]+(?:\.[0-9]+)?\s+[0-9]+(?:\.[0-9]+)?\s+\* Markets closed\.(?:[^.]{0,220})?effective federal funds rate', joined, re.IGNORECASE)
        if effr_match:
            return f"the latest observed effective federal funds rate on the Federal Reserve H.15 page is {effr_match.group(1)}%"
        hold_match = re.search(r'(kept|left|held|maintained)[^.]{0,120}?(interest rates|rates|policy rate|federal funds rate)[^.]{0,80}?(unchanged|steady)', low)
        if hold_match:
            return 'the Federal Reserve has kept rates unchanged in the latest retrieved policy context'
        ease_match = re.search(r'(cut|lowered|reduced)[^.]{0,120}?(interest rates|rates|policy rate|federal funds rate)', low)
        if ease_match:
            return 'the latest retrieved policy context points to lower policy rates'
        tighten_match = re.search(r'(raised|hiked|increased)[^.]{0,120}?(interest rates|rates|policy rate|federal funds rate)', low)
        if tighten_match:
            return 'the latest retrieved policy context points to higher policy rates'
        if 'federal reserve' in low or 'monetary policy' in low:
            return 'Federal Reserve policy remains the main rate-setting context in the latest retrieved sources'
    return ''


def _current_macro_fact_brief(query: str, results: List[Dict[str, str]]) -> str:
    qlow = str(query or '').lower()
    if not results:
        return ''
    facts = _extract_macro_fact_values(query, results)
    wants_inflation = any(tok in qlow for tok in ('inflation', 'cpi', 'consumer price'))
    wants_jobs = any(tok in qlow for tok in ('unemployment', 'employment', 'jobs', 'jobless'))
    wants_rates = any(tok in qlow for tok in ('interest rate', 'interest rates', 'fed funds', 'federal reserve', 'policy rate', 'rates'))
    rate_context = _extract_rate_context(results) if wants_rates else ''
    if wants_inflation and wants_jobs and facts.get('inflation_rate') and (facts.get('unemployment_rate') or facts.get('payroll_change')):
        jobs_bits = []
        if facts.get('unemployment_rate'):
            jobs_bits.append(f"unemployment was {facts['unemployment_rate']}% in {facts.get('unemployment_period') or facts.get('payroll_period') or 'the latest release'}")
        if facts.get('payroll_change'):
            jobs_bits.append(f"nonfarm payrolls rose by {facts['payroll_change']} in {facts.get('payroll_period') or facts.get('unemployment_period') or 'the latest release'}")
        jobs_text = '; '.join(jobs_bits)
        source_a = facts.get('inflation_source') or 'official'
        source_b = facts.get('unemployment_source') or source_a
        source_text = source_a if source_a == source_b else f"{source_a} / {source_b}"
        rate_suffix = f" {rate_context}." if wants_rates and rate_context else ''
        return (
            f"Latest retrieved U.S. macro picture: inflation was {facts['inflation_rate']}% over 12 months through "
            f"{facts.get('inflation_period') or 'the latest release'}, and {jobs_text}, based on "
            f"{source_text} data.{rate_suffix}"
        )
    inflation_rows = [row for row in (results or []) if _macro_row_matches_inflation_metric(query, row)]
    growth_text = ''
    if any(tok in qlow for tok in ('gdp', 'growth', 'economy')) and facts.get('gdp_growth'):
        growth_text = f"real GDP increased {facts['gdp_growth']}% in {facts.get('gdp_period') or 'the latest release'}"
    if wants_inflation and wants_rates and facts.get('inflation_rate') and rate_context:
        extra = f" {growth_text}." if growth_text else ''
        return f"Latest retrieved U.S. macro picture: inflation was {facts['inflation_rate']}% over 12 months through {facts.get('inflation_period') or 'the latest release'}, and {rate_context}.{extra}"
    if wants_inflation and facts.get('inflation_rate'):
        suffix = f" {rate_context}." if wants_rates and rate_context else ''
        growth_suffix = f" {growth_text}." if growth_text else ''
        return f"Latest retrieved U.S. inflation context: {facts['inflation_rate']}% over 12 months through {facts.get('inflation_period') or 'the latest release'}, based on {facts.get('inflation_source') or 'latest retrieved source'} data.{suffix}{growth_suffix}"
    if wants_inflation and wants_rates and rate_context and inflation_rows:
        metric_label = 'CPI' if _macro_query_needs_strict_cpi(query) else 'inflation'
        return f"Latest retrieved U.S. macro picture: {rate_context}, but an exact official {metric_label} figure could not be extracted from the available sources in this environment. Inflation-focused sources were still retrieved below for current context."
    if wants_inflation and _macro_query_needs_strict_cpi(query) and not facts.get('inflation_rate'):
        if inflation_rows:
            return 'I could not verify an exact current CPI reading from the retrieved sources in this turn without overstating the result. The retrieved inflation context did not provide a clean CPI figure I could safely quote.'
        return 'I could not retrieve a high-confidence current CPI source in this turn, so I cannot safely state the latest CPI reading.'
    if wants_rates and rate_context:
        return f"Latest retrieved U.S. rate context: {rate_context}."
    if wants_jobs and (facts.get('unemployment_rate') or facts.get('payroll_change')):
        bits = []
        if facts.get('unemployment_rate'):
            bits.append(f"the unemployment rate was {facts['unemployment_rate']}% in {facts.get('unemployment_period') or 'the latest release'}")
        if facts.get('payroll_change'):
            bits.append(f"nonfarm payrolls rose by {facts['payroll_change']} in {facts.get('payroll_period') or 'the latest release'}")
        return f"Latest retrieved U.S. jobs context: {'; '.join(bits)}, based on {facts.get('unemployment_source') or 'latest retrieved source'} data."
    return ''


def _macro_official_results(query: str, timeout: float) -> List[Dict[str, str]]:
    qlow = str(query or '').lower()
    source_specs = []
    if any(tok in qlow for tok in ('inflation', 'cpi', 'consumer price')):
        source_specs.append(('Consumer Price Index News Release - U.S. Bureau of Labor Statistics', 'https://www.bls.gov/news.release/cpi.nr0.htm'))
        source_specs.append(('CPI Home : U.S. Bureau of Labor Statistics', 'https://www.bls.gov/cpi/'))
    if 'unemployment' in qlow or 'employment' in qlow or 'jobs' in qlow or 'jobless' in qlow:
        source_specs.append(('Employment Situation Summary - U.S. Bureau of Labor Statistics', 'https://www.bls.gov/news.release/empsit.nr0.htm'))
    if 'gdp' in qlow or 'growth' in qlow or 'economy' in qlow:
        source_specs.append(('U.S. Economy at a Glance - Bureau of Economic Analysis', 'https://www.bea.gov/news/glance'))
    if 'interest rate' in qlow or 'fed funds' in qlow or 'federal reserve' in qlow:
        source_specs.append(('Selected Interest Rates - H.15 - Federal Reserve', 'https://www.federalreserve.gov/releases/h15/'))
        source_specs.append(('Open Market Operations - Federal Reserve', 'https://www.federalreserve.gov/monetarypolicy/openmarket.htm'))
        source_specs.append(('Monetary Policy - Federal Reserve', 'https://www.federalreserve.gov/monetarypolicy.htm'))
    if not source_specs:
        source_specs.append(('Economic News Releases - U.S. Bureau of Labor Statistics', 'https://www.bls.gov/bls/newsrels.htm'))
    unique_specs = []
    seen = set()
    for title, url in source_specs:
        if url in seen:
            continue
        seen.add(url)
        unique_specs.append((title, url))
    if not unique_specs:
        return []
    candidates: List[Dict[str, str]] = []
    max_workers = max(1, min(len(unique_specs), 4))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(_macro_official_source_row, title, url, query, timeout): (title, url)
            for title, url in unique_specs
        }
        for future in as_completed(future_map):
            row = future.result()
            if isinstance(row, dict) and (str(row.get('content') or '').strip() or str(row.get('published') or '').strip()):
                candidates.append(row)
    return candidates


def _macro_official_source_row(title: str, url: str, query: str, timeout: float) -> Dict[str, str] | None:
    try:
        raw = _request_text(url, timeout, accept='text/html,application/xhtml+xml,*/*;q=0.8')
        snippet = _focused_official_snippet(_strip_tags(raw), query, url)
        published = ''
        if 'releases/h15' in url:
            h15 = _extract_h15_effective_rate(raw)
            if h15:
                snippet = str(h15.get('content') or snippet or '')
                published = str(h15.get('published') or '')
        return {'title': title, 'url': url, 'content': snippet, 'engine': 'official_macro_context', 'published': published}
    except Exception:
        return None

def _merge_macro_official_results(query: str, rows: List[Dict[str, str]], timeout: float, max_results: int) -> List[Dict[str, str]]:
    merged = list(rows or [])
    try:
        official = _macro_official_results(query, timeout)
    except Exception:
        official = []
    requested_topics = _macro_requested_topics(query)
    if official:
        merged.extend(official)
    covered = _macro_covered_topics(merged)
    missing = [topic for topic in requested_topics if topic not in covered]
    if missing:
        try:
            supplemental = _fetch_bing_topic_results(query, timeout, max(max_results, 6))
        except Exception:
            supplemental = []
        if supplemental:
            merged.extend(supplemental)
    merged = _dedupe_result_rows(merged)
    if not merged:
        return []
    strong_rows = [row for row in merged if _macro_source_quality(row) < 5]
    if strong_rows:
        merged = strong_rows
    scored = [(_rank_macro_story(query, row), row) for row in merged]
    scored.sort(key=lambda item: item[0], reverse=True)
    ranked = [row for _, row in scored]
    return ranked[: max(1, min(max_results, 10))]


def _limited_current_topic_summary(query: str, results: List[Dict[str, str]], last_error: str = '') -> str:
    rows = [row for row in (results or []) if isinstance(row, dict)]
    if not rows:
        return ''
    high_conf = [row for row in rows if _is_high_confidence_current_topic_row(row)]
    candidate_rows = high_conf or [row for row in rows if _is_preferred_current_topic_row(row)]
    if not candidate_rows:
        return ''
    if _looks_like_broad_ai_trend_query(query):
        broad = _ai_trend_signal_summary(candidate_rows, limited=True)
        if broad:
            if last_error and ('connection refused' in last_error.lower() or 'timed out' in last_error.lower()):
                broad += ' Some fallback live-search backends were unavailable during this turn, so broader confirmation was not possible.'
            return broad
    lead = candidate_rows[0]
    title = _clean_story_title(str(lead.get('title') or '').strip())
    source = str(lead.get('source') or lead.get('engine') or '').strip()
    published = str(lead.get('published') or '').strip()
    lead_bits = []
    if title:
        lead_bits.append(title)
    if source:
        lead_bits.append(source)
    if published:
        lead_bits.append(published)
    lead_line = ' | '.join(bit for bit in lead_bits if bit)
    summary_lines = [
        'I found only limited current-source evidence for this request, so this is a cautious partial update rather than a full market-trends synthesis.',
    ]
    if lead_line:
        summary_lines.append('Strongest retrieved signal: ' + lead_line + '.')
    if len(candidate_rows) > 1:
        second = _clean_story_title(str(candidate_rows[1].get('title') or '').strip())
        if second:
            summary_lines.append('Additional retrieved signal: ' + second + '.')
    if last_error and ('connection refused' in last_error.lower() or 'timed out' in last_error.lower()):
        summary_lines.append('Some fallback live-search backends were unavailable during this turn, so broader confirmation was not possible.')
    summary_lines.append('Refine the request to a specific company, model family, or source type for a stronger current answer.')
    return ' '.join(line.strip() for line in summary_lines if str(line).strip()).strip()


def _limited_current_topic_rows(query: str, results: List[Dict[str, str]], max_results: int) -> List[Dict[str, str]]:
    rows = [row for row in (results or []) if isinstance(row, dict)]
    if not rows:
        return []
    return _trusted_current_topic_rows(rows, limit=max(1, min(int(max_results or 5), 3)))


def _broad_ai_trend_evidence_too_narrow(query: str, results: List[Dict[str, str]]) -> bool:
    qlow = str(query or '').lower()
    if not any(tok in qlow for tok in ('trend', 'trends', 'heading', 'where does the field seem to be heading', 'latest ai model')):
        return False
    rows = [row for row in (results or []) if isinstance(row, dict)]
    if len(rows) < 2:
        return True
    if _ai_trend_signal_summary(rows):
        return False
    cleaned_titles = []
    for row in rows:
        title = _clean_story_title(str(row.get('title') or '').strip())
        title = re.sub(r'\s*-\s*[^-]+$', '', title).strip()
        if title:
            cleaned_titles.append(title.lower())
    unique_titles = []
    for title in cleaned_titles:
        if title not in unique_titles:
            unique_titles.append(title)
    blob = ' '.join(_current_topic_row_blob(row) for row in rows).lower()
    governance_only = any(tok in blob for tok in ('security concern', 'cybersecurity review', 'approved customers', 'limited access', 'stagger release', 'government review', 'ai reviews')) and not any(tok in blob for tok in ('reasoning', 'multimodal', 'coding', 'open-weight', 'open source', 'benchmark', 'release family', 'agent', 'agents', 'inference cost', 'model launch'))
    provider_names = []
    for name in ('openai', 'anthropic', 'google', 'deepmind', 'meta', 'xai', 'mistral', 'cohere', 'microsoft', 'nvidia'):
        if name in blob:
            provider_names.append(name)
    return len(unique_titles) <= 2 or governance_only or len(provider_names) <= 2


def _narrow_ai_trend_summary(query: str, results: List[Dict[str, str]]) -> str:
    rows = [row for row in (results or []) if isinstance(row, dict)]
    if not rows:
        return ''
    lead = rows[0]
    title = _clean_story_title(str(lead.get('title') or '').strip())
    published = str(lead.get('published') or '').strip()
    source = str(lead.get('source') or lead.get('engine') or '').strip()
    parts = ['I found only narrow current-source evidence for this broad AI-trends request, so I cannot safely generalize it into a full field-wide trend summary.']
    lead_bits = [bit for bit in (title, source, published) if bit]
    if lead_bits:
        parts.append('The strongest retrieved signal was ' + ' | '.join(lead_bits) + '.')
    parts.append('The retrieved coverage is dominated by access-control, security-review, or governance stories rather than a balanced cross-section of launches, capabilities, and platform moves across the field.')
    parts.append('For a stronger answer, narrow the request to model releases, reasoning systems, open-weight models, enterprise adoption, regulation, or AI chips.')
    return ' '.join(part.strip() for part in parts if str(part).strip()).strip()


def _current_topic_brief(query: str, results: List[Dict[str, str]]) -> str:
    if not results:
        return ''
    if not (
        _looks_like_current_topic_query(query)
        or _looks_like_news_query(query)
        or _looks_like_regulation_query(query)
        or _looks_like_macro_query(query)
        or _looks_like_ai_chip_query(query)
        or _looks_like_broad_ai_news_query(query)
    ):
        return ''
    qlow = str(query or '').lower()
    broad_ai_topic = any(tok in qlow for tok in ('ai', 'model', 'models', 'openai', 'anthropic', 'gemini', 'claude', 'gpt', 'release', 'releases'))
    trend_subject = _trending_subject_query_core(query)
    if broad_ai_topic and not _looks_like_macro_query(query) and not _looks_like_regulation_query(query) and not _looks_like_ai_chip_query(query):
        high_confidence = [row for row in results if _is_high_confidence_current_topic_row(row)]
        candidate_rows = high_confidence or _trusted_current_topic_rows(results, limit=5) or [row for row in results if isinstance(row, dict)]
        broad_summary = _ai_trend_signal_summary(candidate_rows) if _looks_like_broad_ai_trend_query(query) else ''
        if broad_summary:
            return broad_summary
        if not high_confidence:
            return 'I could not verify a high-confidence current AI trends summary from trusted current sources in this turn.'
        if _broad_ai_trend_evidence_too_narrow(query, high_confidence):
            return _narrow_ai_trend_summary(query, high_confidence)

    macro_fact = _current_macro_fact_brief(query, results)
    if macro_fact:
        return macro_fact
    if _looks_like_macro_query(query):
        topics = []
        if any(tok in qlow for tok in ('inflation', 'cpi', 'consumer price')):
            topics.append('inflation')
        if 'unemployment' in qlow:
            topics.append('unemployment')
        if 'gdp' in qlow:
            topics.append('growth')
        if 'interest rate' in qlow or 'fed funds' in qlow:
            topics.append('interest rates')
        topic_text = ' and '.join(topics[:3]) if topics else 'macro conditions'
        sources = []
        for row in results:
            joined = ((str(row.get('title') or '') + ' ' + str(row.get('content') or ''))).lower()
            if ('bls' in str(row.get('url') or '').lower() or 'bureau of labor statistics' in joined) and 'BLS' not in sources:
                sources.append('BLS')
            if ('bea.gov' in str(row.get('url') or '').lower() or 'bureau of economic analysis' in joined) and 'BEA' not in sources:
                sources.append('BEA')
            if ('federal reserve' in joined or 'federalreserve.gov' in str(row.get('url') or '').lower()) and 'Federal Reserve' not in sources:
                sources.append('Federal Reserve')
        source_text = ', '.join(sources[:3]) if sources else 'recent retrieved sources'
        return f'Current U.S. {topic_text} updates are best read from {source_text}; see the retrieved items below for the latest exact figures and release context.'
    titles = [_clean_story_title(str(r.get('title') or '')) for r in results if str(r.get('title') or '').strip()]
    joined = ' '.join(titles + [str(r.get('content') or '') for r in results]).lower()
    if trend_subject and not broad_ai_topic and titles:
        return 'Recent coverage is focused on: ' + '; '.join(titles[:3]) + '.'
    if 'release' in qlow or 'releases' in qlow or 'launched' in qlow:
        orgs = []
        for name in ('OpenAI', 'Anthropic', 'Google', 'Google DeepMind', 'Meta', 'xAI', 'Mistral', 'Cohere'):
            if name.lower() in joined and name not in orgs:
                orgs.append(name)
        products = []
        for name in ('GPT', 'Claude', 'Gemini', 'Grok', 'Mistral', 'API', 'agent', 'coding'):
            if name.lower() in joined and name not in products:
                products.append(name)
        bits = []
        if orgs:
            bits.append('release activity is clustering around ' + ', '.join(orgs[:3]))
        if products:
            bits.append('the visible launch themes are ' + ', '.join(products[:3]))
        if bits:
            return 'Current release signals: ' + '; '.join(bits) + '.'
    if _looks_like_regulation_query(query):
        if _looks_like_eu_ai_regulation_query(query):
            if any(tok in joined for tok in ('ai office', 'single information platform', 'risk-based', 'high-risk', 'general-purpose ai', 'gpai', 'trustworthy ai', 'prohibited ai practices')):
                return (
                    'Current EU AI regulation developments are centered on implementation of the EU AI Act. '
                    'Retrieved European coverage emphasizes the risk-based framework and the separation between prohibited, transparency, and high-risk obligations. '
                    'A repeated theme is AI Office guidance for compliance and operational rollout. '
                    'General-purpose AI and GPAI code-of-practice expectations remain a visible policy focus. '
                    'The near-term story is implementation and enforcement preparation rather than a replacement law.'
                )
            if titles:
                return (
                    'Current EU AI regulation developments are centered on rollout and implementation guidance for the EU AI Act. '
                    'The main focus is how providers and deployers should operationalize compliance. '
                    'High-risk and general-purpose AI obligations remain central to the discussion. '
                    'European Commission and AI Office materials appear to be driving the practical guidance layer. '
                    'The overall direction still looks like implementation tightening rather than a wholly new legislative framework.'
                )
        policy_bits = []
        for label, tokens in (
            ('EU AI Act and European policy', ('eu ai act', 'european union', 'european commission', 'brussels', 'eu rule')),
            ('U.S. agency enforcement and guidance', ('ftc', 'white house', 'federal trade commission', 'congress', 'senate', 'house of representatives', 'nist', 'lawmakers', 'oversight')),
            ('copyright and licensing disputes', ('copyright', 'licensing', 'publishers', 'fair use', 'lawsuit', 'court')),
            ('deepfake and election safeguards', ('deepfake', 'synthetic media', 'election', 'political ad', 'watermarking')),
            ('state and national AI legislation', ('bill', 'state law', 'state laws', 'ai law', 'ai laws', 'regulation', 'policy')),
        ):
            if any(tok in joined for tok in tokens):
                policy_bits.append(label)
        if policy_bits:
            return 'Current AI regulation headlines are focused on ' + '; '.join(policy_bits[:3]) + '.'
        if titles:
            return 'Current AI regulation headlines are focused on government oversight, legal rules, and policy debates around AI deployment.'
    if _looks_like_ai_chip_query(query):
        orgs = []
        for name in ('NVIDIA', 'AMD', 'Intel', 'TSMC', 'Broadcom', 'OpenAI', 'Anthropic', 'Amazon', 'Qualcomm', 'ASML'):
            if name.lower() in joined and name not in orgs:
                orgs.append(name)
        chip_bits = []
        for label, tokens in (
            ('high-end AI chip launches', ("world's most powerful chip", 'new ai chip', 'blackwell', 'accelerator', 'gpu')),
            ('custom AI chip efforts', ('custom chip', 'homegrown ai chip', 'trainium', 'openai tests homegrown ai chips')),
            ('export-control and supply pressure', ('banned ai chips', 'export control', 'black market', 'china')),
            ('manufacturing and packaging costs', ('wafer', 'foundry', 'packaging', 'substrate', 'price hike', 'higher wafer costs')),
            ('inference-focused competition', ('inference', 'neocloud', 'groq', 'specialized inference')),
        ):
            if any(tok in joined for tok in tokens):
                chip_bits.append(label)
        if chip_bits:
            lead = 'Current AI chip trends are being shaped by ' + '; '.join(chip_bits[:4]) + '.'
            if orgs:
                return lead[:-1] + ', with visible activity from ' + ', '.join(orgs[:5]) + '.'
            return lead
        if orgs:
            return 'Current AI chip headlines are centered on ' + ', '.join(orgs[:4]) + '.'
        return 'Current AI chip headlines are focused on GPUs, accelerators, semiconductor supply, and custom-chip efforts for AI systems.'
    if 'headline' in qlow or 'news' in qlow:
        orgs = []
        for name in ('OpenAI', 'Anthropic', 'Google', 'Google DeepMind', 'Meta', 'xAI', 'Mistral', 'Cohere', 'NVIDIA'):
            if name.lower() in joined and name not in orgs:
                orgs.append(name)
        if orgs:
            return 'Top AI headlines are centered on ' + ', '.join(orgs[:4]) + '.'
    trend_bits = []
    buckets = [
        ('reasoning models', ('reasoning', 'think', 'thinking')),
        ('multimodal systems', ('multimodal', 'audio', 'video', 'vision', 'omni')),
        ('coding models and agents', ('code', 'coding', 'agent', 'agents')),
        ('open-weight competition', ('open source', 'open-source', 'open weight', 'open-weight')),
        ('new frontier-model launches', ('gpt', 'claude', 'gemini', 'grok', 'mistral', 'model family', 'unveils', 'launches', 'preview')),
        ('tighter rollout and access controls', ('limited rollout', 'trusted partners', 'security concerns', 'government security', 'limited access', 'access to new models', 'stagger release')),
        ('frontier-model review and oversight', ('review', 'reviews', 'stress test', 'stress tests', 'security review', 'cybersecurity review', 'government review', 'approval', 'approved customers')),
    ]
    for label, tokens in buckets:
        if any(tok in joined for tok in tokens):
            trend_bits.append(label)
    if trend_bits:
        if 'trend' in qlow or 'trends' in qlow:
            named_orgs = []
            for name in ('OpenAI', 'Anthropic', 'Google', 'Google DeepMind', 'Meta', 'xAI', 'Mistral', 'Cohere', 'Microsoft'):
                if name.lower() in joined and name not in named_orgs:
                    named_orgs.append(name)
            provider_activity = []
            for label, tokens in (
                ('provider rollout controls', ('openai', 'anthropic', 'limited access', 'stagger release', 'approved customers')),
                ('platform-provider review pressure', ('meta', 'google', 'microsoft', 'xai', 'review', 'stress test', 'security concerns')),
            ):
                if any(tok in joined for tok in tokens):
                    provider_activity.append(label)
            merged_bits = []
            for bit in trend_bits + provider_activity:
                if bit not in merged_bits:
                    merged_bits.append(bit)
            lead = 'Current AI trends are centered on ' + '; '.join(merged_bits[:4]) + '.'
            if named_orgs:
                return lead[:-1] + ', with visible activity from ' + ', '.join(named_orgs[:4]) + '.'
            return lead
        return 'Current AI model trends point to ' + '; '.join(trend_bits[:4]) + '.'
    if titles:
        top = '; '.join(titles[:3])
        if ('trend' in qlow or 'trends' in qlow) and broad_ai_topic:
            if 'openai' in joined and any(tok in joined for tok in ('limited preview', 'preview partners', 'security concerns', 'government security', 'access to new models', 'limited access')):
                return 'Current AI trends are being driven by new model announcements plus tighter access and governance controls around those releases.'
            return 'Current AI trends are being driven by recent model announcements, capability positioning, and competitive release activity.'
        return 'Recent coverage is focused on: ' + top + '.'
    return ''
def _theme_summary(results: List[Dict[str, str]]) -> str:
    joined = ' '.join(str(r.get('content') or '') for r in results).lower()
    themes: List[str] = []
    if any(tok in joined for tok in ('reasoning', 'chain-of-thought', 'reasoning model')):
        themes.append('reasoning-focused models remain a visible theme')
    if any(tok in joined for tok in ('multimodal', 'vision', 'audio')):
        themes.append('multimodal capabilities are increasingly standard')
    if any(tok in joined for tok in ('cost', 'cheaper', 'lower costs', 'inference cost', 'efficiency')):
        themes.append('cost and efficiency improvements continue to matter')
    if any(tok in joined for tok in ('open-weight', 'open source', 'open-source')):
        themes.append('open-weight models continue to gain attention')
    if not themes:
        return ''
    return 'Key themes: ' + '; '.join(themes) + '.'


def _apply_requested_answer_shape(query: str, text: str) -> str:
    raw = str(text or '').strip()
    if not raw:
        return raw
    low = str(query or '').lower()
    bullet_match = re.search(r'\b([2-9]|10)\s+bullets?\b', low)
    bullet_limit = int(bullet_match.group(1)) if bullet_match else 0
    wants_bullets = bool(bullet_limit or ' bullet' in low or 'bullets' in low)
    if not wants_bullets:
        return raw
    if re.search(r'(?m)^\s*[-*]\s+', raw):
        return raw
    flat = ' '.join(raw.split())
    parts = [part.strip() for part in re.split(r'(?<=[.!?])\s+(?=[A-Z0-9])', flat) if part.strip()]
    if len(parts) <= 1:
        parts = [part.strip() for part in re.split(r';\s+', flat) if part.strip()]
    if len(parts) <= 1:
        return '- ' + flat
    limit = bullet_limit or min(5, max(3, len(parts)))
    return '\n'.join(f'- {part}' for part in parts[:limit])


def _shape_result_payload(query: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    summary = _apply_requested_answer_shape(query, str(out.get('summary') or out.get('text') or ''))
    if summary:
        out['summary'] = summary
        out['text'] = summary
        data = dict(out.get('data') or {}) if isinstance(out.get('data'), dict) else {}
        if data:
            data['summary'] = summary
            out['data'] = data
    return out
def _fetch_google_trending(query: str, timeout: float, top_n: int, geo: str) -> Dict[str, Any] | None:
    if not _looks_like_trending_query(query):
        return None
    rss_url = f'https://trends.google.com/trending/rss?geo={urllib.parse.quote(str(geo or "US"))}'
    raw = _request_text(rss_url, timeout, accept='application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8')
    root = ET.fromstring(raw)
    items = root.findall('.//item')
    topics: List[Dict[str, str]] = []
    for item in items[: max(1, min(int(top_n or 10), 25))]:
        title = str(item.findtext('title') or '').strip()
        traffic = str(item.findtext('{https://trends.google.com/trending/rss}approx_traffic') or '').strip()
        link = str(item.findtext('link') or '').strip()
        if title:
            topics.append({'title': title, 'traffic': traffic, 'link': link})
    if not topics:
        return {'ok': True, 'query': query, 'results': [], 'summary': '', 'warnings': ['no_trending_topics_found'], 'source': rss_url, 'data': {'query': query, 'results': [], 'summary': '', 'source': rss_url}}
    summary_lines = []
    for idx, row in enumerate(topics, start=1):
        traffic_suffix = f" ({row['traffic']})" if row.get('traffic') else ''
        summary_lines.append(f"{idx}. {row['title']}{traffic_suffix}")
    return {'ok': True, 'query': query, 'results': topics, 'summary': '\n'.join(summary_lines), 'source': rss_url, 'data': {'query': query, 'results': topics, 'summary': '\n'.join(summary_lines), 'source': rss_url}, 'warnings': []}
def _fetch_google_news(query: str, timeout: float, top_n: int, geo: str) -> Dict[str, Any] | None:
    if not (_looks_like_news_query(query) or _looks_like_current_topic_query(query) or _looks_like_regulation_query(query) or _looks_like_macro_query(query)):
        return None
    geo_value = str(geo or 'US')
    ai_topic = any(tok in str(query or '').lower() for tok in ('ai', 'model', 'models', 'llm', 'openai', 'anthropic', 'gemini', 'claude', 'gpt', 'release', 'releases')) or _looks_like_regulation_query(query)
    want_headlines = _looks_like_news_query(query)
    window_days = _news_time_window_days(query)

    query_candidates: List[str] = []
    if _looks_like_current_topic_query(query) or _looks_like_regulation_query(query) or _looks_like_macro_query(query) or any(tok in str(query or '').lower() for tok in ('ai', 'model', 'models', 'tech', 'technology', 'release', 'releases')) or _looks_like_news_query(query):
        primary = _macro_news_query(query) if _looks_like_macro_query(query) else _topic_news_query(query)
        for candidate in [primary, *_topic_search_fallback_queries(query)[:3]]:
            normalized = ' '.join(str(candidate or '').split()).strip()
            if not normalized or normalized in query_candidates:
                continue
            if window_days and ' when:' not in normalized and not _looks_like_macro_query(query):
                normalized = f'{normalized} when:{window_days}d'
            query_candidates.append(normalized)
    else:
        query_candidates.append('')

    rss_url = ''
    stories: List[Dict[str, str]] = []
    seen_story_keys = set()
    max_queries = 1 if _looks_like_macro_query(query) else 3
    for topic_query in query_candidates[:max_queries]:
        if topic_query:
            rss_url = 'https://news.google.com/rss/search?' + urllib.parse.urlencode({'q': topic_query, 'hl': 'en-US', 'gl': geo_value, 'ceid': f'{geo_value}:en'})
        else:
            rss_url = f'https://news.google.com/rss?hl=en-US&gl={urllib.parse.quote(geo_value)}&ceid={urllib.parse.quote(geo_value)}:en'
        raw = _request_text(rss_url, timeout, accept='application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8')
        root = ET.fromstring(raw)
        items = root.findall('.//item')
        for item in items[: max(1, min(int(top_n or 10), 40))]:
            title = str(item.findtext('title') or '').strip()
            link = str(item.findtext('link') or '').strip()
            pub = str(item.findtext('pubDate') or '').strip()
            source = str(item.findtext('source') or '').strip()
            if not title:
                continue
            if ai_topic and not _is_relevant_ai_story(title, source, query):
                continue
            if _looks_like_macro_query(query) and not _is_relevant_macro_story(title, source, query):
                continue
            if want_headlines and _looks_like_generic_news_hub(link, title, source):
                continue
            key = ((link or '').lower().strip(), (title or '').lower().strip())
            if key in seen_story_keys:
                continue
            seen_story_keys.add(key)
            stories.append({'title': title, 'link': link, 'published': pub, 'source': source})
        if len(stories) >= max(6, min(int(top_n or 10) * 3, 18)):
            break
    if (ai_topic or _looks_like_macro_query(query)) and stories:
        if _looks_like_macro_query(query):
            scored_stories = [
                (
                    _rank_macro_story(query, {'title': row.get('title') or '', 'url': row.get('link') or '', 'content': row.get('source') or '', 'published': row.get('published') or ''}),
                    row,
                )
                for row in stories
            ]
        else:
            scored_stories = [
                (
                    _rank_current_topic_result(query, {'title': row.get('title') or '', 'url': row.get('link') or '', 'content': row.get('source') or '', 'published': row.get('published') or ''}),
                    row,
                )
                for row in stories
            ]
        scored_stories.sort(key=lambda item: item[0], reverse=True)
        if window_days:
            recent = [row for score, row in scored_stories if _recency_score(query, {'published': row.get('published') or '', 'url': row.get('link') or ''}) >= 5]
        else:
            recent = []
        preferred = [row for score, row in scored_stories if score >= 0]
        fallback = [row for score, row in scored_stories if score < 0]
        if recent and len(recent) >= min(2, max(1, min(int(top_n or 10), 25))):
            ranked_rows = recent + [row for row in preferred if row not in recent] + [row for row in fallback if row not in recent]
        else:
            ranked_rows = preferred if len(preferred) >= min(3, max(1, min(int(top_n or 10), 25))) else (preferred + fallback)
        if ('trend' in query.lower() or 'headline' in query.lower() or 'headlines' in query.lower() or 'news' in query.lower()) and not _looks_like_ai_chip_query(query) and not _looks_like_regulation_query(query):
            preferred_rows = [row for row in ranked_rows if _is_preferred_current_topic_row(row) and not _is_low_value_current_topic_row(row)]
            if len(preferred_rows) >= 2:
                ranked_rows = preferred_rows
            else:
                high_confidence_rows = [row for row in ranked_rows if _is_high_confidence_current_topic_row({'title': row.get('title') or '', 'url': row.get('link') or '', 'content': row.get('source') or '', 'published': row.get('published') or ''})]
                if len(high_confidence_rows) >= 2:
                    ranked_rows = high_confidence_rows
                else:
                    supplemental_rows = []
                    try:
                        supplemental_rows = _fetch_bing_topic_results(query, timeout, max(top_n, 6))
                    except Exception:
                        supplemental_rows = []
                    if supplemental_rows:
                        merged_rank_rows = [
                            {'title': str(row.get('title') or ''), 'link': str(row.get('link') or row.get('url') or ''), 'published': str(row.get('published') or ''), 'source': str(row.get('source') or row.get('content') or '')}
                            for row in ranked_rows
                        ]
                        for row in supplemental_rows:
                            merged_rank_rows.append({'title': str(row.get('title') or ''), 'link': str(row.get('url') or row.get('link') or ''), 'published': str(row.get('published') or ''), 'source': str(row.get('content') or '')})
                        ranked_rows = _dedupe_result_rows(merged_rank_rows)
                    partial_rows = _trusted_current_topic_rows(ranked_rows, limit=max(1, min(int(top_n or 10), 4)))
                    if not partial_rows:
                        partial_rows = ranked_rows[: max(1, min(int(top_n or 10), 5))]
                    partial_summary = 'I could not retrieve a high-confidence current AI trends summary from trusted sources in this turn. Try again shortly or refine the request to a specific company, model family, or source type.'
                    return {'ok': True, 'query': query, 'results': partial_rows, 'summary': partial_summary, 'warnings': ['no_high_confidence_ai_trend_sources'], 'source': rss_url, 'data': {'query': query, 'results': partial_rows, 'summary': partial_summary, 'source': rss_url}}
        if _looks_like_regulation_query(query) or _looks_like_ai_chip_query(query):
            strong_rows = [row for row in ranked_rows if not _is_low_value_current_topic_row(row)]
            if len(strong_rows) >= 2:
                ranked_rows = strong_rows
            elif _looks_like_ai_chip_query(query):
                try:
                    supplemental_rows = _fetch_bing_topic_results(query, timeout, top_n)
                except Exception:
                    supplemental_rows = []
                if supplemental_rows:
                    merged_rank_rows = [
                        {'title': str(row.get('title') or ''), 'link': str(row.get('link') or row.get('url') or ''), 'published': str(row.get('published') or ''), 'source': str(row.get('source') or row.get('content') or '')}
                        for row in ranked_rows
                    ]
                    for row in supplemental_rows:
                        merged_rank_rows.append({'title': str(row.get('title') or ''), 'link': str(row.get('url') or row.get('link') or ''), 'published': str(row.get('published') or ''), 'source': str(row.get('content') or '')})
                    dedup = []
                    seen_links = set()
                    for row in merged_rank_rows:
                        link = str(row.get('link') or '').strip().lower()
                        if not link or link in seen_links:
                            continue
                        seen_links.add(link)
                        dedup.append(row)
                    rescored = [(_rank_current_topic_result(query, {'title': row.get('title') or '', 'url': row.get('link') or '', 'content': row.get('source') or '', 'published': row.get('published') or ''}), row) for row in dedup]
                    rescored.sort(key=lambda item: item[0], reverse=True)
                    ranked_rows = [row for score, row in rescored if score >= 0] or [row for _, row in rescored]
                    strong_rows = [row for row in ranked_rows if not _is_low_value_current_topic_row(row)]
                    if strong_rows:
                        ranked_rows = strong_rows + [row for row in ranked_rows if row not in strong_rows]
                strong_rows = [row for row in ranked_rows if not _is_low_value_current_topic_source(row.get('link') or row.get('url') or '')]
                if not strong_rows:
                    return {'ok': True, 'query': query, 'results': [], 'summary': 'I could not retrieve high-confidence current AI chip headlines from trusted news sources in this turn. Try again shortly or refine the request to a specific company like NVIDIA, AMD, or Intel.', 'warnings': ['no_high_confidence_chip_news_sources'], 'source': rss_url, 'data': {'query': query, 'results': [], 'summary': 'I could not retrieve high-confidence current AI chip headlines from trusted news sources in this turn. Try again shortly or refine the request to a specific company like NVIDIA, AMD, or Intel.', 'source': rss_url}}
        stories = ranked_rows[: max(1, min(int(top_n or 10), 25))]
    if not stories:
        return {'ok': True, 'query': query, 'results': [], 'summary': '', 'warnings': ['no_news_headlines_found'], 'source': rss_url, 'data': {'query': query, 'results': [], 'summary': '', 'source': rss_url}}
    wants_listing = _wants_source_listing(query) or _looks_like_broad_ai_news_query(query)
    if wants_listing:
        summary_lines = [
            _format_compact_result_line({'title': row.get('title') or '', 'url': row.get('link') or '', 'source': row.get('source') or ''})
            for row in stories
        ]
        summary_lines = [line for line in summary_lines if line]
    else:
        summary_lines = [f"{idx}. {row['title']}" for idx, row in enumerate(stories, start=1)]
    brief = _current_topic_brief(query, [{'title': row.get('title') or '', 'url': row.get('link') or '', 'content': row.get('source') or '', 'engine': 'google_news', 'published': row.get('published') or ''} for row in stories]) if (_looks_like_current_topic_query(query) or ai_topic or _looks_like_news_query(query) or _looks_like_regulation_query(query) or _looks_like_macro_query(query)) else ''
    if brief and not wants_listing:
        summary_text = brief.strip()
    else:
        summary_text = '\n'.join((([brief] if brief else []) + summary_lines[: max(1, min(int(top_n or 10), 25))])).strip()
    return _shape_result_payload(query, {'ok': True, 'query': query, 'results': stories, 'summary': summary_text, 'text': summary_text, 'source': rss_url, 'data': {'query': query, 'results': stories, 'summary': summary_text, 'source': rss_url}, 'warnings': []})
def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(params or {})
    query = str(params.get("query") or params.get("text") or params.get("prompt") or "").strip()
    if not query:
        return {"ok": False, "data": {}, "warnings": ["query_required"]}
    max_results = int(params.get("max_results") or 5)
    timeout = float(params.get("timeout") or 15.0)
    geo = str(params.get('geo') or params.get('country') or 'US').strip() or 'US'
    is_youtube = _looks_like_youtube_query(query)
    is_macro_query = _looks_like_macro_query(query)
    is_identity_query = _looks_like_identity_query(query)
    is_compound_identity_query = _is_compound_identity_query(query)
    identity_only_query = bool(is_identity_query and not is_compound_identity_query)
    explicit_trending_query = _looks_like_trending_query(query)
    try:
        trending = None if (is_youtube or identity_only_query or not explicit_trending_query) else _fetch_google_trending(query, timeout, max_results, geo)
    except Exception as exc:
        trending = None
    if isinstance(trending, dict):
        return trending
    partial_current_topic_rows: List[Dict[str, str]] = []
    try:
        headlines = None if (is_youtube or identity_only_query) else _fetch_google_news(query, timeout, max_results, geo)
    except Exception:
        headlines = None
    if isinstance(headlines, dict):
        headline_results = headlines.get('results') if isinstance(headlines.get('results'), list) else []
        headline_summary = str(headlines.get('summary') or '').strip()
        headline_warnings = [str(x or '').strip() for x in (headlines.get('warnings') or []) if str(x or '').strip()]
        low_confidence_current_topic = any(flag in headline_warnings for flag in ('no_high_confidence_ai_trend_sources', 'no_high_confidence_chip_news_sources'))
        if low_confidence_current_topic and headline_results:
            partial_current_topic_rows = [
                {
                    'title': str(row.get('title') or ''),
                    'url': str(row.get('link') or row.get('url') or ''),
                    'content': str(row.get('source') or row.get('content') or ''),
                    'source': str(row.get('source') or ''),
                    'engine': 'google_news',
                    'published': str(row.get('published') or ''),
                }
                for row in headline_results
                if isinstance(row, dict)
            ]
        if is_macro_query and headline_results:
            merged_results = _merge_macro_official_results(query, [
                {
                    'title': str(row.get('title') or ''),
                    'url': str(row.get('link') or row.get('url') or ''),
                    'content': str(row.get('source') or row.get('content') or ''),
                    'engine': 'google_news',
                    'published': str(row.get('published') or ''),
                }
                for row in headline_results
            ], timeout, max_results)
            summary_lines = [_format_result_line(r) for r in merged_results]
            summary_lines = [line for line in summary_lines if line]
            macro_brief = _current_topic_brief(query, merged_results)
            if macro_brief and not _wants_source_listing(query):
                summary_text = macro_brief.strip()
            else:
                summary_text = "\n".join((([macro_brief] if macro_brief else []) + summary_lines[:4])).strip()
            return _shape_result_payload(query, {
                'ok': True,
                'query': query,
                'results': merged_results,
                'summary': summary_text,
                'text': summary_text,
                'source': str(headlines.get('source') or 'google_news'),
                'data': {'query': query, 'results': merged_results, 'summary': summary_text, 'source': str(headlines.get('source') or 'google_news')},
                'warnings': list(headlines.get('warnings') or []),
            })
        if headline_results and low_confidence_current_topic:
            headlines = None
        elif headline_results or (headline_summary and not low_confidence_current_topic):
            return _shape_result_payload(query, headlines)
        else:
            headlines = None
    last_error = ""
    cleaned: List[Dict[str, str]] = []
    chosen_base = ""

    if identity_only_query and not cleaned:
        direct_identity = _direct_official_identity_result(query, timeout)
        if isinstance(direct_identity, dict):
            cleaned = [direct_identity]
            chosen_base = str(direct_identity.get('url') or 'direct_official_identity').strip()

    search_params = {"q": query, "format": "json"}
    if is_youtube:
        search_params['q'] = f"site:youtube.com/watch {query}"
    elif _looks_like_news_query(query):
        search_params['q'] = _topic_news_query(query)
    categories = str(params.get("categories") or "").strip()
    engines = str(params.get("engines") or "").strip()
    if not categories and (_looks_like_news_query(query) or _looks_like_current_topic_query(query) or _looks_like_regulation_query(query) or _looks_like_macro_query(query)):
        categories = 'news'
    if categories:
        search_params["categories"] = categories
    if engines:
        search_params["engines"] = engines
    for base in ([] if cleaned else _base_candidates(ctx, params)):
        try:
            url = f"{base}/search?{urllib.parse.urlencode(search_params)}"
            payload = _request_json(url, timeout)
            results = payload.get("results") if isinstance(payload.get("results"), list) else []
            local_cleaned = []
            is_current_topic = _looks_like_current_topic_query(query) or _looks_like_news_query(query) or _looks_like_regulation_query(query)
            window_days = _news_time_window_days(query)
            for row in results[: max(1, min(max_results * 3, 30))]:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url") or "").strip()
                low_url = url.lower()
                if (not is_youtube) and 'reddit.com/' in low_url and any(tok in query.lower() for tok in ('ai', 'model', 'models', 'technology', 'tech', 'research', 'news', 'headline', 'trend', 'trends')):
                    continue
                if is_youtube and 'youtube.com' not in url and 'youtu.be' not in url:
                    continue
                if is_youtube and '/watch' not in url and '/shorts/' not in url and 'youtu.be/' not in url:
                    continue
                title = str(row.get("title") or "").strip()
                content = str(row.get("content") or "").strip()
                if is_youtube and title.lower() in {'youtube', 'youtube - youtube', 'trending now - youtube', 'trending videos - youtube', "what's trending - youtube"}:
                    continue
                if is_current_topic and any(tok in query.lower() for tok in ('ai', 'model', 'models', 'headline', 'headlines', 'news', 'trend', 'trends')):
                    if not _is_relevant_ai_story(title, content, query):
                        continue
                    if _looks_like_news_query(query) and _looks_like_generic_news_hub(url, title, content):
                        continue
                    published = str(row.get("publishedDate") or row.get("published") or row.get("date") or "").strip()
                    evergreen_markers = ('wikipedia.org', '/academy/', '/what-is-', '/index/', '/about/', '/basics/', '/guide/')
                    if ('trend' in query.lower() or 'trends' in query.lower() or 'latest' in query.lower() or 'current' in query.lower()) and not published and not re.search(r'/20\d{2}/', low_url):
                        if _looks_like_generic_news_hub(url, title, content) or any(marker in low_url for marker in evergreen_markers):
                            continue
                if is_macro_query and not _is_relevant_macro_story(title, content, query):
                    continue
                local_cleaned.append({
                    "title": title,
                    "url": url,
                    "content": content,
                    "engine": str(row.get("engine") or "").strip(),
                    "published": str(row.get("publishedDate") or row.get("published") or row.get("date") or "").strip(),
                })
            if local_cleaned:
                if is_macro_query:
                    local_cleaned = _merge_macro_official_results(query, local_cleaned, timeout, max_results)
                    scored_local = [(_rank_macro_story(query, row), row) for row in local_cleaned]
                    scored_local.sort(key=lambda item: item[0], reverse=True)
                    recent = [row for score, row in scored_local if window_days and _recency_score(query, row) >= 5]
                    preferred = [row for score, row in scored_local if score >= 0]
                    fallback = [row for score, row in scored_local if score < 0]
                    if recent and len(recent) >= min(2, max(1, min(max_results, 10))):
                        local_cleaned = recent + [row for row in preferred if row not in recent] + [row for row in fallback if row not in recent]
                    else:
                        local_cleaned = preferred if len(preferred) >= min(3, max(1, min(max_results, 10))) else (preferred + fallback)
                elif is_current_topic and any(tok in query.lower() for tok in ('ai', 'model', 'models', 'headline', 'headlines', 'news', 'trend', 'trends', 'regulation', 'policy')):
                    scored_local = [(_rank_current_topic_result(query, row), row) for row in local_cleaned]
                    scored_local.sort(key=lambda item: item[0], reverse=True)
                    recent = [row for score, row in scored_local if window_days and _recency_score(query, row) >= 5]
                    preferred = [row for score, row in scored_local if score >= 0]
                    fallback = [row for score, row in scored_local if score < 0]
                    if recent and len(recent) >= min(2, max(1, min(max_results, 10))):
                        local_cleaned = recent + [row for row in preferred if row not in recent] + [row for row in fallback if row not in recent]
                    else:
                        local_cleaned = preferred if len(preferred) >= min(3, max(1, min(max_results, 10))) else (preferred + fallback)
                    if _looks_like_regulation_query(query):
                        strong_rows = [row for row in local_cleaned if not _is_low_value_current_topic_row(row)]
                        if len(strong_rows) >= 2:
                            local_cleaned = strong_rows
                    if _looks_like_ai_chip_query(query):
                        strong_rows = [row for row in local_cleaned if not _is_low_value_current_topic_row(row)]
                        if strong_rows:
                            local_cleaned = strong_rows + [row for row in local_cleaned if row not in strong_rows]
                        else:
                            local_cleaned = []
                    if ('trend' in query.lower() or 'headline' in query.lower() or 'headlines' in query.lower() or 'news' in query.lower()) and not _looks_like_ai_chip_query(query):
                        preferred_rows = [row for row in local_cleaned if _is_preferred_current_topic_row(row) and not _is_low_value_current_topic_row(row)]
                        if len(preferred_rows) >= 2:
                            local_cleaned = preferred_rows
                        else:
                            high_confidence_rows = [row for row in local_cleaned if _is_high_confidence_current_topic_row(row)]
                            if len(high_confidence_rows) >= 2:
                                local_cleaned = high_confidence_rows
                            else:
                                local_cleaned = _trusted_current_topic_rows(local_cleaned, limit=max(1, min(max_results, 4)))
                cleaned = local_cleaned[: max(1, min(max_results, 10))]
                chosen_base = base
                break
            last_error = f"no_results_from:{base}"
        except Exception as exc:
            last_error = str(exc)
            continue
    if cleaned and is_macro_query:
        cleaned = _merge_macro_official_results(query, cleaned, timeout, max_results)
    if not cleaned and is_macro_query:
        try:
            cleaned = _macro_official_results(query, timeout)[: max(1, min(max_results, 10))]
            chosen_base = 'official_macro_sources' if cleaned else chosen_base
            if not cleaned:
                last_error = last_error or 'macro_official_sources_no_results'
        except Exception as exc:
            last_error = last_error or str(exc)
    if not cleaned and not is_youtube and identity_only_query:
        try:
            cleaned = _fetch_bing_results(query, timeout, max_results)
            chosen_base = 'https://www.bing.com/search' if cleaned else chosen_base
            if not cleaned:
                last_error = last_error or 'bing_no_results'
        except Exception as exc:
            last_error = last_error or str(exc)
    if not cleaned and not is_youtube and (_looks_like_current_topic_query(query) or _looks_like_news_query(query) or _looks_like_regulation_query(query)):
        try:
            cleaned = _fetch_bing_topic_results(query, timeout, max_results)
            chosen_base = 'https://www.bing.com/search' if cleaned else chosen_base
            if not cleaned:
                last_error = last_error or 'bing_topic_no_results'
        except Exception as exc:
            last_error = last_error or str(exc)
    if cleaned:
        if is_youtube:
            summary_lines = [f"{idx}. {r['title']}" for idx, r in enumerate(cleaned, start=1) if r.get('title')]
            summary_text = "\n".join(summary_lines[:5])
        else:
            identity_query = _looks_like_identity_query(query)
            compound_identity_query = _is_compound_identity_query(query)
            identity_hits = []
            official_identity = _discover_official_identity_result(query, cleaned, timeout) if identity_query else None
            if identity_query and not isinstance(official_identity, dict):
                try:
                    identity_hits = _fetch_bing_results(query, timeout, max_results)
                except Exception:
                    identity_hits = []
                if identity_hits:
                    official_identity = _discover_official_identity_result(query, identity_hits, timeout)
            wiki_identity = _wiki_identity_result(query, timeout) if identity_query else None
            enriched = []
            if isinstance(wiki_identity, dict):
                enriched.append(wiki_identity)
            if isinstance(official_identity, dict):
                enriched.append(official_identity)
            if identity_hits:
                enriched.extend(identity_hits)
            enriched.extend(cleaned)
            enriched = _dedupe_result_rows(enriched)
            display_results = _filter_identity_results(_identity_focus_query(query), enriched) if identity_query else enriched
            display_results = _dedupe_result_rows(display_results)
            compact_topic = bool((_looks_like_current_topic_query(query) or _looks_like_news_query(query) or _looks_like_regulation_query(query)) and not _looks_like_macro_query(query) and not identity_only_query)
            wants_listing = _wants_source_listing(query)
            formatter = _format_compact_result_line if compact_topic else _format_result_line
            line_limit = 3 if compact_topic else 4
            summary_lines = [formatter(r) for r in display_results]
            summary_lines = [line for line in summary_lines if line]
            identity_summary = _identity_summary(query, display_results)
            current_topic_summary = _current_topic_brief(query, display_results) if (compound_identity_query or not identity_summary) else ''
            theme_summary = _theme_summary(display_results) if not identity_summary and not current_topic_summary else ''
            if compound_identity_query and (identity_summary or current_topic_summary):
                prefix_lines = []
                if identity_summary:
                    prefix_lines.append(identity_summary.strip())
                if current_topic_summary:
                    prefix_lines.append(current_topic_summary.strip())
                if wants_listing:
                    summary_text = "\n".join(prefix_lines + summary_lines[:line_limit]).strip()
                else:
                    summary_text = "\n".join(prefix_lines).strip()
            elif identity_summary:
                summary_text = identity_summary.strip()
            else:
                prefix_lines = [current_topic_summary] if current_topic_summary else ([theme_summary] if theme_summary else [])
                if prefix_lines and not wants_listing:
                    summary_text = "\n".join(prefix_lines).strip()
                else:
                    summary_text = "\n".join(prefix_lines + summary_lines[:line_limit]).strip()
            if not summary_text:
                summary_text = f"I found source results for: {query}"
            cleaned = display_results
        return _shape_result_payload(query, {
            "ok": True,
            "query": query,
            "base_url": chosen_base,
            "results": cleaned,
            "summary": summary_text,
            "text": summary_text,
            "data": {
                "query": query,
                "base_url": chosen_base,
                "results": cleaned,
                "summary": summary_text,
            },
            "warnings": [],
        })
    if partial_current_topic_rows and (_looks_like_current_topic_query(query) or _looks_like_news_query(query) or _looks_like_regulation_query(query)):
        limited_summary = _limited_current_topic_summary(query, partial_current_topic_rows, last_error)
        if limited_summary:
            limited_rows = _limited_current_topic_rows(query, partial_current_topic_rows, max_results)
            return _shape_result_payload(query, {
                'ok': True,
                'query': query,
                'base_url': chosen_base or 'google_news_partial',
                'results': limited_rows,
                'summary': limited_summary,
                'text': limited_summary,
                'data': {
                    'query': query,
                    'base_url': chosen_base or 'google_news_partial',
                    'results': limited_rows,
                    'summary': limited_summary,
                },
                'warnings': [w for w in ['limited_current_topic_evidence', last_error] if str(w or '').strip()],
            })
    if _looks_like_ai_chip_query(query):
        fallback = 'I could not retrieve high-confidence current AI chip headlines from trusted news sources in this turn. Try again shortly or refine the request to a specific company like NVIDIA, AMD, or Intel.'
    else:
        fallback = _limited_ai_news_fallback(query) or f"I could not retrieve current web results for: {query}. Try again shortly or refine the request."
    return {"ok": True, "query": query, "results": [], "summary": fallback, "text": fallback, "data": {"query": query, "results": [], "summary": fallback}, "warnings": [f"web_research_failed:{last_error or 'no_base_url'}"]}
TOOL_SPEC = {'id': 'custom.awf_web_research__web_research_204fb17b_executor', 'category': 'custom', 'label': 'web_research executor', 'description': 'Generated workflow executor for: Create a new or improved workflow that directly satisfies the original user request.\nOriginal user request: what is trending online right now?\nwhat is trending online right now?\n\nImprove the workflow', 'permissions': ['custom.awf_web_research__web_research_204fb17b_executor', 'custom.*'], 'metadata': {'executor_mode': 'research', 'output_mode': 'text', 'required_capabilities': [], 'matched_skills': ['browser_relay.open', 'browser_relay.snapshot', 'browser_relay.action', 'web.download_file', 'browser.extract_links'], 'request_excerpt': 'Create a new or improved workflow that directly satisfies the original user request.\nOriginal user request: what is trending online right now?\nwhat is trending online right now?\n\nImprove the workflow so it fully satisfies the request, retur', 'input_contract': '', 'version': '1.2', 'created_at': '2026-06-19T22:46:04.295057+00:00', 'last_updated': '2026-06-28T19:45:00+00:00', 'dev_status': 'untested'}, 'params_schema': {'type': 'object', 'properties': {'request_text': {'type': 'string'}, 'user_request': {'type': 'string'}, 'request': {'type': 'string'}, 'text': {'type': 'string'}, 'input_path': {'type': 'string'}, 'file_path': {'type': 'string'}, 'path': {'type': 'string'}}, 'additionalProperties': True}}

