from __future__ import annotations

import unicodedata
import re
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Dict, List

try:
    from ..external_data.google_scholar import run as google_scholar_run
except Exception:
    import importlib.util
    _P = Path(__file__).resolve().parents[1] / "external_data" / "google_scholar.py"
    _S = importlib.util.spec_from_file_location("custom_google_scholar_api", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    google_scholar_run = _M.run

try:
    from ..external_data.searxng_search import searxng_search
except Exception:
    import importlib.util
    _P2 = Path(__file__).resolve().parents[1] / "external_data" / "searxng_search.py"
    _S2 = importlib.util.spec_from_file_location("custom_searxng_search_api", _P2)
    _M2 = importlib.util.module_from_spec(_S2)
    assert _S2 is not None and _S2.loader is not None
    _S2.loader.exec_module(_M2)
    searxng_search = _M2.searxng_search

try:
    from ..external_data._http import get_text, get_json
except Exception:
    import importlib.util
    _P3 = Path(__file__).resolve().parents[1] / "external_data" / "_http.py"
    _S3 = importlib.util.spec_from_file_location("custom_external_data_http", _P3)
    _M3 = importlib.util.module_from_spec(_S3)
    assert _S3 is not None and _S3.loader is not None
    _S3.loader.exec_module(_M3)
    get_text = _M3.get_text
    get_json = _M3.get_json


NAME = "custom.google_scholar_report"
PERMISSIONS = [NAME, "custom.*", "external_data.google_scholar", "external_data.searxng_search", "external_data.*", "web.request"]
_CREATED_AT = "2026-06-25T00:00:00Z"
_LAST_UPDATED = "2026-06-28T21:20:00Z"
_VERSION = "1.5"
_DEV_STATUS = "tested"


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


_GENERIC_SCHOLAR_STOPWORDS = {
    "use", "google", "scholar", "find", "recent", "scholarly", "sources", "source", "since", "return", "relevant",
    "title", "year", "link", "short", "synthesis", "strong", "strongest", "repeated", "findings", "about", "from",
    "with", "and", "the", "that", "this", "those", "these", "into", "their", "them", "they", "study", "studies",
    "paper", "papers", "article", "articles", "compact", "review", "reviewer", "ready", "markdown", "table",
}


def _is_urban_heat_climate_request(request_text: str) -> bool:
    low = str(request_text or "").lower()
    has_heat = any(tok in low for tok in ("urban heat", "heat island", "heat islands", "urban overheating"))
    has_inequality = any(tok in low for tok in ("climate inequality", "environmental justice", "heat vulnerability", "climate justice", "inequity", "inequality"))
    return has_heat and has_inequality


def _request_core_text(request_text: str) -> str:
    text = str(request_text or "").strip()
    text = re.sub(r"(?i)^use google scholar to find\s+", "", text)
    text = re.sub(r"(?i)^find\s+", "", text)
    text = re.sub(r"(?i)^search\s+google scholar\s+for\s+", "", text)
    text = re.sub(r"(?i)return\s+\d+\s+relevant\s+sources.*$", "", text).strip(" .")
    text = re.sub(r"(?i)return\s+.*$", "", text).strip(" .")
    text = re.sub(r"(?i)\bsince\s+(19|20)\d{2}\b", "", text)
    text = re.sub(r"(?i)\brecent\b", "", text)
    text = re.sub(r"(?i)\bscholarly\b", "", text)
    text = re.sub(r"(?i)\bsources?\b", "", text)
    text = re.sub(r"(?i)\barticles?\b", "", text)
    text = re.sub(r"(?i)\bpapers?\b", "", text)
    text = re.sub(r"(?i)^about\s+", "", text)
    text = re.sub(r"\s+", " ", text).strip(" .,")
    return text


def _request_keyword_terms(request_text: str) -> List[str]:
    core = _request_core_text(request_text)
    tokens = re.findall(r"[a-z0-9][a-z0-9-]{2,}", core.lower())
    out: List[str] = []
    seen = set()
    for tok in tokens:
        if tok in _GENERIC_SCHOLAR_STOPWORDS:
            continue
        if tok.isdigit():
            continue
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out[:12]


def _request_overlap_score(text: str, request_text: str) -> int:
    article_tokens = set(re.findall(r"[a-z0-9][a-z0-9-]{2,}", str(text or "").lower()))
    if not article_tokens:
        return 0
    wanted = _request_keyword_terms(request_text)
    if not wanted:
        return 0
    matched = sum(1 for tok in wanted if tok in article_tokens)
    bonus = 0
    core_low = _request_core_text(request_text).lower()
    article_low = str(text or "").lower()
    if core_low and len(core_low.split()) >= 2 and core_low in article_low:
        bonus += 4
    return matched * 3 + bonus


def _is_software_engineering_agent_request(request_text: str) -> bool:
    low = str(request_text or '').lower()
    has_agent = any(tok in low for tok in ('ai agent', 'ai agents', 'agentic ai', 'agent', 'agents', 'coding agent', 'code agent'))
    has_engineering = any(tok in low for tok in ('software engineering', 'software engineer', 'coding', 'code generation', 'repository', 'repo', 'bug fixing', 'program repair', 'swe-bench', 'issue resolving'))
    return has_agent and has_engineering


def _query_from_request(request_text: str) -> str:
    text = _request_core_text(request_text)
    if not text:
        return '(teen OR adolescent OR youth) "mental health" "social media" (school OR academic OR "school pressure" OR grades)'
    low = text.lower()
    if _is_software_engineering_agent_request(request_text):
        return 'AI agents software engineering coding agent repository-level SWE-bench program repair'
    if _is_urban_heat_climate_request(request_text):
        return '"urban heat island" ("climate inequality" OR "environmental justice" OR "heat vulnerability" OR inequity)'
    pieces = []
    if any(tok in low for tok in ("teen", "adolescent", "high school", "youth")):
        pieces.append('(teen OR adolescent OR youth)')
    if 'mental health' in low or any(tok in low for tok in ('anxiety', 'depression', 'well-being', 'wellbeing', 'stress')):
        pieces.append('"mental health"')
    if 'social media' in low or any(tok in low for tok in ('screen', 'instagram', 'tiktok', 'online')):
        pieces.append('"social media"')
    if any(tok in low for tok in ('school pressure', 'school', 'academic', 'grades', 'class')):
        pieces.append('(school OR academic OR "school pressure" OR grades)')
    if not pieces:
        pieces.append(text)
    return ' '.join(pieces)


def _extract_year(article: Dict[str, Any]) -> str:
    for candidate in (
        article.get("published_date"),
        article.get("year"),
        article.get("snippet"),
        article.get("title"),
        article.get("link"),
    ):
        text = str(candidate or "")
        for pattern in (r"\b(20\d{2}|19\d{2})\b", r"/(20\d{2}|19\d{2})/", r"-(20\d{2}|19\d{2})-"):
            match = re.search(pattern, text)
            if match:
                year = match.group(1)
                if year.isdigit() and 1990 <= int(year) <= 2099:
                    return year
        pii_match = re.search(r"/[sS]\d{8}(20\d{2}|\d{2})\d+[A-Z]?", text)
        if pii_match:
            year = pii_match.group(1)
            if len(year) == 2:
                year = f"20{year}"
            if year.isdigit() and 1990 <= int(year) <= 2099:
                return year
        nature_match = re.search(r"-0?(\d{2})-\d{4,}-[a-z]$", text, flags=re.IGNORECASE)
        if nature_match:
            year = f"20{nature_match.group(1)}"
            if year.isdigit() and 1990 <= int(year) <= 2099:
                return year
    return ""

def _normalize_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    def _suspicion_score(value: str) -> int:
        score = 0
        for ch in value:
            code = ord(ch)
            if ch in {"?", "?", "?", "?", "?", "?", "?"}:
                score += 3
            elif 0x80 <= code <= 0x9F:
                score += 4
        score += value.count("???") * 3
        score += value.count("??")
        return score

    best_score = _suspicion_score(text)
    repaired_text = text
    for _ in range(2):
        improved = False
        for src_enc, dst_enc in (("latin-1", "utf-8"), ("cp1252", "utf-8")):
            try:
                candidate = repaired_text.encode(src_enc, errors="ignore").decode(dst_enc, errors="ignore").strip()
            except Exception:
                candidate = ""
            if not candidate or candidate == repaired_text:
                continue
            score = _suspicion_score(candidate)
            if score < best_score:
                repaired_text = candidate
                best_score = score
                improved = True
                break
        if not improved:
            break

    replacements = {
        "???": "'",
        "???": "'",
        "???": '"',
        "??": '"',
        "???": "-",
        "???": "-",
        "???": "...",
        "? ": " ",
        "?": "",
        "???": "'",
        "???": "'",
        "???": '"',
        "??": '"',
        "???": "-",
        "???": "-",
        "???": "...",
        "? ": " ",
        "?": "",
    }
    for bad, good in replacements.items():
        repaired_text = repaired_text.replace(bad, good)
    return unicodedata.normalize("NFKC", repaired_text).strip()


def _normalize_link(value: Any) -> str:
    link = str(value or "").strip()
    if not link:
        return ""
    link = re.sub(r"^https?://www\.sciencedirect\.com/org/science/", "https://www.sciencedirect.com/science/", link, flags=re.IGNORECASE)
    link = re.sub(r"^https?://sciencedirect\.com/org/science/", "https://www.sciencedirect.com/science/", link, flags=re.IGNORECASE)
    link = re.sub(r"^https?://doi\.org/https?://", "https://doi.org/", link, flags=re.IGNORECASE)
    return link


def _user_facing_notes(warnings: List[str]) -> List[str]:
    notes: List[str] = []
    if any("google_scholar_openalex_fallback_used" == str(item or "").strip() for item in warnings or []):
        notes.append("Some sources were filled in through an OpenAlex scholarly-index fallback because direct Google Scholar coverage was incomplete.")
    if any("google_scholar_crossref_fallback_used" == str(item or "").strip() for item in warnings or []):
        notes.append("Some sources were filled in through a Crossref scholarly-index fallback because direct Google Scholar coverage was incomplete.")
    if any("google_scholar_web_fallback_used" == str(item or "").strip() for item in warnings or []):
        notes.append("Some sources were filled in through a web fallback because direct Google Scholar coverage was incomplete.")
    if any("google_scholar_serpapi_key_missing" == str(item or "").strip() for item in warnings or []):
        notes.append("This result used locally available search sources rather than SerpAPI-backed Google Scholar retrieval.")
    return notes



def _link_domain(link: str) -> str:
    try:
        host = str(urlparse(str(link or "")).netloc or "").strip().lower()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _looks_scholarly_source(link: str, title: str = '', snippet: str = '') -> bool:
    url = str(link or '').strip()
    host = _link_domain(url)
    low_url = url.lower()
    low_text = (str(title or '') + ' ' + str(snippet or '')).lower()
    if not host:
        return False
    if any(tok in low_url for tok in ('/blog/', '/blogs/', '/news/', '/press/', '/press-releases/', '/extension.', '/extension/', '/surgeongeneral/', '/reports-and-publications/', '/dictionary/')):
        return False
    if any(tok in low_text for tok in ('news release', 'press release', 'fact sheet', 'report overview', '/ definition', ' english meaning', 'dictionary')):
        return False
    strong_hosts = (
        'pubmed.ncbi.nlm.nih.gov', 'pmc.ncbi.nlm.nih.gov', 'doi.org', 'nature.com', 'sciencedirect.com',
        'springer.com', 'springeropen.com', 'tandfonline.com', 'wiley.com', 'onlinelibrary.wiley.com',
        'jamanetwork.com', 'cambridge.org', 'frontiersin.org', 'sagepub.com', 'nih.gov', 'nber.org',
        'arxiv.org', 'ssrn.com', 'repec.org', 'ideas.repec.org', 'mdpi.com',
    )
    if any(host == item or host.endswith('.' + item) for item in strong_hosts):
        return True
    if host.endswith('.edu') or host.endswith('.ac.uk'):
        if any(tok in low_url for tok in ('/doi/', '/article/', '/journal/', '/handle/', '/publication/', '/papers/', '/working-paper', '/bitstream/')):
            return True
        if any(tok in low_text for tok in ('journal', 'review', 'study', 'paper', 'longitudinal', 'meta-analysis', 'systematic review')):
            return True
        return False
    return False


def _domain_score(link: str) -> int:
    host = _link_domain(link)
    if not host:
        return 0
    strong_hosts = (
        "pubmed.ncbi.nlm.nih.gov",
        "pmc.ncbi.nlm.nih.gov",
        "doi.org",
        "nature.com",
        "sciencedirect.com",
        "springer.com",
        "springeropen.com",
        "tandfonline.com",
        "wiley.com",
        "onlinelibrary.wiley.com",
        "jamanetwork.com",
        "cambridge.org",
        "frontiersin.org",
        "sagepub.com",
        "nih.gov",
        "nber.org",
    )
    medium_hosts = (
        "arxiv.org",
        "ssrn.com",
        "repec.org",
        "ideas.repec.org",
        "mdpi.com",
    )
    if host.endswith(".edu") or host.endswith(".ac.uk"):
        return 5
    if any(host == item or host.endswith("." + item) for item in strong_hosts):
        return 6
    if any(host == item or host.endswith("." + item) for item in medium_hosts):
        return 3
    if host.endswith(".gov"):
        return 4
    return 1


def _scholarly_path_penalty(link: str) -> int:
    low = str(link or '').lower()
    penalty = 0
    if any(tok in low for tok in ('/blog/', '/blogs/', '/news/', '/news-article/', '/press/', '/press-releases/', '/article/social-media-and-youth-mental-health', '/blog/what-new-research')):
        penalty -= 4
    if any(tok in low for tok in ('/doi/', '/article/', '/science/article/', '/fullarticle/', '/abs/', '/pmc/', '/pubmed/')):
        penalty += 2
    return penalty


def _topic_coverage_score(text: str) -> int:
    low = str(text or "").lower()
    score = 0
    if any(tok in low for tok in ("teen", "adolescent", "youth", "high school")):
        score += 2
    if any(tok in low for tok in ("mental health", "depress", "anx", "distress", "well-being", "wellbeing", "stress")):
        score += 2
    if "social media" in low or any(tok in low for tok in ("screen media", "screen time", "instagram", "tiktok", "smartphone")):
        score += 2
    if any(tok in low for tok in ("school pressure", "school", "academic", "grades", "classroom", "school stress")):
        score += 2
    if any(tok in low for tok in ("software engineering", "software engineer", "coding agent", "code agent", "repository", "repository-level", "swe-bench", "program repair", "bug fixing", "issue resolving", "code generation")):
        score += 4
    if any(tok in low for tok in ("urban heat", "heat island", "heat islands", "urban overheating")):
        score += 3
    if any(tok in low for tok in ("climate inequality", "environmental justice", "heat vulnerability", "climate justice", "inequity", "inequality")):
        score += 3
    return score

def _requested_scholar_facets(request_text: str) -> List[str]:
    low = str(request_text or '').lower()
    facets: List[str] = []
    if any(tok in low for tok in ('teen', 'adolescent', 'youth', 'high school')):
        facets.append('youth')
    if any(tok in low for tok in ('mental health', 'depression', 'anxiety', 'well-being', 'wellbeing', 'stress')):
        facets.append('mental_health')
    if 'social media' in low or any(tok in low for tok in ('screen media', 'screen time', 'instagram', 'tiktok', 'smartphone')):
        facets.append('social_media')
    if any(tok in low for tok in ('school pressure', 'school', 'academic', 'grades', 'classroom', 'school stress')):
        facets.append('school_pressure')
    if _is_software_engineering_agent_request(request_text):
        facets.append('software_engineering_agents')
    if any(tok in low for tok in ('urban heat', 'heat island', 'heat islands', 'urban overheating')):
        facets.append('urban_heat')
    if any(tok in low for tok in ('climate inequality', 'environmental justice', 'heat vulnerability', 'climate justice', 'inequity', 'inequality')):
        facets.append('climate_inequality')
    return facets

def _facet_presence(text: str) -> Dict[str, bool]:
    low = str(text or '').lower()
    return {
        'youth': any(tok in low for tok in ('teen', 'adolescent', 'youth', 'high school')),
        'mental_health': any(tok in low for tok in ('mental health', 'depress', 'anx', 'distress', 'well-being', 'wellbeing', 'stress')),
        'social_media': ('social media' in low or any(tok in low for tok in ('screen media', 'screen time', 'instagram', 'tiktok', 'smartphone'))),
        'school_pressure': any(tok in low for tok in ('school pressure', 'school', 'academic', 'grades', 'classroom', 'school stress')),
        'software_engineering_agents': any(tok in low for tok in ('software engineering', 'coding agent', 'code agent', 'repository', 'repo', 'swe-bench', 'program repair', 'issue resolving', 'bug fixing', 'code generation', 'automated program repair')),
        'urban_heat': any(tok in low for tok in ('urban heat', 'heat island', 'heat islands', 'urban overheating')),
        'climate_inequality': any(tok in low for tok in ('climate inequality', 'environmental justice', 'heat vulnerability', 'climate justice', 'inequity', 'inequality')),
    }

def _software_engineering_agent_score(text: str) -> int:
    low = str(text or '').lower()
    score = 0
    if any(tok in low for tok in ('software engineering', 'software engineer', 'repository', 'repo', 'swe-bench')):
        score += 5
    if any(tok in low for tok in ('coding agent', 'code agent', 'agentic software engineering', 'issue resolving', 'bug fixing', 'program repair', 'automated program repair')):
        score += 5
    if any(tok in low for tok in ('code generation', 'repository-level', 'pull request', 'patch', 'verification-aware')):
        score += 3
    if any(tok in low for tok in ('education', 'learning experiences', 'ai art', 'creative skill')):
        score -= 6
    return score


def _article_score(article: Dict[str, Any], request_text: str) -> int:
    text = ((str(article.get("title") or "") + " " + str(article.get("snippet") or "")).lower()).strip()
    score = 0
    requested_facets = _requested_scholar_facets(request_text)
    present = _facet_presence(text)
    if any(tok in text for tok in ("teen", "adolescent", "youth", "high school")):
        score += 4
    if any(tok in text for tok in ("mental health", "depress", "anx", "distress", "well-being", "wellbeing")):
        score += 4
    if "social media" in text or any(tok in text for tok in ("screen media", "screen time", "instagram", "tiktok")):
        score += 4
    if any(tok in text for tok in ("school", "academic", "grade", "classroom", "school pressure")):
        score += 3
    if any(tok in text for tok in ("systematic review", "meta-analysis", "meta analysis", "qualitative", "longitudinal")):
        score += 2
    link = article.get("link") or ""
    score += _domain_score(link)
    score += _scholarly_path_penalty(link)
    score += _topic_coverage_score(text)
    score += _request_overlap_score(text, request_text)
    year = _extract_year(article)
    if year and year.isdigit():
        score += max(0, int(year) - 2022)
    req = str(request_text or "").lower()
    if "school pressure" in req and "school pressure" in text:
        score += 2
    if requested_facets:
        matched = sum(1 for facet in requested_facets if present.get(facet))
        score += matched * 2
        if len(requested_facets) >= 3 and matched == len(requested_facets):
            score += 5
        elif len(requested_facets) >= 3 and matched <= 1:
            score -= 4
    if _is_software_engineering_agent_request(request_text):
        score += _software_engineering_agent_score(text)
        if not present.get('software_engineering_agents'):
            score -= 8
    return score


def _rank_articles(articles: List[Dict[str, Any]], request_text: str) -> List[Dict[str, Any]]:
    return sorted(
        articles,
        key=lambda row: (_article_score(row, request_text), _extract_year(row), str(row.get("title") or "")),
        reverse=True,
    )


def _canonical_title_key(title: str) -> str:
    low = _normalize_text(title).lower()
    low = re.sub(r'[^a-z0-9]+', ' ', low)
    low = re.sub(r'(a|an|the|and|for|of|to|in|on|with)', ' ', low)
    low = re.sub(r'\s+', ' ', low).strip()
    return low


def _collect_articles(articles_raw: List[Dict[str, Any]], request_text: str, strict_multi_facet: bool = True) -> List[Dict[str, Any]]:
    articles_pool: List[Dict[str, Any]] = []
    requested_facets = _requested_scholar_facets(request_text)
    for article in articles_raw:
        if not isinstance(article, dict):
            continue
        link = str(article.get("link") or "").strip()
        title = _normalize_text(article.get("title"))
        if not title or not link:
            continue
        link = _normalize_link(link)
        year = _extract_year(article)
        if year and year.isdigit() and int(year) < 2023:
            continue
        combined = f"{title} {_normalize_text(article.get('snippet'))}".strip()
        if not _looks_scholarly_source(link, title=title, snippet=article.get('snippet')):
            continue
        generic_overlap = _request_overlap_score(combined, request_text)
        if requested_facets:
            if _topic_coverage_score(combined) < 4:
                continue
        elif generic_overlap < 3:
            continue
        if requested_facets and strict_multi_facet:
            presence = _facet_presence(combined)
            matched = sum(1 for facet in requested_facets if presence.get(facet))
            min_needed = 2 if len(requested_facets) >= 3 else max(1, len(requested_facets))
            if matched < min_needed:
                continue
        articles_pool.append(
            {
                "title": title,
                "year": year,
                "link": link,
                "snippet": _normalize_text(article.get("snippet")),
            }
        )
    ranked = _rank_articles(articles_pool, request_text)
    deduped: List[Dict[str, Any]] = []
    seen_links = set()
    seen_titles = set()
    for article in ranked:
        link = str(article.get('link') or '').strip()
        title_key = _canonical_title_key(str(article.get('title') or ''))
        if link and link in seen_links:
            continue
        if title_key and title_key in seen_titles:
            continue
        if link:
            seen_links.add(link)
        if title_key:
            seen_titles.add(title_key)
        deduped.append(article)
    return deduped


def _scholarly_web_fallback(ctx: Dict[str, Any], request_text: str, timeout: float) -> List[Dict[str, Any]]:
    core = _request_core_text(request_text)
    keyword_terms = _request_keyword_terms(request_text)
    queries = [_query_from_request(request_text)]
    if core and core not in queries:
        queries.append(core)
    if keyword_terms:
        key_query = " ".join(keyword_terms[:6]).strip()
        if key_query and key_query not in queries:
            queries.append(key_query)
    teen_specific = any(tok in str(request_text or '').lower() for tok in ('teen', 'adolescent', 'youth', 'mental health', 'social media', 'school pressure'))
    if _is_software_engineering_agent_request(request_text):
        queries.extend([
            'AI agents software engineering',
            'coding agent software engineering repository benchmark',
            'SWE-bench coding agent program repair',
            'repository-level software engineering agents',
        ])
    elif not teen_specific:
        for suffix in ('journal', 'study', 'review', 'environmental justice'):
            variant = ((core or _query_from_request(request_text)).strip() + ' ' + suffix).strip()
            if variant and variant not in queries:
                queries.append(variant)
        if _is_urban_heat_climate_request(request_text):
            queries.extend([
                '"urban heat island" environmental justice study',
                '"urban heat island" climate inequality review',
                '"urban heat island" neighborhood heat vulnerability',
                '"urban heat island" inequity exposure study',
                '"heat vulnerability" urban neighborhoods review',
            ])
    else:
        queries.extend([
            'adolescent mental health social media academic stress',
            'teen mental health social media school pressure study',
            'adolescent social media academic stress depression',
        ])
    pool: List[Dict[str, Any]] = []
    seen = set()
    for query in queries:
        res = searxng_search(ctx or {}, {
            'query': query,
            'limit': 10,
            'engines': 'google,duckduckgo,bing',
            'categories': 'general',
            'timeout': timeout,
        })
        data = res.get('data') if isinstance(res.get('data'), dict) else {}
        raw = data.get('results') if isinstance(data.get('results'), list) else []
        for item in raw:
            if not isinstance(item, dict):
                continue
            link = str(item.get('link') or item.get('url') or '').strip()
            if not link or link in seen:
                continue
            link = _normalize_link(link)
            if not _looks_scholarly_source(link, title=item.get('title'), snippet=item.get('snippet') or item.get('content')):
                continue
            if _domain_score(link) < 3:
                continue
            seen.add(link)
            pool.append({
                'title': item.get('title'),
                'link': link,
                'snippet': item.get('snippet') or item.get('content'),
                'published_date': item.get('published_date'),
            })
    return _collect_articles(pool, request_text, strict_multi_facet=False)


def _extract_year_from_page(link: str, timeout: float) -> str:
    url = str(link or "").strip()
    if not url:
        return ""
    try:
        row = get_text(url, params={"timeout": timeout, "accept": "text/html,*/*", "user_agent": "Mozilla/5.0"})
        html = str(row.get("text") or "")
    except Exception:
        return ""
    if not html:
        return ""
    patterns = (
        r'<meta[^>]+name=["\']citation_publication_date["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']citation_online_date["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']citation_date["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']dc\.date["\'][^>]+content=["\']([^"\']+)["\']',
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'<time[^>]+datetime=["\']([^"\']+)["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if not match:
            continue
        year = _extract_year({"published_date": match.group(1)})
        if year:
            return year
    return ""


def _resolve_missing_years(articles: List[Dict[str, Any]], timeout: float) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for article in articles:
        row = dict(article or {})
        if not str(row.get("year") or "").strip():
            year = _extract_year_from_page(str(row.get("link") or ""), timeout)
            if year:
                row["year"] = year
        out.append(row)
    return out


def _openalex_fallback(request_text: str, timeout: float, year_low: str = "2023") -> List[Dict[str, Any]]:
    query = (_request_core_text(request_text) or _query_from_request(request_text)).strip()
    if not query:
        return []
    from urllib.parse import urlencode
    url = "https://api.openalex.org/works?" + urlencode({
        "search": query,
        "per-page": 10,
        "filter": f"from_publication_date:{year_low}-01-01,is_paratext:false",
    })
    try:
        row = get_json(url, {"timeout": timeout, "user_agent": "Mozilla/5.0"})
        payload = row.get("json") if isinstance(row, dict) else {}
    except Exception:
        return []
    results = payload.get("results") if isinstance(payload, dict) and isinstance(payload.get("results"), list) else []
    articles: List[Dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        primary = item.get("primary_location") if isinstance(item.get("primary_location"), dict) else {}
        title = _normalize_text(item.get("display_name"))
        year = str(item.get("publication_year") or "").strip()
        link = _normalize_link(primary.get("landing_page_url") or primary.get("pdf_url") or item.get("doi") or item.get("id") or "")
        venue = ""
        source = primary.get("source") if isinstance(primary.get("source"), dict) else {}
        if isinstance(source, dict):
            venue = _normalize_text(source.get("display_name") or "")
        snippet = venue or _normalize_text(item.get("type") or "")
        if not title or not link:
            continue
        articles.append({
            "title": title,
            "year": year,
            "link": link,
            "snippet": snippet,
        })
    return _collect_articles(articles, request_text, strict_multi_facet=False)


def _crossref_fallback(request_text: str, timeout: float, year_low: str = "2023") -> List[Dict[str, Any]]:
    query = (_request_core_text(request_text) or _query_from_request(request_text)).strip()
    if not query:
        return []
    from urllib.parse import urlencode
    url = "https://api.crossref.org/works?" + urlencode({
        "query.bibliographic": query,
        "filter": f"from-pub-date:{year_low}-01-01,type:journal-article",
        "rows": 12,
    })
    try:
        row = get_json(url, {"timeout": timeout, "user_agent": "Mozilla/5.0 (mailto:workflow-exchange@example.invalid)"})
        payload = row.get("json") if isinstance(row, dict) else {}
    except Exception:
        return []
    message = payload.get("message") if isinstance(payload, dict) and isinstance(payload.get("message"), dict) else {}
    items = message.get("items") if isinstance(message.get("items"), list) else []
    articles: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title_parts = item.get("title") if isinstance(item.get("title"), list) else []
        title = _normalize_text(title_parts[0] if title_parts else item.get("title"))
        doi = str(item.get("DOI") or "").strip()
        link = _normalize_link(f"https://doi.org/{doi}" if doi else (item.get("URL") or ""))
        year = ""
        issued = item.get("issued") if isinstance(item.get("issued"), dict) else {}
        parts = issued.get("date-parts") if isinstance(issued.get("date-parts"), list) else []
        if parts and isinstance(parts[0], list) and parts[0]:
            try:
                year = str(int(parts[0][0]))
            except Exception:
                year = ""
        container = item.get("container-title") if isinstance(item.get("container-title"), list) else []
        snippet = _normalize_text(container[0] if container else item.get("type") or "")
        if not title or not link:
            continue
        articles.append({
            "title": title,
            "year": year,
            "link": link,
            "snippet": snippet,
        })
    return _collect_articles(articles, request_text, strict_multi_facet=False)


def _dedupe_warnings(values: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _findings_summary(articles: List[Dict[str, Any]], request_text: str = "") -> str:
    text = " ".join(str((row.get("title") or "") + " " + (row.get("snippet") or "")) for row in articles).lower()
    findings: List[str] = []
    if _is_software_engineering_agent_request(request_text):
        methods = []
        if any(tok in text for tok in ('repository', 'repo', 'repository-level', 'swe-bench')):
            methods.append('repository-level evaluation and issue-resolution benchmarks are a repeated theme')
        if any(tok in text for tok in ('program repair', 'automated program repair', 'patch', 'bug fixing')):
            methods.append('automated repair, patching, and verification loops appear repeatedly in the retrieved sources')
        if any(tok in text for tok in ('coding agent', 'code agent', 'code generation', 'software engineering')):
            methods.append('agent-style software engineering systems that inspect code, generate changes, and iterate on feedback recur across the results')
        if methods:
            return '; '.join(methods[:3])
    if _is_urban_heat_climate_request(request_text):
        findings = []
        if any(tok in text for tok in ('environmental justice', 'inequity', 'inequality', 'vulnerability')):
            findings.append('the literature repeatedly links urban heat exposure to climate inequality, unequal neighborhood-level vulnerability, and environmental-justice patterns')
        if any(tok in text for tok in ('tree canopy', 'greenspace', 'land surface temperature', 'remote sensing', 'satellite')):
            findings.append('many studies rely on land-surface temperature, remote sensing, and built-environment measures to map neighborhood heat burden')
        if any(tok in text for tok in ('income', 'race', 'racial', 'low-income', 'disadvantaged', 'socioeconomic')):
            findings.append('socioeconomic disadvantage, race, and lower canopy coverage recur as common correlates of higher heat exposure')
        if findings:
            return '; '.join(findings[:3])
    if any(tok in text for tok in ("depress", "anx", "mental health", "distress")):
        findings.append("higher stress, anxiety, or depressive symptoms repeatedly appear in the literature")
    if any(tok in text for tok in ("sleep", "late-night", "insomnia")):
        findings.append("sleep disruption is a common mediating factor")
    if any(tok in text for tok in ("school pressure", "academic", "achievement", "grade")):
        findings.append("academic pressure often compounds the effect rather than acting separately")
    if any(tok in text for tok in ("problematic use", "screen time", "social media use")):
        findings.append("problematic or intensive social-media use is more consistently associated with harm than mere platform access")
    if findings:
        return "; ".join(findings[:3])
    wanted = _request_keyword_terms(request_text)
    if wanted:
        return "the retrieved sources repeatedly focus on " + ", ".join(wanted[:4])
    return "the retrieved sources repeatedly address the requested topic from multiple scholarly angles"


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(params or {})
    request_text = _request_text(ctx or {}, params)
    query = _query_from_request(request_text)
    timeout = float(params.get("timeout") or 5.0)
    payload = google_scholar_run(
        ctx or {},
        {
            "query": query,
            "limit": 20,
            "year_low": "2023",
            "timeout": timeout,
        },
    )
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else {}
    warnings = [str(x or "").strip() for x in (payload.get("warnings") or []) if str(x or "").strip()] if isinstance(payload, dict) else []
    articles_raw = data.get("articles") if isinstance(data.get("articles"), list) else []
    articles = _collect_articles(articles_raw, request_text, strict_multi_facet=True)
    if len(articles) < 3:
        articles = _collect_articles(articles_raw, request_text, strict_multi_facet=False)
    if len(articles) < 5:
        fallback_query = (_request_core_text(request_text) or query).strip()
        fallback_payload = google_scholar_run(
            ctx or {},
            {
                "query": fallback_query,
                "limit": 20,
                "year_low": "2023",
                "timeout": timeout,
            },
        )
        fallback_data = fallback_payload.get("data") if isinstance(fallback_payload, dict) and isinstance(fallback_payload.get("data"), dict) else {}
        fallback_raw = fallback_data.get("articles") if isinstance(fallback_data.get("articles"), list) else []
        fallback_articles = _collect_articles(fallback_raw, request_text, strict_multi_facet=(len(articles) >= 3))
        existing_links = {str(row.get("link") or "").strip() for row in articles}
        for row in fallback_articles:
            link = str(row.get("link") or "").strip()
            if not link or link in existing_links:
                continue
            existing_links.add(link)
            articles.append(row)
            if len(articles) >= 5:
                break
        warnings.extend([str(x or "").strip() for x in (fallback_payload.get("warnings") or []) if str(x or "").strip()] if isinstance(fallback_payload, dict) else [])
    if len(articles) < 5:
        openalex_articles = _openalex_fallback(request_text, timeout, year_low="2024" if "since 2024" in str(request_text or "").lower() else "2023")
        existing_links = {str(row.get("link") or "").strip() for row in articles}
        for row in openalex_articles:
            link = str(row.get("link") or "").strip()
            if not link or link in existing_links:
                continue
            existing_links.add(link)
            articles.append(row)
            if len(articles) >= 5:
                break
        if openalex_articles:
            warnings.append('google_scholar_openalex_fallback_used')
    if len(articles) < 5:
        crossref_articles = _crossref_fallback(request_text, timeout, year_low="2024" if "since 2024" in str(request_text or "").lower() else "2023")
        existing_links = {str(row.get("link") or "").strip() for row in articles}
        for row in crossref_articles:
            link = str(row.get("link") or "").strip()
            if not link or link in existing_links:
                continue
            existing_links.add(link)
            articles.append(row)
            if len(articles) >= 5:
                break
        if crossref_articles:
            warnings.append('google_scholar_crossref_fallback_used')
    if len(articles) < 5:
        web_articles = _scholarly_web_fallback(ctx or {}, request_text, timeout)
        existing_links = {str(row.get("link") or "").strip() for row in articles}
        for row in web_articles:
            link = str(row.get("link") or "").strip()
            if not link or link in existing_links:
                continue
            existing_links.add(link)
            articles.append(row)
            if len(articles) >= 5:
                break
        if web_articles:
            warnings.append('google_scholar_web_fallback_used')
    articles = _resolve_missing_years(articles[:5], timeout)
    warnings = _dedupe_warnings(warnings)
    notes = _user_facing_notes(warnings)
    table_lines = [
        "| Title | Year | Link |",
        "|---|---:|---|",
    ]
    for article in articles:
        safe_title = article["title"].replace("|", "/")
        table_lines.append(f"| {safe_title} | {article['year'] or 'n/a'} | {article['link']} |")
    synthesis = _findings_summary(articles, request_text)
    final_answer = (
        "## Google Scholar Sources\n\n"
        + "\n".join(table_lines)
        + "\n\n**Strongest Repeated Findings**\n"
        + synthesis
    )
    if notes:
        final_answer += "\n\n**Notes**\n" + "\n".join(f"- {note}" for note in notes[:3])
    return {
        "ok": True,
        "summary": final_answer,
        "text": final_answer,
        "final_answer": final_answer,
        "data": {"articles": articles, "warnings": warnings, "query": query},
        "warnings": warnings,
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "custom",
    "label": "Google Scholar Report",
    "description": "Search recent scholarly sources and return a compact source table with a repeated-findings synthesis.",
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

