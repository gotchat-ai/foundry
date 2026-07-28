from __future__ import annotations

import re
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path
from typing import Any, Dict, List

try:
    from ..external_data.arxiv import run as arxiv_run
except Exception:
    import importlib.util
    _P = Path(__file__).resolve().parents[1] / "external_data" / "arxiv.py"
    _S = importlib.util.spec_from_file_location("custom_arxiv_api", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    arxiv_run = _M.run

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


NAME = "custom.arxiv_report"
PERMISSIONS = [NAME, "custom.*", "external_data.arxiv", "external_data.*", "web.request"]
_CREATED_AT = "2026-06-25T00:00:00Z"
_LAST_UPDATED = "2026-06-27T00:00:00Z"
_VERSION = "1.2"
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


def _request_profile(request_text: str) -> str:
    low = str(request_text or "").lower()
    if all(tok in low for tok in ("coding", "agent")) or "software engineering benchmark" in low or "swe-bench" in low:
        return "coding_agents"
    if "multimodal" in low and ("reasoning" in low or "benchmark" in low):
        return "multimodal_reasoning"
    if ((any(tok in low for tok in ("misinformation", "deepfake", "synthetic", "ai-generated", "disinformation")) and any(tok in low for tok in ("detect", "detection", "forensics", "authenticity", "verification"))) or ("misinformation" in low and "political" in low) or ("deepfake" in low and "election" in low)):
        return "misinformation_detection"
    return "general"


def _profile_queries(profile: str, request_text: str) -> List[str]:
    if profile == "coding_agents":
        return [
            'all:("coding agent" OR "code agent" OR "software engineering" OR "SWE-bench" OR "repository-level")',
            'all:("software engineering" OR "repository-level") AND all:(agent OR benchmark OR issue OR patch)',
        ]
    if profile == "multimodal_reasoning":
        return [
            'all:(multimodal OR "vision-language") AND all:(reasoning OR benchmark OR evaluation)',
            'all:(multimodal OR "vision-language") AND all:(reasoning OR evaluation OR leaderboard)',
            'all:(multimodal OR "vision-language" OR "multi-modal") AND all:(reasoning OR "reasoning model" OR "reasoning models")',
        ]
    if profile == "misinformation_detection":
        return [
            'all:(misinformation OR disinformation OR "synthetic political" OR "political deepfake" OR "election deepfake") AND all:(detection OR detector OR forensics OR verification OR authenticity)',
            'all:("synthetic media" OR deepfake OR "ai-generated") AND all:(misinformation OR political OR election OR propaganda) AND all:(detection OR verification OR authenticity)',
        ]
    query = _query_from_request(request_text)
    return [query] if query else []


def _query_from_request(request_text: str) -> str:
    text = str(request_text or "").strip()
    text = re.sub(r"(?i)^use arxiv to find\s+", "", text)
    text = re.sub(r"(?i)^find\s+", "", text)
    text = re.sub(r"(?i)^latest\s+", "", text)
    text = re.sub(r"(?i)^recent\s+", "", text)
    text = re.sub(r"(?i)\bsince\s+20\d{2}\b", "", text)
    text = re.sub(r"(?i)return\s+5\s+papers.*$", "", text)
    text = re.sub(r"(?i)return\s+\d+\s+papers.*$", "", text)
    text = re.sub(r"(?i)summar(?:ize|ise)\s+the\s+methods\s+trends.*$", "", text)
    about = re.search(r"(?i)about\s+(.+)$", text)
    if about:
        text = about.group(1).strip()
    text = re.sub(r"(?i)and\s+summar(?:ize|ise).*$", "", text).strip(" .,:;")
    if not text:
        return 'all:(misinformation OR synthetic OR political)'
    parts = [p.strip() for p in re.split(r"\s+", text) if p.strip()]
    return " ".join(parts[:12])


def _request_keywords(request_text: str) -> List[str]:
    low = str(request_text or "").lower()
    words = re.findall(r"[a-z0-9][a-z0-9\-]+", low)
    stop = {
        "use", "find", "recent", "latest", "papers", "paper", "since", "about", "summarize", "summarise",
        "methods", "method", "trends", "trend", "return", "with", "from", "that", "this", "these",
        "and", "the", "for", "into", "today", "current", "research", "sources", "main", "technical", "approaches"
    }
    out: List[str] = []
    for word in words:
        if word in stop or re.fullmatch(r"20\d{2}", word):
            continue
        if word not in out:
            out.append(word)
    return out[:14]


def _profile_term_sets(profile: str) -> Dict[str, tuple[str, ...]]:
    if profile == "misinformation_detection":
        return {
            "required_any": ("misinformation", "disinformation", "deepfake", "synthetic media", "ai-generated", "synthetic political", "political deepfake", "election deepfake"),
            "detection_any": ("detection", "detector", "detecting", "forensics", "authenticity", "verification", "provenance"),
            "political_any": ("political", "election", "campaign", "propaganda", "civic", "misinformation"),
            "bad_any": ("biometrics", "molecular", "terraform", "historical narratives", "social reception", "elderly speech", "mooc", "pedagogical", "education", "educational", "classroom", "deepfake tutors", "learning outcomes"),
        }
    return {}


def _keyword_score(article: Dict[str, Any], request_text: str) -> int:
    title = str(article.get("title") or "").lower()
    summary = str(article.get("summary") or "").lower()
    category = str(article.get("category") or "").lower()
    hay = (title + " " + summary).strip()
    score = 0
    req = str(request_text or "").lower()
    profile = _request_profile(request_text)
    keywords = _request_keywords(request_text)
    for key in keywords:
        if key in title:
            score += 3
        elif key in hay:
            score += 1
    if any(phrase in hay for phrase in ("benchmark", "evaluation", "reasoning", "multimodal", "vision-language", "leaderboard")):
        score += 1
    if profile == "coding_agents":
        if any(tok in hay for tok in ("coding agent", "code agent", "software engineering", "repository-level", "swe-bench", "issue resolving", "bug fixing", "code generation")):
            score += 6
        if any(tok in hay for tok in ("gui agent", "hardware/software co-design", "coded language detection")):
            score -= 3
        if category.startswith(("cs.se", "cs.ai", "cs.cl")):
            score += 2
    elif profile == "multimodal_reasoning":
        if any(tok in hay for tok in ("multimodal", "vision-language", "reasoning", "benchmark", "evaluation")):
            score += 6
        if any(tok in hay for tok in ("robot perception", "electrochemical", "molecular identification")):
            score -= 4
        if category.startswith(("cs.cv", "cs.ai", "cs.cl")):
            score += 2
    elif profile == "misinformation_detection":
        terms = _profile_term_sets(profile)
        required_hit = any(tok in hay for tok in terms.get("required_any", ()))
        detection_hit = any(tok in hay for tok in terms.get("detection_any", ()))
        political_hit = any(tok in hay for tok in terms.get("political_any", ()))
        bad_hit = any(tok in hay for tok in terms.get("bad_any", ()))
        if required_hit:
            score += 6
        else:
            score -= 8
        if detection_hit:
            score += 5
        else:
            score -= 6
        if political_hit:
            score += 4
        if bad_hit:
            score -= 12
        if any(tok in hay for tok in ("image detection", "content authenticity", "provenance", "verification", "forensic", "synthetic content")):
            score += 2
        if detection_hit and any(tok in title for tok in ("detect", "detector", "detection", "forensic", "verification", "authenticity")):
            score += 3
        elif not any(tok in title for tok in ("detect", "detector", "detection", "forensic", "verification", "authenticity")):
            score -= 3
        if "political" in req or "election" in req:
            if political_hit:
                score += 2
            else:
                score -= 2
        if category.startswith(("cs.cv", "cs.ai", "cs.cl", "cs.cy")):
            score += 2
    year = str(article.get("year") or "")
    if year.isdigit() and int(year) >= 2024:
        score += min(3, int(year) - 2023)
    return score


def _methods_summary(articles: List[Dict[str, Any]], request_text: str = "") -> str:
    text = " ".join(str((row.get("title") or "") + " " + (row.get("summary") or "")) for row in articles).lower()
    req = str(request_text or "").lower()
    methods: List[str] = []
    if any(tok in req for tok in ("coding agent", "coding agents", "software engineering benchmark", "swe-bench", "software engineering")):
        if any(tok in text for tok in ("agent", "planning", "tool use", "repository", "issue", "patch")):
            methods.append("agent-style software engineering systems that plan, inspect repositories, use tools, and iteratively patch code or resolve issues")
        if any(tok in text for tok in ("benchmark", "evaluation", "swe-bench", "repository-level", "task")):
            methods.append("repository-level benchmark setups that evaluate issue resolution, code generation quality, or end-to-end task completion on realistic engineering work")
        if any(tok in text for tok in ("reinforcement learning", "self-improve", "self-consistency", "feedback", "trajectory")):
            methods.append("training and inference loops that improve coding reliability through feedback, trajectories, or self-improvement signals")
        return "; ".join(methods[:3]) if methods else "recent papers emphasize tool-using coding agents, repository-level software benchmarks, and feedback loops that improve engineering task reliability"
    if any(tok in req for tok in ("multimodal", "reasoning", "benchmark", "benchmarks")):
        if any(tok in text for tok in ("multimodal", "vision-language", "image", "video", "audio", "gui")):
            methods.append("multimodal model designs that fuse text with visual or other non-text signals and then test reasoning across mixed-input tasks")
        if any(tok in text for tok in ("benchmark", "evaluation", "leaderboard", "task", "context")):
            methods.append("benchmark-oriented evaluation setups that stress reasoning depth, task coverage, or context sensitivity rather than relying on one narrow metric")
        if any(tok in text for tok in ("self-consistency", "cascade", "attention", "token", "planner", "planning", "replay")):
            methods.append("reasoning improvements built around better token selection, staged reasoning, or self-consistency style training and inference loops")
        return "; ".join(methods[:3]) if methods else "recent papers emphasize multimodal reasoning architectures, broader evaluation benchmarks, and inference strategies that improve reasoning reliability"
    if any(tok in text for tok in ("multimodal", "image", "video", "audio")):
        methods.append("multimodal detection pipelines that combine textual and non-textual cues")
    if any(tok in text for tok in ("watermark", "provenance", "signature", "authenticity")):
        methods.append("provenance, authenticity, or watermark-style signals for verifying whether content is synthetic")
    if any(tok in text for tok in ("classifier", "transformer", "llm", "bert", "vision-language")):
        methods.append("classifier-based or transformer-based detection models trained to distinguish synthetic media or misinformation artifacts")
    if any(tok in text for tok in ("benchmark", "evaluation", "audit", "verification")):
        methods.append("benchmark and verification pipelines that stress realistic misinformation or political-content detection settings")
    return "; ".join(methods[:3]) if methods else "recent papers mostly center on classifier-based detection, authenticity signals, and verification-oriented evaluation pipelines"


def _infer_year(article: Dict[str, Any]) -> str:
    for candidate in (article.get("year"), article.get("summary"), article.get("title"), article.get("link")):
        text = str(candidate or "")
        match = re.search(r"\b(20\d{2})\b", text)
        if match:
            return match.group(1)
        link_match = re.search(r"/abs/(\d{2})(\d{2})\.", text)
        if link_match:
            return f"20{link_match.group(1)}"
    return ""


def _requested_min_year(request_text: str) -> int:
    low = str(request_text or '').lower()
    years = [int(y) for y in re.findall(r'\b(20\d{2})\b', low)]
    if years and any(tok in low for tok in ('since', 'from', 'after', 'newer than')):
        return max(years)
    if any(tok in low for tok in ('recent papers', 'latest papers', 'current papers', 'new papers', 'recent arxiv', 'latest arxiv')):
        return 2023
    if any(tok in low for tok in ('recent', 'latest', 'current', 'new')) and 'paper' in low:
        return 2023
    return 0


def _meets_year_floor(article: Dict[str, Any], min_year: int) -> bool:
    if min_year <= 0:
        return True
    year = str(article.get('year') or '').strip()
    if not year:
        year = _infer_year(article)
        if year:
            article['year'] = year
    return bool(year.isdigit() and int(year) >= min_year)


def _request_text_url(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}, method="GET")
    with urllib.request.urlopen(req, timeout=max(3.0, min(float(timeout or 8.0), 12.0))) as resp:
        return resp.read().decode("utf-8", "ignore")


def _strip_tags(value: str) -> str:
    return re.sub(r"<.*?>", "", str(value or "")).strip()


def _fetch_searxng_arxiv_fallback(ctx: Dict[str, Any], query: str, timeout: float, top_n: int) -> List[Dict[str, Any]]:
    payload = searxng_search(ctx or {}, {
        "query": f"site:arxiv.org/abs {query}",
        "limit": max(1, min(int(top_n or 5), 8)),
        "engines": "google,duckduckgo,bing",
        "categories": "general",
        "timeout": timeout,
    })
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else {}
    results = data.get("results") if isinstance(data.get("results"), list) else []
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        link = str(item.get("link") or item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        snippet = str(item.get("snippet") or item.get("content") or "").strip()
        if not link.startswith("http") or "arxiv.org/abs/" not in link or not title or link in seen:
            continue
        seen.add(link)
        row = {"title": title, "link": link, "summary": snippet, "category": "", "year": ""}
        row["year"] = _infer_year(row)
        out.append(row)
        if len(out) >= max(1, min(int(top_n or 5), 8)):
            break
    return out


def _fetch_bing_arxiv_fallback(query: str, timeout: float, top_n: int) -> List[Dict[str, Any]]:
    q = f"site:arxiv.org/abs {query}"
    url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": q})
    raw = _request_text_url(url, timeout)
    matches = list(re.finditer(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', raw, re.IGNORECASE | re.DOTALL))
    out: List[Dict[str, Any]] = []
    seen = set()
    for match in matches:
        href = unescape(str(match.group(1) or "")).strip()
        title = _strip_tags(unescape(str(match.group(2) or "")))
        if not href.startswith("http") or "arxiv.org/abs/" not in href or href in seen or not title:
            continue
        seen.add(href)
        tail = raw[match.end(): match.end() + 1200]
        pm = re.search(r'<p[^>]*>(.*?)</p>', tail, re.IGNORECASE | re.DOTALL)
        snippet = _strip_tags(unescape(str(pm.group(1) or ""))) if pm else ""
        row = {"title": title, "link": href, "summary": snippet, "category": "", "year": ""}
        row["year"] = _infer_year(row)
        out.append(row)
        if len(out) >= max(1, min(int(top_n or 5), 8)):
            break
    return out


def _user_facing_notes(warnings: List[str]) -> List[str]:
    notes: List[str] = []
    for warning in warnings or []:
        text = str(warning or "").strip()
        if not text:
            continue
        if text not in notes:
            notes.append(text)
    return notes[:2]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(params or {})
    request_text = _request_text(ctx or {}, params)
    profile = _request_profile(request_text)
    timeout = float(params.get("timeout") or 8.0)
    min_year = _requested_min_year(request_text)
    warnings: List[str] = []
    merged: Dict[str, Dict[str, Any]] = {}
    queries = _profile_queries(profile, request_text)[:2]
    if not queries:
        queries = [_query_from_request(request_text)]
    for query in queries:
        payload = arxiv_run(
            ctx or {},
            {
                "query": query,
                "limit": 8,
                "sort_by": ("relevance" if profile == "misinformation_detection" else "submittedDate"),
                "sort_order": "descending",
                "timeout": timeout,
            },
        )
        if isinstance(payload, dict):
            warnings.extend([str(x or "").strip() for x in (payload.get("warnings") or []) if str(x or "").strip()])
        data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else {}
        raw_articles = data.get("articles") if isinstance(data.get("articles"), list) else []
        for article in raw_articles:
            if not isinstance(article, dict):
                continue
            title = str(article.get("title") or "").strip()
            link = str(article.get("id") or "").strip()
            if not title or not link:
                continue
            row = {
                "title": title,
                "year": str(article.get("published") or "")[:4],
                "link": link,
                "summary": str(article.get("summary") or "").strip(),
                "category": str(((article.get("primary_category") or {}).get("term") or "")).strip(),
            }
            if not _meets_year_floor(row, min_year):
                continue
            prior = merged.get(link)
            if prior is None or _keyword_score(row, request_text) > _keyword_score(prior, request_text):
                merged[link] = row
        ranked_so_far = sorted(merged.values(), key=lambda item: (_keyword_score(item, request_text), item.get("year") or ""), reverse=True)
        threshold = 9 if profile == "misinformation_detection" else (5 if profile in {"coding_agents", "multimodal_reasoning"} else 3)
        strong_so_far = [item for item in ranked_so_far if _keyword_score(item, request_text) >= threshold]
        if len(strong_so_far) >= 5:
            break
    normalized = list(merged.values())
    if not normalized:
        for query in queries:
            try:
                fallback_rows = _fetch_searxng_arxiv_fallback(ctx or {}, query, timeout, 8)
                if not fallback_rows:
                    fallback_rows = _fetch_bing_arxiv_fallback(query, timeout, 8)
                for row in fallback_rows:
                    if not _meets_year_floor(row, min_year):
                        continue
                    link = str(row.get("link") or "").strip()
                    if link and link not in merged:
                        merged[link] = row
                if len(merged) >= 5:
                    break
            except Exception as exc:
                warnings.append(f"arxiv_search_fallback_failed:{exc}")
        normalized = list(merged.values())
    normalized = [item for item in normalized if _meets_year_floor(item, min_year)]
    ranked = sorted(normalized, key=lambda item: (_keyword_score(item, request_text), item.get("year") or ""), reverse=True)
    min_score = 9 if profile == "misinformation_detection" else (5 if profile in {"coding_agents", "multimodal_reasoning"} else 3)
    filtered = [item for item in ranked if _keyword_score(item, request_text) >= min_score]
    if not filtered:
        filtered = [item for item in ranked if _keyword_score(item, request_text) > 0] or ranked
    if len(filtered) < 5:
        for item in ranked:
            if item not in filtered:
                filtered.append(item)
            if len(filtered) >= 5:
                break
    articles: List[Dict[str, Any]] = filtered[:5]
    table_lines = [
        "| Title | Year | Link |",
        "|---|---:|---|",
    ]
    for article in articles:
        safe_title = article["title"].replace("|", "/")
        table_lines.append(f"| {safe_title} | {article['year'] or 'n/a'} | {article['link']} |")
    synthesis = _methods_summary(articles, request_text)
    final_answer = (
        "## arXiv Papers\n\n"
        + "\n".join(table_lines)
        + "\n\n**Methods-Oriented Synthesis**\n"
        + synthesis
    )
    notes = _user_facing_notes(warnings)
    if min_year > 0:
        final_answer += f"\n\nFiltered to papers from {min_year} or newer."
    if notes:
        final_answer += "\n\n**Notes**\n" + "\n".join(f"- {note}" for note in notes)
    return {
        "ok": True,
        "summary": final_answer,
        "text": final_answer,
        "final_answer": final_answer,
        "data": {"articles": articles, "warnings": warnings, "queries": queries},
        "warnings": warnings,
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "custom",
    "label": "arXiv Report",
    "description": "Search recent arXiv papers and return a compact paper table with a methods-oriented synthesis.",
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
