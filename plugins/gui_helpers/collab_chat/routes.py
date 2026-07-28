from __future__ import annotations

import json
import os
import queue
import secrets
import re
import sqlite3
import threading
import time
import unicodedata
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple, Iterable

import asyncio
from fastapi import APIRouter, HTTPException, Request, Body, Query
from pydantic import BaseModel, Field
import httpx

try:
    from sse_starlette.sse import EventSourceResponse
except Exception:  # pragma: no cover
    EventSourceResponse = None

from fastapi.responses import JSONResponse, StreamingResponse, PlainTextResponse


from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled, _parse_enabled_header
from plugins.gui_helpers._framework.services import register_plugin_service


GUI_PLUGIN_ID = "collab_chat"
NO_FLOW_VALUE = "__none__"
LLM_AUTOFLOW_FLOW_VALUE = "__llm_autoflow__"
LLM_SKILL_AUTOFLOW_FLOW_VALUE = "__llm_skill_autoflow__"
_SSE_STREAM_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate, no-transform",
    "Pragma": "no-cache",
    "X-Accel-Buffering": "no",
    "Content-Encoding": "identity",
}

_INTERNAL_SESSION_PREFIXES: Tuple[str, ...] = (
    "af_sandbox",
    "af_sandbox_exec_",
    "autoflow_creator_",
    "codex_action_",
    "codex_autobuild_",
    "codex_",
    "creator_",
    "designer_",
    "parent_",
    "status_",
    "subflow_",
    "validate_",
)


def _is_internal_session_sid(sid: Any) -> bool:
    text = str(sid or "").strip().lower()
    if not text:
        return False
    return any(text.startswith(prefix.lower()) for prefix in _INTERNAL_SESSION_PREFIXES)


def _delete_internal_sessions_for_project(con: sqlite3.Connection, pid: str) -> None:
    clauses = " OR ".join(["sid LIKE ?"] * len(_INTERNAL_SESSION_PREFIXES))
    like_params = [f"{prefix}%" for prefix in _INTERNAL_SESSION_PREFIXES]
    args = [pid, *like_params]
    con.execute(f"DELETE FROM messages WHERE pid=? AND ({clauses})", args)
    con.execute(f"DELETE FROM session_members WHERE pid=? AND ({clauses})", args)
    con.execute(f"DELETE FROM join_requests WHERE pid=? AND ({clauses})", args)
    con.execute(f"DELETE FROM sessions WHERE pid=? AND ({clauses})", args)


def _default_db_path() -> str:
    # Prefer the repo-mounted DB if present (common in Docker dev setups where
    # ./data is bind-mounted into /app/data). Fall back to ~/.model_loader.
    try:
        app_data = os.path.join(os.getcwd(), "data", "collab_chat.db")
        if os.path.exists(app_data):
            os.makedirs(os.path.dirname(app_data), exist_ok=True)
            return app_data
    except Exception:
        pass
    base = os.path.join(os.path.expanduser("~"), ".model_loader")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "collab_chat.db")


def _now_ts() -> int:
    return int(time.time())


def _locked_stream(lock: threading.Lock, stream_fn):
    with lock:
        for piece in stream_fn():
            yield piece


def _rand_token() -> str:
    return secrets.token_urlsafe(32)


def _normalize_user_role(role: str) -> str:
    value = str(role or "").strip().lower()
    if value in {"admin", "administrator", "superadmin", "super_admin", "root"}:
        return "admin"
    if value == "guest":
        return "guest"
    return "user" if value else "user"


def _pbkdf2_sha256(password: str, salt_hex: str, iters: int) -> str:
    import hashlib

    salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iters))
    return dk.hex()


def _sse(event: str, data: Dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


def _router_project_defaults_key(pid: str) -> str:
    clean_pid = str(pid or "").strip()
    return f"{clean_pid}::__project__" if clean_pid else "__project__"


def _router_scope_key(pid: str, sid: str) -> str:
    clean_pid = str(pid or "").strip()
    clean_sid = str(sid or "").strip()
    if not clean_sid:
        return ""
    return f"{clean_pid}::{clean_sid}" if clean_pid else clean_sid


def _deep_merge_dict(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(a or {})
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge_dict(out.get(k) or {}, v)
        else:
            out[k] = v
    return out


def _dedupe_list(values: Iterable[Any]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _extract_router_config_from_prefs(prefs: Dict[str, Any], pid: str, sid: str) -> Dict[str, Any]:
    src = prefs if isinstance(prefs, dict) else {}
    project_defaults = src.get("router_project_defaults") if isinstance(src.get("router_project_defaults"), dict) else {}
    router_state = src.get("router_state") if isinstance(src.get("router_state"), dict) else {}
    enabled_map = router_state.get("enabled") if isinstance(router_state.get("enabled"), dict) else {}
    settings_map = router_state.get("settings") if isinstance(router_state.get("settings"), dict) else {}
    project_key = _router_project_defaults_key(pid)
    scope_key = _router_scope_key(pid, sid)
    legacy_key = str(sid or "").strip()
    project_enabled = project_defaults.get("enabled") if isinstance(project_defaults.get("enabled"), list) else []
    scoped_enabled = enabled_map.get(scope_key) if isinstance(enabled_map.get(scope_key), list) else []
    legacy_enabled = enabled_map.get(legacy_key) if legacy_key and legacy_key != scope_key and isinstance(enabled_map.get(legacy_key), list) else []
    project_settings = project_defaults.get("settings") if isinstance(project_defaults.get("settings"), dict) else {}
    scoped_settings = settings_map.get(scope_key) if isinstance(settings_map.get(scope_key), dict) else {}
    legacy_settings = settings_map.get(legacy_key) if legacy_key and legacy_key != scope_key and isinstance(settings_map.get(legacy_key), dict) else {}
    use_legacy_settings = bool(legacy_settings) and not bool(scoped_settings)
    merged_settings = {
        **(project_settings if isinstance(project_settings, dict) else {}),
        **(legacy_settings if use_legacy_settings else {}),
        **(scoped_settings if isinstance(scoped_settings, dict) else {}),
    }
    return {
        "project_key": project_key,
        "scope_key": scope_key,
        "enabled": _dedupe_list([*project_enabled, *scoped_enabled, *legacy_enabled]),
        "settings": merged_settings,
    }


def _build_completion_messages_for_session(
    db: "_DB",
    *,
    pid: str,
    sid: str,
    prompt: str,
    system_prompt: str = "",
    limit: int = 120,
    skip_internal_assistant_trace: bool = False,
) -> List[Dict[str, str]]:
    rows = db.list_messages(pid=pid, sid=sid, after_msg_id=None, since_ts=None, limit=limit)
    messages: List[Dict[str, str]] = []
    sys_text = str(system_prompt or "").strip()
    if sys_text:
        messages.append({"role": "system", "content": sys_text})
    for row in rows:
        role = str(row.get("role") or "user").strip().lower() or "user"
        if role not in {"user", "assistant", "system"}:
            role = "user"
        if role == "system":
            continue
        content = str(row.get("content") or "")
        low = content.strip().lower()
        if skip_internal_assistant_trace and role == "assistant":
            if low.startswith("autoflow ") or low.startswith("[agent_flow]"):
                continue
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": str(prompt or "")})
    return messages


def _latest_assistant_message(db: "_DB", pid: str, sid: str, limit: int = 40) -> Optional[Dict[str, Any]]:
    rows = db.list_messages(pid=pid, sid=sid, after_msg_id=None, since_ts=None, limit=limit, order_desc=True)
    for row in rows:
        if str(row.get("role") or "").strip().lower() == "assistant":
            return row
    return None


def _latest_assistant_message_after(
    db: "_DB",
    pid: str,
    sid: str,
    *,
    previous_msg_id: str = "",
    previous_ts: int = 0,
    limit: int = 40,
) -> Optional[Dict[str, Any]]:
    rows = db.list_messages(pid=pid, sid=sid, after_msg_id=None, since_ts=None, limit=limit, order_desc=True)
    for row in rows:
        if str(row.get("role") or "").strip().lower() != "assistant":
            continue
        msg_id = str(row.get("msg_id") or "").strip()
        ts = int(row.get("ts") or 0)
        if previous_msg_id and msg_id and msg_id != previous_msg_id:
            return row
        if previous_ts and ts > previous_ts:
            return row
    return None


def _service_enabled_plugins(router_enabled: Iterable[Any]) -> str:
    merged = _dedupe_list(["collab_chat", *list(router_enabled or [])])
    return ",".join(merged)


def _service_chat_wants_stream(request: Request, body: "ServiceChatRequest") -> bool:
    try:
        if bool(getattr(body, "stream", False)):
            return True
    except Exception:
        pass
    accept = str(request.headers.get("accept") or "").lower()
    if "text/event-stream" in accept:
        return True
    if str(request.headers.get("x-service-stream") or "").strip() == "1":
        return True
    return False


def _has_explicit_file_or_repo_scope(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if not text:
        return False
    low = text.lower()
    low_slash = low.replace("\\", "/")
    if re.search(r"(?:/uploads/|/app/|/data/|[a-z]:[\/].+\.(?:csv|json|txt|md|pdf|docx|pptx|xlsx|zip|js|ts|py|yml|yaml|html|htm|css)\b)", text, flags=re.IGNORECASE):
        return True
    if "/data/agent_workflow/repo" in low_slash:
        return True
    if re.search(r"\b(repo|repository|codebase)\b", low):
        return True
    if re.search(r"\b[\w./-]+\.(?:js|ts|py|json|md|txt|csv|yml|yaml)\b", text, flags=re.IGNORECASE):
        return True
    return False


def _looks_like_conceptual_workflow_question(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if not text:
        return False
    if re.search(r"(?:/uploads/|/app/|/data/|[a-z]:[\\/].+\.(?:csv|json|txt|md|pdf|docx|pptx|xlsx|zip|js|ts|py|yml|yaml|html|htm|css)\b)", text, flags=re.IGNORECASE):
        return False
    low = text.lower()
    low_slash = low.replace("\\", "/")
    if "/data/agent_workflow/repo" in low_slash:
        return False
    if re.search(r"\b[\w./\\-]+\.(?:js|ts|py|json|md|txt|csv|yml|yaml|html|htm|css)\b", text, flags=re.IGNORECASE):
        return False
    if not re.search(r"\b(what is|what does|how does|how do|why does|why is|explain|define|tell me about|walk me through)\b", low):
        return False
    concept_terms = (
        "workflow",
        "router",
        "plugin",
        "agent flow",
        "autoflow",
        "reference search",
        "file summary",
        "repo summary",
        "weather skill",
        "market data",
    )
    return any(term in low for term in concept_terms)


def _conceptual_workflow_fallback_answer(prompt: str) -> str:
    low = str(prompt or "").strip().lower()
    if "repo reference search" in low or "reference search" in low:
        return (
            "A repo reference search looks through a codebase for where a symbol, name, or concept is used. "
            "It is best for questions like where a function is referenced, which files mention a setting, or where a workflow name appears. "
            "It is different from a file summary because it answers location and usage questions rather than explaining one file in isolation."
        )
    if "file summary" in low:
        return (
            "A file summary explains what one file contains and what role it plays. "
            "It is best for quickly understanding the purpose, structure, and likely use of a file before you inspect it in detail. "
            "It does not search the rest of the repo for references unless you ask for that separately."
        )
    if "workflow router" in low or ("router" in low and "workflow" in low):
        return (
            "A workflow router decides which path should handle a request. "
            "In practice, it checks the request for signals like live-data needs, file paths, repo scope, or output type, then sends the request to the best matching workflow or direct answer path. "
            "A good router improves speed by avoiding unnecessary workflow creation and improves accuracy by choosing the right skill first."
        )
    if "autoflow" in low:
        return (
            "AutoFlow is a workflow-selection layer. "
            "Its job is to decide whether a request should go to a direct answer, a builtin workflow, an existing saved workflow, or workflow creation as a last resort. "
            "The main quality bar is to satisfy simple requests quickly and only use heavier flow logic when the request truly needs it."
        )
    return (
        "This is a conceptual workflow question. "
        "The direct answer model is unavailable right now, but the intended behavior is to answer these questions in plain language without invoking a repo workflow unless you explicitly ask about files, code paths, or a specific repository scope."
    )


def _looks_like_general_chat(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if not text:
        return False
    low = text.lower()
    low_compact = re.sub(r"[\s?!.,:;]+$", "", low)
    if re.fullmatch(r"(?:hi|hello|hey|yo|sup|thanks|thank you|ok|okay|cool|nice)", low_compact):
        return True
    if re.fullmatch(r"(?:how are you|what can you do|who are you|are you there|good morning|good afternoon|good evening)", low_compact):
        return True
    words = re.findall(r"[a-z0-9']+", low)
    if len(words) <= 6 and not re.search(r"(?:/uploads/|\.csv\b|\.json\b|\.txt\b|\.pdf\b|\.docx\b|\.pptx\b|\.xlsx\b|\.html\b|\.htm\b|\.css\b)", low):
        if not re.search(r"\b(create|draft|write|review|analyze|analyse|compare|summarize|summarise|plan|design|build|run|prepare|make|outline|research|use|turn|convert)\b", low):
            return True
    if re.search(r"(?:/uploads/|/app/|\.csv\b|\.json\b|\.txt\b|\.pdf\b|\.docx\b|\.pptx\b|\.xlsx\b|\.zip\b|\.html\b|\.htm\b|\.css\b)", low):
        return False
    if re.search(r"\b(weather|forecast|temperature|news|headline|stock|stocks|ticker|market cap|yahoo finance|world bank|imf|google scholar|arxiv|search the web|go online|browse)\b", low):
        return False
    if re.search(r"\b(create|draft|write|review|analyze|analyse|compare|summarize|summarise|plan|design|build|run|prepare|make|outline|research|use|turn|convert|generate|inspect|open|read|edit|fix|patch)\b", low):
        return False
    if re.search(r"\b(what is|who is|why is|why does|how does|how do|explain|define|tell me about|walk me through)\b", low):
        return True
    return False


def _looks_like_direct_text_generation(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if not text:
        return False
    low = text.lower()
    if _has_explicit_file_or_repo_scope(text):
        return False
    if re.search(r"\b(weather|forecast|temperature|news|headline|stock|stocks|ticker|market cap|yahoo finance|world bank|imf|google scholar|arxiv|search the web|go online|browse)\b", low):
        return False
    if re.search(r"\b(zip|archive|bundle|compress|download|export as file|output file)\b", low):
        return False
    if _looks_like_conceptual_workflow_question(text):
        return True
    return bool(
        re.search(
            r"\b(create|draft|write|rewrite|revise|outline|plan|design|build|suggest|explain|summarize|summarise|brainstorm|generate|compose|prepare|make|project|proposal|concept statement|essay|poem|presentation|powerpoint|slides|speech|email)\b",
            low,
        )
    )


def _looks_like_explanatory_choice_or_compare(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if not text:
        return False
    low = text.lower()
    has_explain_shape = bool(re.search(r"\b(explain|summarize|summarise|difference between|compare|versus|vs\.?|which should|which is better|help me choose|choosing)\b", low))
    if not has_explain_shape:
        return False
    if any(tok in low for tok in ("create a", "draft a", "write a", "build a", "design a", "make a", "outline a", "proposal for", "presentation for", "slides for", "powerpoint for")):
        return False
    return True


def _looks_like_structured_authoring_request(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if not text:
        return False
    low = text.lower()
    if _has_explicit_file_or_repo_scope(text):
        return False
    if re.search(r"\b(weather|forecast|temperature|news|headline|stock|stocks|ticker|market cap|yahoo finance|world bank|imf|google scholar|arxiv|search the web|go online|browse)\b", low):
        return False
    if _looks_like_explanatory_choice_or_compare(text):
        return False
    authoring_markers = (
        'create', 'draft', 'write', 'rewrite', 'revise', 'outline', 'plan', 'design', 'build',
        'generate', 'compose', 'prepare', 'make', 'project', 'proposal', 'concept statement',
        'essay', 'poem', 'presentation', 'powerpoint', 'slides', 'speech', 'email'
    )
    return any(marker in low for marker in authoring_markers)


def _looks_like_current_context_authoring(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if not _looks_like_direct_text_generation(text):
        return False
    low = text.lower()
    authoring_verbs = (
        'help me build', 'build', 'draft', 'write', 'rewrite', 'revise', 'outline', 'plan', 'design', 'prepare', 'compose', 'make', 'generate',
        'project', 'proposal', 'concept statement', 'essay', 'poem', 'presentation', 'powerpoint', 'slides', 'speech', 'email'
    )
    if not any(verb in low for verb in authoring_verbs):
        return False
    if any(tok in low for tok in ('manager', 'teammate', 'status update', 'project update', 'remind', 'reminder', 'routing fixes', 'repo-summary', 'file-summary')):
        return False
    explicit_current_markers = (
        "latest",
        "today",
        "right now",
        "recent",
        "current affairs",
        "current problems",
        "modern",
        "today's",
        "trends heading",
        "trend",
        "trends",
        "migration today",
        "current events",
        "real data",
        "current sources",
        "current source",
        "current literature",
        "current research",
        "current scholarship",
        "housing prices",
        "college tuition",
        "energy costs",
        "regulation",
        "policy",
        "elections",
        "public trust",
        "free speech",
        "ai-generated content",
    )
    if any(marker in low for marker in explicit_current_markers):
        return True
    if bool(re.search(r"\bcurrent\s+(?:affairs|problems|events|inflation|gdp|unemployment|interest(?:\s+rates?)?|policy|regulation|trend|trends|energy|costs|research|technology|tech|housing|tuition)\b", low)):
        return True
    if bool(re.search(r"\b(?:connect(?:ed)?\s+it\s+to|tied\s+to|relate\s+it\s+to)\b.*\b(?:today|current|recent|latest)\b", low)):
        return True
    return False


def _looks_like_current_context_explanatory_chat(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if not text:
        return False
    low = text.lower()
    if re.search(r"(?:/uploads/|/app/|/data/|[a-z]:[\/].+\.(?:csv|json|txt|md|pdf|docx|pptx|xlsx|zip|html|htm|css)\b)", text, flags=re.IGNORECASE):
        return False
    if re.search(r"\b(weather|forecast|temperature|yahoo finance|world bank|imf|google scholar|arxiv|repo|repository|codebase|workflow|agent flow|agent_workflow)\b", low):
        return False
    has_current = any(tok in low for tok in ("latest", "today", "right now", "recent", "new", "trend", "trends", "headlines", "news", "current affairs", "current events")) or bool(re.search(r"\bcurrent\s+(?:inflation|gdp|unemployment|interest(?:\s+rates?)?|policy|regulation|trend|trends|research|technology|tech|market|economy|ceo|president|prime minister|chair|founder)\b", low))
    has_prompt_shape = bool(re.search(r"\b(what is|what are|how is|how are|why is|why are|explain|summarize|summarise|analyze|analyse|compare|tell me about|who is|who are|who's|what's)\b", low))
    has_topic = any(tok in low for tok in ("ai", "model", "models", "technology", "tech", "regulation", "policy", "economy", "market", "research", "trend", "trends", "inflation", "interest rate", "interest rates", "fed funds", "federal reserve", "gdp", "unemployment", "chip", "chips", "gpu", "semiconductor", "ceo", "president", "prime minister", "chair", "founder", "nvidia", "openai", "meta", "google", "alphabet", "anthropic", "tesla", "microsoft", "amazon"))
    return has_current and has_prompt_shape and has_topic


def _current_context_lines(research_text: str, limit: int = 5) -> List[str]:
    out: List[str] = []
    for raw in str(research_text or "").splitlines():
        line = _repair_common_mojibake(str(raw or "")).strip().lstrip("-*").strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith(("current ", "## ", "**notes", "warnings:", "sources:", "retrieved")):
            continue
        if "http://" in low or "https://" in low or "::" in line:
            continue
        if line.count(";") >= 2:
            continue
        if len(line) > 180:
            continue
        if any(marker in line for marker in ("?", "??", "AP ?")):
            continue
        if line not in out:
            out.append(line)
        if len(out) >= max(1, int(limit or 5)):
            break
    return out


def _looks_like_failed_current_context(research_text: str) -> bool:
    low = str(research_text or "").strip().lower()
    if not low:
        return True
    if "limited current-source evidence" in low or "cautious partial update" in low:
        return False
    return any(tok in low for tok in (
        "could not retrieve current web results",
        "could not retrieve a high-confidence",
        "could not verify a high-confidence",
        "try again shortly",
        "request_failed:",
        "timed out",
        "http error",
        "unavailable",
    ))


def _looks_like_macro_fact_prompt(prompt: str) -> bool:
    low = str(prompt or '').strip().lower()
    if not low:
        return False
    has_prompt_shape = bool(re.search(r"\b(what is|what are|how is|how are|summarize|summarise|explain|compare|tell me about)\b", low))
    has_topic = any(tok in low for tok in ('inflation', 'cpi', 'consumer price', 'gdp', 'unemployment', 'interest rate', 'interest rates', 'fed funds', 'federal reserve', 'jobs', 'jobless'))
    has_current = any(tok in low for tok in ('latest', 'current', 'today', 'right now', 'recent'))
    return has_prompt_shape and has_topic and has_current


def _looks_like_macro_fact_research_answer(prompt: str, research_text: str) -> bool:
    if not _looks_like_macro_fact_prompt(prompt):
        return False
    low = str(research_text or '').strip().lower()
    if not low:
        return False
    if low.startswith('latest retrieved u.s. inflation context:'):
        return True
    if low.startswith('latest retrieved u.s. macro picture:'):
        return True
    if low.startswith('latest retrieved u.s. jobs context:'):
        return True
    if low.startswith('latest retrieved u.s. rate context:'):
        return True
    if 'i could not verify an exact current cpi reading' in low:
        return True
    if 'i could not retrieve a high-confidence current cpi source' in low:
        return True
    return False


def _macro_fact_answer_only(research_text: str) -> str:
    text = str(research_text or '').strip()
    if not text:
        return ''
    marker = '\nRetrieved evidence:'
    if marker in text:
        text = text.split(marker, 1)[0].strip()
    return text


def _prompt_has_explicit_time_range(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    if re.search(r"\b(?:from|between)\s+(?:the\s+)?\d{3,4}\s+(?:and|to)\s+\d{3,4}\b", text):
        return True
    if re.search(r"\b\d{3,4}\s*-\s*\d{2,4}\b", text):
        return True
    return bool(re.search(r"\b(?:ancient|medieval|renaissance|industrial revolution|cold war|world war|1750|1800|1900|1950|2000)\b", text))


def _research_scope_too_narrow_for_prompt(prompt: str, research_text: str) -> bool:
    low_prompt = str(prompt or "").strip().lower()
    low_research = str(research_text or "").strip().lower()
    if not low_prompt or not low_research:
        return False
    if not _looks_like_current_context_authoring(prompt):
        return False
    if _prompt_has_explicit_time_range(prompt):
        return False
    broad_prompt = any(marker in low_prompt for marker in (
        "today compares",
        "today compare",
        "today compared",
        "compares with earlier",
        "compare with earlier",
        "earlier migration waves",
        "historical comparisons",
        "global migration today",
        "over time",
        "how affordability has changed over time",
        "current affairs",
        "current problems",
        "today and earlier",
        "today versus",
        "today vs",
    )) or (
        ("today" in low_prompt or "current" in low_prompt)
        and any(marker in low_prompt for marker in ("earlier", "historical", "over time", "compares with", "compare with", "versus", "vs"))
    )
    if not broad_prompt:
        return False
    narrow_period_markers = (
        r"\b\d{3,4}\s*-\s*\d{2,4}\b",
        r"\b(?:from|between)\s+(?:the\s+)?\d{3,4}\s+(?:and|to)\s+\d{3,4}\b",
        r"\b1750\s*-\s*1900\b",
        r"\b1450\s*-\s*1750\b",
        r"\b1900\s*-\s*present\b",
    )
    if not any(re.search(pattern, low_research) for pattern in narrow_period_markers):
        return False
    return not any(marker in low_prompt for marker in ("1750", "1450", "1900", "industrial revolution", "cold war", "world war"))



def _apply_requested_answer_shape(prompt: str, text: str) -> str:
    raw = str(text or '').strip()
    if not raw:
        return raw
    low = str(prompt or '').lower()
    bullet_match = re.search(r'\b([2-9]|10)\s+bullets?\b', low)
    bullet_limit = int(bullet_match.group(1)) if bullet_match else 0
    wants_bullets = bool(bullet_limit or ' bullet' in low or 'bullets' in low)
    if not wants_bullets:
        return raw
    if re.search(r'(?m)^\s*(?:[-*]|\d+\.)\s+', raw):
        return raw
    flat = ' '.join(raw.split())
    parts = [part.strip() for part in re.split(r'(?<=[.!?])\s+(?=[A-Z0-9])', flat) if part.strip()]
    if len(parts) <= 1:
        parts = [part.strip() for part in re.split(r';\s+', flat) if part.strip()]
    if len(parts) <= 1:
        return '- ' + flat
    limit = bullet_limit or min(5, max(3, len(parts)))
    return '\n'.join(f'- {part}' for part in parts[:limit])


def _web_research_context_text(result: Dict[str, Any], *, max_items: int = 5) -> str:
    if not isinstance(result, dict):
        return ""
    parts: List[str] = []
    base_summary = str(result.get("final_answer") or result.get("summary") or result.get("text") or result.get("response") or result.get("content") or "").strip()
    if base_summary:
        parts.append(base_summary)
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    results = data.get("results") if isinstance(data.get("results"), list) else []
    detail_lines: List[str] = []
    for row in results[: max(1, int(max_items or 5))]:
        if not isinstance(row, dict):
            continue
        title = _repair_common_mojibake(str(row.get("title") or "").strip())
        content = _repair_common_mojibake(str(row.get("content") or row.get("source") or "").strip())
        url = str(row.get("url") or row.get("link") or "").strip()
        published = str(row.get("published") or row.get("date") or "").strip()
        bits = []
        if title:
            bits.append(title)
        if published:
            bits.append(f"date={published}")
        if content:
            bits.append(content[:260])
        if url:
            bits.append(url)
        line = " | ".join(bit for bit in bits if bit)
        if line:
            detail_lines.append(f"- {line}")
    if detail_lines:
        parts.append("Retrieved evidence:")
        parts.extend(detail_lines)
    return "\n".join(part for part in parts if str(part).strip()).strip()


def _identity_verification_fallback(answer_text: str) -> str:
    urls = re.findall(r'https?://[^\s)]+', str(answer_text or ''))
    unique = []
    seen = set()
    for url in urls:
        clean = str(url or '').rstrip('.,;')
        if clean and clean not in seen:
            seen.add(clean)
            unique.append(clean)
    bits = [
        "I could not verify the current officeholder from the retrieved sources because the extracted identity evidence was contradictory or malformed.",
    ]
    if unique:
        bits.append("Retrieved sources: " + '; '.join(unique[:2]))
    return ' '.join(bits).strip()


def _looks_like_supported_identity_answer(prompt: str, answer_text: str) -> bool:
    low_prompt = str(prompt or '').strip().lower()
    if not (any(phrase in low_prompt for phrase in ('who is', "who's", 'what is')) and any(tok in low_prompt for tok in ('ceo', 'president', 'prime minister', 'chair', 'founder', 'governor', 'mayor'))):
        return False
    text = ' '.join(str(answer_text or '').split())
    if 'source:' not in text.lower():
        return False
    if ' is the current ' not in text.lower() and ' is the founder' not in text.lower():
        return False
    return bool(re.search(r"\b[A-Z][a-z]+(?:\s+[A-Z][A-Za-z'.-]+){1,3}\b", text)) and not _looks_like_bad_identity_answer(prompt, text)


def _looks_like_bad_identity_answer(prompt: str, answer_text: str) -> bool:
    low_prompt = str(prompt or '').strip().lower()
    if not (any(phrase in low_prompt for phrase in ('who is', "who's", 'what is')) and any(tok in low_prompt for tok in ('ceo', 'president', 'prime minister', 'chair', 'founder', 'governor', 'mayor'))):
        return False
    text = ' '.join(str(answer_text or '').split())
    low = text.lower()
    suspicious = (
        ' armed forces ', ' vice ', ' administration is the current ', ' united states is the current ',
        ' the trump administration is the current ', ' the biden administration is the current ',
        ' part of the trump administration', ' part of the biden administration',
    )
    if any(token in f' {low} ' for token in suspicious):
        return True
    if any(role in low_prompt for role in ('president', 'prime minister', 'governor', 'mayor')):
        person_matches = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][A-Za-z.]+){1,3}\b', text)
        filtered = [m for m in person_matches if not str(m).strip().lower().startswith('the ')]
        if not filtered:
            return True
        bad_name_tokens = {'home', 'menu', 'about', 'accessibility', 'activate', 'office', 'city', 'council', 'government', 'news', 'contact'}
        for match in filtered:
            lowered = str(match).strip().lower()
            match_tokens = {tok for tok in re.findall(r'[a-z]+', lowered) if tok}
            if 'administration' in lowered or 'armed forces' in lowered:
                return True
            if match_tokens & bad_name_tokens:
                return True
    if 'is the current president' in low or 'is the current prime minister' in low or 'is the current governor' in low or 'is the current mayor' in low or 'is the current ceo' in low:
        head = text.split(' is the current ', 1)[0].strip()
        if not re.fullmatch(r'[A-Z][a-z]+(?:\s+[A-Z][A-Za-z.]+){1,3}', head):
            return True
    return False


def _looks_like_identity_verification_failure(prompt: str, answer_text: str) -> bool:
    low_prompt = str(prompt or '').strip().lower()
    if not (any(phrase in low_prompt for phrase in ('who is', "who's", 'what is')) and any(tok in low_prompt for tok in ('ceo', 'president', 'prime minister', 'chair', 'founder', 'governor', 'mayor'))):
        return False
    low = ' '.join(str(answer_text or '').split()).lower()
    return ('could not verify the current officeholder' in low) or ('could not verify the current ' in low and 'retrieved sources:' in low) or ('did not expose a reliable person name' in low)


def _looks_like_raw_web_research_answer(answer_text: str) -> bool:
    text = str(answer_text or "").strip()
    if not text:
        return False
    low = text.lower()
    lines = [str(line or "").strip() for line in text.splitlines() if str(line or "").strip()]
    bulletish = sum(
        1
        for line in lines
        if line.startswith("- ")
        or line.startswith("* ")
        or bool(re.match(r"^\d+\.\s+", line))
    )
    url_count = len(re.findall(r"https?://[^\s)]+", text))
    retrieval_markers = (
        ":: https://",
        "retrieved items below",
        "retrieved sources:",
        "skip to content",
        "an official website of the united states government",
        "here is how you know",
    )
    if any(marker in low for marker in retrieval_markers):
        return True
    if url_count >= 2 and bulletish >= 2:
        return True
    if bulletish >= 3 and any(tok in low for tok in ("current ", "latest ", "today", "right now", "recent")):
        return True
    return False


def _should_rewrite_web_research_answer(prompt: str, answer_text: str) -> bool:
    if _looks_like_raw_web_research_answer(answer_text):
        return True
    low_prompt = str(prompt or "").strip().lower()
    low_answer = str(answer_text or "").strip().lower()
    if not low_answer:
        return False
    current_markers = ("latest", "current", "today", "right now", "recent", "market", "trend", "trends", "outlook", "heading")
    if not any(tok in low_prompt for tok in current_markers):
        return False
    broad_ai_prompt = any(tok in low_prompt for tok in ("ai", "model", "models", "trend", "trends", "heading", "field"))
    narrow_evidence_markers = (
        "narrow current-source evidence",
        "cannot safely generalize",
        "limited current-source evidence",
        "for a stronger answer, narrow the request",
        "could not retrieve a high-confidence current ai trends summary",
    )
    if broad_ai_prompt and any(marker in low_answer for marker in narrow_evidence_markers):
        return True
    plain_lines = [line for line in str(answer_text or "").splitlines() if str(line).strip()]
    compact = " ".join(str(answer_text or "").split())
    if len(compact) < 220:
        return True
    if len(plain_lines) <= 2 and len(compact) < 420:
        return True
    return False


def _looks_like_generic_current_info_answer(prompt: str, answer_text: str) -> bool:
    low_prompt = str(prompt or "").strip().lower()
    low_answer = str(answer_text or "").strip().lower()
    if not low_answer:
        return True
    if any(marker in low_answer for marker in ("narrow current-source evidence", "cannot safely generalize", "limited current-source evidence", "for a stronger answer, narrow the request")):
        return True
    current_markers = ("latest", "current", "today", "right now", "recent", "market", "trend", "trends", "outlook", "heading", "news", "headline")
    if not any(tok in low_prompt for tok in current_markers):
        return False
    compact = " ".join(str(answer_text or "").split())
    generic_phrases = (
        "major players",
        "industry players",
        "this indicates",
        "market is moving",
        "appears to be moving",
        "we can expect",
        "focus is on",
        "continues to advance rapidly",
        "the industry is likely",
        "this suggests",
        "strategic shift",
    )
    generic_hits = sum(1 for phrase in generic_phrases if phrase in low_answer)
    has_specifics = bool(re.search(r"\b(?:19|20)\d{2}\b", low_answer) or re.search(r"\b\d+(?:\.\d+)?%\b", low_answer) or re.search(r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b", low_answer))
    named_examples = sum(1 for token in ("openai", "anthropic", "google", "meta", "microsoft", "nvidia", "gemini", "claude", "gpt", "copilot", "llama") if token in low_answer)
    if has_specifics:
        return False
    if named_examples >= 3 and len(compact) >= 260:
        return False
    return generic_hits >= 2 or len(compact) < 260


def _structured_authoring_fallback_answer(prompt: str) -> str:
    req = str(prompt or "").strip()
    low = req.lower()
    if any(tok in low for tok in ("research proposal", "paper proposal", "ap research", "20-page", "20 page")):
        return "\n".join([
            "## Research Proposal Framework",
            "",
            "**Working Topic**",
            req,
            "",
            "**Core Research Question**",
            "- How strongly are teen mental health outcomes associated with social media intensity and school pressure?",
            "",
            "**Possible Sub-Questions**",
            "- Which mental-health outcomes appear most strongly linked with heavy or problematic social-media use?",
            "- How does school pressure change or intensify that relationship?",
            "- Which age groups, school settings, or usage patterns should the paper focus on?",
            "",
            "**Suggested Proposal Sections**",
            "- Topic significance and why it matters now",
            "- Literature context and gap",
            "- Research questions or hypothesis",
            "- Method or evidence plan",
            "- Ethics and limitations",
            "- Expected contribution or finding shape",
            "",
            "**Possible Current Sources To Gather**",
            "- Recent peer-reviewed studies on teen mental health and social-media use since 2023",
            "- CDC, WHO, or UNICEF material on adolescent well-being, sleep, anxiety, or depression",
            "- Current survey or school-climate reports that discuss academic pressure and stress",
            "",
            "**Method Direction**",
            "- Define the age range, geography, and outcome measure before collecting sources.",
            "- Separate general platform use from problematic or high-intensity use.",
            "- Treat school pressure as a moderating variable rather than assuming it is the only driver.",
        ])
    if any(tok in low for tok in ("project", "experiment", "proposal")):
        dataset_lines = []
        if "housing" in low:
            dataset_lines.append("- Housing prices: use a long-run FRED housing series or a Census median-home-price series.")
        if "inflation" in low or "cpi" in low:
            dataset_lines.append("- Inflation: use BLS CPI data directly or the same CPI series through FRED.")
        if "tuition" in low or "college" in low:
            dataset_lines.append("- Tuition: use College Board Trends in College Pricing or NCES tuition data.")
        if not dataset_lines:
            dataset_lines.append("- Pick 1-2 primary datasets and one baseline series so the scope stays manageable.")
        if any(tok in low for tok in ("housing", "inflation", "tuition", "college")):
            method_lines = [
                "- Build one affordability ratio, such as price divided by median income or tuition divided by median household income.",
                "- Normalize the series to a common starting year so the change over time is easy to compare.",
            ]
            if "calculus" in low:
                method_lines.append("- For AP Calculus, include rate-of-change analysis to show when affordability worsened fastest.")
            if "statistics" in low or "statistic" in low:
                method_lines.append("- For AP Statistics, include correlation, regression, and a short note on limits or confounding variables.")
        elif any(tok in low for tok in ("physics", "solar", "battery", "renewable", "energy")):
            method_lines = [
                "- Compare one controlled variable at a time, such as panel angle, panel material, or storage setup.",
                "- Measure output with the same time window, weather assumptions, or simulated load so the comparison stays fair.",
                "- Connect the output or efficiency difference back to current electricity cost, payback, or storage tradeoffs.",
            ]
        else:
            method_lines = [
                "- Define one measurable comparison and keep the scope small enough to finish cleanly.",
                "- Use one baseline or control so the result is interpretable rather than descriptive only.",
            ]
        body = [
            "## Project Framework",
            "",
            "**Working Topic**",
            req,
            "",
            "**Project Shape**",
            "- Define one clear question you can test or document.",
            "- Use 1-3 primary datasets so the scope stays manageable.",
            "- Compare the main trend against one baseline so the change is measurable.",
            "- End with a short conclusion about what the pattern shows.",
            "",
            "**Suggested Sections**",
            "- Question or hypothesis",
            "- Why it matters",
            "- Data to collect",
            "- Method or comparison setup",
            "- Expected chart, table, or final product",
            "",
            "**Suggested Data Sources**",
        ] + dataset_lines + [
            "",
            "**Suggested Analysis**",
        ] + method_lines
        return "\n".join(body)
    if any(tok in low for tok in ("essay", "discussion", "response", "thesis")):
        return "\n".join([
            "## Essay Framework",
            "",
            "**Prompt Focus**",
            req,
            "",
            "**Thesis Shape**",
            "- Make one main claim, then support it with 2-3 clear points.",
            "",
            "**Suggested Structure**",
            "- Introduction and thesis",
            "- Body point 1",
            "- Body point 2",
            "- Body point 3 or counterpoint",
            "- Conclusion",
        ])
    if any(tok in low for tok in ("presentation", "slides", "powerpoint", "structure", "outline")):
        slide_lines = [
            "- Slide 1: title, claim, and why the issue matters",
            "- Slide 2: the main constitutional or policy question",
            "- Slide 3: strongest evidence or examples",
            "- Slide 4: arguments on the other side",
            "- Slide 5: conclusion and recommended takeaway",
        ]
        if "government" in low and "ai-generated content" in low:
            slide_lines = [
                "- Slide 1: title, question, and why AI-generated content matters in government",
                "- Slide 2: free speech and First Amendment concerns",
                "- Slide 3: elections, misinformation, and campaign integrity",
                "- Slide 4: public trust, disclosure rules, and enforcement options",
                "- Slide 5: conclusion: what should be regulated and what should remain protected speech",
            ]
        return "\n".join([
            "## Presentation Outline",
            "",
            *slide_lines,
        ])
    if "email" in low or "teacher" in low or "professor" in low:
        return "\n".join([
            "Subject: [Short subject line]",
            "",
            "Dear [Name],",
            "",
            "[Direct request in 1-2 sentences.]",
            "",
            "[Brief reason or context.]",
            "",
            "Thank you for your consideration.",
            "",
            "Best regards,",
            "[Your Name]",
        ])
    return "\n".join([
        "## Drafting Framework",
        "",
        req,
        "",
        "**Suggested Next Step**",
        "- Start with the requested deliverable directly and keep the structure compact.",
    ])


def _structured_current_context_fallback_answer(prompt: str, research_text: str) -> str:
    req = str(prompt or "").strip()
    low = req.lower()
    lines = _current_context_lines(research_text, limit=6)
    has_context = bool(lines) and not _looks_like_failed_current_context(research_text)
    if any(tok in low for tok in ("research proposal", "paper proposal", "ap research", "20-page", "20 page")):
        body = [
            "## Research Proposal Framework",
            "",
            "**Working Topic**",
            req,
            "",
            "**Core Research Question**",
            "- How strongly are teen mental health outcomes associated with social media intensity and perceived school pressure?",
            "",
            "**Possible Sub-Questions**",
            "- Which mental health outcomes are most consistently linked with heavy or problematic social media use?",
            "- How does school pressure change or intensify that relationship?",
            "- Which age groups, school settings, or usage patterns appear most affected?",
            "",
            "**Proposal Sections**",
            "- Topic significance and why it matters now",
            "- Literature context and gap",
            "- Research questions or hypothesis",
            "- Method or evidence plan",
            "- Ethics and limitations",
            "- Expected contribution or finding shape",
            "",
            "**Possible Current Sources To Gather**",
            "- Recent peer-reviewed studies on teen mental health and social media use since 2023",
            "- School climate or adolescent well-being reports from CDC, WHO, or UNICEF",
            "- Current survey data on anxiety, depression, or sleep disruption among teens",
            "",
            "**Method Direction**",
            "- Define the age range, geographic scope, and mental-health outcome before collecting sources.",
            "- Separate general social-media exposure from problematic or high-intensity use.",
            "- Treat school pressure as a moderating variable rather than assuming it is the only driver.",
        ]
        if has_context:
            body += ["", "**Current Context You Can Use**"] + [f"- {line}" for line in lines]
        else:
            body += ["", "**Current Context Note**", "- Live current-context retrieval was unavailable in this turn, so keep the proposal structure above and add fresh scholarly or institutional sources when available."]
        return "\n".join(body)
    if any(tok in low for tok in ("project", "experiment", "proposal")):
        title = "Current-Context Project Framework"
        dataset_lines = []
        if "housing" in low:
            dataset_lines.append("- Housing prices: use a long-run FRED housing series or a Census median-home-price series.")
        if "inflation" in low or "cpi" in low:
            dataset_lines.append("- Inflation: use BLS CPI data directly or the same CPI series through FRED.")
        if "tuition" in low or "college" in low:
            dataset_lines.append("- Tuition: use College Board Trends in College Pricing or NCES tuition data.")
        if not dataset_lines:
            dataset_lines.append("- Pick 1-2 primary datasets and one baseline series so the comparison stays manageable.")
        method_lines = [
            "- Build one affordability ratio, such as price divided by median income or tuition divided by median household income.",
            "- Normalize the series to a common starting year so the change over time is easy to compare.",
        ]
        if "calculus" in low:
            method_lines.append("- For AP Calculus, include rate-of-change analysis to show when affordability worsened fastest.")
        if "statistics" in low or "statistic" in low:
            method_lines.append("- For AP Statistics, include correlation, regression, and a short note on limits or confounding variables.")
        body = [
            f"## {title}",
            "",
            "**Working Topic**",
            req,
            "",
            "**Project Shape**",
            "- Define one clear question you can test or document with current evidence.",
            "- Collect a small, credible dataset or 2-4 current source points you can cite directly.",
            "- Compare the current situation with one historical or baseline reference so the change is measurable.",
            "- End with a short conclusion about what the current evidence suggests.",
            "",
            "**Suggested Sections**",
            "- Question or hypothesis",
            "- Why it matters now",
            "- Data or evidence to collect",
            "- Method or comparison setup",
            "- Expected chart, table, or final product",
            "",
            "**Suggested Data Sources**",
        ] + dataset_lines + [
            "",
            "**Suggested Analysis**",
        ] + method_lines
        if has_context:
            body += ["", "**Current Context You Can Use**"] + [f"- {line}" for line in lines]
        else:
            body += ["", "**Current Context Note**", "- Live current-context retrieval was unavailable in this turn, so use the project structure above and add fresh sources when available."]
        return "\n".join(body)
    if any(tok in low for tok in ("essay", "discussion", "response", "thesis")):
        body = [
            "## Essay and Discussion Framework",
            "",
            "**Prompt Focus**",
            req,
            "",
            "**Thesis Shape**",
            "- Make one main claim, then compare today with an earlier period using 2-3 clear dimensions.",
            "",
            "**Body Structure**",
            "- Point 1: what is similar",
            "- Point 2: what is different",
            "- Point 3: why the current case matters now",
            "",
            "**Discussion Points**",
            "- Which causes are strongest today?",
            "- What changed because of technology, institutions, or scale?",
            "- Which historical comparison is most convincing?",
        ]
        if has_context:
            body += ["", "**Current Context You Can Cite**"] + [f"- {line}" for line in lines]
        else:
            body += ["", "**Current Context Note**", "- Live current-context retrieval was unavailable in this turn, so keep the structure above and add fresh supporting examples when available."]
        return "\n".join(body)
    if any(tok in low for tok in ("presentation", "slides", "powerpoint")):
        body = [
            "## Presentation Outline",
            "",
            "- Slide 1: title and current significance",
            "- Slide 2: the core problem or question",
            "- Slide 3: current evidence or examples",
            "- Slide 4: analysis or comparison",
            "- Slide 5: implications and conclusion",
        ]
        if has_context:
            body += ["", "**Current Context to Place in the Deck**"] + [f"- {line}" for line in lines]
        else:
            body += ["", "**Current Context Note**", "- Live current-context retrieval was unavailable in this turn, so use the outline above and add updated evidence when available."]
        return "\n".join(body)
    body = [
        "## Current-Context Drafting Fallback",
        "",
        req,
    ]
    if has_context:
        body += ["", "**Current Context**"] + [f"- {line}" for line in lines]
    else:
        body += ["", "**Current Context Note**", "- Live current-context retrieval was unavailable in this turn."]
    body += ["", "**Next Step**", "- Use the points above to draft the final answer once live context or the direct text model is available."]
    return "\n".join(body)


def _is_limited_current_context_answer(research_text: str) -> bool:
    low = str(research_text or '').strip().lower()
    return (
        'limited current-source evidence' in low
        or 'cautious partial update' in low
        or 'narrow current-source evidence' in low
        or 'cannot safely generalize it into a full field-wide trend summary' in low
    )


def _extract_current_context_rows(research_result: Dict[str, Any], research_text: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    data = research_result.get('data') if isinstance(research_result.get('data'), dict) else {}
    result_rows = data.get('results') if isinstance(data.get('results'), list) else []
    for row in result_rows:
        if not isinstance(row, dict):
            continue
        title = _repair_common_mojibake(str(row.get('title') or '').strip())
        if not title:
            continue
        rows.append({
            'title': title,
            'published': str(row.get('published') or row.get('date') or '').strip(),
            'source': _repair_common_mojibake(str(row.get('source') or row.get('engine') or row.get('content') or '').strip()),
            'url': str(row.get('url') or row.get('link') or '').strip(),
        })
    if rows:
        return rows
    capture = False
    for raw in str(research_text or '').splitlines():
        line = str(raw or '').strip()
        low = line.lower()
        if low.startswith('retrieved evidence:'):
            capture = True
            continue
        if not capture or not line.startswith('- '):
            continue
        body = line[2:].strip()
        parts = [part.strip() for part in body.split(' | ') if part.strip()]
        if not parts:
            continue
        title = parts[0]
        published = ''
        source = ''
        url = ''
        for part in parts[1:]:
            if part.startswith('date='):
                published = part.split('=', 1)[1].strip()
            elif part.startswith('http://') or part.startswith('https://'):
                url = part
            elif not source:
                source = part
        rows.append({'title': title, 'published': published, 'source': source, 'url': url})
    return rows


def _limited_current_context_themes(prompt: str, rows: List[Dict[str, str]]) -> List[str]:
    blob = ' '.join(' '.join(str(row.get(key) or '') for key in ('title', 'source')) for row in rows).lower()
    themes: List[str] = []
    if any(tok in blob for tok in ('security', 'government', 'access', 'limits', 'restricted', 'export control', 'scrutiny')):
        themes.append('governance, access control, and security constraints are showing up in current frontier-AI coverage')
    if any(tok in blob for tok in ('release', 'launch', 'model', 'reasoning', 'multimodal', 'open-weight', 'agent')):
        themes.append('competition still appears to be centered on model launches and capability positioning')
    if any(tok in blob for tok in ('nvidia', 'amd', 'intel', 'gpu', 'chip', 'semiconductor', 'compute', 'datacenter')):
        themes.append('compute supply and infrastructure economics still look central to the near-term market story')
    if any(tok in blob for tok in ('regulation', 'policy', 'copyright', 'eu', 'ftc', 'congress', 'white house')):
        themes.append('policy and regulatory pressure remain part of the near-term outlook')
    if any(tok in blob for tok in ('microsoft', 'google', 'meta', 'amazon', 'aws', 'enterprise', 'copilot', 'workspace')):
        themes.append('distribution through major platforms and enterprise products still appears important')
    if not themes and rows:
        themes.append('the strongest verified signal this turn is still too narrow to support a broad market-wide claim')
    return themes[:3]


def _structured_limited_current_context_answer(prompt: str, research_result: Dict[str, Any], research_text: str) -> str:
    if not _is_limited_current_context_answer(research_text):
        return ''
    rows = _extract_current_context_rows(research_result, research_text)
    if not rows:
        return str(research_text or '').strip()
    lead = rows[0]
    title = str(lead.get('title') or '').strip()
    published = str(lead.get('published') or '').strip()
    source = str(lead.get('source') or '').strip()
    lead_bits = [bit for bit in (title, source, published) if bit]
    themes = _limited_current_context_themes(prompt, rows)
    answer_lines = [
        'I could not verify a full cross-market current summary from multiple trusted live sources in this turn, so the answer has to stay cautious.',
    ]
    if lead_bits:
        answer_lines.append('The strongest verified signal I did retrieve was ' + ' | '.join(lead_bits) + '.')
    if themes:
        answer_lines.append('Within that limited evidence, the clearest theme' + ('s are' if len(themes) > 1 else ' is') + ': ' + '; '.join(themes) + '.')
    if any(tok in str(prompt or '').lower() for tok in ('next year', 'outlook', 'heading', 'where does the market seem to be heading')):
        if themes:
            answer_lines.append('For the next year, the safest read is that these themes are likely to matter more than any single headline, but this is not broad enough evidence for a strong market-wide forecast.')
        else:
            answer_lines.append('For the next year, the safest read is that the retrieved evidence is directional only, not broad enough for a strong market-wide forecast.')
    answer_lines.append('For a stronger answer, narrow the request to a company set, model family, regulation track, or chip segment, or rerun when broader live-search backends are available.')
    if lead.get('url'):
        answer_lines.append('Strongest source: ' + str(lead.get('url') or '').strip())
    return ' '.join(line.strip() for line in answer_lines if str(line).strip()).strip()


def _looks_like_unsupported_current_context_specifics(answer_text: str, research_text: str) -> bool:
    answer = str(answer_text or "").strip()
    research = str(research_text or "").strip()
    if not answer or not research:
        return False
    answer_low = answer.lower()
    research_low = research.lower()
    unsupported = 0
    for token in re.findall(r"\b\d+(?:\.\d+)?%\b", answer_low):
        if token not in research_low:
            unsupported += 1
    for token in re.findall(r"\b(?:19|20)\d{2}\s*[-?]\s*(?:19|20)\d{2}\b", answer_low):
        if token not in research_low and token.replace('?', '-') not in research_low:
            unsupported += 1
    for token in re.findall(r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(?:19|20)\d{2}\b", answer_low):
        if token not in research_low:
            unsupported += 1
    return unsupported >= 2 or (unsupported >= 1 and '%' in answer_low)


def _looks_like_authoring_frame_drift(prompt: str, answer_text: str) -> bool:
    low_prompt = str(prompt or '').strip().lower()
    low_answer = str(answer_text or '').strip().lower()
    if not low_answer:
        return True
    foreign_frames = ('ap capstone', 'ap seminar', 'ap research', 'senior thesis')
    if any(frame in low_answer for frame in foreign_frames) and not any(frame in low_prompt for frame in foreign_frames):
        return True
    if any(course in low_prompt for course in ('ap calculus', 'ap statistics')) and any(frame in low_answer for frame in foreign_frames):
        return True
    return False


def _looks_like_chatty_authoring_answer(answer_text: str) -> bool:
    raw = str(answer_text or '').strip()
    low = raw.lower()
    if not low:
        return True
    praise_markers = (
        'this is a fantastic',
        'this is an excellent',
        'excellent idea',
        'great topic',
        'great choice',
        'highly relevant',
    )
    decorative_markers = ('??', '??', '---', 'core project title ideas')
    return any(marker in low for marker in praise_markers) or any(marker in raw for marker in decorative_markers)


def _looks_like_overcautious_current_context_authoring_answer(prompt: str, answer_text: str) -> bool:
    if not _looks_like_current_context_authoring(prompt):
        return False
    low = str(answer_text or '').strip().lower()
    if not low:
        return True
    markers = (
        'i cannot provide specific, verified current',
        'i cannot provide specific, verified',
        'cannot provide specific, verified current',
        'precise figure cannot be verified',
        'real-time data',
        'actual statistical data points needed',
        'required for up-to-date analysis',
    )
    refusal_like = any(marker_text in low for marker_text in markers)
    constructive = any(marker_text in low for marker_text in (
        'project shape', 'suggested sections', 'question or hypothesis', 'data or evidence to collect',
        'method or comparison setup', 'expected chart', 'working topic', 'framework', 'outline',
    ))
    return refusal_like and not constructive

def _autoflow_precheck_failure(prompt: str, result_text: str) -> str:
    req = str(prompt or "").strip().lower()
    text = str(result_text or "").strip()
    low = text.lower()
    if not text:
        return "empty result"
    generic_markers = (
        "value_unavailable_from_tool_results",
        "source data inaccessible",
        "see cited market output",
        "verify in latest imf / world bank releases",
        "review latest world bank indicator",
        "compare after source verification",
        "source link not captured",
    )
    for marker_text in generic_markers:
        if marker_text in low:
            return marker_text
    if "yahoo finance" in req and "nvda" in req and "amd" in req:
        if "top stocks" in low:
            return "returned generic top stocks instead of explicit nvda/amd comparison"
        if "| nvda |" not in low or "| amd |" not in low:
            return "missing explicit nvda/amd comparison rows"
        for marker_text in ("52-week", "market cap", "average volume"):
            if marker_text.lower() not in low:
                return f"missing requested field: {marker_text}"
    if "world bank" in req and all(tok in req for tok in ("inflation", "gdp growth", "unemployment")):
        if any(marker_text in low for marker_text in ("review latest world bank indicator", "compare after source verification")):
            return "world bank result still contains placeholder indicators"
    if "imf" in req and "world bank" in req and "macro brief" in req and "verify in latest imf / world bank releases" in low:
        return "macro brief still contains placeholder outlook values"
    if "google scholar" in req:
        if low.count("\nyear:") + low.count("year:") < 5:
            return "google scholar result missing 5 structured sources with years"
        if low.count("\nlink:") + low.count("link:") < 5:
            return "google scholar result missing 5 structured source links"
    if "arxiv" in req:
        if low.count("arxiv.org") < 4:
            return "arxiv result missing enough arxiv links"
        if low.count("\nyear:") + low.count("year:") < 5:
            return "arxiv result missing 5 structured years"
    return ""


def _general_chat_canned_response(prompt: str) -> str:
    low = str(prompt or "").strip().lower()
    low_compact = re.sub(r"[\s?!.,:;]+$", "", low)
    if re.fullmatch(r"(?:hi|hello|hey|yo|sup|good morning|good afternoon|good evening)", low_compact):
        return "Hello. What do you need help with?"
    if re.fullmatch(r"(?:thanks|thank you)", low_compact):
        return "You're welcome."
    if re.fullmatch(r"(?:ok|okay|cool|nice)", low_compact):
        return "Understood."
    if re.fullmatch(r"(?:how are you|are you there)", low_compact):
        return "I am here. What do you need?"
    if re.fullmatch(r"(?:what can you do|who are you)", low_compact):
        return "I can help with workflows, files, documents, analysis, and code tasks in this workspace."
    return ""


_MOJIBAKE_MARKERS: Tuple[str, ...] = (
    "\u00e2",
    "\u00c3",
    "\u00c2",
    "\u00f0",
    "??",
    "???",
    "???",
    "???",
    "???",
    "\u00e2\u0080",
    "\u00c2\u00a0",
)


def _repair_common_mojibake(text: str) -> str:
    raw = str(text or "")
    if not raw:
        return raw

    suspicious_literals = ("\u00e2", "\u00c3", "\u00c2", "\u0101", "\u0100", "\ufffd")

    def _suspicion_score(value: str) -> int:
        score = 0
        for ch in value:
            code = ord(ch)
            if ch in suspicious_literals:
                score += 3
            elif 0x80 <= code <= 0x9F:
                score += 4
        score += value.count("\u00e2\u0080") * 3
        score += value.count("\u00c3\u00a2\u00c2\u0080") * 4
        return score

    repaired = raw
    best_score = _suspicion_score(raw)
    for _ in range(3):
        improved = False
        for src_enc, dst_enc in (("latin-1", "utf-8"), ("cp1252", "utf-8")):
            try:
                candidate = repaired.encode(src_enc, errors="ignore").decode(dst_enc, errors="ignore").strip()
            except Exception:
                candidate = ""
            if not candidate or candidate == repaired:
                continue
            score = _suspicion_score(candidate)
            if score < best_score:
                repaired = candidate
                best_score = score
                improved = True
                break
        if not improved:
            break

    replacements = {
        "\u00e2\u0080\u0099": "'",
        "\u00e2\u0080\u0098": "'",
        "\u00e2\u0080\u009c": '"',
        "\u00e2\u0080\u009d": '"',
        "\u00e2\u0080\u0093": "-",
        "\u00e2\u0080\u0094": "-",
        "\u00e2\u0080\u00a6": "...",
        "\u00c3\u00a2\u00c2\u0080\u00c2\u0099": "'",
        "\u00c3\u00a2\u00c2\u0080\u00c2\u0098": "'",
        "\u00c3\u00a2\u00c2\u0080\u00c2\u009c": '"',
        "\u00c3\u00a2\u00c2\u0080\u00c2\u009d": '"',
        "\u00c3\u00a2\u00c2\u0080\u00c2\u0093": "-",
        "\u00c3\u00a2\u00c2\u0080\u00c2\u0094": "-",
        "\u00c3\u00a2\u00c2\u0080\u00c2\u00a6": "...",
        "\u0101\u0080\u0099": "'",
        "\u0101\u0080\u0098": "'",
        "\u0101\u0080\u009c": '"',
        "\u0101\u0080\u009d": '"',
        "\u0101\u0080\u0093": "-",
        "\u0101\u0080\u0094": "-",
        "\u0101\u0080\u00a6": "...",
        "\u0100\u00a0": " ",
        "\u00c2\u00a0": " ",
    }
    for bad, good in replacements.items():
        repaired = repaired.replace(bad, good)
    return unicodedata.normalize("NFKC", repaired).strip()


def _strip_reasoning_artifacts(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return cleaned
    cleaned = re.sub(r"^\s*<think>.*?</think>\s*", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"^\s*</think>\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\s*```(?:thinking|thought|reasoning)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    return cleaned.strip()


def _service_assistant_message(db: "_DB", pid: str, sid: str, content: str, *, client_msg_id: str = "", meta: Optional[Dict[str, Any]] = None, ts: Optional[int] = None) -> Dict[str, Any]:
    msg_id = secrets.token_hex(12)
    ts = int(ts if ts is not None else time.time())
    payload_meta = dict(meta or {})
    if client_msg_id:
        payload_meta["client_msg_id"] = str(client_msg_id)
    content_text = _strip_reasoning_artifacts(_repair_common_mojibake(str(content or "")))
    db.add_message(
        msg_id=msg_id,
        pid=pid,
        sid=sid,
        ts=ts,
        role="assistant",
        kind="model",
        author_username="assistant",
        author_alias="assistant",
        content=content_text,
        meta=payload_meta,
    )
    return {
        "msg_id": msg_id,
        "pid": pid,
        "sid": sid,
        "ts": ts,
        "role": "assistant",
        "kind": "model",
        "author_username": "assistant",
        "author_alias": "assistant",
        "content": content_text,
        "meta": payload_meta,
    }


def _service_user_message(
    db: "_DB",
    pid: str,
    sid: str,
    content: str,
    *,
    author_username: str,
    author_alias: str,
    client_msg_id: str = "",
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    msg_id = secrets.token_hex(12)
    ts = int(time.time())
    payload_meta = dict(meta or {})
    if client_msg_id:
        payload_meta["client_msg_id"] = str(client_msg_id)
    username = str(author_username or "").strip() or "user"
    alias = str(author_alias or "").strip() or username
    content_text = _repair_common_mojibake(str(content or "")).strip()
    db.add_message(
        msg_id=msg_id,
        pid=pid,
        sid=sid,
        ts=ts,
        role="user",
        kind="human",
        author_username=username,
        author_alias=alias,
        content=content_text,
        meta=payload_meta,
    )
    return {
        "msg_id": msg_id,
        "pid": pid,
        "sid": sid,
        "ts": ts,
        "role": "user",
        "kind": "human",
        "author_username": username,
        "author_alias": alias,
        "content": content_text,
        "meta": payload_meta,
    }


def _service_startup_warmup_state(app: Any) -> Dict[str, Any]:
    try:
        warmup_s = float(os.environ.get("MODEL_LOADER_SERVICE_CHAT_WARMUP_SECONDS") or 60.0)
    except Exception:
        warmup_s = 60.0
    if warmup_s < 0:
        warmup_s = 0.0
    started_at = float(getattr(getattr(app, "state", None), "service_started_at_ts", 0.0) or 0.0)
    now = time.time()
    age_s = max(0.0, now - started_at) if started_at > 0 else warmup_s
    remaining_s = max(0.0, warmup_s - age_s)
    return {
        "active": bool(started_at > 0 and remaining_s > 0),
        "warmup_seconds": warmup_s,
        "age_seconds": age_s,
        "remaining_seconds": remaining_s,
    }


def _service_text_model_available(app: Any) -> bool:
    try:
        state = getattr(app, "state", None)
        getter = getattr(state, "model", None)
        model = getter() if callable(getter) else getter
    except Exception:
        state = getattr(app, "state", None)
        model = None
    if model is None:
        try:
            get_loaded = getattr(state, "get_main_text_llm_if_loaded", None)
        except Exception:
            get_loaded = None
        if callable(get_loaded):
            try:
                model = get_loaded()
            except Exception:
                model = None
    if model is None:
        return False
    try:
        base_url = str(getattr(model, "base_url", None) or "").strip()
    except Exception:
        base_url = ""
    if base_url:
        session = getattr(model, "_session", None)
        try:
            if session is not None:
                health_resp = session.get(f"{base_url}/health", timeout=2)
                if int(getattr(health_resp, "status_code", 0) or 0) >= 500:
                    return False
            else:
                return False
        except Exception:
            return False
    try:
        if hasattr(model, "stream_chat") or hasattr(model, "chat"):
            return True
        model_id = str(getattr(model, "model_id", None) or "").strip()
    except Exception:
        model_id = ""
    return bool(model_id)


def _service_ensure_text_model(app: Any) -> bool:
    try:
        state = getattr(app, "state", None)
        getter = getattr(state, "model", None)
    except Exception:
        return False
    try:
        model = getter() if callable(getter) else getter
    except Exception:
        model = None
    if model is not None:
        return True
    try:
        ensure_main = getattr(state, "ensure_main_text_llm_loaded", None)
    except Exception:
        ensure_main = None
    if callable(ensure_main):
        try:
            return ensure_main() is not None
        except Exception:
            return False
    return False


async def _internal_json_request(
    app,
    *,
    method: str,
    path: str,
    headers: Dict[str, str],
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://service.internal") as client:
        resp = await client.request(method.upper(), path, headers=headers, json=body)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:400] or "internal_request_failed")
    try:
        return resp.json()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"internal_json_decode_failed: {exc}")


async def _consume_sse_stream(
    resp,
    *,
    timeout_s: float,
    on_event: Optional[Callable[[str, Any], None]] = None,
) -> Dict[str, Any]:
    tokens: List[str] = []
    last_done: Dict[str, Any] = {}
    last_diag: Dict[str, Any] = {}
    last_router: Dict[str, Any] = {}
    started = time.time()
    event_name = "message"
    async for raw_line in resp.aiter_lines():
        if timeout_s > 0 and (time.time() - started) > timeout_s:
            raise HTTPException(status_code=504, detail="service_chat_timeout")
        line = str(raw_line or "")
        if not line:
            event_name = "message"
            continue
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip() or "message"
            continue
        if not line.startswith("data:"):
            continue
        data_text = line.split(":", 1)[1].strip()
        try:
            payload = json.loads(data_text)
        except Exception:
            payload = data_text
        if callable(on_event):
            try:
                on_event(event_name, payload)
            except Exception:
                pass
        if event_name == "token" and isinstance(payload, dict):
            piece = str(payload.get("text") or "")
            if piece:
                tokens.append(piece)
        elif event_name == "diag" and isinstance(payload, dict):
            last_diag = payload
        elif event_name == "router" and isinstance(payload, dict):
            last_router = payload
        elif event_name == "done":
            last_done = payload if isinstance(payload, dict) else {"raw": payload}
            break
    return {"text": "".join(tokens), "done": last_done, "diag": last_diag, "router": last_router}


async def _internal_sse_request(
    app,
    *,
    method: str,
    path: str,
    headers: Dict[str, str],
    body: Dict[str, Any],
    timeout_s: float,
    on_event: Optional[Callable[[str, Any], None]] = None,
) -> Dict[str, Any]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://service.internal", timeout=None) as client:
        async with client.stream(method.upper(), path, headers=headers, json=body) as resp:
            if resp.status_code >= 400:
                text = await resp.aread()
                raise HTTPException(status_code=resp.status_code, detail=text.decode("utf-8", errors="ignore")[:400] or "internal_stream_failed")
            return await _consume_sse_stream(resp, timeout_s=timeout_s, on_event=on_event)


async def _loopback_sse_request(
    request: Request,
    *,
    method: str,
    path: str,
    headers: Dict[str, str],
    body: Dict[str, Any],
    timeout_s: float,
    on_event: Optional[Callable[[str, Any], None]] = None,
) -> Dict[str, Any]:
    base_url = str(getattr(request, 'base_url', '') or '').rstrip('/')
    if not base_url:
        raise HTTPException(status_code=500, detail='missing_base_url')
    async with httpx.AsyncClient(base_url=base_url, timeout=None) as client:
        async with client.stream(method.upper(), path, headers=headers, json=body) as resp:
            if resp.status_code >= 400:
                text = await resp.aread()
                raise HTTPException(status_code=resp.status_code, detail=text.decode('utf-8', errors='ignore')[:400] or 'loopback_stream_failed')
            return await _consume_sse_stream(resp, timeout_s=timeout_s, on_event=on_event)

def _project_member_role(db: "_DB", pid: str, username: str) -> Optional[str]:
    pid = (pid or "").strip()
    username = (username or "").strip()
    if not pid or not username:
        return None
    with db._lock:
        con = db._connect()
        try:
            row = con.execute(
                "SELECT role FROM project_members WHERE pid=? AND lower(username)=lower(?)",
                (pid, username),
            ).fetchone()
            if not row:
                return None
            return str(row["role"] or "").strip() or "user"
        finally:
            con.close()


def _is_project_public(db: "_DB", pid: str) -> bool:
    pid = (pid or "").strip()
    if not pid:
        return False
    with db._lock:
        con = db._connect()
        try:
            row = con.execute(
                "SELECT is_public FROM projects WHERE pid=?",
                (pid,),
            ).fetchone()
            if not row:
                return False
            try:
                return bool(int(row["is_public"] or 0))
            except Exception:
                return bool(row["is_public"])
        finally:
            con.close()


def _require_project_access(app, u: "UserInfo", pid: str) -> None:
    """
    Access rule for operations that target a project:
      - admin can access all projects
      - non-admin can access if:
         - project is public, OR
         - user is a member of the project (project_members row exists)
    """
    pid = (pid or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="Missing project id")

    if u.role == "admin":
        return

    db: _DB = app.state.collab_db

    # Public project => allow
    if _is_project_public(db, pid):
        return

    # Private project => require membership
    role = _project_member_role(db, pid, u.username)
    if role:
        return

    raise HTTPException(status_code=403, detail="Project access denied")

class CollabStreamHook:
    """
    StreamHook sink for app.py /v1/chat/completions_stream.

    - Enforces auth + project access
    - Persists user prompt at start
    - Persists assistant completion at end
    - Broadcasts message/token/done events to collab_hub
    """

    def __init__(self, app) -> None:
        self.app = app

    def on_stream_start(self, request: Request, ctx: Dict[str, Any]) -> None:
        pid = (ctx.get("project_id") or "").strip()
        sid = (ctx.get("session_id") or "").strip()
        if not pid or not sid:
            return  # not a collab-scoped stream
        if str(request.headers.get("X-Collab-Suppress-Persist") or "").strip() == "1":
            ctx["collab_suppress_persist"] = True
            return

        db: _DB = self.app.state.collab_db
        hub: _SessionHub = self.app.state.collab_hub

        actor = _require_user_or_guest(
            self.app,
            request,
            pid,
            sid,
            alias_value=ctx.get("alias"),
        )
        u = actor["user"]

        prompt = (ctx.get("last_user_content") or "").strip()
        if not prompt:
            return

        turn_id = (ctx.get("turn_id") or secrets.token_hex(10))
        ctx["turn_id"] = turn_id
        if actor.get("kind") == "guest":
            alias_u = str(actor.get("alias") or "").strip() or u.username
        else:
            alias_u = (ctx.get("alias") or u.username).strip() or u.username

        # --- PERSIST USER MESSAGE (exact db.add_message call) ---
        if not bool(ctx.get("no_user_message")):
            user_msg_id = secrets.token_hex(12)
            ts_u = _now_ts()
            meta_u: Dict[str, Any] = {"turn_id": turn_id, "via": "completions_stream"}
            if ctx.get("client_msg_id"):
                meta_u["client_msg_id"] = ctx.get("client_msg_id")
            attachments = ctx.get("attachments") or []
            if isinstance(attachments, list) and attachments:
                meta_u["attachments"] = attachments

            db.add_message(
                msg_id=user_msg_id,
                pid=pid,
                sid=sid,
                ts=ts_u,
                role="user",
                kind="human",
                author_username=u.username,
                author_alias=alias_u,
                content=prompt,
                meta=meta_u,
            )

            # Broadcast persisted message
            try:
                hub.publish(
                    pid,
                    sid,
                    event="message",
                    data={
                        "msg": {
                            "msg_id": user_msg_id,
                            "pid": pid,
                            "sid": sid,
                            "ts": ts_u,
                            "role": "user",
                            "kind": "human",
                            "author_username": u.username,
                            "author_alias": alias_u,
                            "content": prompt,
                            "meta": meta_u,
                        }
                    }
                )
            except Exception:
                pass

        # keep for end
        ctx["collab_username"] = u.username
        ctx["collab_alias"] = alias_u

        # Create a draft assistant message now so it exists even if the client switches sessions mid-stream
        client_turn_id = ctx.get("turn_id")
        turn_id = db.new_id("t")  # or uuid
        msg_id = db.new_id("m")

        ctx["client_turn_id"] = client_turn_id
        ctx["turn_id"] = turn_id
        ctx["asst_msg_id"] = msg_id
        ctx["asst_text"] = ""
        ctx["origin"] = u.username
        ctx["pid"] = pid
        ctx["sid"] = sid
        ts_a = _now_ts()
        meta_a: Dict[str, Any] = {"turn_id": turn_id, "is_draft": True}
        if ctx.get("client_msg_id"):
            meta_a["client_msg_id"] = ctx.get("client_msg_id")
        if client_turn_id:
            meta_a["client_turn_id"] = client_turn_id

        # print("asst_msg_id:", msg_id)
        # print("ctx: ", ctx)

        db.add_message(
            pid=pid,
            sid=sid,
            msg_id=msg_id,
            role="assistant",
            content="",
            ts=ts_a,
            author_username="assistant",
            author_alias="assistant",
            kind="model",
            meta=meta_a,
        )

        # notify collaborators a new assistant turn started (optional)
        hub.publish(pid, sid, event = "message", data = {"msg": {
            "pid": pid, "sid": sid, "msg_id": msg_id,
            "role": "assistant", "content": "", "author_username": "assistant", "author_alias": "assistant",
            "meta": meta_a,
        }})

        try:
            ai_jobs = getattr(self.app.state, "ai_jobs", None)
            if ai_jobs and client_turn_id:
                ai_jobs.upsert(
                    client_turn_id,
                    asst_msg_id=msg_id,
                    collab_turn_id=turn_id,
                )
        except Exception:
            pass

    def on_stream_token(self, token_text: str, ctx: Dict[str, Any]) -> None:
        pid = (ctx.get("project_id") or "").strip()
        sid = (ctx.get("session_id") or "").strip()
        # print(242352352)
        if not pid or not sid:
            return

        db: _DB = self.app.state.collab_db
        hub: _SessionHub = self.app.state.collab_hub
        turn_id = (ctx.get("turn_id") or "")
        origin = ctx.get("origin") or ""
        msg_id = ctx.get("asst_msg_id") or ""

        if token_text:
            ctx["asst_text"] = f"{ctx.get('asst_text') or ''}{token_text}"
        
        # print("on_stream_token asst_msg_id:", msg_id)
        # Best-effort live token broadcast
        try:
            # hub.publish(
            #     pid,
            #     sid,
            #     event="token",
            #     data={
            #         "turn_id": turn_id,
            #         "pid": pid,
            #         "sid": sid,
            #         "role": "assistant",
            #         "text": str(token_text or ""),
            #     },
            # )
            # broadcast token to collaborators
            hub.publish(
                pid, 
                sid, 
                event="token",
                data={
                     "turn_id": turn_id,
                     "msg_id": msg_id,
                     "origin": origin,
                     "text": token_text,
                     "pid": pid,
                     "sid": sid,
                     "pos": len(ctx.get("asst_text") or ""),
                     }
                     )

        except Exception:
            pass

        
        ## periodically flush draft to DB (prevents losing content on switch/close)
        # now = time.time()
        # last = float(ctx.get("_last_flush_ts") or 0.0)
        # if (now - last) >= 0.8 or (len(ctx["asst_text"]) % 256) == 0:
        #     ctx["_last_flush_ts"] = now
        #     # print("set message")
        #     # print("ctx: ", ctx)
        #     # db.update_message_content(msg_id, ctx["asst_text"], meta_patch={"is_draft": True})
        #     db.set_message_content(msg_id=msg_id, content=ctx["asst_text"])
                                                                            

    def on_stream_diag(self, data: Any, ctx: Dict[str, Any]) -> None:
        pid = (ctx.get("project_id") or "").strip()
        sid = (ctx.get("session_id") or "").strip()
        if not pid or not sid:
            return

        hub: _SessionHub = self.app.state.collab_hub
        msg_id = ctx.get("asst_msg_id") or ""
        if not msg_id:
            return

        payload = {
            "turn_id": ctx.get("turn_id") or "",
            "msg_id": msg_id,
        }
        if isinstance(data, dict):
            payload.update(data)
        else:
            payload["data"] = data
        try:
            hub.publish(pid, sid, event="diag", data=payload)
        except Exception:
            pass


    def on_stream_end(self, full_text: str, ctx: Dict[str, Any], error: Optional[str] = None) -> None:
        pid = (ctx.get("project_id") or "").strip()
        sid = (ctx.get("session_id") or "").strip()
        if not pid or not sid:
            return
        if bool(ctx.get("collab_suppress_persist")):
            return

        db: _DB = self.app.state.collab_db
        hub: _SessionHub = self.app.state.collab_hub

        turn_id = (ctx.get("turn_id") or "")
        username = (ctx.get("collab_username") or "").strip()
        alias_u = (ctx.get("collab_alias") or username).strip() or username
        
        msg_id = ctx.get("asst_msg_id") or ""
        if not pid or not sid or not turn_id or not msg_id:
            return

        text = (full_text or "").strip() or (ctx.get("asst_text") or "").strip()
        if text:
            db.set_message_content(msg_id=msg_id, content=text)

        # hub.publish(pid, sid, {"event": "done", "data": {"turn_id": turn_id, "ok": bool(ok), "error": error}})
        
        if error:
            # broadcast end with error (no persistence)
            try:
                hub.publish(pid, sid, event="done", data={"turn_id": turn_id, "msg_id": msg_id, "ok": False, "error": str(error)})
            except Exception:
                pass
            return

        txt = (full_text or "").strip()
        if not txt:
            try:
                hub.publish(pid, sid, event="done", data={"turn_id": turn_id, "msg_id": msg_id, "ok": True})
            except Exception:
                pass
            return

        # # --- PERSIST ASSISTANT MESSAGE (exact db.add_message call) ---
        # asst_msg_id = secrets.token_hex(12)
        # ts_a = _now_ts()
        # meta_a: Dict[str, Any] = {"turn_id": turn_id, "streamed": True, "via": "completions_stream"}

        # db.add_message(
        #     msg_id=asst_msg_id,
        #     pid=pid,
        #     sid=sid,
        #     ts=ts_a,
        #     role="assistant",
        #     kind="model",
        #     author_username=username or "unknown",
        #     author_alias=alias_u or (username or "unknown"),
        #     content=txt,
        #     meta=meta_a,
        # )

        # # Broadcast persisted assistant message
        # try:
        #     hub.publish(
        #         pid,
        #         sid,
        #         event="message",
        #         data={
        #             "msg": {
        #                 "msg_id": asst_msg_id,
        #                 "pid": pid,
        #                 "sid": sid,
        #                 "ts": ts_a,
        #                 "role": "assistant",
        #                 "kind": "model",
        #                 "author_username": username or "unknown",
        #                 "author_alias": alias_u or (username or "unknown"),
        #                 "content": txt,
        #                 "meta": meta_a,
        #             }
        #         },
        #     )
        # except Exception:
        #     pass

        # broadcast done
        try:
            hub.publish(pid, sid, event="done", data={"turn_id": turn_id, "msg_id": msg_id, "ok": True})
        except Exception:
            pass

class _PresenceStore:
    """
    In-memory roster + typing state.
    Keyed by (pid, sid) -> { username -> {alias, last_seen, is_typing} }
    """
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rooms: Dict[tuple[str, str], Dict[str, Dict[str, Any]]] = {}

    def _room(self, pid: str, sid: str) -> Dict[str, Dict[str, Any]]:
        return self._rooms.setdefault((pid, sid), {})

    def join(self, pid: str, sid: str, username: str, alias: str) -> Dict[str, Any]:
        now = _now_ts()
        with self._lock:
            r = self._room(pid, sid)
            r[username] = {"username": username, "alias": alias, "last_seen": now, "is_typing": False}
            return dict(r[username])

    def leave(self, pid: str, sid: str, username: str) -> None:
        with self._lock:
            r = self._rooms.get((pid, sid))
            if not r:
                return
            r.pop(username, None)
            if not r:
                self._rooms.pop((pid, sid), None)

    def touch(self, pid: str, sid: str, username: str) -> None:
        now = _now_ts()
        with self._lock:
            r = self._rooms.get((pid, sid))
            if not r or username not in r:
                return
            r[username]["last_seen"] = now

    def set_typing(self, pid: str, sid: str, username: str, is_typing: bool) -> Dict[str, Any] | None:
        now = _now_ts()
        with self._lock:
            r = self._rooms.get((pid, sid))
            if not r or username not in r:
                return None
            r[username]["is_typing"] = bool(is_typing)
            r[username]["last_seen"] = now
            return dict(r[username])

    def roster(self, pid: str, sid: str) -> List[Dict[str, Any]]:
        with self._lock:
            r = self._rooms.get((pid, sid), {})
            # most recent first
            out = list(r.values())
            out.sort(key=lambda x: int(x.get("last_seen") or 0), reverse=True)
            return [dict(x) for x in out]

class _SessionHub:
    """In-memory pub/sub for live collaboration events (SSE).

    This hub is intentionally *ephemeral*: it exists per server process.
    Durable data (messages, prefs, etc.) are stored in SQLite via _DB.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subs: Dict[Tuple[str, str], List[queue.Queue]] = {}

    def subscribe(self, pid: str, sid: str) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=2048)
        key = (pid, sid)
        with self._lock:
            self._subs.setdefault(key, []).append(q)
            sub_count = len(self._subs.get(key) or [])
        try:
            print(f"[collab_events] subscribe pid={pid} sid={sid} subs={sub_count}", flush=True)
        except Exception:
            pass
        return q

    def unsubscribe(self, pid: str, sid: str, q: queue.Queue) -> None:
        key = (pid, sid)
        with self._lock:
            cur = self._subs.get(key) or []
            try:
                cur.remove(q)
            except Exception:
                return
            if not cur:
                self._subs.pop(key, None)
            sub_count = len(self._subs.get(key) or [])
        try:
            print(f"[collab_events] unsubscribe pid={pid} sid={sid} subs={sub_count}", flush=True)
        except Exception:
            pass

    # def publish(self, pid: str, sid: str, *, event: str, data: Dict[str, Any]) -> None:
    def publish(self, pid: str, sid: str, event: str, data: Dict[str, Any]) -> None:

        key = (pid, sid)
        with self._lock:
            subs = list(self._subs.get(key) or [])
        try:
            data_keys = ",".join(sorted((data or {}).keys()))
            msg_id = str((data or {}).get("msg_id") or ((data or {}).get("msg") or {}).get("msg_id") or "").strip()
            role = str(((data or {}).get("msg") or {}).get("role") or "").strip()
            print(
                f"[collab_events] publish pid={pid} sid={sid} event={event} subs={len(subs)} msg_id={msg_id} role={role} keys={data_keys}",
                flush=True,
            )
        except Exception:
            pass
        if not subs:
            return
        payload = {"event": event, "data": data}
        for q in subs:
            try:
                q.put_nowait(payload)
            except Exception:
                # Best-effort: if a client is too slow, drop events.
                pass


@dataclass
class UserInfo:
    username: str
    role: str  # "admin" | "user"


GUI_PREFS_DEFAULT_USER = "__default__"
class _DB:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._init()

    def new_id(self, prefix: str = "") -> str:
        """
        Create a short unique id. Some code paths (stream hooks) call db.new_id("m"/"t").
        We keep it compatible with older secrets.token_hex usage.
        """
        p = (prefix or "").strip()
        tok = secrets.token_hex(12)  # 24 hex chars
        return f"{p}{tok}" if p else tok

    def new_turn_id(self) -> str:
        # Convenience if you want a consistent turn id format
        return self.new_id("t")

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, check_same_thread=False)
        con.row_factory = sqlite3.Row
        return con

    def _init(self) -> None:
        with self._lock:
            con = self._connect()
            try:
                cur = con.cursor()

                def _has_col(_cur, table: str, col: str) -> bool:
                    rows = _cur.execute(f"PRAGMA table_info({table})").fetchall()
                    return any(str(r["name"]) == col for r in rows)

                def _add_col(_cur, table: str, col: str, ddl: str) -> None:
                    if not _has_col(_cur, table, col):
                        _cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        username TEXT PRIMARY KEY,
                        role TEXT NOT NULL,
                        pw_salt_hex TEXT NOT NULL,
                        pw_hash_hex TEXT NOT NULL,
                        pw_iters INTEGER NOT NULL,
                        created_ts INTEGER NOT NULL
                    )
                    """
                )
                try:
                    cur.execute("ALTER TABLE users ADD COLUMN scope_all INTEGER NOT NULL DEFAULT 1")
                except sqlite3.OperationalError:
                    pass
                # --- schema upgrade (sqlite): add must_change_pw if missing ---
                try:
                    cur.execute("ALTER TABLE users ADD COLUMN must_change_pw INTEGER NOT NULL DEFAULT 0")
                except sqlite3.OperationalError:
                    # column already exists
                    pass
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tokens (
                        token TEXT PRIMARY KEY,
                        username TEXT NOT NULL,
                        created_ts INTEGER NOT NULL,
                        expires_ts INTEGER NOT NULL,
                        FOREIGN KEY(username) REFERENCES users(username)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS projects (
                        pid TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        created_by TEXT NOT NULL,
                        created_ts INTEGER NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS project_members (
                        pid TEXT NOT NULL,
                        username TEXT NOT NULL,
                        role TEXT NOT NULL,
                        PRIMARY KEY(pid, username),
                        FOREIGN KEY(pid) REFERENCES projects(pid),
                        FOREIGN KEY(username) REFERENCES users(username)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        sid TEXT NOT NULL,
                        pid TEXT NOT NULL,
                        title TEXT NOT NULL,
                        created_by TEXT NOT NULL,
                        created_ts INTEGER NOT NULL,
                        is_public INTEGER NOT NULL DEFAULT 1,
                        allow_guest INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY(pid, sid),
                        FOREIGN KEY(pid) REFERENCES projects(pid)
                    )
                    """
                )
                # ---- schema upgrades: project/session visibility ----
                _add_col(cur, "projects", "is_public", "is_public INTEGER NOT NULL DEFAULT 0")
                _add_col(cur, "sessions", "is_public", "is_public INTEGER NOT NULL DEFAULT 0")

                _add_col(cur, "projects", "ai_default", "ai_default INTEGER NOT NULL DEFAULT 1")
                _add_col(cur, "projects", "collab_prompt_id", "collab_prompt_id TEXT")
                _add_col(cur, "sessions", "ai_default", "ai_default INTEGER NOT NULL DEFAULT 1")
                _add_col(cur, "sessions", "collab_prompt_id", "collab_prompt_id TEXT")
                _add_col(cur, "sessions", "allow_guest", "allow_guest INTEGER NOT NULL DEFAULT 0")

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS collab_prompts (
                        prompt_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        prompt TEXT NOT NULL,
                        created_by TEXT NOT NULL,
                        created_ts INTEGER NOT NULL,
                        updated_ts INTEGER NOT NULL
                    )
                    """
                )

                # ---- per-session membership for private sessions in public projects ----
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS session_members (
                        pid TEXT NOT NULL,
                        sid TEXT NOT NULL,
                        username TEXT NOT NULL,
                        role TEXT NOT NULL,
                        created_ts INTEGER NOT NULL,
                        PRIMARY KEY(pid, sid, username)
                    )
                    """
                )

                # ---- join requests for private sessions (and private projects via approval logic) ----
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS join_requests (
                        req_id TEXT PRIMARY KEY,
                        pid TEXT NOT NULL,
                        sid TEXT NOT NULL,
                        username TEXT NOT NULL,
                        created_ts INTEGER NOT NULL,
                        status TEXT NOT NULL,          -- pending|approved|denied
                        acted_by TEXT,
                        acted_ts INTEGER
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_joinreq_pid_sid_status ON join_requests(pid, sid, status)"
                )
                # ---- schema migration: sessions.is_public ----
                try:
                    cols = [str(r["name"]) for r in cur.execute("PRAGMA table_info(sessions)").fetchall()]
                    if "is_public" not in set(cols):
                        cur.execute("ALTER TABLE sessions ADD COLUMN is_public INTEGER NOT NULL DEFAULT 1")
                except Exception:
                    pass

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS gui_prefs (
                        pid TEXT NOT NULL,
                        username TEXT NOT NULL,
                        prefs_json TEXT NOT NULL,
                        updated_ts INTEGER NOT NULL,
                        PRIMARY KEY(pid, username)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS messages (
                        msg_id TEXT PRIMARY KEY,
                        pid TEXT NOT NULL,
                        sid TEXT NOT NULL,
                        ts INTEGER NOT NULL,
                        role TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        author_username TEXT NOT NULL,
                        author_alias TEXT NOT NULL,
                        content TEXT NOT NULL,
                        meta_json TEXT NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS transcript_cache (
                        pid TEXT NOT NULL,
                        sid TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        updated_ts INTEGER NOT NULL,
                        PRIMARY KEY (pid, sid),
                        FOREIGN KEY(pid) REFERENCES projects(pid),
                        FOREIGN KEY(pid, sid) REFERENCES sessions(pid, sid)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_messages_session_ts
                    ON messages(pid, sid, ts, msg_id)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bootstrap_secrets (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        created_ts INTEGER NOT NULL,
                        consumed_ts INTEGER
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS app_settings (
                        key TEXT PRIMARY KEY,
                        value_json TEXT NOT NULL,
                        updated_ts INTEGER NOT NULL
                    )
                    """
                )
                con.commit()
            finally:
                con.close()

    # -------- users / auth --------

    def get_must_change_pw(self, username: str) -> bool:
        if not username:
            return False
        with self._lock:
            con = self._connect()
            try:
                row = con.execute(
                    "SELECT must_change_pw FROM users WHERE lower(username)=lower(?)",
                    (username,),
                ).fetchone()
                return bool(int(row["must_change_pw"])) if row else False
            finally:
                con.close()

    def set_must_change_pw(self, username: str, val: bool) -> None:
        if not username:
            return
        with self._lock:
            con = self._connect()
            try:
                con.execute(
                    "UPDATE users SET must_change_pw=? WHERE lower(username)=lower(?)",
                    (1 if val else 0, username),
                )
                con.commit()
            finally:
                con.close()

    def set_bootstrap_secret(self, key: str, value: str) -> None:
        with self._lock:
            con = self._connect()
            try:
                con.execute(
                    "INSERT OR REPLACE INTO bootstrap_secrets(key, value, created_ts, consumed_ts) VALUES(?,?,?,NULL)",
                    (key, value, _now_ts()),
                )
                con.commit()
            finally:
                con.close()

    def consume_bootstrap_secret(self, key: str) -> Optional[str]:
        with self._lock:
            con = self._connect()
            try:
                row = con.execute(
                    "SELECT value, consumed_ts FROM bootstrap_secrets WHERE key=?",
                    (key,),
                ).fetchone()
                if not row:
                    return None
                if row["consumed_ts"] is not None:
                    return None
                val = str(row["value"])
                con.execute(
                    "UPDATE bootstrap_secrets SET consumed_ts=? WHERE key=?",
                    (_now_ts(), key),
                )
                con.commit()
                return val
            finally:
                con.close()

    def ensure_bootstrap_admin(self) -> Optional[str]:
        """Ensure there is at least one admin user.

        Returns:
            temp_password if a new admin was created, else None.
        """
        with self._lock:
            con = self._connect()
            try:
                cur = con.cursor()
                row = cur.execute("SELECT username FROM users WHERE role='admin' LIMIT 1").fetchone()
                if row:
                    return None

                username = "admin"
                temp_password = os.environ.get("MODEL_LOADER_ADMIN_PASSWORD") or secrets.token_urlsafe(10)
                salt_hex = secrets.token_bytes(16).hex()
                iters = int(os.environ.get("MODEL_LOADER_PW_ITERS") or 200_000)
                pw_hash_hex = _pbkdf2_sha256(temp_password, salt_hex, iters)
                # cur.execute(
                #     "INSERT OR REPLACE INTO users(username, role, pw_salt_hex, pw_hash_hex, pw_iters, created_ts) VALUES(?,?,?,?,?,?)",
                #     (username, "admin", salt_hex, pw_hash_hex, iters, _now_ts()),
                # )
                cur.execute(
                    "INSERT OR REPLACE INTO users(username, role, pw_salt_hex, pw_hash_hex, pw_iters, created_ts, must_change_pw) VALUES(?,?,?,?,?,?,?)",
                    (username, "admin", salt_hex, pw_hash_hex, iters, _now_ts(), 1),
                )
                con.commit()
                return temp_password
            finally:
                con.close()

    def get_app_setting_json(self, key: str) -> Optional[Dict[str, Any]]:
        if not key:
            return None
        with self._lock:
            con = self._connect()
            try:
                row = con.execute(
                    "SELECT value_json FROM app_settings WHERE key=?",
                    (key,),
                ).fetchone()
                if not row:
                    return None
                raw = str(row["value_json"] or "").strip()
                if not raw:
                    return None
                try:
                    data = json.loads(raw)
                except Exception:
                    return None
                return data if isinstance(data, dict) else None
            finally:
                con.close()

    def set_app_setting_json(self, key: str, value: Dict[str, Any]) -> None:
        if not key:
            return
        payload = json.dumps(value or {}, ensure_ascii=False)
        with self._lock:
            con = self._connect()
            try:
                con.execute(
                    "INSERT OR REPLACE INTO app_settings(key, value_json, updated_ts) VALUES(?,?,?)",
                    (key, payload, _now_ts()),
                )
                con.commit()
            finally:
                con.close()

    def verify_login(self, username: str, password: str) -> Optional[UserInfo]:
        with self._lock:
            con = self._connect()
            try:
                cur = con.cursor()
                row = cur.execute(
                    "SELECT username, role, pw_salt_hex, pw_hash_hex, pw_iters FROM users WHERE lower(username)=lower(?)",
                    (username,),
                ).fetchone()
                if not row:
                    return None
                salt_hex = str(row["pw_salt_hex"])
                iters = int(row["pw_iters"])
                want = str(row["pw_hash_hex"])
                got = _pbkdf2_sha256(password or "", salt_hex, iters)
                if secrets.compare_digest(want, got):
                    return UserInfo(username=str(row["username"]), role=_normalize_user_role(str(row["role"])))
                return None
            finally:
                con.close()

    def issue_token(self, username: str, *, ttl_s: int = 7 * 24 * 3600) -> str:
        tok = _rand_token()
        now = _now_ts()
        exp = now + int(ttl_s)
        with self._lock:
            con = self._connect()
            try:
                con.execute(
                    "INSERT INTO tokens(token, username, created_ts, expires_ts) VALUES(?,?,?,?)",
                    (tok, username, now, exp),
                )
                con.commit()
            finally:
                con.close()
        return tok

    def revoke_token(self, token: str) -> None:
        with self._lock:
            con = self._connect()
            try:
                con.execute("DELETE FROM tokens WHERE token=?", (token,))
                con.commit()
            finally:
                con.close()

    def resolve_token(self, token: str) -> Optional[UserInfo]:
        if not token:
            return None
        with self._lock:
            con = self._connect()
            try:
                row = con.execute(
                    """
                    SELECT t.username as username, u.role as role, t.expires_ts as expires_ts
                    FROM tokens t
                    JOIN users u ON u.username = t.username
                    WHERE t.token=?
                    """,
                    (token,),
                ).fetchone()
                if not row:
                    return None
                if int(row["expires_ts"]) < _now_ts():
                    try:
                        con.execute("DELETE FROM tokens WHERE token=?", (token,))
                        con.commit()
                    except Exception:
                        pass
                    return None
                return UserInfo(username=str(row["username"]), role=_normalize_user_role(str(row["role"])))
            finally:
                con.close()

    # -------- projects / sessions / prefs --------

    def ensure_project(self, pid: str, name: str, created_by: str) -> None:
        with self._lock:
            con = self._connect()
            try:
                con.execute(
                    "INSERT OR IGNORE INTO projects(pid, name, created_by, created_ts) VALUES(?,?,?,?)",
                    (pid, name, created_by, _now_ts()),
                )
                # Creator becomes member/admin for that project
                con.execute(
                    "INSERT OR IGNORE INTO project_members(pid, username, role) VALUES(?,?,?)",
                    (pid, created_by, "admin"),
                )
                con.commit()
            finally:
                con.close()

    def delete_session(self, pid: str, sid: str) -> None:
        with self._lock:
            con = self._connect()
            try:
                con.execute("DELETE FROM messages WHERE pid=? AND sid=?", (pid, sid))
                con.execute("DELETE FROM session_members WHERE pid=? AND sid=?", (pid, sid))
                con.execute("DELETE FROM join_requests WHERE pid=? AND sid=?", (pid, sid))
                con.execute("DELETE FROM sessions WHERE pid=? AND sid=?", (pid, sid))
                con.commit()
            finally:
                con.close()

    def delete_project(self, pid: str) -> None:
        with self._lock:
            con = self._connect()
            try:
                con.execute("DELETE FROM messages WHERE pid=?", (pid,))
                con.execute("DELETE FROM session_members WHERE pid=?", (pid,))
                con.execute("DELETE FROM join_requests WHERE pid=?", (pid,))
                con.execute("DELETE FROM sessions WHERE pid=?", (pid,))
                con.execute("DELETE FROM project_members WHERE pid=?", (pid,))
                con.execute("DELETE FROM gui_prefs WHERE pid=?", (pid,))
                con.execute("DELETE FROM projects WHERE pid=?", (pid,))
                con.commit()
            finally:
                con.close()

    # def list_projects(self, u: UserInfo) -> List[Dict[str, Any]]:
    #     with self._lock:
    #         con = self._connect()
    #         try:
    #             if u.role == "admin":
    #                 rows = con.execute("SELECT pid, name, created_by, created_ts FROM projects ORDER BY pid").fetchall()
    #             else:
    #                 rows = con.execute(
    #                     """
    #                     SELECT p.pid, p.name, p.created_by, p.created_ts
    #                     FROM projects p
    #                     JOIN project_members m ON m.pid = p.pid
    #                     WHERE lower(m.username)=lower(?)
    #                     ORDER BY p.pid
    #                     """,
    #                     (u.username,),
    #                 ).fetchall()
    #             return [dict(r) for r in rows]
    #         finally:
    #             con.close()

    # def list_projects(self, u: UserInfo) -> List[Dict[str, Any]]:
    #     # Everyone can see all projects (private/public); content access is enforced elsewhere.
    #     with self._lock:
    #         con = self._connect()
    #         try:
    #             rows = con.execute(
    #                 "SELECT pid, name, created_by, created_ts, is_public FROM projects ORDER BY pid"
    #             ).fetchall()
    #             return [dict(r) for r in rows]
    #         finally:
    #             con.close()

    def list_projects(self, u: UserInfo) -> List[Dict[str, Any]]:
        # Admin always sees all
        if u.role == "admin":
            with self._lock:
                con = self._connect()
                try:
                    rows = con.execute(
                        "SELECT pid, name, created_by, created_ts, is_public, ai_default, collab_prompt_id FROM projects ORDER BY pid"
                    ).fetchall()
                    return [dict(r) for r in rows]
                finally:
                    con.close()

        # Scoped: list membership projects + any public projects
        with self._lock:
            con = self._connect()
            try:
                rows = con.execute(
                    """
                    SELECT DISTINCT p.pid, p.name, p.created_by, p.created_ts, p.is_public, p.ai_default, p.collab_prompt_id
                    FROM projects p
                    LEFT JOIN project_members m
                      ON m.pid = p.pid AND lower(m.username)=lower(?)
                    WHERE p.is_public=1 OR m.username IS NOT NULL
                    ORDER BY p.pid
                    """,
                    (u.username,),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                con.close()

    def ensure_session(self, pid: str, sid: str, title: str, created_by: str, is_public: bool = True) -> None:
        with self._lock:
            con = self._connect()
            try:
                con.execute(
                    "INSERT OR IGNORE INTO sessions(pid, sid, title, created_by, created_ts, is_public) VALUES(?,?,?,?,?,?)",
                    (pid, sid, title, created_by, _now_ts(), (1 if is_public else 0)),
                )
                con.commit()
            finally:
                con.close

    # def list_sessions(self, pid: str) -> List[Dict[str, Any]]:
    #     with self._lock:
    #         con = self._connect()
    #         try:
    #             rows = con.execute(
    #                 "SELECT sid, pid, title, created_by, created_ts, is_public FROM sessions WHERE pid=? ORDER BY created_ts",
    #                 (pid,),
    #             ).fetchall()
    #             return [dict(r) for r in rows]
    #         finally:
    #             con.close()

    def list_sessions(self, pid: str) -> List[Dict[str, Any]]:
        with self._lock:
            con = self._connect()
            try:
                _delete_internal_sessions_for_project(con, pid)
                con.commit()
                rows = con.execute(
                    "SELECT sid, pid, title, created_by, created_ts, is_public, allow_guest, ai_default, collab_prompt_id FROM sessions WHERE pid=? ORDER BY created_ts",
                    (pid,),
                ).fetchall()
                return [dict(r) for r in rows if not _is_internal_session_sid(r["sid"])]
            finally:
                con.close()

    def get_session(self, pid: str, sid: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            con = self._connect()
            try:
                row = con.execute(
                    "SELECT sid, pid, title, created_by, created_ts, is_public, allow_guest, ai_default, collab_prompt_id FROM sessions WHERE pid=? AND sid=?",
                    (pid, sid),
                ).fetchone()
                return dict(row) if row else None
            finally:
                con.close()

    def set_session_visibility(self, pid: str, sid: str, is_public: bool) -> None:
        with self._lock:
            con = self._connect()
            try:
                con.execute(
                    "UPDATE sessions SET is_public=? WHERE pid=? AND sid=?",
                    (1 if is_public else 0, pid, sid),
                )
                con.commit()
            finally:
                con.close()

    # def get_gui_prefs(self, pid: str, username: str) -> Dict[str, Any]:
    #     with self._lock:
    #         con = self._connect()
    #         try:
    #             row = con.execute(
    #                 "SELECT prefs_json FROM gui_prefs WHERE pid=? AND lower(username)=lower(?)",
    #                 (pid, username),
    #             ).fetchone()
    #             if not row:
    #                 return {}
    #             try:
    #                 return json.loads(str(row[0]) or "{}") or {}
    #             except Exception:
    #                 return {}
    #         finally:
    #             con.close()



    def _get_gui_prefs_raw(self, pid: str, username: str) -> Dict[str, Any]:
        with self._lock:
            con = self._connect()
            try:
                row = con.execute(
                    "SELECT prefs_json FROM gui_prefs WHERE pid=? AND lower(username)=lower(?)",
                    (pid, username),
                ).fetchone()
                if not row:
                    return {}
                try:
                    return json.loads(str(row[0]) or "{}") or {}
                except Exception:
                    return {}
            finally:
                try:
                    con.close()
                except Exception:
                    pass

    def get_gui_prefs_default(self, pid: str) -> Dict[str, Any]:
        return self._get_gui_prefs_raw(pid, GUI_PREFS_DEFAULT_USER)

    def get_gui_prefs_user(self, pid: str, username: str) -> Dict[str, Any]:
        return self._get_gui_prefs_raw(pid, username)

    def get_gui_prefs_effective(self, pid: str, username: str) -> Dict[str, Any]:
        """Merge admin project defaults with user overrides."""
        base = self.get_gui_prefs_default(pid) or {}
        user = self.get_gui_prefs_user(pid, username) or {}

        def deep_merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
            out = dict(a)
            for k, v in (b or {}).items():
                if isinstance(v, dict) and isinstance(out.get(k), dict):
                    out[k] = deep_merge(out.get(k) or {}, v)
                else:
                    out[k] = v
            return out

        return deep_merge(base, user)

    def put_gui_prefs(self, pid: str, username: str, prefs: Dict[str, Any]) -> None:
        with self._lock:
            con = self._connect()
            try:
                con.execute(
                    "INSERT OR REPLACE INTO gui_prefs(pid, username, prefs_json, updated_ts) VALUES(?,?,?,?)",
                    (pid, username, json.dumps(prefs or {}), _now_ts()),
                )
                con.commit()
            finally:
                con.close()


    def ensure_default_collab_prompt(self) -> None:
        default_id = "collab_default"
        with self._lock:
            con = self._connect()
            try:
                row = con.execute("SELECT prompt_id FROM collab_prompts WHERE prompt_id=?", (default_id,)).fetchone()
                if row:
                    return
                prompt = (
                    "You are the collaboration assistant in a multi-user chat session.\n"
                    "Multiple human participants are discussing tasks, decisions, and questions.\n\n"
                    "Your job is to:\n"
                    "1) Briefly summarize the conversation so far (focus on agreements, decisions, and open questions).\n"
                    "2) Identify action items and who owns them if obvious.\n"
                    "3) Point out missing information, risks, or contradictions.\n"
                    "4) Suggest the next best step or a concise plan.\n\n"
                    "Keep it concise, structured, and grounded in the conversation.\n"
                    "If users are just chatting socially, keep the response minimal."
                )
                now = _now_ts()
                con.execute(
                    "INSERT OR REPLACE INTO collab_prompts(prompt_id, name, prompt, created_by, created_ts, updated_ts) VALUES(?,?,?,?,?,?)",
                    (default_id, "Collab Summary", prompt, "system", now, now),
                )
                con.commit()
            finally:
                con.close()

    def list_collab_prompts(self) -> List[Dict[str, Any]]:
        self.ensure_default_collab_prompt()
        with self._lock:
            con = self._connect()
            try:
                rows = con.execute(
                    "SELECT prompt_id, name, prompt, created_by, created_ts, updated_ts FROM collab_prompts ORDER BY lower(name)"
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                con.close()

    def upsert_collab_prompt(self, prompt_id: str, name: str, prompt: str, username: str) -> str:
        pid = (prompt_id or "").strip()
        if not pid:
            pid = secrets.token_hex(8)
        now = _now_ts()
        with self._lock:
            con = self._connect()
            try:
                row = con.execute("SELECT created_by, created_ts FROM collab_prompts WHERE prompt_id=?", (pid,)).fetchone()
                created_by = username
                created_ts = now
                if row:
                    created_by = str(row["created_by"] or username)
                    try:
                        created_ts = int(row["created_ts"] or now)
                    except Exception:
                        created_ts = now
                con.execute(
                    "INSERT OR REPLACE INTO collab_prompts(prompt_id, name, prompt, created_by, created_ts, updated_ts) VALUES(?,?,?,?,?,?)",
                    (pid, name, prompt, created_by, created_ts, now),
                )
                con.commit()
                return pid
            finally:
                con.close()

    def set_project_collab_settings(self, pid: str, ai_default: Optional[bool], collab_prompt_id: Optional[str]) -> None:
        with self._lock:
            con = self._connect()
            try:
                if ai_default is not None:
                    con.execute("UPDATE projects SET ai_default=? WHERE pid=?", (1 if ai_default else 0, pid))
                if collab_prompt_id is not None:
                    con.execute("UPDATE projects SET collab_prompt_id=? WHERE pid=?", (collab_prompt_id, pid))
                con.commit()
            finally:
                con.close()

    def set_session_collab_settings(
        self,
        pid: str,
        sid: str,
        ai_default: Optional[bool],
        collab_prompt_id: Optional[str],
        allow_guest: Optional[bool] = None,
    ) -> None:
        with self._lock:
            con = self._connect()
            try:
                if ai_default is not None:
                    con.execute("UPDATE sessions SET ai_default=? WHERE pid=? AND sid=?", (1 if ai_default else 0, pid, sid))
                if collab_prompt_id is not None:
                    con.execute("UPDATE sessions SET collab_prompt_id=? WHERE pid=? AND sid=?", (collab_prompt_id, pid, sid))
                if allow_guest is not None:
                    con.execute("UPDATE sessions SET allow_guest=? WHERE pid=? AND sid=?", (1 if allow_guest else 0, pid, sid))
                con.commit()
            finally:
                con.close()               


    def set_project_public(self, pid: str, is_public: bool) -> None:
        val = 1 if bool(is_public) else 0
        with self._lock:
            con = self._connect()
            try:
                con.execute("UPDATE projects SET is_public=? WHERE pid=?", (val, pid))
                # If project becomes private => force all sessions private
                if val == 0:
                    con.execute("UPDATE sessions SET is_public=0 WHERE pid=?", (pid,))
                con.commit()
            finally:
                con.close()

    def set_session_public(self, pid: str, sid: str, is_public: bool) -> None:
        with self._lock:
            con = self._connect()
            try:
                # If project is private, session is forced private regardless.
                prow = con.execute("SELECT is_public FROM projects WHERE pid=?", (pid,)).fetchone()
                if not prow:
                    return
                if int(prow["is_public"] or 0) == 0:
                    con.execute("UPDATE sessions SET is_public=0 WHERE pid=? AND sid=?", (pid, sid))
                else:
                    val = 1 if bool(is_public) else 0
                    con.execute("UPDATE sessions SET is_public=? WHERE pid=? AND sid=?", (val, pid, sid))
                con.commit()
            finally:
                con.close()

    def add_session_member(self, pid: str, sid: str, username: str, role: str = "user") -> None:
        with self._lock:
            con = self._connect()
            try:
                con.execute(
                    "INSERT OR IGNORE INTO session_members(pid, sid, username, role, created_ts) VALUES(?,?,?,?,?)",
                    (pid, sid, username, role, _now_ts()),
                )
                con.commit()
            finally:
                con.close()

    def upsert_project_member(self, pid: str, username: str, role: str = "user") -> None:
        with self._lock:
            con = self._connect()
            try:
                con.execute(
                    "INSERT OR REPLACE INTO project_members(pid, username, role) VALUES(?,?,?)",
                    (pid, username, role),
                )
                con.commit()
            finally:
                con.close()

    def add_join_request(self, pid: str, sid: str, username: str) -> str:
        req_id = secrets.token_hex(12)
        with self._lock:
            con = self._connect()
            try:
                con.execute(
                    "INSERT INTO join_requests(req_id, pid, sid, username, created_ts, status) VALUES(?,?,?,?,?,?)",
                    (req_id, pid, sid, username, _now_ts(), "pending"),
                )
                con.commit()
            finally:
                con.close()
        return req_id

    def list_join_requests(self, pid: str, sid: str, status: str = "pending") -> List[Dict[str, Any]]:
        with self._lock:
            con = self._connect()
            try:
                rows = con.execute(
                    "SELECT req_id, pid, sid, username, created_ts, status, acted_by, acted_ts "
                    "FROM join_requests WHERE pid=? AND sid=? AND status=? ORDER BY created_ts",
                    (pid, sid, status),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                con.close()

    def set_join_request_status(self, req_id: str, status: str, acted_by: str) -> None:
        with self._lock:
            con = self._connect()
            try:
                con.execute(
                    "UPDATE join_requests SET status=?, acted_by=?, acted_ts=? WHERE req_id=?",
                    (status, acted_by, _now_ts(), req_id),
                )
                con.commit()
            finally:
                con.close()


    #--------- scoping ---------

    def get_scope_all(self, username: str) -> bool:
        if not username:
            return True
        with self._lock:
            con = self._connect()
            try:
                row = con.execute(
                    "SELECT scope_all FROM users WHERE lower(username)=lower(?)",
                    (username,),
                ).fetchone()
                return True if not row else bool(int(row["scope_all"] or 0))
            finally:
                con.close()

    def set_scope_all(self, username: str, scope_all: bool) -> None:
        if not username:
            return
        with self._lock:
            con = self._connect()
            try:
                con.execute(
                    "UPDATE users SET scope_all=? WHERE lower(username)=lower(?)",
                    (1 if scope_all else 0, username),
                )
                con.commit()
            finally:
                con.close()

    def set_user_project_scope(self, username: str, projects: Optional[List[str]]) -> None:
        """
        projects:
          - None  => UNscoped (scope_all=1): can list all projects/sessions
          - []    => scoped to none (scope_all=0): sees no projects
          - [pids...] => scoped (scope_all=0): sees only those pids
        """
        uname = (username or "").strip()
        if not uname:
            return
        with self._lock:
            con = self._connect()
            try:
                if projects is None:
                    # unscoped: list all (but not automatic access)
                    con.execute(
                        "UPDATE users SET scope_all=1 WHERE lower(username)=lower(?)",
                        (uname,),
                    )
                    con.commit()
                    return

                # scoped: exact membership set
                pids = []
                for p in projects:
                    p = (p or "").strip()
                    if p:
                        pids.append(p)

                con.execute(
                    "UPDATE users SET scope_all=0 WHERE lower(username)=lower(?)",
                    (uname,),
                )

                # rewrite project memberships for this user
                con.execute(
                    "DELETE FROM project_members WHERE lower(username)=lower(?)",
                    (uname,),
                )
                for pid in pids:
                    con.execute(
                        "INSERT OR REPLACE INTO project_members(pid, username, role) VALUES(?,?,?)",
                        (pid, uname, "user"),
                    )

                con.commit()
            finally:
                con.close()

    # -------- messages --------

    def add_message(
        self,
        *,
        msg_id: str,
        pid: str,
        sid: str,
        ts: Optional[int] = None,
        role: str,
        kind: str,
        author_username: str,
        author_alias: str,
        content: str,
        meta: Dict[str, Any],
    ) -> None:
        with self._lock:
            con = self._connect()
            try:
                ts_i = int(ts if ts is not None else _now_ts())
                con.execute(
                    """
                    INSERT OR IGNORE INTO messages(
                        msg_id, pid, sid, ts, role, kind,
                        author_username, author_alias, content, meta_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        msg_id,
                        pid,
                        sid,
                        ts_i,
                        role,
                        kind,
                        author_username,
                        author_alias,
                        content,
                        json.dumps(meta or {}),
                    ),
                )
                con.commit()
            finally:
                con.close()

    def set_message_content(self, *, msg_id: str, content: str) -> None:
            with self._lock:
                con = self._connect()
                try:
                    con.execute("UPDATE messages SET content=? WHERE msg_id=?", (content, msg_id))
                    con.commit()
                finally:
                    con.close()

    def list_messages(
        self,
        *,
        pid: str,
        sid: str,
        after_msg_id: Optional[str] = None,
        since_ts: Optional[int] = None,
        limit: int = 200,
        order_desc: bool = False,
    ) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit or 200), 500))
        with self._lock:
            con = self._connect()
            try:
                where = ["pid=?", "sid=?"]
                args: List[Any] = [pid, sid]
                if since_ts is not None:
                    where.append("ts>=?")
                    args.append(int(since_ts))
                if after_msg_id:
                    # convert to ts boundary for efficiency
                    row = con.execute(
                        "SELECT ts FROM messages WHERE msg_id=? AND pid=? AND sid=?",
                        (after_msg_id, pid, sid),
                    ).fetchone()
                    if row:
                        where.append("(ts>? OR (ts=? AND msg_id>?))")
                        args.extend([int(row[0]), int(row[0]), after_msg_id])
                order = "ORDER BY ts DESC, msg_id DESC" if order_desc else "ORDER BY ts, msg_id"
                q = (
                    "SELECT msg_id, pid, sid, ts, role, kind, author_username, author_alias, content, meta_json "
                    "FROM messages WHERE " + " AND ".join(where) + f" {order} LIMIT ?"
                )
                args.append(limit)
                rows = con.execute(q, tuple(args)).fetchall()
                out: List[Dict[str, Any]] = []
                for r in rows:
                    d = dict(r)
                    try:
                        d["meta"] = json.loads(d.pop("meta_json") or "{}")
                    except Exception:
                        d["meta"] = {}
                        d.pop("meta_json", None)
                    out.append(d)
                if order_desc:
                    out.reverse()
                return out
            finally:
                con.close()

    def get_transcript_cache(self, pid: str, sid: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            con = self._connect()
            try:
                row = con.execute(
                    "SELECT payload_json, updated_ts FROM transcript_cache WHERE pid=? AND sid=?",
                    (pid, sid),
                ).fetchone()
                if not row:
                    return None
                try:
                    payload = json.loads(row["payload_json"] or "{}")
                except Exception:
                    payload = None
                if not isinstance(payload, dict):
                    return None
                payload["updated_ts"] = int(row["updated_ts"] or 0)
                return payload
            finally:
                con.close()

    def set_transcript_cache(self, pid: str, sid: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            con = self._connect()
            try:
                ts = _now_ts()
                blob = json.dumps(payload or {}, ensure_ascii=False)
                con.execute(
                    """
                    INSERT INTO transcript_cache(pid, sid, payload_json, updated_ts)
                    VALUES(?,?,?,?)
                    ON CONFLICT(pid, sid) DO UPDATE SET
                        payload_json=excluded.payload_json,
                        updated_ts=excluded.updated_ts
                    """,
                    (pid, sid, blob, ts),
                )
                con.commit()
            finally:
                con.close()


def _token_from_headers(request: Request) -> str:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    tok = request.headers.get("X-Auth-Token") or ""
    return tok.strip()


def _require_user(app, request: Request) -> UserInfo:
    db: _DB = app.state.collab_db
    token = _token_from_headers(request)
    u = db.resolve_token(token)
    if not u:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return u


def _optional_user(app, request: Request) -> Optional[UserInfo]:
    db: _DB = app.state.collab_db
    token = _token_from_headers(request)
    if not token:
        return None
    return db.resolve_token(token)


# def _require_project_access(app, u: UserInfo, pid: str) -> None:
#     if u.role == "admin":
#         return
#     db: _DB = app.state.collab_db
#     with db._lock:
#         con = db._connect()
#         try:
#             row = con.execute(
#                 "SELECT role FROM project_members WHERE pid=? AND lower(username)=lower(?)",
#                 (pid, u.username),
#             ).fetchone()
#             if not row:
#                 raise HTTPException(status_code=403, detail="No project access")
#         finally:
#             con.close()

def _require_project_admin(app, u: UserInfo, pid: str) -> None:
    """Project admin gate: global admin OR project member role=admin OR project creator."""
    if u.role == "admin":
        return
    db: _DB = app.state.collab_db
    with db._lock:
        con = db._connect()
        try:
            prow = con.execute("SELECT created_by FROM projects WHERE pid=?", (pid,)).fetchone()
            if prow and str(prow["created_by"]).lower() == u.username.lower():
                return
            row = con.execute(
                "SELECT role FROM project_members WHERE pid=? AND lower(username)=lower(?)",
                (pid, u.username),
            ).fetchone()
            if row and str(row["role"] or "").lower() == "admin":
                return
            raise HTTPException(status_code=403, detail="Project admin only")
        finally:
            con.close()

def _require_named_permission(app, request: Request, permission_key: str, detail: Optional[str] = None) -> Dict[str, Any]:
    try:
        from plugins.gui_helpers.permissions_manager.core import require_permission
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"permissions unavailable: {exc}") from exc
    return require_permission(app, request, permission_key, detail=detail)


def _get_project_row(db: "_DB", pid: str) -> Optional[Dict[str, Any]]:
    with db._lock:
        con = db._connect()
        try:
            row = con.execute(
                "SELECT pid, name, created_by, created_ts, is_public, ai_default, collab_prompt_id FROM projects WHERE pid=?",
                (pid,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            con.close()


def _get_session_row(db: "_DB", pid: str, sid: str) -> Optional[Dict[str, Any]]:
    with db._lock:
        con = db._connect()
        try:
            row = con.execute(
                "SELECT sid, pid, title, created_by, created_ts, is_public, allow_guest, ai_default, collab_prompt_id FROM sessions WHERE pid=? AND sid=?",
                (pid, sid),
            ).fetchone()
            return dict(row) if row else None
        finally:
            con.close()


def _project_member_role(db: "_DB", pid: str, username: str) -> Optional[str]:
    with db._lock:
        con = db._connect()
        try:
            row = con.execute(
                "SELECT role FROM project_members WHERE pid=? AND lower(username)=lower(?)",
                (pid, username),
            ).fetchone()
            return str(row["role"]) if row else None
        finally:
            con.close()


def _is_session_member(db: "_DB", pid: str, sid: str, username: str) -> bool:
    with db._lock:
        con = db._connect()
        try:
            row = con.execute(
                "SELECT 1 FROM session_members WHERE pid=? AND sid=? AND lower(username)=lower(?)",
                (pid, sid, username),
            ).fetchone()
            return bool(row)
        finally:
            con.close()


def _effective_public(proj: Dict[str, Any], sess: Dict[str, Any]) -> bool:
    # project private => all sessions effectively private
    ppub = int(proj.get("is_public") or 0) == 1
    if not ppub:
        return False
    return int(sess.get("is_public") or 0) == 1


def _session_allows_guest(proj: Dict[str, Any], sess: Dict[str, Any]) -> bool:
    return _effective_public(proj, sess) and int(sess.get("allow_guest") or 0) == 1


def _guest_id_from_request(request: Request) -> str:
    return str(request.headers.get("X-Guest-Id") or "").strip()


def _guest_alias_from_request(request: Request, alias_value: Optional[str] = None) -> str:
    raw = str(alias_value or request.headers.get("X-User-Alias") or "").strip()
    return raw[:80].strip()


def _format_guest_alias(alias: str) -> str:
    base = str(alias or "").strip() or "Guest"
    return base if base.lower().endswith("(guest)") else f"{base} (guest)"


def _get_session_guest_access(db: "_DB", pid: str, sid: str) -> Dict[str, Any]:
    proj = _get_project_row(db, pid)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    sess = _get_session_row(db, pid, sid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    if not _session_allows_guest(proj, sess):
        raise HTTPException(status_code=403, detail="Guest access not allowed")
    return {"project": proj, "session": sess}


def _require_user_or_guest(app, request: Request, pid: str, sid: str, alias_value: Optional[str] = None) -> Dict[str, Any]:
    db: _DB = app.state.collab_db
    token = _token_from_headers(request)
    u = db.resolve_token(token)
    if u:
        access = require_session_access(db, u, pid, sid)
        return {"kind": "user", "user": u, "access": access}
    access = _get_session_guest_access(db, pid, sid)
    guest_id = _guest_id_from_request(request)
    if not guest_id:
        raise HTTPException(status_code=401, detail="Guest id required")
    alias = _guest_alias_from_request(request, alias_value)
    if not alias:
        alias = "Guest"
    guest_username = f"guest:{guest_id}"
    return {
        "kind": "guest",
        "user": UserInfo(username=guest_username, role="guest"),
        "alias": _format_guest_alias(alias),
        "access": access,
        "guest_id": guest_id,
    }


def require_session_access(db: "_DB", u: UserInfo, pid: str, sid: str) -> Dict[str, Any]:
    """
    Access to session CONTENT (messages/events/post/model turns):
      - Global admin: always
      - Effective public (project public + session public): any authenticated user
      - Otherwise:
          * session owner (created_by) always
          * private project: project members allowed
          * public project + private session: session_members allowed; project admin allowed
    """
    proj = _get_project_row(db, pid)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    sess = _get_session_row(db, pid, sid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    if u.role == "admin":
        return {"project": proj, "session": sess}

    if _effective_public(proj, sess):
        return {"project": proj, "session": sess}

    if (sess.get("created_by") or "").lower() == (u.username or "").lower():
        return {"project": proj, "session": sess}

    ppub = int(proj.get("is_public") or 0) == 1
    if not ppub:
        # private project => project members can access
        if _project_member_role(db, pid, u.username):
            return {"project": proj, "session": sess}
        raise HTTPException(status_code=403, detail="Project is private")

    # public project + private session:
    role = _project_member_role(db, pid, u.username)
    if role and role.lower() == "admin":
        return {"project": proj, "session": sess}

    if _is_session_member(db, pid, sid, u.username):
        return {"project": proj, "session": sess}

    raise HTTPException(status_code=403, detail="Session is private")


def _require_session_access(app, u: UserInfo, pid: str, sid: str) -> Dict[str, Any]:
    db: _DB = app.state.collab_db
    return require_session_access(db, u, pid, sid)

def _require_project_admin_or_owner(db: "_DB", u: UserInfo, pid: str, sid: str) -> None:
    """
    Admin gate for join approvals:
      - global admin always
      - session owner (created_by) always
      - project admin always
      - project owner (created_by) always
    """
    if u.role == "admin":
        return

    sess = _get_session_row(db, pid, sid)
    if sess and (sess.get("created_by") or "").lower() == (u.username or "").lower():
        return

    proj = _get_project_row(db, pid)
    if proj and (proj.get("created_by") or "").lower() == (u.username or "").lower():
        return

    role = _project_member_role(db, pid, u.username)
    if role and role.lower() == "admin":
        return

    raise HTTPException(status_code=403, detail="Admin/owner only")

# def require_session_access(db: "_DB", u: UserInfo, pid: str, sid: str) -> Dict[str, Any]:
#     """
#     Session visibility rules:
#       - Global admin: always allowed
#       - Public session: any user with project access is allowed
#       - Private session: ONLY the session creator is allowed
#     """
#     s = db.get_session(pid, sid)
#     if not s:
#         raise HTTPException(status_code=404, detail="Session not found")

#     if u.role == "admin":
#         return s

#     is_public = int(s.get("is_public") or 0) == 1
#     if is_public:
#         return s

#     created_by = (s.get("created_by") or "")
#     if created_by.lower() == (u.username or "").lower():
#         return s

#     raise HTTPException(status_code=403, detail="Session is private")


# def _require_session_access(app, u: UserInfo, pid: str, sid: str) -> Dict[str, Any]:
#     db: _DB = app.state.collab_db
#     return require_session_access(db, u, pid, sid)



class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    ok: bool = True
    token: str
    username: str
    role: str
    must_change_pw: Optional[bool] = False

class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=1)


class EnsureStarterSessionRequest(BaseModel):
    pid: str = "default"
    project_name: str = "Default"
    sid: str = "chat"
    title: str = "Chat"


class ChatUiInfoIn(BaseModel):
    title: str = "OS-Chat"
    subtitle: str = "Your AI Chat"
    logo_data_url: str = ""


class CreateProjectRequest(BaseModel):
    pid: Optional[str] = None
    name: str = Field(..., min_length=1)
    is_public: bool = False


class CreateSessionRequest(BaseModel):
    sid: Optional[str] = None
    title: Optional[str] = None
    is_public: Optional[bool] = None  # default handled in route (private by default

class SetSessionVisibilityRequest(BaseModel):
    is_public: bool


class PutGuiPrefsRequest(BaseModel):
    prefs: Dict[str, Any] = Field(default_factory=dict)
    scope: str = "user"  # "user" or "project" (admin-only)


class PostMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)
    role: str = "user"  # user|assistant|system
    kind: str = "human"  # human|model|event
    alias: Optional[str] = None
    client_msg_id: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)

class TranscriptCacheRequest(BaseModel):
    payload: Dict[str, Any] = Field(default_factory=dict)


class ModelTurnRequest(BaseModel):
    # Accept multiple client shapes to avoid 422:
    # - {prompt: "..."} (preferred)
    # - {content: "..."} (legacy)
    # - {messages: [...]} (OpenAI-ish)
    prompt: Optional[str] = None
    content: Optional[str] = None
    messages: Optional[List[Dict[str, Any]]] = None

    alias: Optional[str] = None
    client_msg_id: Optional[str] = None

    # Optional generation knobs
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    stop: Optional[Any] = None


class ServiceChatRequest(BaseModel):
    message: Optional[str] = None
    prompt: Optional[str] = None
    content: Optional[str] = None
    selected_flow: Optional[str] = None
    alias: Optional[str] = None
    client_msg_id: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    stream: Optional[bool] = None
    wait_timeout_s: Optional[float] = 90.0
    stream_capture_timeout_s: Optional[float] = 90.0


class BuiltinAutoFlowExecuteRequest(BaseModel):
    message: Optional[str] = None
    prompt: Optional[str] = None
    candidate: Optional[Dict[str, Any]] = None
    client_msg_id: Optional[str] = None


def install(app) -> None:
    db_path = os.environ.get("MODEL_LOADER_COLLAB_DB") or _default_db_path()
    db = _DB(db_path)
    app.state.collab_db = db
    if not hasattr(app.state, "collab_hub"):
        app.state.collab_hub = _SessionHub()
    register_plugin_service(
        app,
        GUI_PLUGIN_ID,
        {
            "UserInfo": UserInfo,
            "pbkdf2_sha256": _pbkdf2_sha256,
            "token_from_headers": _token_from_headers,
            "require_user": lambda request: _require_user(app, request),
            "optional_user": lambda request: _optional_user(app, request),
            "require_session_access": lambda user, pid, sid: _require_session_access(app, user, pid, sid),
            "now_ts": _now_ts,
        },
        family="gui_helper",
    )
    
    # Register StreamHook sink so /v1/chat/completions_stream persists turns for collab sessions
    try:
        hooks = getattr(app.state, "stream_hooks", None)
        if hooks is None:
            app.state.stream_hooks = []
            hooks = app.state.stream_hooks
        already = False
        try:
            for h in list(hooks):
                if isinstance(h, CollabStreamHook):
                    already = True
                    break
        except Exception:
            already = False
        if not already:
            hooks.append(CollabStreamHook(app))
            print("[collab_chat] StreamHook registered (completions_stream sink)")
        else:
            print("[collab_chat] StreamHook already registered")
    except Exception as e:
        print("[collab_chat] StreamHook register failed:", e)

    if not hasattr(app.state, "collab_presence"):
        app.state.collab_presence = _PresenceStore()
    if not hasattr(app.state, "collab_stop_tokens"):
        app.state.collab_stop_tokens = {}

    temp_pw = db.ensure_bootstrap_admin()
    if temp_pw:
        db.set_bootstrap_secret("admin_temp_password", temp_pw)
        print("[collab_chat] created bootstrap admin user: admin")
        # print("[collab_chat] bootstrap admin password:", temp_pw)
        print("\n" + "="*72)
        print("[collab_chat] ADMIN TEMP PASSWORD (copy this, shown once in GUI):")
        print(temp_pw)
        print("="*72 + "\n")

    # Ensure a default project so fresh installs have something to land on.
    try:
        db.ensure_project("default", "default", "admin")
    except Exception:
        pass

    r = APIRouter()

    @r.get("/v1/auth/ping")
    def auth_ping():
        return {"ok": True, "provider": "collab_chat", "ts": _now_ts()}
    
    @r.get("/v1/auth/bootstrap_admin_password")
    def bootstrap_admin_password(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        if u.role != "admin":
            raise HTTPException(status_code=403, detail="Admin only")

        pw = db.consume_bootstrap_secret("admin_temp_password")
        return {"ok": True, "password": pw}

    @r.get("/v1/auth/bootstrap_admin_setup")
    def bootstrap_admin_setup(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        try:
            must = bool(db.get_must_change_pw("admin"))
        except Exception:
            must = False
        if not must:
            return {"ok": True, "show": False}
        pw = db.consume_bootstrap_secret("admin_temp_password")
        if not pw:
            return {"ok": True, "show": False}
        return {
            "ok": True,
            "show": True,
            "username": "admin",
            "password": pw,
            "must_change_pw": True,
        }

    @r.get("/v1/chat_ui/info")
    def chat_ui_info(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        info = db.get_app_setting_json("chat_ui_info") or {}
        title = str(info.get("title") or "OS-Chat").strip() or "OS-Chat"
        subtitle = str(info.get("subtitle") or "Your AI Chat").strip() or "Your AI Chat"
        logo_data_url = str(info.get("logo_data_url") or "").strip()
        return {
            "ok": True,
            "title": title,
            "subtitle": subtitle,
            "logo_data_url": logo_data_url,
        }

    @r.post("/v1/chat_ui/info")
    def save_chat_ui_info(req: ChatUiInfoIn, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        if str(getattr(u, "role", "")).lower() != "admin":
            raise HTTPException(status_code=403, detail="Admin only")

        title = str(req.title or "OS-Chat").strip() or "OS-Chat"
        subtitle = str(req.subtitle or "Your AI Chat").strip() or "Your AI Chat"
        logo_data_url = str(req.logo_data_url or "").strip()
        if len(title) > 120:
            raise HTTPException(status_code=400, detail="Title too long")
        if len(subtitle) > 200:
            raise HTTPException(status_code=400, detail="Subtitle too long")
        if logo_data_url:
            if not logo_data_url.startswith("data:image/"):
                raise HTTPException(status_code=400, detail="Logo must be an image data URL")
            if len(logo_data_url) > 900_000:
                raise HTTPException(status_code=400, detail="Logo too large")

        payload = {
            "title": title,
            "subtitle": subtitle,
            "logo_data_url": logo_data_url,
        }
        db.set_app_setting_json("chat_ui_info", payload)
        return {"ok": True, **payload}

    @r.post("/v1/auth/login", response_model=LoginResponse)
    def auth_login(req: LoginRequest, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = db.verify_login(req.username.strip(), req.password)
        if not u:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        tok = db.issue_token(u.username)
        must = bool(db.get_must_change_pw(req.username))
        return LoginResponse(token=tok, username=u.username, role=u.role, must_change_pw=must )

    @r.post("/v1/auth/logout")
    def auth_logout(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        tok = _token_from_headers(request)
        if tok:
            db.revoke_token(tok)
        return {"ok": True}

    # @r.get("/v1/auth/me")
    # def auth_me(request: Request):
    #     require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
    #     u = _require_user(app, request)
    #     return {"ok": True, "username": u.username, "role": u.role}
    @r.get("/v1/auth/me")
    def auth_me(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        must = False
        try:
            must = bool(db.get_must_change_pw(u.username))
        except Exception:
            must = False
        return {"ok": True, "user": {"username": u.username, "role": u.role, "must_change_pw": must}}

    def _internal_service_headers(request: Request, *, pid: str, sid: str, enabled_plugins: Iterable[Any], suppress_persist: bool = False) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "X-Project-Id": str(pid or "").strip(),
            "X-Session-Id": str(sid or "").strip(),
            "X-Gui-Enabled-Plugins": _service_enabled_plugins(enabled_plugins),
        }
        if suppress_persist:
            headers["X-Collab-Suppress-Persist"] = "1"
        auth = str(request.headers.get("Authorization") or "").strip()
        if auth:
            headers["Authorization"] = auth
        xauth = str(request.headers.get("X-Auth-Token") or "").strip()
        if xauth and not auth:
            headers["X-Auth-Token"] = xauth
        alias = str(request.headers.get("X-User-Alias") or "").strip()
        if alias:
            headers["X-User-Alias"] = alias
        return headers

    async def _wait_for_agent_flow_completion(pid: str, sid: str, run_id: str, headers: Dict[str, str], timeout_s: float) -> Dict[str, Any]:
        started = time.time()
        while True:
            if timeout_s > 0 and (time.time() - started) > timeout_s:
                raise HTTPException(status_code=504, detail="service_chat_agent_flow_timeout")
            status = await _internal_json_request(
                app,
                method="GET",
                path=f"/v1/projects/{pid}/sessions/{sid}/agent_flow/status?run_id={run_id}",
                headers=headers,
            )
            state = status.get("state") if isinstance(status, dict) else None
            if not isinstance(state, dict) or not bool(state.get("running")):
                return state if isinstance(state, dict) else {}
            await asyncio.sleep(1.0)
    def _local_builtin_candidate(prompt: str) -> Dict[str, Any]:
        text = str(prompt or "").strip()
        if not text:
            return {}
        try:
            from plugins.ai_routes.autoflow import AutoFlowRoute
            from plugins.ai_routes.base import RouterCore

            route = AutoFlowRoute(RouterCore(chat_llm=None, settings={}))
            profile = route._request_profile(text)
            candidate = route._builtin_direct_candidate(text, profile)
            if not isinstance(candidate, dict):
                return {}
            flow_name = str(candidate.get("name") or "").strip()
            if not flow_name:
                return {}
            if not route._is_fast_builtin_candidate(candidate):
                return {}
            return candidate
        except Exception:
            return {}

    def _inline_market_data_top_n(prompt: str) -> int:
        raw = str(prompt or "")
        low = raw.lower()
        seen = set()
        for sym in re.findall(r"\(([A-Z][A-Z0-9.\-]{0,9})\)", raw):
            val = str(sym or "").strip().upper()
            if val:
                seen.add(val)
        for sym in re.findall(r"([A-Z]{2,5})", raw):
            val = str(sym or "").strip().upper()
            if val and val not in {"USD", "ETF", "ETD", "API"}:
                seen.add(val)
        for name, ticker in {
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
        }.items():
            if name in low:
                seen.add(ticker)
        return max(2, min(len(seen) if seen else 10, 10))

    def _load_skill_runner(skill_id: str):
        import importlib.util
        from pathlib import Path

        skill = str(skill_id or "").strip()
        if "." not in skill:
            return None
        group, _, name = skill.partition(".")
        skill_path = Path(__file__).resolve().parents[1] / "agent_flow" / "skills" / group / f"{name}.py"
        if not skill_path.is_file():
            return None
        mod_name = f"collab_chat_inline_{group}_{name}"
        spec = importlib.util.spec_from_file_location(mod_name, skill_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        runner = getattr(module, "run", None)
        return runner if callable(runner) else None

    async def _run_builtin_candidate_result(pid: str, sid: str, prompt: str, svc: ServiceChatRequest, candidate: Dict[str, Any], router_cfg: Dict[str, Any], request: Request) -> Optional[Dict[str, Any]]:
        generated = candidate.get("generated_workflow") if isinstance(candidate.get("generated_workflow"), dict) else {}
        flow_name = str((candidate.get("selected_flow") or candidate.get("flow_name") or candidate.get("name") or generated.get("flow_name") or "")).strip()
        generated_flow = generated.get("workflow_json") if isinstance(generated.get("workflow_json"), dict) else None
        if flow_name in {"__autoflow_builtin_repo_code_explain__", "__autoflow_builtin_repo_code_improve__"} and isinstance(generated_flow, dict):
            return await _run_agent_flow_service_turn(
                pid,
                sid,
                prompt,
                svc,
                router_cfg,
                request,
                flow_name=flow_name,
                flow_def=generated_flow,
                temp_skill_dirs=[str(x or "").strip() for x in (generated.get("temp_skill_dirs") or []) if str(x or "").strip()],
            )
        return _inline_builtin_skill_result(pid, sid, prompt, svc, candidate)

    def _inline_builtin_skill_result(pid: str, sid: str, prompt: str, svc: ServiceChatRequest, candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            generated = candidate.get("generated_workflow") if isinstance(candidate.get("generated_workflow"), dict) else {}
            flow_name = str((candidate.get("selected_flow") or candidate.get("flow_name") or candidate.get("name") or generated.get("flow_name") or "")).strip()
            skill_map = {
                "__autoflow_builtin_weather_lookup__": ("external_data.weather_lookup", {
                    "request_text": prompt,
                    "query": prompt,
                    "temperature_unit": "fahrenheit",
                    "wind_speed_unit": "mph",
                    "timeout": 8.0,
                }),
                "__autoflow_builtin_market_data__": ("custom.market_data_report", {
                    "request_text": prompt,
                    "query": prompt,
                    "top_n": _inline_market_data_top_n(prompt),
                    "timeout": 8.0,
                    "output_mode": "text",
                }),
                "__autoflow_builtin_world_bank_compare__": ("custom.world_bank_compare_report", {
                    "request_text": prompt,
                    "query": prompt,
                    "timeout": 8.0,
                }),
                "__autoflow_builtin_budget_compare__": ("custom.budget_compare_report", {
                    "request_text": prompt,
                    "query": prompt,
                }),
                "__autoflow_builtin_zip_files__": ("custom.zip_requested_files", {
                    "request_text": prompt,
                    "query": prompt,
                }),
                "__autoflow_builtin_file_chart_report__": ("custom.file_chart_report", {
                    "request_text": prompt,
                    "query": prompt,
                }),
                "__autoflow_builtin_support_ticket_triage__": ("custom.support_ticket_triage_report", {
                    "request_text": prompt,
                    "query": prompt,
                }),
                "__autoflow_builtin_vendor_shortlist__": ("custom.vendor_shortlist_report", {
                    "request_text": prompt,
                    "query": prompt,
                }),
                "__autoflow_builtin_sprint_plan__": ("custom.sprint_plan_report", {
                    "request_text": prompt,
                    "query": prompt,
                }),
                "__autoflow_builtin_scheduling_resolution__": ("custom.scheduling_resolution_report", {
                    "request_text": prompt,
                    "query": prompt,
                }),
                "__autoflow_builtin_contract_risk_review__": ("custom.contract_risk_review", {
                    "request_text": prompt,
                    "query": prompt,
                }),
                "__autoflow_builtin_incident_timeline__": ("custom.incident_timeline_report", {
                    "request_text": prompt,
                    "query": prompt,
                }),
                "__autoflow_builtin_release_announcement_email__": ("custom.release_announcement_email", {
                    "request_text": prompt,
                    "query": prompt,
                }),
                "__autoflow_builtin_faq_compiler__": ("custom.faq_compiler", {
                    "request_text": prompt,
                    "query": prompt,
                }),
                "__autoflow_builtin_repo_project_summary__": ("custom.repo_project_summary", {
                    "request_text": prompt,
                    "query": prompt,
                }),
                "__autoflow_builtin_repo_path_inspect__": ("custom.repo_path_inspect", {
                    "request_text": prompt,
                    "query": prompt,
                }),
                "__autoflow_builtin_repo_reference_search__": ("custom.repo_reference_search", {
                    "request_text": prompt,
                    "query": prompt,
                }),
                "__autoflow_builtin_repo_code_explain__": ("custom.repo_code_explain", {
                    "request_text": prompt,
                    "query": prompt,
                }),
                "__autoflow_builtin_repo_file_summary__": ("custom.repo_file_summary", {
                    "request_text": prompt,
                    "query": prompt,
                }),
                "__autoflow_builtin_imf_world_bank_macro_brief__": ("custom.imf_world_bank_macro_brief", {
                    "request_text": prompt,
                    "query": prompt,
                    "timeout": 8.0,
                }),
                "__autoflow_builtin_google_scholar_report__": ("custom.google_scholar_report", {
                    "request_text": prompt,
                    "query": prompt,
                    "timeout": 8.0,
                }),
                "__autoflow_builtin_arxiv_report__": ("custom.arxiv_report", {
                    "request_text": prompt,
                    "query": prompt,
                    "timeout": 8.0,
                }),
                "__autoflow_builtin_web_research__": ("custom.awf_web_research__web_research_204fb17b_executor", {
                    "request_text": prompt,
                    "query": prompt,
                    "text": prompt,
                    "timeout": 8.0,
                    "max_results": 6,
                }),
            }
            mapping = skill_map.get(flow_name)
            if not mapping:
                return None
            tool_name, params = mapping
            runner = _load_skill_runner(tool_name)
            if not callable(runner):
                print(f"[service_chat inline builtin missing runner] flow={flow_name} tool={tool_name}", flush=True)
                return None
            ctx = {
                "app": app,
                "original_request": prompt,
                "user_text": prompt,
                "project_id": pid,
                "session_id": sid,
                "sid": sid,
            }
            raw = runner(ctx, dict(params))
            result = raw if isinstance(raw, dict) else {"ok": bool(raw), "text": str(raw or "")}
            text_out = ""
            for key in ("final_answer", "summary", "text", "response", "content"):
                value = str(result.get(key) or "").strip()
                if value:
                    text_out = value
                    break
            if not text_out and isinstance(result.get("data"), dict):
                try:
                    text_out = json.dumps(result.get("data") or {}, ensure_ascii=False)
                except Exception:
                    text_out = str(result.get("data") or "").strip()
            if not text_out:
                print(f"[service_chat inline builtin empty] flow={flow_name} tool={tool_name} result_keys={sorted(result.keys()) if isinstance(result, dict) else type(result).__name__}", flush=True)
                return None
            print(f"[service_chat inline builtin] flow={flow_name} tool={tool_name} chars={len(text_out)}", flush=True)
            return {
                "mode": "chat",
                "flow_name": flow_name,
                "run": {"ok": True, "inline_builtin": True, "flow_name": flow_name, "skill": tool_name, "kind": "inline_builtin_direct"},
                "state": {
                    "running": False,
                    "status": "Completed",
                    "final_result": text_out,
                    "final_result_mode": "text",
                },
                "assistant_message": None,
                "autoflow": {
                    "selected_flow": flow_name,
                    "flow_name": flow_name,
                    "source": "builtin",
                    "reason": str(candidate.get("reason") or "builtin_direct_fast_path"),
                    "candidates": [candidate],
                },
            }
        except Exception as exc:
            import traceback
            print(f"[service_chat inline builtin failed] {exc!r}", flush=True)
            traceback.print_exc()
            return None

    async def _run_direct_model_with_research_context(pid: str, sid: str, prompt: str, svc: ServiceChatRequest, request: Request, *, research_text: str, context_label: str = "current research context", answer_style: str = "default") -> Dict[str, Any]:
        cleaned_research = str(research_text or "").strip()
        if not cleaned_research:
            raise HTTPException(status_code=400, detail="missing_research_context")
        if not _service_ensure_text_model(app):
            raise HTTPException(status_code=503, detail="chat_model_not_loaded")
        payload = {
            "model": "",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        (
                            "You are helping with a drafting or project-building request that needs some current context. "
                            "Use the provided research context as grounding, but keep the answer productive and usable even if some figures are incomplete. "
                            "Draft the requested project, outline, proposal, or plan directly. Start with the deliverable itself, not commentary about how good the topic is. "
                            "If an exact live number is uncertain, do not refuse the task. Instead, mark that figure as something the user should verify or update, then continue with the strongest workable structure. Keep the tone practical and concise. Avoid emojis, filler praise, and overly decorative formatting. Prefer short sections, short bullets, or short paragraphs. "
                            "Do not mention internal tools, workflows, routing, or research-process details. "
                            "Do not replace the user's requested topic, comparison scope, time frame, assignment type, or framing with a different canned template or historical period. Preserve the user's actual request unless the provided context explicitly narrows it. "
                            "Do not replace the user's requested topic, comparison scope, time frame, assignment type, or framing with a different canned template or historical period. If the user asks about earlier waves, earlier periods, or historical comparisons generally, keep that broader framing and offer examples rather than collapsing the answer to one chosen period unless the user explicitly asked for that period. "
                        )
                        if str(answer_style or "default").strip().lower() == "authoring"
                        else (
                            "You are answering a current-information question using only the provided evidence. "
                            "Answer directly in 4-7 sentences unless 3-5 compact bullets are clearly better. "
                            "Name concrete developments, organizations, products, policies, or events from the context when available instead of speaking only in abstractions. "
                            "For trend or outlook questions, explicitly separate what appears to be happening now from what seems likely next. "
                            "Include exact dates or periods when the context provides them, and say plainly when the retrieved evidence is too weak to support a precise claim. "
                            "Do not mention internal tools, workflows, routing, or research-process details."
                        )
                        if str(answer_style or "default").strip().lower() == "current_context_explanatory"
                        else (
                            "You are repairing or restating a current-facts answer using only the provided evidence. "
                            "Use only facts directly supported by the provided context. Do not use outside knowledge, memory, or assumptions. "
                            "If the evidence is contradictory, corrupted, or insufficient, say that you could not verify the answer from the retrieved sources and mention the strongest source links briefly. "
                            "Do not guess a person, officeholder, date, or figure that is not clearly supported by the context. "
                            "Do not mention internal tools, workflows, routing, or research-process details. "
                            "Prefer a short direct answer and cite one or two source URLs when helpful."
                        )
                        if str(answer_style or "default").strip().lower() == "identity_repair"
                        else (
                            "You are rewriting raw web research into a final user-facing answer. "
                            "Use only the provided context as evidence. "
                            "Answer the request directly in 4-8 sentences unless a tiny table or 3-5 compact bullets is clearly better. "
                            "Do not reproduce numbered source lists, scraped boilerplate, navigation text, or raw headline dumps. "
                            "Do not say 'based on the provided context' or 'see the retrieved items below'. "
                            "If the evidence mostly consists of headlines, summarize the common themes cautiously and note uncertainty where needed. For trend or outlook questions, include both what is happening now and what direction the market or field appears to be heading next. "
                            "When the topic is current or time-sensitive, include exact dates or periods when the context provides them. "
                            "Prefer concrete developments, named organizations, products, policies, or events from the context over abstract market-summary language."
                        )
                        if str(answer_style or "default").strip().lower() == "web_research_rewrite"
                        else (
                            "You are rewriting raw web research into a final user-facing current-information answer. "
                            "Use only the provided context as evidence. "
                            "Give a compact but concrete synthesis in 5-8 sentences or 3-5 compact bullets. "
                            "Name 2-4 specific developments, organizations, products, policies, or events from the context when available. "
                            "For trend or outlook questions, explicitly separate: what is happening now, and what appears to be happening next. "
                            "Avoid vague phrases like major players, the market is moving, strategic shift, or we can expect unless they are immediately supported by concrete examples. "
                            "Include exact dates or periods when the context provides them."
                        )
                        if str(answer_style or "default").strip().lower() == "web_research_rewrite_detailed"
                        else (
                            "You are answering a user request that needs current factual context. "
                            "Use the provided research context as your factual basis and write the final user-facing answer directly. "
                            "Do not mention internal tools, workflows, routing, or research-process details. "
                            "Synthesize instead of copying raw snippets. Prefer a short direct answer, then compact bullets or a small table only if useful. "
                            "When the topic is current or time-sensitive, include exact dates or periods when the context provides them. "
                            "If the context is incomplete or a precise figure cannot be verified, say that plainly and use cautious wording rather than inventing details."
                        )
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"User request:\n{str(prompt or '').strip()}\n\n"
                        f"{context_label.title()}:\n{cleaned_research}\n\n"
                        "Write the final answer for the user now. Keep it concise, grounded in the provided context, and ready to send."
                    ),
                },
            ],
            "backend_type": "auto",
            "stream": False,
            "router_enabled_plugins": [],
            "ext": {
                "project_id": pid,
                "session_id": sid,
                "session-id": sid,
                "sid": sid,
            },
            "sid": sid,
        }
        if svc.temperature is not None:
            payload["temperature"] = svc.temperature
        if svc.max_tokens is not None:
            payload["max_tokens"] = svc.max_tokens
        if svc.top_p is not None:
            payload["top_p"] = svc.top_p
        try:
            response = await asyncio.wait_for(
                _internal_json_request(
                    app,
                    method="POST",
                    path="/v1/chat/completions",
                    headers=_internal_service_headers(request, pid=pid, sid=sid, enabled_plugins=[]),
                    body=payload,
                ),
                timeout=min(float(svc.stream_capture_timeout_s or svc.wait_timeout_s or 60.0), 60.0),
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="service_chat_contextual_model_timeout")
        choices = response.get("choices") if isinstance(response.get("choices"), list) else []
        first = choices[0] if choices else {}
        message = first.get("message") if isinstance(first, dict) else {}
        text_out = str((message or {}).get("content") or "").strip()
        if str(answer_style or "default").strip().lower() == "authoring" and _looks_like_overcautious_current_context_authoring_answer(prompt, text_out):
            text_out = _structured_current_context_fallback_answer(prompt, cleaned_research)
        if str(answer_style or "default").strip().lower() == "authoring" and _looks_like_unsupported_current_context_specifics(text_out, cleaned_research):
            text_out = _structured_current_context_fallback_answer(prompt, cleaned_research)
        if str(answer_style or "default").strip().lower() == "authoring" and (_looks_like_authoring_frame_drift(prompt, text_out) or _looks_like_chatty_authoring_answer(text_out)):
            text_out = _structured_current_context_fallback_answer(prompt, cleaned_research)
        text_out = _apply_requested_answer_shape(prompt, text_out)
        assistant = _service_assistant_message(
            db,
            pid,
            sid,
            text_out,
            client_msg_id=str(svc.client_msg_id or ""),
            meta={"service_direct_model_with_context": True, "service_context_label": context_label},
        )
        return {
            "mode": "chat",
            "router_enabled_plugins": [],
            "stream": {"text": text_out, "done": {"ok": True, "msg_id": str(assistant.get("msg_id") or "")}, "diag": {"direct_model_with_context": True}},
            "assistant_message": assistant,
        }

    async def _run_direct_model_with_research_context_timed(pid: str, sid: str, prompt: str, svc: ServiceChatRequest, request: Request, *, research_text: str, context_label: str = "current research context", answer_style: str = "default", timeout_s: float = 18.0) -> Dict[str, Any]:
        return await asyncio.wait_for(
            _run_direct_model_with_research_context(
                pid,
                sid,
                prompt,
                svc,
                request,
                research_text=research_text,
                context_label=context_label,
                answer_style=answer_style,
            ),
            timeout=float(timeout_s or 18.0),
        )

    async def _run_direct_model_authoring_without_research(pid: str, sid: str, prompt: str, svc: ServiceChatRequest, request: Request, *, framing_note: str = "") -> Dict[str, Any]:
        low_prompt = str(prompt or '').strip().lower()
        should_force_structured_fallback = (
            any(tok in low_prompt for tok in ('project', 'proposal', 'presentation', 'powerpoint', 'slides', 'structure', 'outline'))
            and not _looks_like_explanatory_choice_or_compare(prompt)
        )
        if should_force_structured_fallback:
            text_out = _structured_authoring_fallback_answer(prompt)
            assistant = _service_assistant_message(
                db,
                pid,
                sid,
                text_out,
                client_msg_id=str(svc.client_msg_id or ""),
                meta={"service_direct_authoring_structured_fallback": True},
            )
            return {
                "mode": "chat",
                "router_enabled_plugins": [],
                "stream": {"text": text_out, "done": {"ok": True, "msg_id": str(assistant.get("msg_id") or "")}, "diag": {"direct_authoring_structured_fallback": True}},
                "assistant_message": assistant,
            }
        if not _service_ensure_text_model(app):
            raise HTTPException(status_code=503, detail="chat_model_not_loaded")
        note = str(framing_note or "").strip()
        payload = {
            "model": "",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are helping with a drafting or project-building request. Draft the requested outline, proposal, plan, deck structure, essay framework, or project design directly. Start with the deliverable itself, not praise or commentary about the request. "
                        "Preserve the user's requested topic, scope, assignment type, and framing. "
                        "If exact current facts or figures are uncertain, keep the answer useful by marking those items as things to verify or update rather than inventing precision. Keep the tone practical and concise. Avoid emojis, filler praise, and overly decorative formatting. "
                        "Do not mention internal tools, workflows, routing, or research-process details."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"User request:\n{str(prompt or '').strip()}\n\n"
                        + (f"Extra guidance:\n{note}\n\n" if note else "")
                        + "Write the final answer for the user now. Keep it concrete, useful, and ready to send."
                    ),
                },
            ],
            "backend_type": "auto",
            "stream": False,
            "router_enabled_plugins": [],
            "ext": {
                "project_id": pid,
                "session_id": sid,
                "session-id": sid,
                "sid": sid,
            },
            "sid": sid,
        }
        if svc.temperature is not None:
            payload["temperature"] = svc.temperature
        if svc.max_tokens is not None:
            payload["max_tokens"] = svc.max_tokens
        if svc.top_p is not None:
            payload["top_p"] = svc.top_p
        try:
            response = await asyncio.wait_for(
                _internal_json_request(
                    app,
                    method="POST",
                    path="/v1/chat/completions",
                    headers=_internal_service_headers(request, pid=pid, sid=sid, enabled_plugins=[]),
                    body=payload,
                ),
                timeout=min(float(svc.stream_capture_timeout_s or svc.wait_timeout_s or 45.0), 45.0),
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="service_chat_direct_authoring_timeout")
        except HTTPException as exc:
            if int(getattr(exc, "status_code", 0) or 0) not in (500, 502, 503, 504):
                raise
            text_out = _structured_authoring_fallback_answer(prompt)
            assistant = _service_assistant_message(
                db,
                pid,
                sid,
                text_out,
                client_msg_id=str(svc.client_msg_id or ""),
                meta={"service_direct_authoring_structured_fallback": True, "service_direct_authoring_model_unavailable": True},
            )
            return {
                "mode": "chat",
                "router_enabled_plugins": [],
                "stream": {"text": text_out, "done": {"ok": True, "msg_id": str(assistant.get("msg_id") or "")}, "diag": {"direct_authoring_structured_fallback": True, "model_unavailable": True}},
                "assistant_message": assistant,
            }
        choices = response.get("choices") if isinstance(response.get("choices"), list) else []
        first = choices[0] if choices else {}
        message = first.get("message") if isinstance(first, dict) else {}
        text_out = str((message or {}).get("content") or "").strip()
        if _looks_like_authoring_frame_drift(prompt, text_out) or _looks_like_chatty_authoring_answer(text_out):
            text_out = _structured_authoring_fallback_answer(prompt)
        text_out = _apply_requested_answer_shape(prompt, text_out)
        assistant = _service_assistant_message(
            db,
            pid,
            sid,
            text_out,
            client_msg_id=str(svc.client_msg_id or ""),
            meta={"service_direct_authoring_without_research": True},
        )
        return {
            "mode": "chat",
            "router_enabled_plugins": [],
            "stream": {"text": text_out, "done": {"ok": True, "msg_id": str(assistant.get("msg_id") or "")}, "diag": {"direct_authoring_without_research": True}},
            "assistant_message": assistant,
        }


    async def _run_direct_model_answer_without_history(pid: str, sid: str, prompt: str, svc: ServiceChatRequest, request: Request, *, framing_note: str = "") -> Dict[str, Any]:
        if not _service_ensure_text_model(app):
            raise HTTPException(status_code=503, detail="chat_model_not_loaded")
        note = str(framing_note or "").strip()
        payload = {
            "model": "",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Answer the user's latest request directly and only from the latest request content. "
                        "Do not rely on earlier conversation turns unless the latest request explicitly refers to them. "
                        "Be concise, accurate, and practical. Avoid mentioning internal tools, workflows, routing, or research-process details."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Latest user request:\n{str(prompt or '').strip()}\n\n"
                        + (f"Extra guidance:\n{note}\n\n" if note else "")
                        + "Write the final answer for the user now."
                    ),
                },
            ],
            "backend_type": "auto",
            "stream": False,
            "router_enabled_plugins": [],
            "ext": {
                "project_id": pid,
                "session_id": sid,
                "session-id": sid,
                "sid": sid,
            },
            "sid": sid,
        }
        if svc.temperature is not None:
            payload["temperature"] = svc.temperature
        if svc.max_tokens is not None:
            payload["max_tokens"] = svc.max_tokens
        if svc.top_p is not None:
            payload["top_p"] = svc.top_p
        try:
            response = await asyncio.wait_for(
                _internal_json_request(
                    app,
                    method="POST",
                    path="/v1/chat/completions",
                    headers=_internal_service_headers(request, pid=pid, sid=sid, enabled_plugins=[]),
                    body=payload,
                ),
                timeout=min(float(svc.stream_capture_timeout_s or svc.wait_timeout_s or 45.0), 45.0),
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="service_chat_direct_answer_timeout")
        choices = response.get("choices") if isinstance(response.get("choices"), list) else []
        first = choices[0] if choices else {}
        message = first.get("message") if isinstance(first, dict) else {}
        text_out = _strip_reasoning_artifacts(str((message or {}).get("content") or "")).strip()
        if not text_out:
            raise HTTPException(status_code=504, detail="service_chat_direct_answer_timeout")
        assistant = _service_assistant_message(
            db,
            pid,
            sid,
            text_out,
            client_msg_id=str(svc.client_msg_id or ""),
            meta={"service_direct_answer_without_history": True},
        )
        return {
            "mode": "chat",
            "router_enabled_plugins": [],
            "stream": {"text": text_out, "done": {"ok": True, "msg_id": str(assistant.get("msg_id") or "")}, "diag": {"direct_answer_without_history": True}},
            "assistant_message": assistant,
        }

    def _autoflow_wrap_direct_result(result: Dict[str, Any], *, flow_name: str, reason: str, candidate: Optional[Dict[str, Any]] = None, run_kind: str = "inline_builtin") -> Dict[str, Any]:
        out = dict(result or {})
        assistant = out.get("assistant_message") if isinstance(out.get("assistant_message"), dict) else {}
        assistant_text = _strip_reasoning_artifacts(str((assistant or {}).get("content") or "")).strip()
        state = out.get("state") if isinstance(out.get("state"), dict) else {}
        final_result = str(state.get("final_result") or assistant_text or "").strip()
        out["flow_name"] = str(flow_name or "").strip()
        out["run"] = {
            "ok": True,
            "inline_builtin": True,
            "flow_name": str(flow_name or "").strip(),
            "kind": str(run_kind or "inline_builtin"),
        }
        out["state"] = {
            **state,
            "running": False,
            "status": "Completed",
            "final_result": final_result,
            "final_result_mode": "text",
        }
        out["autoflow"] = {
            "selected_flow": str(flow_name or "").strip(),
            "flow_name": str(flow_name or "").strip(),
            "source": "builtin",
            "reason": str(reason or "builtin_direct_fast_path"),
            "candidates": [candidate] if isinstance(candidate, dict) and candidate else [],
        }
        return out

    async def _run_autoflow_builtin_direct_answer(pid: str, sid: str, prompt: str, svc: ServiceChatRequest, router_cfg: Dict[str, Any], request: Request, *, flow_name: str, candidate: Optional[Dict[str, Any]] = None, reason: str = "") -> Dict[str, Any]:
        builtin_name = str(flow_name or "").strip()
        if builtin_name == "__autoflow_builtin_general_answer__":
            if _looks_like_explanatory_choice_or_compare(prompt):
                direct = await _run_direct_model_answer_without_history(
                    pid,
                    sid,
                    prompt,
                    svc,
                    request,
                    framing_note="Answer the comparison directly based on the latest request only.",
                )
                return _autoflow_wrap_direct_result(
                    direct,
                    flow_name=builtin_name,
                    reason=reason,
                    candidate=candidate,
                    run_kind="direct_model_only",
                )
            if _looks_like_structured_authoring_request(prompt) or _looks_like_direct_text_generation(prompt):
                direct = await _run_direct_model_authoring_without_research(
                    pid,
                    sid,
                    prompt,
                    svc,
                    request,
                    framing_note="Start directly with the requested deliverable. Preserve the user's topic, scope, and framing.",
                )
                return _autoflow_wrap_direct_result(
                    direct,
                    flow_name=builtin_name,
                    reason=reason,
                    candidate=candidate,
                    run_kind="direct_model_authoring",
                )
            direct = await _run_direct_model_answer_without_history(
                pid,
                sid,
                prompt,
                svc,
                request,
                framing_note="Answer the user's latest question directly and do not carry forward stale topic context from earlier turns.",
            )
            return _autoflow_wrap_direct_result(
                direct,
                flow_name=builtin_name,
                reason=reason,
                candidate=candidate,
                run_kind="direct_model_standard",
            )
        if builtin_name != "__autoflow_builtin_current_context_answer__":
            raise HTTPException(status_code=400, detail="unsupported_autoflow_builtin_direct_answer")
        research_runner = _load_skill_runner("custom.awf_web_research__web_research_204fb17b_executor")
        research_text = ""
        research_result: Dict[str, Any] = {}
        if callable(research_runner):
            raw_research = research_runner({
                "app": app,
                "original_request": prompt,
                "user_text": prompt,
                "project_id": pid,
                "session_id": sid,
                "sid": sid,
            }, {
                "request_text": prompt,
                "query": prompt,
                "text": prompt,
                "timeout": 8.0,
                "max_results": 6,
            })
            research_result = raw_research if isinstance(raw_research, dict) else {"ok": bool(raw_research), "text": str(raw_research or "")}
            research_text = _web_research_context_text(research_result, max_items=5)
            if not research_text:
                for key in ("final_answer", "summary", "text", "response", "content"):
                    value = str(research_result.get(key) or "").strip()
                    if value:
                        research_text = value
                        break
        if research_text.strip():
            if _looks_like_identity_verification_failure(prompt, research_text) or _looks_like_failed_current_context(research_text):
                if not _looks_like_current_context_authoring(prompt):
                    assistant = _service_assistant_message(
                        db,
                        pid,
                        sid,
                        research_text,
                        client_msg_id=str(svc.client_msg_id or ""),
                        meta={"service_context_direct_response": True, "autoflow_builtin_current_context_answer": True},
                    )
                    return _autoflow_wrap_direct_result(
                        {"mode": "chat", "assistant_message": assistant},
                        flow_name=builtin_name,
                        reason=reason,
                        candidate=candidate,
                        run_kind="builtin_web_research_direct",
                    )
                authored = await _run_direct_model_authoring_without_research(
                    pid,
                    sid,
                    prompt,
                    svc,
                    request,
                    framing_note="If current web lookups are unavailable, still draft the requested deliverable and mark exact live facts as items to verify rather than refusing the task.",
                )
                return _autoflow_wrap_direct_result(
                    authored,
                    flow_name=builtin_name,
                    reason=reason,
                    candidate=candidate,
                    run_kind="direct_authoring_fallback",
                )
            if _looks_like_macro_fact_research_answer(prompt, research_text):
                macro_answer = _macro_fact_answer_only(research_text) or research_text
                assistant = _service_assistant_message(
                    db,
                    pid,
                    sid,
                    macro_answer,
                    client_msg_id=str(svc.client_msg_id or ""),
                    meta={"service_context_direct_response": True, "autoflow_builtin_current_context_answer": True, "current_context_macro_fact_direct": True},
                )
                return _autoflow_wrap_direct_result(
                    {"mode": "chat", "assistant_message": assistant},
                    flow_name=builtin_name,
                    reason=reason,
                    candidate=candidate,
                    run_kind="builtin_web_research_direct",
                )
            if _looks_like_current_context_authoring(prompt):
                if _research_scope_too_narrow_for_prompt(prompt, research_text):
                    assistant_text = _structured_current_context_fallback_answer(prompt, research_text)
                    assistant = _service_assistant_message(
                        db,
                        pid,
                        sid,
                        assistant_text,
                        client_msg_id=str(svc.client_msg_id or ""),
                        meta={"service_context_fallback": True, "service_context_scope_guard": True, "autoflow_builtin_current_context_answer": True},
                    )
                    return _autoflow_wrap_direct_result(
                        {"mode": "chat", "assistant_message": assistant},
                        flow_name=builtin_name,
                        reason=reason,
                        candidate=candidate,
                        run_kind="context_scope_guard",
                    )
                try:
                    contextual = await _run_direct_model_with_research_context_timed(
                        pid,
                        sid,
                        prompt,
                        svc,
                        request,
                        research_text=research_text,
                        context_label="current research context",
                        answer_style="authoring",
                    )
                except HTTPException as exc:
                    if int(getattr(exc, "status_code", 0) or 0) not in (500, 502, 503, 504):
                        raise
                    fallback_text = _structured_current_context_fallback_answer(prompt, research_text)
                    fallback_assistant = _service_assistant_message(
                        db,
                        pid,
                        sid,
                        fallback_text,
                        client_msg_id=str(svc.client_msg_id or ""),
                        meta={"service_context_fallback": True, "autoflow_builtin_current_context_answer": True, "context_timeout_fallback": True},
                    )
                    return _autoflow_wrap_direct_result(
                        {"mode": "chat", "assistant_message": fallback_assistant},
                        flow_name=builtin_name,
                        reason=reason,
                        candidate=candidate,
                        run_kind="context_timeout_fallback",
                    )
                except Exception:
                    fallback_text = _structured_current_context_fallback_answer(prompt, research_text)
                    fallback_assistant = _service_assistant_message(
                        db,
                        pid,
                        sid,
                        fallback_text,
                        client_msg_id=str(svc.client_msg_id or ""),
                        meta={"service_context_fallback": True, "autoflow_builtin_current_context_answer": True, "context_timeout_fallback": True},
                    )
                    return _autoflow_wrap_direct_result(
                        {"mode": "chat", "assistant_message": fallback_assistant},
                        flow_name=builtin_name,
                        reason=reason,
                        candidate=candidate,
                        run_kind="context_timeout_fallback",
                    )
                contextual_assistant = contextual.get("assistant_message") if isinstance(contextual, dict) else None
                contextual_text = str((contextual_assistant or {}).get("content") or "").strip() if isinstance(contextual_assistant, dict) else ""
                low_contextual_text = contextual_text.lower()
                if (
                    (contextual_text and _looks_like_overcautious_current_context_authoring_answer(prompt, contextual_text))
                    or (contextual_text and _looks_like_authoring_frame_drift(prompt, contextual_text))
                    or (contextual_text and _looks_like_chatty_authoring_answer(contextual_text))
                    or low_contextual_text.startswith("based on the provided evidence, i cannot")
                    or low_contextual_text.startswith("i cannot construct a complete project")
                    or (_looks_like_structured_authoring_request(prompt) and contextual_text and "## " not in contextual_text and "**working topic**" not in low_contextual_text)
                ):
                    fallback_text = _structured_current_context_fallback_answer(prompt, research_text)
                    fallback_assistant = _service_assistant_message(
                        db,
                        pid,
                        sid,
                        fallback_text,
                        client_msg_id=str(svc.client_msg_id or ""),
                        meta={"service_context_fallback": True, "autoflow_builtin_current_context_answer": True, "service_context_scope_guard": True},
                    )
                    return _autoflow_wrap_direct_result(
                        {"mode": "chat", "assistant_message": fallback_assistant},
                        flow_name=builtin_name,
                        reason=reason,
                        candidate=candidate,
                        run_kind="context_structured_fallback",
                    )
                return _autoflow_wrap_direct_result(
                    contextual,
                    flow_name=builtin_name,
                    reason=reason,
                    candidate=candidate,
                    run_kind="direct_model_with_context",
                )
            limited_direct_answer = _structured_limited_current_context_answer(prompt, research_result, research_text)
            if limited_direct_answer:
                assistant = _service_assistant_message(
                    db,
                    pid,
                    sid,
                    limited_direct_answer,
                    client_msg_id=str(svc.client_msg_id or ""),
                    meta={"service_context_direct_response": True, "autoflow_builtin_current_context_answer": True, "current_context_limited_synthesis": True},
                )
                return _autoflow_wrap_direct_result(
                    {"mode": "chat", "assistant_message": assistant},
                    flow_name=builtin_name,
                    reason=reason,
                    candidate=candidate,
                    run_kind="limited_current_context_synthesis",
                )
            try:
                contextual = await _run_direct_model_with_research_context_timed(
                    pid,
                    sid,
                    prompt,
                    svc,
                    request,
                    research_text=research_text,
                    context_label="current research context",
                    answer_style="current_context_explanatory",
                )
                return _autoflow_wrap_direct_result(
                    contextual,
                    flow_name=builtin_name,
                    reason=reason,
                    candidate=candidate,
                    run_kind="direct_model_with_context",
                )
            except HTTPException as exc:
                if int(getattr(exc, "status_code", 0) or 0) not in (500, 502, 503, 504):
                    raise
                fallback_text = _structured_limited_current_context_answer(prompt, research_result, research_text) or research_text
                assistant = _service_assistant_message(
                    db,
                    pid,
                    sid,
                    fallback_text,
                    client_msg_id=str(svc.client_msg_id or ""),
                    meta={"service_context_direct_response": True, "autoflow_builtin_current_context_answer": True, "current_context_limited_synthesis": True},
                )
                return _autoflow_wrap_direct_result(
                    {"mode": "chat", "assistant_message": assistant},
                    flow_name=builtin_name,
                    reason=reason,
                    candidate=candidate,
                    run_kind="limited_current_context_synthesis",
                )
        authored = await _run_direct_model_authoring_without_research(
            pid,
            sid,
            prompt,
            svc,
            request,
            framing_note="If the request depends on current conditions, keep the answer useful and mark exact live facts as items to verify rather than inventing them.",
        )
        return _autoflow_wrap_direct_result(
            authored,
            flow_name=builtin_name,
            reason=reason,
            candidate=candidate,
            run_kind="direct_authoring_fallback",
        )

    async def _run_standard_service_turn(pid: str, sid: str, prompt: str, svc: ServiceChatRequest, router_cfg: Dict[str, Any], request: Request, *, direct_model_only: bool = False, text_model_prechecked: bool = False) -> Dict[str, Any]:
        previous_assistant = None if direct_model_only else _latest_assistant_message(db, pid, sid)
        previous_msg_id = str((previous_assistant or {}).get("msg_id") or "").strip() if isinstance(previous_assistant, dict) else ""
        previous_ts = int((previous_assistant or {}).get("ts") or 0) if isinstance(previous_assistant, dict) else 0
        direct_messages = ([{"role": "user", "content": str(prompt or "")}]
            if direct_model_only
            else _build_completion_messages_for_session(
                db,
                pid=pid,
                sid=sid,
                prompt=prompt,
                limit=120,
                skip_internal_assistant_trace=False,
            ))
        payload = {
            "model": "",
            "messages": direct_messages,
            "backend_type": "auto",
            "stream": True,
            "router_enabled_plugins": [] if direct_model_only else list(router_cfg.get("enabled") or []),
            "ext": {
                "project_id": pid,
                "session_id": sid,
                "session-id": sid,
                "sid": sid,
            },
            "sid": sid,
        }
        settings_map = router_cfg.get("settings") if isinstance(router_cfg.get("settings"), dict) else {}
        if settings_map:
            payload["ext"]["router_plugin_settings"] = settings_map
        if svc.temperature is not None:
            payload["temperature"] = svc.temperature
        if svc.max_tokens is not None:
            payload["max_tokens"] = svc.max_tokens
        if svc.top_p is not None:
            payload["top_p"] = svc.top_p
        if direct_model_only:
            payload["stream"] = False
            if (not text_model_prechecked) and (not _service_ensure_text_model(app)):
                raise HTTPException(status_code=503, detail="chat_model_not_loaded")
            direct_headers = _internal_service_headers(request, pid=pid, sid=sid, enabled_plugins=[])
            direct_timeout = min(float(svc.stream_capture_timeout_s or svc.wait_timeout_s or 45.0), 45.0)
            try:
                response = await asyncio.wait_for(
                    _internal_json_request(
                        app,
                        method="POST",
                        path="/v1/chat/completions",
                        headers=direct_headers,
                        body=payload,
                    ),
                    timeout=direct_timeout,
                )
                choices = response.get("choices") if isinstance(response.get("choices"), list) else []
                first = choices[0] if choices else {}
                message = first.get("message") if isinstance(first, dict) else {}
                text_out = str((message or {}).get("content") or "").strip()
            except asyncio.TimeoutError:
                text_out = ""
                response = {}
            except Exception:
                text_out = ""
                response = {}
            if not text_out or text_out == str(prompt or "").strip():
                stream_payload = dict(payload)
                stream_payload["stream"] = True
                try:
                    stream = await _internal_sse_request(
                        app,
                        method="POST",
                        path="/v1/chat/completions_stream",
                        headers=direct_headers,
                        body=stream_payload,
                        timeout_s=float(svc.stream_capture_timeout_s or svc.wait_timeout_s or 45.0),
                    )
                    stream_text = _repair_common_mojibake(str(((stream.get("text") if isinstance(stream, dict) else "") or ""))).strip()
                    if stream_text and stream_text != str(prompt or "").strip():
                        text_out = stream_text
                except Exception:
                    pass
            if not text_out:
                raise HTTPException(status_code=504, detail="service_chat_direct_model_timeout")
            assistant = _service_assistant_message(
                db,
                pid,
                sid,
                text_out,
                client_msg_id=str(svc.client_msg_id or ""),
                meta={"service_direct_model_only": True},
            )
            return {
                "mode": "chat",
                "router_enabled_plugins": [],
                "stream": {"text": text_out, "done": {"ok": True, "msg_id": str(assistant.get("msg_id") or "")}, "diag": {"direct_model_only": True}},
                "assistant_message": assistant,
            }
        headers = _internal_service_headers(request, pid=pid, sid=sid, enabled_plugins=payload["router_enabled_plugins"])
        stream = await _internal_sse_request(
            app,
            method="POST",
            path="/v1/chat/completions_stream",
            headers=headers,
            body=payload,
            timeout_s=float(svc.stream_capture_timeout_s or svc.wait_timeout_s or 90.0),
        )
        latest = _latest_assistant_message_after(
            db,
            pid,
            sid,
            previous_msg_id=previous_msg_id,
            previous_ts=previous_ts,
        )
        if isinstance(latest, dict):
            latest_msg_id = str(latest.get("msg_id") or "").strip()
            latest_ts = int(latest.get("ts") or 0)
            if (previous_msg_id and latest_msg_id == previous_msg_id) or (previous_ts and latest_ts <= previous_ts):
                latest = None
        if not isinstance(latest, dict):
            stream_text = str((stream or {}).get("text") or "").strip()
            done_meta = (stream or {}).get("done") if isinstance((stream or {}).get("done"), dict) else {}
            diag_meta = (stream or {}).get("diag") if isinstance((stream or {}).get("diag"), dict) else {}
            final_result_text = stream_text
            state_error = str(done_meta.get("error") or diag_meta.get("error") or "").strip()
            if final_result_text:
                latest = _service_assistant_message(
                    db,
                    pid,
                    sid,
                    final_result_text,
                    client_msg_id=str(svc.client_msg_id or ""),
                    meta={"service_result_proxy": True, "service_flow_only": True},
                )
            elif state_error:
                latest = _service_assistant_message(
                    db,
                    pid,
                    sid,
                    f"The assistant backend failed during this turn: {state_error}",
                    client_msg_id=str(svc.client_msg_id or ""),
                    meta={"service_flow_error": True},
                )
        return {
            "mode": "chat",
            "router_enabled_plugins": payload["router_enabled_plugins"],
            "stream": stream,
            "assistant_message": latest,
        }

    async def _run_agent_flow_service_turn(pid: str, sid: str, prompt: str, svc: ServiceChatRequest, router_cfg: Dict[str, Any], request: Request, *, flow_name: str, flow_def: Optional[Dict[str, Any]] = None, temp_skill_dirs: Optional[List[str]] = None) -> Dict[str, Any]:
        previous_assistant = _latest_assistant_message(db, pid, sid)
        previous_msg_id = str((previous_assistant or {}).get("msg_id") or "").strip() if isinstance(previous_assistant, dict) else ""
        previous_ts = int((previous_assistant or {}).get("ts") or 0) if isinstance(previous_assistant, dict) else 0
        flows_payload = await _internal_json_request(
            app,
            method="GET",
            path=f"/v1/projects/{pid}/sessions/{sid}/agent_flow/flows",
            headers=_internal_service_headers(request, pid=pid, sid=sid, enabled_plugins=["agent_flow"]),
        )
        flows = flows_payload.get("flows") if isinstance(flows_payload.get("flows"), dict) else {}
        runtime_flow_name = str(flow_name or "").strip()
        runtime_flow_def = flow_def if isinstance(flow_def, dict) else flows.get(runtime_flow_name)
        if not runtime_flow_name or not isinstance(runtime_flow_def, dict):
            raise HTTPException(status_code=400, detail="service_chat_flow_not_found")
        enabled = set(str(x or "").strip() for x in (router_cfg.get("enabled") or []) if str(x or "").strip())
        enabled.add("agent_flow")
        nodes = runtime_flow_def.get("nodes") if isinstance(runtime_flow_def.get("nodes"), dict) else {}
        for node in nodes.values():
            plugin_id = str((node or {}).get("plugin_id") or "").strip()
            if plugin_id:
                enabled.add(plugin_id)
        agent_settings = router_cfg.get("settings", {}).get("agent_flow") if isinstance(router_cfg.get("settings", {}).get("agent_flow"), dict) else {}
        ext = {
            "project_id": pid,
            "session_id": sid,
            "session-id": sid,
            "sid": sid,
            "base_url": str(request.base_url).rstrip("/"),
            "agent_flow_flows": dict(flows or {}),
            "agent_flow_active_flow": runtime_flow_name,
            "agent_flow_default_flow": str(agent_settings.get("agent_flow_default_flow") or runtime_flow_name),
            "agent_flow_max_steps": int(agent_settings.get("agent_flow_max_steps") or 8),
            "agent_flow_enabled_plugins": sorted(enabled),
        }
        if runtime_flow_name not in ext["agent_flow_flows"] or flow_def is not None:
            ext["agent_flow_flows"][runtime_flow_name] = runtime_flow_def
            ext["agent_flow_force_runtime_flow"] = True
        if temp_skill_dirs:
            ext["agent_flow_temp_skill_dirs"] = [str(x or "").strip() for x in temp_skill_dirs if str(x or "").strip()]
        if runtime_flow_name.startswith("__autoflow_builtin_"):
            ext["agent_flow_disable_temp_skill_inference"] = True
        if isinstance(router_cfg.get("settings"), dict) and router_cfg.get("settings"):
            ext["router_plugin_settings"] = dict(router_cfg.get("settings") or {})
        for key in (
            "agent_flow_autobuild_sandbox_profile",
            "agent_flow_autobuild_lightweight_max_requests",
            "agent_flow_autobuild_lightweight_wait_s",
            "agent_flow_autobuild_lightweight_final_grace_s",
            "agent_flow_autobuild_independent_max_requests",
            "agent_flow_autobuild_independent_wait_s",
            "agent_flow_autobuild_independent_final_grace_s",
        ):
            if key in agent_settings:
                ext[key] = agent_settings.get(key)
        headers = _internal_service_headers(request, pid=pid, sid=sid, enabled_plugins=sorted(enabled))
        run = await _internal_json_request(
            app,
            method="POST",
            path=f"/v1/projects/{pid}/sessions/{sid}/agent_flow/run",
            headers=headers,
            body={"text": prompt, "client_msg_id": str(svc.client_msg_id or ""), "ext": ext},
        )
        run_id = str(run.get("run_id") or "").strip()
        wait_timeout_s = float(svc.wait_timeout_s or 90.0)
        if runtime_flow_name == "__autoflow_builtin_general_answer__" and wait_timeout_s < 150.0:
            wait_timeout_s = 150.0
        state = await _wait_for_agent_flow_completion(pid, sid, run_id, headers, wait_timeout_s) if run_id else {}
        latest = _latest_assistant_message_after(
            db,
            pid,
            sid,
            previous_msg_id=previous_msg_id,
            previous_ts=previous_ts,
        )
        if not isinstance(latest, dict):
            final_result_text = str((state or {}).get("final_result") or "").strip()
            state_error = str((state or {}).get("error") or "").strip()
            if final_result_text:
                latest = _service_assistant_message(
                    db,
                    pid,
                    sid,
                    final_result_text,
                    client_msg_id=str(svc.client_msg_id or ""),
                    meta={"service_result_proxy": True, "service_flow_only": True},
                )
            elif state_error:
                latest = _service_assistant_message(
                    db,
                    pid,
                    sid,
                    f"The assistant backend failed during this turn: {state_error}",
                    client_msg_id=str(svc.client_msg_id or ""),
                    meta={"service_flow_error": True},
                )
        return {
            "mode": "agent_flow",
            "flow_name": runtime_flow_name,
            "run": run,
            "state": state,
            "assistant_message": latest,
        }

    async def _run_autoflow_service_turn(pid: str, sid: str, prompt: str, svc: ServiceChatRequest, router_cfg: Dict[str, Any], request: Request) -> Dict[str, Any]:
        settings_map = router_cfg.get("settings") if isinstance(router_cfg.get("settings"), dict) else {}
        autoflow_cfg = settings_map.get("autoflow") if isinstance(settings_map.get("autoflow"), dict) else {}
        configured_retry_loops = max(1, int(autoflow_cfg.get("autoflow_retry_loops") or 2))
        require_judge = autoflow_cfg.get("autoflow_require_satisfaction_check", True) is not False
        create_enabled = autoflow_cfg.get("autoflow_create_if_request_not_satisfied") is True
        retry_loops = max(3, configured_retry_loops) if create_enabled else configured_retry_loops
        attempts: List[Dict[str, Any]] = []
        avoid_flows: List[str] = []
        avoid_generated_record_ids: List[str] = []
        last_result: Dict[str, Any] = {
            "mode": "autoflow",
            "autoflow": {},
            "assistant_message": _latest_assistant_message(db, pid, sid),
        }

        direct_pick = _local_builtin_candidate(prompt)
        direct_flow_name = str((direct_pick.get("name") if isinstance(direct_pick, dict) else "") or "").strip()
        if direct_flow_name:
            if direct_flow_name in {"__autoflow_builtin_general_answer__", "__autoflow_builtin_current_context_answer__"}:
                direct_result = await _run_autoflow_builtin_direct_answer(
                    pid,
                    sid,
                    prompt,
                    svc,
                    router_cfg,
                    request,
                    flow_name=direct_flow_name,
                    candidate=direct_pick,
                    reason=str(direct_pick.get("reason") or "builtin_direct_fast_path"),
                )
                if isinstance(direct_result, dict):
                    direct_result["autoflow"] = direct_pick
                    return direct_result
            inline_result = await _run_builtin_candidate_result(pid, sid, prompt, svc, direct_pick, router_cfg, request)
            if isinstance(inline_result, dict):
                return inline_result

        async def _run_builtin_autoflow_candidate(candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            flow_name = str((candidate.get("selected_flow") or candidate.get("flow_name") or candidate.get("name") or "")).strip()
            if not flow_name.startswith("__autoflow_builtin_"):
                return None
            if flow_name in {"__autoflow_builtin_general_answer__", "__autoflow_builtin_current_context_answer__"}:
                result = await _run_autoflow_builtin_direct_answer(
                    pid,
                    sid,
                    prompt,
                    svc,
                    router_cfg,
                    request,
                    flow_name=flow_name,
                    candidate=candidate,
                    reason=str(candidate.get("reason") or "builtin_direct_fast_path"),
                )
                if isinstance(result, dict):
                    result["autoflow"] = candidate
                return result
            inline_candidate = dict(candidate)
            if not str(inline_candidate.get("name") or "").strip():
                inline_candidate["name"] = flow_name
            result = await _run_builtin_candidate_result(pid, sid, prompt, svc, inline_candidate, router_cfg, request)
            if isinstance(result, dict):
                result["autoflow"] = candidate
            return result if isinstance(result, dict) else None

        flows: Dict[str, Any] = {}

        async def _ensure_flows_loaded() -> Dict[str, Any]:
            nonlocal flows
            if flows:
                return flows
            flows_payload = await _internal_json_request(
                app,
                method="GET",
                path=f"/v1/projects/{pid}/sessions/{sid}/agent_flow/flows",
                headers=_internal_service_headers(request, pid=pid, sid=sid, enabled_plugins=["agent_flow", "autoflow"]),
            )
            flows = flows_payload.get("flows") if isinstance(flows_payload.get("flows"), dict) else {}
            return flows

        def _clip(text: Any, limit: int = 72) -> str:
            raw = str(text or "").strip()
            if len(raw) <= limit:
                return raw
            return raw[: max(0, limit - 3)].rstrip() + "..."

        def _emit_status(*lines: Any) -> Dict[str, Any]:
            body = "\n".join(str(line or "").strip() for line in lines if str(line or "").strip())
            msg_id = secrets.token_hex(12)
            ts = _now_ts()
            meta = {"flow": True}
            if svc.client_msg_id:
                meta["client_msg_id"] = str(svc.client_msg_id)
            db.add_message(
                msg_id=msg_id,
                pid=pid,
                sid=sid,
                role="assistant",
                kind="model",
                author_username="assistant",
                author_alias="assistant",
                content=body,
                meta=meta,
            )
            return {
                "msg_id": msg_id,
                "pid": pid,
                "sid": sid,
                "ts": ts,
                "role": "assistant",
                "kind": "model",
                "author_username": "assistant",
                "author_alias": "assistant",
                "content": body,
                "meta": meta,
            }

        async def _call_autoflow(mode: str, *, request_plan: Optional[Dict[str, Any]] = None, flow_result_text: str = "", flow_name: str = "", flow_result_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
            if mode != "select" or create_enabled:
                await _ensure_flows_loaded()
            ext = {
                "agent_flow_flows": flows,
                "last_user_content": prompt,
                "autoflow_settings": autoflow_cfg,
                "autoflow_mode": str(mode or "select").strip(),
                "project_id": pid,
                "session_id": sid,
                "session-id": sid,
                "sid": sid,
            }
            if avoid_flows:
                ext["autoflow_avoid_flows"] = list(avoid_flows)
            if avoid_generated_record_ids:
                ext["autoflow_avoid_generated_record_ids"] = list(avoid_generated_record_ids)
            if attempts:
                ext["autoflow_attempts"] = [dict(x) for x in attempts if isinstance(x, dict)]
            if request_plan:
                ext["autoflow_request_plan"] = dict(request_plan)
            if flow_result_text:
                ext["autoflow_flow_result_text"] = str(flow_result_text)
            if flow_name:
                ext["autoflow_flow_name"] = str(flow_name)
            if isinstance(flow_result_meta, dict) and flow_result_meta:
                ext["autoflow_flow_result_meta"] = dict(flow_result_meta)
            if settings_map:
                ext["router_plugin_settings"] = settings_map
            select_res = await _internal_sse_request(
                app,
                method="POST",
                path="/v1/chat/completions_stream",
                headers=_internal_service_headers(request, pid=pid, sid=sid, enabled_plugins=["autoflow", "agent_flow"], suppress_persist=True),
                body={
                    "model": "",
                    "messages": [{"role": "user", "content": prompt}],
                    "backend_type": "auto",
                    "route_id": "autoflow",
                    "router_enabled_plugins": ["autoflow"],
                    "ext": ext,
                    "sid": sid,
                },
                timeout_s=240.0,
            )
            rr = {}
            if isinstance(select_res, dict):
                router_evt = select_res.get("router") if isinstance(select_res.get("router"), dict) else {}
                rr = router_evt.get("router_result") if isinstance(router_evt.get("router_result"), dict) else {}
            return rr if isinstance(rr, dict) else {}

        creator_name = str(autoflow_cfg.get("autoflow_creator_flow_name") or "Flow Creator / Adaptive Loop").strip() or "Flow Creator / Adaptive Loop"
        if not create_enabled:
            quick_rr = await _call_autoflow("select")
            quick_flow = str(quick_rr.get("selected_flow") or quick_rr.get("flow_name") or "").strip() if isinstance(quick_rr, dict) else ""
            if quick_flow.startswith("__autoflow_builtin_"):
                quick_result = await _run_builtin_autoflow_candidate(quick_rr if isinstance(quick_rr, dict) else {})
                if isinstance(quick_result, dict):
                    quick_result["autoflow"] = quick_rr if isinstance(quick_rr, dict) else {}
                return quick_result
        for attempt_index in range(retry_loops):
            _emit_status(
                f"AutoFlow {attempt_index + 1}/{retry_loops}",
                "Checking direct answers, built-in skills, and existing workflows.",
                "Creating a new workflow only if nothing suitable matches." if create_enabled else "",
            )
            rr = await _call_autoflow("select_or_create" if create_enabled else "select")
            plan_obj = rr.get("plan") if isinstance(rr.get("plan"), dict) else {}
            plan_summary = str(plan_obj.get("summary") or "").strip()
            plan_need = [str(x or "").strip() for x in (plan_obj.get("must_use_capabilities") or []) if str(x or "").strip()]
            plan_avoid = [str(x or "").strip() for x in (plan_obj.get("avoid_capabilities") or []) if str(x or "").strip()]
            if plan_summary or plan_need or plan_avoid:
                _emit_status(
                    f"AutoFlow {attempt_index + 1}/{retry_loops}",
                    f"Plan: {_clip(plan_summary, 96)}" if plan_summary else "Plan ready.",
                    f"Need: {_clip(', '.join(plan_need), 72)}" if plan_need else "",
                    f"Avoid: {_clip(', '.join(plan_avoid), 72)}" if plan_avoid else "",
                )
            last_result = {
                "mode": "autoflow",
                "autoflow": rr,
                "assistant_message": _latest_assistant_message(db, pid, sid),
            }
            chosen_flow = str(rr.get("selected_flow") or rr.get("flow_name") or "").strip()
            generated = rr.get("generated_workflow") if isinstance(rr.get("generated_workflow"), dict) else {}
            creator_run = rr.get("creator_run") if isinstance(rr.get("creator_run"), dict) else {}
            builtin_result = await _run_builtin_autoflow_candidate(rr if isinstance(rr, dict) else {})
            if isinstance(builtin_result, dict):
                builtin_result["autoflow"] = rr
                return builtin_result
            if not generated:
                await _ensure_flows_loaded()
            flow_def = generated.get("workflow_json") if isinstance(generated.get("workflow_json"), dict) else (flows.get(chosen_flow) if isinstance(flows.get(chosen_flow), dict) else None)
            temp_skill_dirs = generated.get("temp_skill_dirs") if isinstance(generated.get("temp_skill_dirs"), list) else []
            generated_record_id = str(generated.get("record_id") or "").strip()
            if not chosen_flow or not isinstance(flow_def, dict) or not isinstance(flow_def.get("nodes"), dict) or not flow_def.get("nodes"):
                last_result["assistant_message"] = _emit_status(
                    f"AutoFlow {attempt_index + 1}/{retry_loops}",
                    "No builtin, existing workflow, or generated workflow was selected yet." if create_enabled else "No runnable builtin or existing workflow match.",
                    _clip((str(creator_run.get("status") or "") if creator_run else "") or str(rr.get("reason") or "No direct answer, built-in skill, or runnable workflow matched this request."), 96),
                )
                return last_result
            last_result["assistant_message"] = _emit_status(
                f"AutoFlow {attempt_index + 1}/{retry_loops}",
                f"Built: {_clip(chosen_flow, 56)}." if generated else f"Using: {_clip(chosen_flow, 56)}.",
                f"Creator run {creator_run.get('run_id')}." if generated and creator_run.get("run_id") else "",
                "Running.",
            )
            flow_result = await _run_agent_flow_service_turn(
                pid,
                sid,
                prompt,
                svc,
                router_cfg,
                request,
                flow_name=chosen_flow,
                flow_def=flow_def if generated else None,
                temp_skill_dirs=temp_skill_dirs,
            )
            flow_result["autoflow"] = rr
            last_result = flow_result
            if not require_judge:
                last_result["assistant_message"] = _emit_status(
                    f"AutoFlow {attempt_index + 1}/{retry_loops}",
                    "Done. Review disabled." if flow_result.get("run", {}).get("ok") else "Run failed.",
                )
                return last_result
            last_result["assistant_message"] = _emit_status(
                f"AutoFlow {attempt_index + 1}/{retry_loops}",
                "Checking result.",
            )
            assistant_msg = flow_result.get("assistant_message") if isinstance(flow_result.get("assistant_message"), dict) else {}
            assistant_text = str(assistant_msg.get("content") or "").strip()
            assistant_meta = assistant_msg.get("meta") if isinstance(assistant_msg.get("meta"), dict) else {}
            state_meta = flow_result.get("state") if isinstance(flow_result.get("state"), dict) else {}
            final_result_text = str(state_meta.get("final_result") or "").strip()
            judge_text = final_result_text or assistant_text or json.dumps(assistant_meta, ensure_ascii=False)
            precheck_failure = _autoflow_precheck_failure(prompt, judge_text)
            if precheck_failure:
                judge = {
                    "satisfied": False,
                    "reason": precheck_failure,
                }
            else:
                low_judge_text = str(judge_text or "").lower()
                has_structured_result = bool(
                    len(str(judge_text or "").strip()) >= 180
                    and (
                        "## " in str(judge_text or "")
                        or "|---" in low_judge_text
                        or low_judge_text.startswith("subject:")
                        or "\nsubject:" in low_judge_text
                    )
                )
                if has_structured_result:
                    judge = {
                        "satisfied": True,
                        "score": 0.92,
                        "reason": "Completed workflow returned a structured direct result.",
                        "improved_request": "",
                    }
                else:
                    judge = await _call_autoflow(
                        "judge",
                        request_plan=plan_obj,
                        flow_result_text=judge_text,
                        flow_name=chosen_flow,
                        flow_result_meta=assistant_meta if assistant_meta else state_meta,
                    )
            satisfied = judge.get("satisfied") is True
            judge_reason = str(judge.get("reason") or "").strip()
            attempts.append({
                "flow_name": chosen_flow,
                "source": str(rr.get("source") or ("generated" if generated else "existing")).strip() or "existing",
                "judge_reason": judge_reason,
                "improved_request": str(judge.get("improved_request") or "").strip(),
            })
            if satisfied:
                last_result["judge"] = judge
                last_result["autoflow_status_message"] = _emit_status(
                    f"AutoFlow {attempt_index + 1}/{retry_loops}",
                    "Passed.",
                    _clip(judge_reason, 84),
                )
                return last_result
            avoid_flows.append(chosen_flow)
            if generated_record_id:
                avoid_generated_record_ids.append(generated_record_id)
            last_result["judge"] = judge
            last_result["autoflow_status_message"] = _emit_status(
                f"AutoFlow {attempt_index + 1}/{retry_loops}",
                f"Missed: {_clip(judge_reason or 'missing requested output', 72)}",
                "Retrying with another flow or creating one if needed." if (attempt_index + 1) < retry_loops else "No retries left.",
            )
        return last_result

    async def _compute_llm_skill_autoflow_result(pid: str, sid: str, prompt: str, svc: ServiceChatRequest, router_cfg: Dict[str, Any], request: Request, *, on_event: Optional[Callable[[str, Any], None]] = None) -> Dict[str, Any]:
        settings_map = router_cfg.get("settings") if isinstance(router_cfg.get("settings"), dict) else {}
        llm_skill_autoflow_cfg = settings_map.get("llm_skill_autoflow") if isinstance(settings_map.get("llm_skill_autoflow"), dict) else {}
        llm_skill_autoflow_cfg = {**llm_skill_autoflow_cfg, "llm_skill_autoflow_enabled": True}
        ext = {
            "last_user_content": prompt,
            "llm_skill_autoflow_settings": llm_skill_autoflow_cfg,
            "project_id": pid,
            "session_id": sid,
            "session-id": sid,
            "sid": sid,
        }
        if settings_map:
            ext["router_plugin_settings"] = settings_map

        direct_error = None
        try:
            from ai_router import AIRouter

            if not _service_ensure_text_model(app):
                raise RuntimeError("chat_model_not_loaded")
            model_fn = getattr(app.state, "model", None)
            model_obj = model_fn() if callable(model_fn) else None
            if model_obj is None:
                raise RuntimeError("chat_model_not_loaded")
            settings_fn = getattr(app.state, "settings", None)
            route_settings = dict(settings_fn() if callable(settings_fn) else {})
            route_settings.update(llm_skill_autoflow_cfg)
            route_settings["__server_app"] = app
            route_settings["__sid"] = sid
            route_settings["__pid"] = pid
            route_settings["__request_headers"] = dict(request.headers)
            route_settings["__model_loader_registry"] = getattr(app.state, "model_loader_registry", None)
            reg = getattr(app.state, "agent_workflow_tools", None)
            request_user = None
            permission_summary = None
            try:
                request_user = _optional_user(app, request)
            except Exception:
                request_user = None
            try:
                from plugins.gui_helpers.permissions_manager.core import can_access_skill, compute_effective_permissions
                permission_summary = compute_effective_permissions(app, request_user)
            except Exception:
                can_access_skill = None  # type: ignore
                compute_effective_permissions = None  # type: ignore
                permission_summary = None
            route_settings["__request_user"] = request_user
            route_settings["__permission_summary"] = permission_summary
            if reg is not None and hasattr(reg, "call_tool"):
                def _aw_tool_call(name: str, ctx: dict, params: dict):
                    tool_name = str(name or "").strip()
                    try:
                        if callable(can_access_skill) and isinstance(permission_summary, dict):
                            if tool_name and not can_access_skill(permission_summary, tool_name):
                                return {
                                    "ok": False,
                                    "data": {
                                        "tool": tool_name,
                                        "permission_denied": True,
                                        "required_skill": tool_name,
                                        "role_ids": list(permission_summary.get("role_ids") or []),
                                        "is_admin": bool(permission_summary.get("is_admin")),
                                    },
                                    "warnings": ["skill_access_denied"],
                                }
                    except Exception:
                        pass
                    return reg.call_tool(tool_name, dict(ctx or {}), dict(params or {}))
                route_settings["__agent_workflow_tool_call"] = _aw_tool_call
            route_settings["__cancel_cb"] = lambda: False
            if callable(on_event):
                route_settings["__router_diag_cb"] = lambda data: on_event("diag", data)
                route_settings["__router_token_cb"] = lambda piece: on_event("token", {"text": str(piece or "")})
            router = AIRouter(chat_llm=model_obj, backend_type="auto", settings=route_settings)
            route_req = SimpleNamespace(
                model="",
                messages=[{"role": "user", "content": prompt}],
                backend_type="auto",
                route_id="llm_skill_autoflow",
                router_enabled_plugins=["llm_skill_autoflow"],
                ext=ext,
                sid=sid,
                client_msg_id=str(svc.client_msg_id or ""),
            )
            handled, route_result = await asyncio.to_thread(router.try_route, route_req)
            if not handled or not isinstance(route_result, dict):
                raise RuntimeError("llm_skill_autoflow_not_handled")
            rr = route_result
        except Exception as exc:
            direct_error = exc
            request_headers = _internal_service_headers(request, pid=pid, sid=sid, enabled_plugins=["llm_skill_autoflow", "llm_autoflow", "autoflow", "agent_flow"], suppress_persist=True)
            request_body = {
                "model": "",
                "messages": [{"role": "user", "content": prompt}],
                "backend_type": "auto",
                "route_id": "llm_skill_autoflow",
                "router_enabled_plugins": ["llm_skill_autoflow"],
                "ext": ext,
                "sid": sid,
            }
            try:
                select_res = await _loopback_sse_request(
                    request,
                    method="POST",
                    path="/v1/chat/completions_stream",
                    headers=request_headers,
                    body=request_body,
                    timeout_s=240.0,
                    on_event=on_event,
                )
            except Exception:
                select_res = await _internal_sse_request(
                    app,
                    method="POST",
                    path="/v1/chat/completions_stream",
                    headers=request_headers,
                    body=request_body,
                    timeout_s=240.0,
                    on_event=on_event,
                )
            rr = {}
            router_evt = select_res.get("router") if isinstance(select_res, dict) else {}
            if isinstance(router_evt, dict):
                rr = router_evt.get("router_result") if isinstance(router_evt.get("router_result"), dict) else {}
            rr = rr if isinstance(rr, dict) else {}
        assistant_text = _strip_reasoning_artifacts(_repair_common_mojibake(str(rr.get("assistant_response") or rr.get("text") or ""))).strip()
        pre_tool_message = _strip_reasoning_artifacts(_repair_common_mojibake(str(rr.get("pre_tool_message") or ""))).strip()
        if not assistant_text:
            action_history = rr.get("action_history") if isinstance(rr.get("action_history"), list) else []
            if action_history:
                last_action = action_history[-1] if isinstance(action_history[-1], dict) else {}
                assistant_text = _strip_reasoning_artifacts(_repair_common_mojibake(str(last_action.get("preview") or last_action.get("result_text") or ""))).strip()
        if not assistant_text:
            route_error = str(rr.get("error") or "").strip() if isinstance(rr, dict) else ""
            debug_payload = {
                "route_error": route_error,
                "direct_error": str(direct_error or "").strip(),
                "assistant_response": str(rr.get("assistant_response") or "")[:400] if isinstance(rr, dict) else "",
                "text": str(rr.get("text") or "")[:400] if isinstance(rr, dict) else "",
                "warning": str(rr.get("warning") or "") if isinstance(rr, dict) else "",
                "action_history_len": len(rr.get("action_history") or []) if isinstance(rr, dict) and isinstance(rr.get("action_history"), list) else 0,
                "selected_categories": list(rr.get("selected_categories") or []) if isinstance(rr, dict) else [],
                "allowed_skill_count": int(rr.get("allowed_skill_count") or 0) if isinstance(rr, dict) else 0,
            }
            if route_error:
                raise HTTPException(status_code=500, detail=f"llm_skill_autoflow_route_error: {route_error} | debug={json.dumps(debug_payload, ensure_ascii=False)}")
            if direct_error is not None:
                raise HTTPException(status_code=500, detail=f"llm_skill_autoflow_empty_result: {direct_error} | debug={json.dumps(debug_payload, ensure_ascii=False)}")
            raise HTTPException(status_code=500, detail=f"llm_skill_autoflow_empty_result | debug={json.dumps(debug_payload, ensure_ascii=False)}")
        return {
            "router_result": rr,
            "assistant_text": assistant_text,
            "pre_tool_message": pre_tool_message,
            "llm_skill_settings": llm_skill_autoflow_cfg,
        }

    def _stream_llm_skill_autoflow_verified_answer(*, app: Any, user_text: str, settings: Dict[str, Any], selected_categories: List[str], action_history: List[Dict[str, Any]], fallback_text: str):
        successful = [row for row in action_history if isinstance(row, dict) and row.get("ok")]
        if not successful:
            return
        model_fn = getattr(app.state, "model", None)
        model_obj = model_fn() if callable(model_fn) else None
        if model_obj is None or not hasattr(model_obj, "stream_chat"):
            return
        synthesis_prompt = (
            str(settings.get("llm_skill_autoflow_system_prompt") or "").strip()
            + "\n\nYou are writing the final answer for the user from verified tool results only."
            + "\nDo not mention internal tool names unless directly useful."
            + "\nIf tool results are incomplete, say exactly what is still missing."
            + "\nCurrent user request:\n"
            + str(user_text or "")
            + "\n\nAvailable result evidence:\n"
            + json.dumps(
                {
                    "selected_categories": list(selected_categories or []),
                    "tool_results": [
                        {
                            "skill": str(row.get("skill") or ""),
                            "preview": str(row.get("preview") or ""),
                            "warnings": list(row.get("warnings") or []),
                        }
                        for row in successful[-6:]
                    ],
                },
                ensure_ascii=False,
            )
        )
        messages = [{"role": "user", "content": synthesis_prompt}]
        kwargs = {
            "messages": messages,
            "max_new_tokens": 1200,
            "temperature": float(settings.get("llm_skill_autoflow_temperature") or 0.1),
            "top_p": 0.95,
            "token_chunk_size": 1,
        }
        try:
            stream_iter = model_obj.stream_chat(**kwargs)
        except TypeError:
            kwargs.pop("token_chunk_size", None)
            stream_iter = model_obj.stream_chat(**kwargs)
        emitted = False
        for piece in stream_iter:
            if not piece:
                continue
            emitted = True
            yield str(piece)
        if not emitted and fallback_text:
            return

    def _stream_llm_skill_autoflow_direct_answer(*, app: Any, user_text: str, settings: Dict[str, Any], draft_text: str):
        draft = str(draft_text or "").strip()
        if not draft:
            return
        model_fn = getattr(app.state, "model", None)
        model_obj = model_fn() if callable(model_fn) else None
        if model_obj is None or not hasattr(model_obj, "stream_chat"):
            return
        system_prompt = (
            str(settings.get("llm_skill_autoflow_system_prompt") or "").strip()
            + "\n\nYou are writing the final user-facing answer."
            + "\nReturn only the final answer text."
            + "\nDo not output JSON, tool calls, tags, chain-of-thought, or commentary about your internal process."
        )
        user_prompt = (
            "User request:\n"
            + str(user_text or "")
            + "\n\nDraft answer to restate cleanly for the user:\n"
            + draft
        )
        kwargs = {
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "max_new_tokens": 1200,
            "temperature": float(settings.get("llm_skill_autoflow_temperature") or 0.1),
            "top_p": 0.95,
            "token_chunk_size": 1,
        }
        try:
            stream_iter = model_obj.stream_chat(**kwargs)
        except TypeError:
            kwargs.pop("token_chunk_size", None)
            stream_iter = model_obj.stream_chat(**kwargs)
        emitted = False
        for piece in stream_iter:
            if not piece:
                continue
            emitted = True
            yield str(piece)
        if not emitted:
            return

    def _stream_llm_autoflow_direct_answer(*, app: Any, user_text: str, settings: Dict[str, Any], draft_text: str):
        draft = str(draft_text or "").strip()
        if not draft:
            return
        model_fn = getattr(app.state, "model", None)
        model_obj = model_fn() if callable(model_fn) else None
        if model_obj is None or not hasattr(model_obj, "stream_chat"):
            return
        system_prompt = (
            str(settings.get("llm_autoflow_system_prompt") or "").strip()
            + "\n\nYou are writing the final user-facing answer."
            + "\nReturn only the final answer text."
            + "\nDo not output workflow tags, JSON, chain-of-thought, or commentary about your internal process."
        )
        user_prompt = (
            "User request:\n"
            + str(user_text or "")
            + "\n\nDraft answer to restate cleanly for the user:\n"
            + draft
        )
        kwargs = {
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "max_new_tokens": 1200,
            "temperature": float(settings.get("llm_autoflow_temperature") or 0.1),
            "top_p": 0.95,
            "token_chunk_size": 1,
        }
        try:
            stream_iter = model_obj.stream_chat(**kwargs)
        except TypeError:
            kwargs.pop("token_chunk_size", None)
            stream_iter = model_obj.stream_chat(**kwargs)
        emitted = False
        for piece in stream_iter:
            if not piece:
                continue
            emitted = True
            yield str(piece)
        if not emitted:
            return

    async def _run_llm_skill_autoflow_service_turn(pid: str, sid: str, prompt: str, svc: ServiceChatRequest, router_cfg: Dict[str, Any], request: Request) -> Dict[str, Any]:
        computed = await _compute_llm_skill_autoflow_result(pid, sid, prompt, svc, router_cfg, request)
        rr = computed.get("router_result") if isinstance(computed.get("router_result"), dict) else {}
        assistant_text = str(computed.get("assistant_text") or "").strip()
        pre_tool_message = str(computed.get("pre_tool_message") or "").strip()
        notice_ts = _now_ts()
        assistant_ts = notice_ts
        assistant = _service_assistant_message(
            db,
            pid,
            sid,
            assistant_text,
            client_msg_id=str(svc.client_msg_id or ""),
            meta={"llm_skill_autoflow": True, "flow": False, "skills": True},
            ts=assistant_ts,
        )
        try:
            hub = getattr(app.state, "collab_hub", None)
            if hub is not None:
                hub.publish(
                    pid,
                    sid,
                    event="message",
                    data={"msg": assistant},
                )
        except Exception:
            pass
        return {
            "ok": True,
            "mode": "chat",
            "project_id": pid,
            "session_id": sid,
            "selected_flow": "",
            "assistant_response": assistant_text,
            "assistant_message": assistant,
            "pre_tool_message": pre_tool_message,
            "result": {
                "mode": "chat",
                "assistant_message": assistant,
                "llm_skill_autoflow": rr,
            },
        }

    async def _run_llm_autoflow_service_turn(pid: str, sid: str, prompt: str, svc: ServiceChatRequest, router_cfg: Dict[str, Any], request: Request) -> Dict[str, Any]:
        settings_map = router_cfg.get("settings") if isinstance(router_cfg.get("settings"), dict) else {}
        llm_autoflow_cfg = settings_map.get("llm_autoflow") if isinstance(settings_map.get("llm_autoflow"), dict) else {}
        llm_autoflow_cfg = {**llm_autoflow_cfg, "llm_autoflow_enabled": True}
        ext = {
            "last_user_content": prompt,
            "llm_autoflow_settings": llm_autoflow_cfg,
            "project_id": pid,
            "session_id": sid,
            "session-id": sid,
            "sid": sid,
        }
        if settings_map:
            ext["router_plugin_settings"] = settings_map
        select_res = await _internal_sse_request(
            app,
            method="POST",
            path="/v1/chat/completions_stream",
            headers=_internal_service_headers(request, pid=pid, sid=sid, enabled_plugins=["llm_autoflow", "autoflow", "agent_flow"], suppress_persist=True),
            body={
                "model": "",
                "messages": [{"role": "user", "content": prompt}],
                "backend_type": "auto",
                "route_id": "llm_autoflow",
                "router_enabled_plugins": ["llm_autoflow"],
                "ext": ext,
                "sid": sid,
            },
            timeout_s=240.0,
        )
        rr = {}
        router_evt = select_res.get("router") if isinstance(select_res, dict) else {}
        if isinstance(router_evt, dict):
            rr = router_evt.get("router_result") if isinstance(router_evt.get("router_result"), dict) else {}
        rr = rr if isinstance(rr, dict) else {}
        assistant_text = _strip_reasoning_artifacts(_repair_common_mojibake(str(rr.get("assistant_response") or rr.get("text") or ""))).strip()
        if not assistant_text:
            action_history = rr.get("action_history") if isinstance(rr.get("action_history"), list) else []
            if action_history:
                last_action = action_history[-1] if isinstance(action_history[-1], dict) else {}
                assistant_text = _strip_reasoning_artifacts(_repair_common_mojibake(str(last_action.get("result_text") or ""))).strip()
        if not assistant_text:
            raise HTTPException(status_code=500, detail="llm_autoflow_empty_result")
        assistant = _service_assistant_message(
            db,
            pid,
            sid,
            assistant_text,
            client_msg_id=str(svc.client_msg_id or ""),
            meta={"llm_autoflow": True, "flow": True},
        )
        return {
            "ok": True,
            "mode": "chat",
            "project_id": pid,
            "session_id": sid,
            "selected_flow": "",
            "assistant_response": assistant_text,
            "assistant_message": assistant,
            "result": {
                "mode": "chat",
                "assistant_message": assistant,
                "llm_autoflow": rr,
            },
        }

    @r.post("/v1/projects/{pid}/sessions/{sid}/llm_skill_autoflow/turn")
    async def session_llm_skill_autoflow_turn(pid: str, sid: str, body: ServiceChatRequest, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        prompt = str(body.message or body.prompt or body.content or "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="llm_skill_autoflow_message_required")
        prefs = db.get_gui_prefs_effective(pid, u.username)
        router_cfg = _extract_router_config_from_prefs(prefs, pid, sid)
        settings_map = router_cfg.get("settings") if isinstance(router_cfg.get("settings"), dict) else {}
        llm_skill_autoflow_cfg = settings_map.get("llm_skill_autoflow") if isinstance(settings_map.get("llm_skill_autoflow"), dict) else {}
        header_enabled = _parse_enabled_header(request.headers.get("X-Gui-Enabled-Plugins")) or set()
        enabled = set(router_cfg.get("enabled") or []) | set(header_enabled)
        llm_skill_autoflow_enabled = ("llm_skill_autoflow" in enabled) and llm_skill_autoflow_cfg.get("llm_skill_autoflow_enabled", True) is not False
        if not llm_skill_autoflow_enabled:
            raise HTTPException(status_code=409, detail="llm_skill_autoflow_not_enabled")
        alias = str((prefs.get("alias") if isinstance(prefs, dict) else None) or u.username).strip() or u.username
        user_msg = _service_user_message(
            db,
            pid,
            sid,
            prompt,
            author_username=u.username,
            author_alias=alias,
            client_msg_id=str(body.client_msg_id or ""),
            meta={"via": "llm_skill_autoflow", "flow": False, "skills": True},
        )
        try:
            hub = getattr(app.state, "collab_hub", None)
            if hub is not None:
                hub.publish(
                    pid,
                    sid,
                    event="message",
                    data={"msg": user_msg},
                )
        except Exception:
            pass
        result = await _run_llm_skill_autoflow_service_turn(pid, sid, prompt, body, router_cfg, request)
        assistant = result.get("assistant_message") if isinstance(result, dict) else None
        assistant_text = str((assistant or {}).get("content") or result.get("assistant_response") or "").strip() if isinstance(result, dict) else ""
        return {
            "ok": True,
            "mode": "llm_skill_autoflow",
            "project_id": pid,
            "session_id": sid,
            "assistant_response": assistant_text,
            "assistant_message": assistant,
            "result": result,
        }

    @r.post("/v1/projects/{pid}/sessions/{sid}/llm_autoflow/turn")
    async def session_llm_autoflow_turn(pid: str, sid: str, body: ServiceChatRequest, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        prompt = str(body.message or body.prompt or body.content or "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="llm_autoflow_message_required")
        prefs = db.get_gui_prefs_effective(pid, u.username)
        router_cfg = _extract_router_config_from_prefs(prefs, pid, sid)
        settings_map = router_cfg.get("settings") if isinstance(router_cfg.get("settings"), dict) else {}
        llm_autoflow_cfg = settings_map.get("llm_autoflow") if isinstance(settings_map.get("llm_autoflow"), dict) else {}
        header_enabled = _parse_enabled_header(request.headers.get("X-Gui-Enabled-Plugins")) or set()
        enabled = set(router_cfg.get("enabled") or []) | set(header_enabled)
        llm_autoflow_enabled = ("llm_autoflow" in enabled) and llm_autoflow_cfg.get("llm_autoflow_enabled", True) is not False
        if not llm_autoflow_enabled:
            raise HTTPException(status_code=409, detail="llm_autoflow_not_enabled")
        result = await _run_llm_autoflow_service_turn(pid, sid, prompt, body, router_cfg, request)
        assistant = result.get("assistant_message") if isinstance(result, dict) else None
        assistant_text = str((assistant or {}).get("content") or result.get("assistant_response") or "").strip() if isinstance(result, dict) else ""
        return {
            "ok": True,
            "mode": "llm_autoflow",
            "project_id": pid,
            "session_id": sid,
            "assistant_response": assistant_text,
            "assistant_message": assistant,
            "result": result,
        }

    @r.get("/v1/projects/{pid}/sessions/{sid}/service_info")
    def session_service_info(pid: str, sid: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        prefs = db.get_gui_prefs_effective(pid, u.username)
        router_cfg = _extract_router_config_from_prefs(prefs, pid, sid)
        agent_settings = router_cfg.get("settings", {}).get("agent_flow") if isinstance(router_cfg.get("settings", {}).get("agent_flow"), dict) else {}
        raw_active = str(agent_settings.get("agent_flow_active_flow") or "").strip()
        llm_autoflow_selected = raw_active == LLM_AUTOFLOW_FLOW_VALUE
        llm_skill_autoflow_selected = raw_active == LLM_SKILL_AUTOFLOW_FLOW_VALUE
        no_flow_selected = raw_active == NO_FLOW_VALUE or ("agent_flow_active_flow" in agent_settings and raw_active == "")
        active_flow = raw_active if raw_active and raw_active not in {NO_FLOW_VALUE, LLM_AUTOFLOW_FLOW_VALUE, LLM_SKILL_AUTOFLOW_FLOW_VALUE} else ""
        if not active_flow and not llm_autoflow_selected and not llm_skill_autoflow_selected:
            no_flow_selected = True
        autoflow_cfg = router_cfg.get("settings", {}).get("autoflow") if isinstance(router_cfg.get("settings", {}).get("autoflow"), dict) else {}
        autoflow_enabled = "autoflow" in set(router_cfg.get("enabled") or []) and autoflow_cfg.get("autoflow_enabled", True) is not False
        base = str(request.base_url).rstrip("/")
        warmup_state = _service_startup_warmup_state(app)
        return {
            "ok": True,
            "project_id": pid,
            "session_id": sid,
            "service_url": f"{base}/v1/projects/{pid}/sessions/{sid}/service_chat",
            "service_path": f"/v1/projects/{pid}/sessions/{sid}/service_chat",
            "auth_url": f"{base}/v1/auth/login",
            "auth_path": "/v1/auth/login",
            "method": "POST",
            "auth_header": "Authorization: Bearer <token>",
            "router_enabled_plugins": list(router_cfg.get("enabled") or []),
            "active_flow": active_flow,
            "no_flow_selected": no_flow_selected,
            "autoflow_enabled": bool(autoflow_enabled),
            "service_warming": bool(warmup_state.get("active")),
            "service_warmup_seconds": int(round(float(warmup_state.get("warmup_seconds") or 0.0))),
            "service_warmup_remaining_seconds": int(round(float(warmup_state.get("remaining_seconds") or 0.0))),
            "sample_body": {"message": "Add your message here."},
        }

    @r.post("/v1/projects/{pid}/sessions/{sid}/autoflow/execute_builtin")
    async def session_autoflow_execute_builtin(pid: str, sid: str, body: BuiltinAutoFlowExecuteRequest, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        prompt = str(body.message or body.prompt or "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="builtin_autoflow_message_required")
        candidate = body.candidate if isinstance(body.candidate, dict) else {}
        svc = ServiceChatRequest(message=prompt, client_msg_id=str(body.client_msg_id or ""))
        prefs = db.get_gui_prefs_effective(pid, u.username)
        pref_alias = None
        try:
            pref_alias = prefs.get("alias") if isinstance(prefs, dict) else None
        except Exception:
            pref_alias = None
        alias = str(pref_alias or u.username).strip() or u.username
        _service_user_message(
            db,
            pid,
            sid,
            prompt,
            author_username=u.username,
            author_alias=alias,
            client_msg_id=str(body.client_msg_id or ""),
            meta={"via": "autoflow_execute_builtin", "flow": True},
        )
        router_cfg = _extract_router_config_from_prefs(prefs, pid, sid)
        flow_name = str(candidate.get("selected_flow") or candidate.get("flow_name") or candidate.get("name") or "").strip()
        generated = candidate.get("generated_workflow") if isinstance(candidate.get("generated_workflow"), dict) else {}
        generated_flow = generated.get("workflow_json") if isinstance(generated.get("workflow_json"), dict) else None

        if flow_name in {"__autoflow_builtin_repo_code_explain__", "__autoflow_builtin_repo_code_improve__"} and isinstance(generated_flow, dict):
            result = await _run_agent_flow_service_turn(
                pid,
                sid,
                prompt,
                svc,
                router_cfg,
                request,
                flow_name=flow_name,
                flow_def=generated_flow,
                temp_skill_dirs=[str(x or "").strip() for x in (generated.get("temp_skill_dirs") or []) if str(x or "").strip()],
            )
        else:
            result = await _run_builtin_candidate_result(pid, sid, prompt, svc, candidate, router_cfg, request)

        if not isinstance(result, dict):
            raise HTTPException(status_code=400, detail="builtin_autoflow_candidate_not_executable")
        state = result.get("state") if isinstance(result.get("state"), dict) else {}
        assistant = result.get("assistant_message") if isinstance(result.get("assistant_message"), dict) else None
        assistant_text = str((assistant or {}).get("content") or state.get("final_result") or result.get("assistant_response") or "").strip()
        if not assistant_text:
            raise HTTPException(status_code=500, detail="builtin_autoflow_empty_result")
        if not isinstance(assistant, dict):
            flow_name = str(result.get("flow_name") or ((result.get("autoflow") or {}).get("selected_flow") or flow_name or "")).strip()
            assistant = _service_assistant_message(
                db,
                pid,
                sid,
                assistant_text,
                client_msg_id=str(body.client_msg_id or ""),
                meta={"autoflow_builtin_proxy": True, "flow_name": flow_name},
            )
            result["assistant_message"] = assistant
        return {
            "ok": True,
            "mode": "chat",
            "project_id": pid,
            "session_id": sid,
            "selected_flow": "",
            "assistant_response": assistant_text,
            "assistant_message": assistant,
            "result": result,
        }

    @r.post("/v1/projects/{pid}/sessions/{sid}/service_chat")
    async def session_service_chat(pid: str, sid: str, body: ServiceChatRequest, request: Request):
        try:
            with open("/app/data/service_chat_trace.log", "a", encoding="utf-8") as _fh:
                _fh.write(json.dumps({"ts": int(time.time()), "label": "service_chat_entry_inline", "pid": pid, "sid": sid}) + "\n")
        except Exception:
            pass
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        prompt = str(body.message or body.prompt or body.content or "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="service_chat_message_required")
        prefs = db.get_gui_prefs_effective(pid, u.username)
        router_cfg = _extract_router_config_from_prefs(prefs, pid, sid)
        wants_stream = _service_chat_wants_stream(request, body)
        if wants_stream and body.selected_flow is None:
            stream_body = ModelTurnRequest(
                prompt=prompt,
                content=prompt,
                alias=body.alias,
                client_msg_id=body.client_msg_id,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
                top_p=body.top_p,
            )
            return await model_turn_stream(stream_body, pid, sid, request)
        canned_response = _general_chat_canned_response(prompt) if _looks_like_general_chat(prompt) else ""
        if canned_response:
            assistant = _service_assistant_message(db, pid, sid, canned_response, client_msg_id=str(body.client_msg_id or ""))
            return {
                "ok": True,
                "mode": "chat",
                "project_id": pid,
                "session_id": sid,
                "assistant_response": canned_response,
                "assistant_message": assistant,
                "result": {"mode": "chat", "assistant_message": assistant, "canned": True},
            }
        if _looks_like_conceptual_workflow_question(prompt):
            conceptual_response = _conceptual_workflow_fallback_answer(prompt)
            assistant = _service_assistant_message(db, pid, sid, conceptual_response, client_msg_id=str(body.client_msg_id or ""), meta={"service_conceptual_direct": True})
            return {
                "ok": True,
                "mode": "chat",
                "project_id": pid,
                "session_id": sid,
                "selected_flow": "",
                "assistant_response": conceptual_response,
                "assistant_message": assistant,
                "result": {"mode": "chat", "assistant_message": assistant, "conceptual_direct": True},
            }
        settings_map = router_cfg.get("settings") if isinstance(router_cfg.get("settings"), dict) else {}
        agent_settings = settings_map.get("agent_flow") if isinstance(settings_map.get("agent_flow"), dict) else {}
        raw_active = str(agent_settings.get("agent_flow_active_flow") or "").strip()
        llm_autoflow_selected = raw_active == LLM_AUTOFLOW_FLOW_VALUE
        llm_skill_autoflow_selected = raw_active == LLM_SKILL_AUTOFLOW_FLOW_VALUE
        no_flow_selected = raw_active == NO_FLOW_VALUE or ("agent_flow_active_flow" in agent_settings and raw_active == "")
        active_flow = raw_active if raw_active and raw_active not in {NO_FLOW_VALUE, LLM_AUTOFLOW_FLOW_VALUE, LLM_SKILL_AUTOFLOW_FLOW_VALUE} else ""
        if not active_flow and not llm_autoflow_selected and not llm_skill_autoflow_selected:
            no_flow_selected = True
        request_selected_flow = body.selected_flow if hasattr(body, "selected_flow") else None
        if request_selected_flow is not None:
            requested_flow = str(request_selected_flow or "").strip()
            if not requested_flow or requested_flow == NO_FLOW_VALUE:
                no_flow_selected = True
                active_flow = ""
                llm_autoflow_selected = False
                llm_skill_autoflow_selected = False
            elif requested_flow == LLM_AUTOFLOW_FLOW_VALUE:
                no_flow_selected = False
                active_flow = ""
                llm_autoflow_selected = True
                llm_skill_autoflow_selected = False
            elif requested_flow == LLM_SKILL_AUTOFLOW_FLOW_VALUE:
                no_flow_selected = False
                active_flow = ""
                llm_autoflow_selected = False
                llm_skill_autoflow_selected = True
            else:
                no_flow_selected = False
                active_flow = requested_flow
                llm_autoflow_selected = False
                llm_skill_autoflow_selected = False
        autoflow_cfg = settings_map.get("autoflow") if isinstance(settings_map.get("autoflow"), dict) else {}
        llm_autoflow_cfg = settings_map.get("llm_autoflow") if isinstance(settings_map.get("llm_autoflow"), dict) else {}
        llm_skill_autoflow_cfg = settings_map.get("llm_skill_autoflow") if isinstance(settings_map.get("llm_skill_autoflow"), dict) else {}
        header_enabled = _parse_enabled_header(request.headers.get("X-Gui-Enabled-Plugins")) or set()
        autoflow_enabled = (("autoflow" in set(router_cfg.get("enabled") or [])) or ("autoflow" in header_enabled)) and autoflow_cfg.get("autoflow_enabled", True) is not False
        llm_autoflow_enabled = (("llm_autoflow" in set(router_cfg.get("enabled") or [])) or ("llm_autoflow" in header_enabled)) and llm_autoflow_cfg.get("llm_autoflow_enabled", True) is not False
        llm_skill_autoflow_enabled = (("llm_skill_autoflow" in set(router_cfg.get("enabled") or [])) or ("llm_skill_autoflow" in header_enabled)) and llm_skill_autoflow_cfg.get("llm_skill_autoflow_enabled", True) is not False
        text_model_available = _service_text_model_available(app)
        direct_pick_any = _local_builtin_candidate(prompt)
        direct_flow_any = str((direct_pick_any.get("name") if isinstance(direct_pick_any, dict) else "") or "").strip()
        direct_general_chat = bool(no_flow_selected and not direct_flow_any and _looks_like_general_chat(prompt) and not _looks_like_current_context_explanatory_chat(prompt) and not _looks_like_current_context_authoring(prompt))
        direct_text_generation = bool(no_flow_selected and not direct_flow_any and _looks_like_direct_text_generation(prompt))
        direct_structured_authoring = bool(no_flow_selected and not direct_flow_any and _looks_like_structured_authoring_request(prompt))
        direct_current_context_authoring = bool(no_flow_selected and not direct_flow_any and _looks_like_current_context_authoring(prompt))
        direct_current_context_question = bool(no_flow_selected and not direct_flow_any and _looks_like_current_context_explanatory_chat(prompt))
        direct_model_chat = bool(direct_general_chat or (direct_text_generation and not direct_structured_authoring))
        if (direct_model_chat or direct_structured_authoring or direct_current_context_authoring or direct_current_context_question) and not text_model_available:
            try:
                ensured = _service_ensure_text_model(app)
            except Exception:
                ensured = False
            if ensured:
                text_model_available = _service_text_model_available(app)
        route_with_llm_skill_autoflow = bool(llm_skill_autoflow_selected and llm_skill_autoflow_enabled)
        route_with_llm_autoflow = bool((not route_with_llm_skill_autoflow) and llm_autoflow_selected and llm_autoflow_enabled)
        route_with_autoflow = bool((not route_with_llm_skill_autoflow) and (not route_with_llm_autoflow) and no_flow_selected and autoflow_enabled and not direct_flow_any and not direct_model_chat and not (direct_structured_authoring and not direct_current_context_authoring))
        warmup_state = _service_startup_warmup_state(app)
        if warmup_state.get("active") and direct_general_chat and not text_model_available:
            remaining_s = int(round(float(warmup_state.get("remaining_seconds") or 0.0)))
            warmup_text = (
                f"The assistant service is still warming up after startup. Try again in about {remaining_s} seconds."
                if remaining_s > 0
                else "The assistant service is still warming up after startup. Try again shortly."
            )
            assistant = _service_assistant_message(
                db,
                pid,
                sid,
                warmup_text,
                client_msg_id=str(body.client_msg_id or ""),
                meta={
                    "service_warming": True,
                    "retry_after_seconds": remaining_s,
                },
            )
            return {
                "ok": False,
                "mode": "chat",
                "project_id": pid,
                "session_id": sid,
                "selected_flow": "",
                "assistant_response": warmup_text,
                "assistant_message": assistant,
                "result": {
                    "mode": "chat",
                    "selected_flow": "",
                    "assistant_message": assistant,
                    "warming": True,
                    "retry_after_seconds": remaining_s,
                },
            }
        if route_with_llm_skill_autoflow:
            result = await _run_llm_skill_autoflow_service_turn(pid, sid, prompt, body, router_cfg, request)
            assistant = result.get("assistant_message") if isinstance(result, dict) else None
            assistant_text = str((assistant or {}).get("content") or result.get("assistant_response") or "").strip() if isinstance(result, dict) else ""
            return {
                "ok": True,
                "mode": "chat",
                "project_id": pid,
                "session_id": sid,
                "selected_flow": "",
                "assistant_response": assistant_text,
                "assistant_message": assistant,
                "result": result,
            }
        if route_with_llm_autoflow:
            result = await _run_llm_autoflow_service_turn(pid, sid, prompt, body, router_cfg, request)
            assistant = result.get("assistant_message") if isinstance(result, dict) else None
            assistant_text = str((assistant or {}).get("content") or result.get("assistant_response") or "").strip() if isinstance(result, dict) else ""
            return {
                "ok": True,
                "mode": "chat",
                "project_id": pid,
                "session_id": sid,
                "selected_flow": "",
                "assistant_response": assistant_text,
                "assistant_message": assistant,
                "result": result,
            }
        if direct_current_context_question and not route_with_autoflow:
            research_runner = _load_skill_runner("custom.awf_web_research__web_research_204fb17b_executor")
            if callable(research_runner):
                try:
                    raw_research = research_runner({
                        "app": app,
                        "original_request": prompt,
                        "user_text": prompt,
                        "project_id": pid,
                        "session_id": sid,
                        "sid": sid,
                    }, {
                        "request_text": prompt,
                        "query": prompt,
                        "text": prompt,
                        "timeout": 8.0,
                        "max_results": 6,
                    })
                    research_result = raw_research if isinstance(raw_research, dict) else {"ok": bool(raw_research), "text": str(raw_research or "")}
                    research_text = _web_research_context_text(research_result, max_items=5)
                    if not research_text:
                        for key in ("final_answer", "summary", "text", "response", "content"):
                            value = str(research_result.get(key) or "").strip()
                            if value:
                                research_text = value
                                break
                    if research_text.strip() and _looks_like_identity_verification_failure(prompt, research_text):
                        assistant = _service_assistant_message(
                            db,
                            pid,
                            sid,
                            research_text,
                            client_msg_id=str(body.client_msg_id or ""),
                            meta={
                                "service_context_direct_response": True,
                                "current_context_from_builtin_web_research": True,
                                "identity_verification_failure_direct": True,
                            },
                        )
                        return {
                            "ok": True,
                            "mode": "chat",
                            "project_id": pid,
                            "session_id": sid,
                            "selected_flow": "",
                            "assistant_response": research_text,
                            "assistant_message": assistant,
                            "result": {
                                "mode": "chat",
                                "assistant_message": assistant,
                                "current_context_used": True,
                                "current_context_preview": research_text[:500],
                                "current_context_from_builtin_web_research": True,
                                "current_context_direct_response": True,
                                "identity_verification_failure_direct": True,
                            },
                        }
                    if research_text.strip() and _looks_like_failed_current_context(research_text):
                        assistant = _service_assistant_message(
                            db,
                            pid,
                            sid,
                            research_text,
                            client_msg_id=str(body.client_msg_id or ""),
                            meta={
                                "service_context_direct_response": True,
                                "current_context_from_builtin_web_research": True,
                                "current_context_insufficient_trusted_sources": True,
                            },
                        )
                        return {
                            "ok": True,
                            "mode": "chat",
                            "project_id": pid,
                            "session_id": sid,
                            "selected_flow": "",
                            "assistant_response": research_text,
                            "assistant_message": assistant,
                            "result": {
                                "mode": "chat",
                                "assistant_message": assistant,
                                "current_context_used": True,
                                "current_context_preview": research_text[:500],
                                "current_context_from_builtin_web_research": True,
                                "current_context_direct_response": True,
                                "current_context_insufficient_trusted_sources": True,
                            },
                        }
                    if research_text.strip() and not _looks_like_failed_current_context(research_text):
                        if _looks_like_macro_fact_research_answer(prompt, research_text):
                            macro_answer = _macro_fact_answer_only(research_text) or research_text
                            assistant = _service_assistant_message(
                                db,
                                pid,
                                sid,
                                macro_answer,
                                client_msg_id=str(body.client_msg_id or ""),
                                meta={
                                    "service_context_direct_response": True,
                                    "current_context_from_builtin_web_research": True,
                                    "current_context_macro_fact_direct": True,
                                },
                            )
                            return {
                                "ok": True,
                                "mode": "chat",
                                "project_id": pid,
                                "session_id": sid,
                                "selected_flow": "",
                                "assistant_response": macro_answer,
                                "assistant_message": assistant,
                                "result": {
                                    "mode": "chat",
                                    "assistant_message": assistant,
                                    "current_context_used": True,
                                    "current_context_preview": research_text[:500],
                                    "current_context_from_builtin_web_research": True,
                                    "current_context_direct_response": True,
                                    "current_context_macro_fact_direct": True,
                                },
                            }
                        limited_direct_answer = _structured_limited_current_context_answer(prompt, research_result, research_text)
                        if limited_direct_answer:
                            assistant = _service_assistant_message(
                                db,
                                pid,
                                sid,
                                limited_direct_answer,
                                client_msg_id=str(body.client_msg_id or ""),
                                meta={
                                    "service_context_direct_response": True,
                                    "current_context_from_builtin_web_research": True,
                                    "current_context_limited_synthesis": True,
                                },
                            )
                            return {
                                "ok": True,
                                "mode": "chat",
                                "project_id": pid,
                                "session_id": sid,
                                "selected_flow": "",
                                "assistant_response": limited_direct_answer,
                                "assistant_message": assistant,
                                "result": {
                                    "mode": "chat",
                                    "assistant_message": assistant,
                                    "current_context_used": True,
                                    "current_context_preview": research_text[:500],
                                    "current_context_from_builtin_web_research": True,
                                    "current_context_direct_response": True,
                                    "current_context_limited_synthesis": True,
                                },
                            }
                        try:
                            contextual = await _run_direct_model_with_research_context_timed(
                                pid,
                                sid,
                                prompt,
                                body,
                                request,
                                research_text=research_text,
                                context_label="current research context",
                                answer_style="current_context_explanatory",
                            )
                            assistant = contextual.get("assistant_message") if isinstance(contextual, dict) else None
                            assistant_text = _strip_reasoning_artifacts(str((assistant or {}).get("content") or "")).strip() if isinstance(assistant, dict) else ""
                            if assistant_text:
                                return {
                                    "ok": True,
                                    "mode": "chat",
                                    "project_id": pid,
                                    "session_id": sid,
                                    "selected_flow": "",
                                    "assistant_response": assistant_text,
                                    "assistant_message": assistant,
                                    "result": {
                                        **(contextual or {}),
                                        "current_context_used": True,
                                        "current_context_preview": research_text[:500],
                                        "current_context_from_builtin_web_research": True,
                                        "current_context_direct_response": True,
                                    },
                                }
                        except HTTPException:
                            pass
                        except Exception:
                            pass
                        assistant = _service_assistant_message(
                            db,
                            pid,
                            sid,
                            research_text,
                            client_msg_id=str(body.client_msg_id or ""),
                            meta={
                                "service_context_direct_response": True,
                                "current_context_from_builtin_web_research": True,
                            },
                        )
                        return {
                            "ok": True,
                            "mode": "chat",
                            "project_id": pid,
                            "session_id": sid,
                            "selected_flow": "",
                            "assistant_response": research_text,
                            "assistant_message": assistant,
                            "result": {
                                "mode": "chat",
                                "assistant_message": assistant,
                                "current_context_used": True,
                                "current_context_preview": research_text[:500],
                                "current_context_from_builtin_web_research": True,
                                "current_context_direct_response": True,
                            },
                        }
                except Exception:
                    pass
        if direct_flow_any:
            if direct_flow_any in {"__autoflow_builtin_general_answer__", "__autoflow_builtin_current_context_answer__"}:
                direct_result = await _run_autoflow_builtin_direct_answer(
                    pid,
                    sid,
                    prompt,
                    body,
                    router_cfg,
                    request,
                    flow_name=direct_flow_any,
                    candidate=direct_pick_any if isinstance(direct_pick_any, dict) else None,
                    reason=str((direct_pick_any or {}).get("reason") or "builtin_direct_fast_path") if isinstance(direct_pick_any, dict) else "builtin_direct_fast_path",
                )
                assistant = direct_result.get("assistant_message") if isinstance(direct_result, dict) else None
                assistant_text = _strip_reasoning_artifacts(_repair_common_mojibake(str((assistant or {}).get("content") or "")))
                if isinstance(direct_result, dict):
                    state = direct_result.get("state") if isinstance(direct_result.get("state"), dict) else {}
                    final_result_text = _strip_reasoning_artifacts(_repair_common_mojibake(str(state.get("final_result") or "")))
                    if final_result_text.strip():
                        assistant_text = final_result_text
                    direct_result = dict(direct_result)
                    direct_result["assistant_message"] = assistant
                return {
                    "ok": True,
                    "mode": "chat",
                    "project_id": pid,
                    "session_id": sid,
                    "selected_flow": "",
                    "assistant_response": assistant_text,
                    "assistant_message": assistant,
                    "result": direct_result,
                }
            inline_result = await _run_builtin_candidate_result(pid, sid, prompt, body, direct_pick_any, router_cfg, request)
            if isinstance(inline_result, dict):
                assistant = inline_result.get("assistant_message") if isinstance(inline_result, dict) else None
                assistant_text = _strip_reasoning_artifacts(_repair_common_mojibake(str((assistant or {}).get("content") or "")))
                if isinstance(inline_result, dict):
                    state = inline_result.get("state") if isinstance(inline_result.get("state"), dict) else {}
                    final_result_text = _strip_reasoning_artifacts(_repair_common_mojibake(str(state.get("final_result") or "")))
                    if final_result_text.strip():
                        assistant_text = final_result_text
                if assistant_text.strip():
                    current_assistant_text = _strip_reasoning_artifacts(str((assistant or {}).get("content") or "")).strip() if isinstance(assistant, dict) else ""
                    if current_assistant_text != assistant_text.strip():
                        if isinstance(assistant, dict):
                            assistant = dict(assistant)
                            assistant["content"] = assistant_text
                        else:
                            assistant = _service_assistant_message(
                                db,
                                pid,
                                sid,
                                assistant_text,
                                client_msg_id=str(body.client_msg_id or ""),
                                meta={"service_result_proxy": True},
                            )
                selected_flow = str(
                    (inline_result.get("flow_name") or ((inline_result.get("autoflow") or {}).get("selected_flow")) or "")
                ).strip()
                if selected_flow == "__autoflow_builtin_web_research__":
                    try:
                        if _looks_like_supported_identity_answer(prompt, assistant_text):
                            inline_result = dict(inline_result)
                            inline_result["mode"] = "chat"
                            inline_result["assistant_message"] = assistant
                            inline_result["state"] = {
                                **(inline_result.get("state") if isinstance(inline_result.get("state"), dict) else {}),
                                "final_result": assistant_text,
                                "final_result_mode": "text",
                                "identity_answer_direct": True,
                            }
                        elif _looks_like_identity_verification_failure(prompt, assistant_text):
                            inline_result = dict(inline_result)
                            inline_result["mode"] = "chat"
                            inline_result["assistant_message"] = assistant
                            inline_result["state"] = {
                                **(inline_result.get("state") if isinstance(inline_result.get("state"), dict) else {}),
                                "final_result": assistant_text,
                                "final_result_mode": "text",
                                "identity_verification_failure_direct": True,
                            }
                        elif _looks_like_macro_fact_research_answer(prompt, assistant_text):
                            assistant_text = _macro_fact_answer_only(assistant_text) or assistant_text
                            if isinstance(assistant, dict):
                                assistant = dict(assistant)
                                assistant["content"] = assistant_text
                            else:
                                assistant = _service_assistant_message(
                                    db,
                                    pid,
                                    sid,
                                    assistant_text,
                                    client_msg_id=str(body.client_msg_id or ""),
                                    meta={"current_context_macro_fact_direct": True},
                                )
                            inline_result = dict(inline_result)
                            inline_result["mode"] = "chat"
                            inline_result["assistant_message"] = assistant
                            inline_result["state"] = {
                                **(inline_result.get("state") if isinstance(inline_result.get("state"), dict) else {}),
                                "final_result": assistant_text,
                                "final_result_mode": "text",
                                "current_context_macro_fact_direct": True,
                            }
                        elif _looks_like_bad_identity_answer(prompt, assistant_text):
                            repaired = await _run_direct_model_with_research_context_timed(
                                pid,
                                sid,
                                prompt,
                                body,
                                request,
                                research_text=assistant_text,
                                context_label="retrieved identity evidence",
                                answer_style="identity_repair",
                            )
                            repaired_assistant = repaired.get("assistant_message") if isinstance(repaired, dict) else None
                            repaired_text = str((repaired_assistant or {}).get("content") or "").strip() if isinstance(repaired_assistant, dict) else ""
                            if repaired_text:
                                if _looks_like_bad_identity_answer(prompt, repaired_text):
                                    repaired_text = _identity_verification_fallback(assistant_text)
                                    repaired_assistant = _service_assistant_message(
                                        db,
                                        pid,
                                        sid,
                                        repaired_text,
                                        client_msg_id=str(body.client_msg_id or ""),
                                        meta={"service_identity_verification_fallback": True},
                                    )
                                assistant = repaired_assistant
                                assistant_text = repaired_text
                        elif _should_rewrite_web_research_answer(prompt, assistant_text):
                            rewritten = await _run_direct_model_with_research_context_timed(
                                pid,
                                sid,
                                prompt,
                                body,
                                request,
                                research_text=assistant_text,
                                context_label="retrieved web research",
                                answer_style="web_research_rewrite",
                            )
                            rewritten_assistant = rewritten.get("assistant_message") if isinstance(rewritten, dict) else None
                            rewritten_text = str((rewritten_assistant or {}).get("content") or "").strip() if isinstance(rewritten_assistant, dict) else ""
                            if rewritten_text and _looks_like_generic_current_info_answer(prompt, rewritten_text):
                                detailed = await _run_direct_model_with_research_context_timed(
                                    pid,
                                    sid,
                                    prompt,
                                    body,
                                    request,
                                    research_text=assistant_text,
                                    context_label="retrieved web research",
                                    answer_style="web_research_rewrite_detailed",
                                )
                                detailed_assistant = detailed.get("assistant_message") if isinstance(detailed, dict) else None
                                detailed_text = str((detailed_assistant or {}).get("content") or "").strip() if isinstance(detailed_assistant, dict) else ""
                                if detailed_text and not _looks_like_generic_current_info_answer(prompt, detailed_text):
                                    rewritten_assistant = detailed_assistant
                                    rewritten_text = detailed_text
                            if rewritten_text and not _should_rewrite_web_research_answer(prompt, rewritten_text):
                                assistant = rewritten_assistant
                                assistant_text = rewritten_text
                        inline_result = dict(inline_result)
                        inline_result["mode"] = "chat"
                        inline_result["assistant_message"] = assistant
                        inline_result["state"] = {
                            **(inline_result.get("state") if isinstance(inline_result.get("state"), dict) else {}),
                            "final_result": assistant_text,
                            "final_result_mode": "text",
                        }
                    except Exception:
                        pass
                inline_result["assistant_message"] = assistant
                inline_mode = str((inline_result or {}).get("mode") or "chat")
                response_selected_flow = selected_flow if inline_mode == "agent_flow" else ""
                return {
                    "ok": True,
                    "mode": inline_mode,
                    "project_id": pid,
                    "session_id": sid,
                    "selected_flow": response_selected_flow,
                    "assistant_response": assistant_text,
                    "assistant_message": assistant,
                    "result": inline_result,
                }
        if direct_current_context_authoring and not route_with_autoflow:
            research_text = ""
            research_runner = _load_skill_runner("custom.awf_web_research__web_research_204fb17b_executor")
            if callable(research_runner):
                try:
                    raw_research = research_runner({
                        "app": app,
                        "original_request": prompt,
                        "user_text": prompt,
                        "project_id": pid,
                        "session_id": sid,
                        "sid": sid,
                    }, {
                        "request_text": prompt,
                        "query": prompt,
                        "text": prompt,
                        "timeout": 8.0,
                        "max_results": 6,
                    })
                    research_result = raw_research if isinstance(raw_research, dict) else {"ok": bool(raw_research), "text": str(raw_research or "")}
                    for key in ("final_answer", "summary", "text", "response", "content"):
                        value = str(research_result.get(key) or "").strip()
                        if value:
                            research_text = value
                            break
                    if research_text.strip() and not _looks_like_failed_current_context(research_text):
                        if _research_scope_too_narrow_for_prompt(prompt, research_text):
                            assistant_text = _structured_current_context_fallback_answer(prompt, research_text)
                            assistant = _service_assistant_message(
                                db,
                                pid,
                                sid,
                                assistant_text,
                                client_msg_id=str(body.client_msg_id or ""),
                                meta={"service_context_fallback": True, "service_context_scope_guard": True},
                            )
                            contextual = {
                                "mode": "chat",
                                "assistant_message": assistant,
                                "current_context_used": True,
                                "current_context_fallback": True,
                                "current_context_scope_guard": True,
                            }
                        else:
                            contextual = await _run_direct_model_with_research_context_timed(
                                pid,
                                sid,
                                prompt,
                                body,
                                request,
                                research_text=research_text,
                                context_label="current research context",
                                answer_style="authoring",
                            )
                            assistant = contextual.get("assistant_message") if isinstance(contextual, dict) else None
                            assistant_text = _strip_reasoning_artifacts(str((assistant or {}).get("content") or "")).strip() if isinstance(assistant, dict) else ""
                        return {
                            "ok": True,
                            "mode": "chat",
                            "project_id": pid,
                            "session_id": sid,
                            "selected_flow": "",
                            "assistant_response": assistant_text,
                            "assistant_message": assistant,
                            "result": {
                                **(contextual or {}),
                                "current_context_used": True,
                                "current_context_preview": research_text[:500],
                            },
                        }
                except Exception:
                    pass
            try:
                authored = await _run_direct_model_authoring_without_research(
                    pid,
                    sid,
                    prompt,
                    body,
                    request,
                    framing_note="If the request mentions current conditions, costs, or trends, keep the answer useful and mark exact live facts or figures as items to verify rather than inventing them.",
                )
                assistant = authored.get("assistant_message") if isinstance(authored, dict) else None
                assistant_text = _strip_reasoning_artifacts(str((assistant or {}).get("content") or "")).strip() if isinstance(assistant, dict) else ""
                if assistant_text:
                    return {
                        "ok": True,
                        "mode": "chat",
                        "project_id": pid,
                        "session_id": sid,
                        "selected_flow": "",
                        "assistant_response": assistant_text,
                        "assistant_message": assistant,
                        "result": {
                            **(authored or {}),
                            "current_context_used": False,
                            "current_context_fallback": True,
                            "current_context_model_only": True,
                            "current_context_preview": research_text[:500] if research_text.strip() else "",
                        },
                    }
            except Exception:
                pass
            fallback_text = _structured_current_context_fallback_answer(prompt, research_text)
            assistant = _service_assistant_message(
                db,
                pid,
                sid,
                fallback_text,
                client_msg_id=str(body.client_msg_id or ""),
                meta={"service_context_fallback": True, "service_context_fallback_no_live_context": not (bool(research_text.strip()) and not _looks_like_failed_current_context(research_text))},
            )
            return {
                "ok": True,
                "mode": "chat",
                "project_id": pid,
                "session_id": sid,
                "selected_flow": "",
                "assistant_response": fallback_text,
                "assistant_message": assistant,
                "result": {"mode": "chat", "assistant_message": assistant, "current_context_used": bool(research_text.strip()) and not _looks_like_failed_current_context(research_text), "current_context_fallback": True, "current_context_preview": research_text[:500] if research_text.strip() else ""},
            }
        if direct_structured_authoring and not direct_current_context_authoring and not route_with_autoflow:
            try:
                authored = await _run_direct_model_authoring_without_research(
                    pid,
                    sid,
                    prompt,
                    body,
                    request,
                    framing_note="Start directly with the requested deliverable. Preserve the course, assignment type, and framing exactly as requested.",
                )
                assistant = authored.get("assistant_message") if isinstance(authored, dict) else None
                assistant_text = _strip_reasoning_artifacts(str((assistant or {}).get("content") or "")).strip() if isinstance(assistant, dict) else ""
                if assistant_text:
                    return {
                        "ok": True,
                        "mode": "chat",
                        "project_id": pid,
                        "session_id": sid,
                        "selected_flow": "",
                        "assistant_response": assistant_text,
                        "assistant_message": assistant,
                        "result": {
                            **(authored or {}),
                            "structured_authoring_direct": True,
                        },
                    }
            except HTTPException:
                pass
            except Exception:
                pass

        if route_with_llm_autoflow:
            result = await _run_llm_autoflow_service_turn(pid, sid, prompt, body, router_cfg, request)
        elif route_with_autoflow:
            result = await _run_autoflow_service_turn(pid, sid, prompt, body, router_cfg, request)
        elif active_flow:
            result = await _run_agent_flow_service_turn(pid, sid, prompt, body, router_cfg, request, flow_name=active_flow)
        else:
            try:
                result = await _run_standard_service_turn(
                    pid,
                    sid,
                    prompt,
                    body,
                    router_cfg,
                    request,
                    direct_model_only=direct_model_chat,
                    text_model_prechecked=bool(direct_model_chat and text_model_available),
                )
            except HTTPException as exc:
                status_code = int(getattr(exc, "status_code", 0) or 0)
                if direct_model_chat and status_code == 503:
                    conceptual_fallback = _conceptual_workflow_fallback_answer(prompt) if _looks_like_conceptual_workflow_question(prompt) else ""
                    unavailable_text = conceptual_fallback or "The text chat model is not loaded right now, so a direct answer is unavailable. Load a text model or wait for the main text LLM to finish loading, then try again. Built-in skill requests such as weather, web research, finance lookups, and file analysis can still run through AutoFlow when they match those capabilities."
                    assistant = _service_assistant_message(db, pid, sid, unavailable_text, client_msg_id=str(body.client_msg_id or ""), meta={"service_text_model_unavailable": True, "service_conceptual_fallback": bool(conceptual_fallback)})
                    return {
                        "ok": bool(conceptual_fallback),
                        "mode": "chat",
                        "project_id": pid,
                        "session_id": sid,
                        "assistant_response": unavailable_text,
                        "assistant_message": assistant,
                        "result": {"mode": "chat", "assistant_message": assistant, "text_model_unavailable": True, "conceptual_fallback": bool(conceptual_fallback)},
                    }
                elif direct_model_chat and status_code >= 500:
                    conceptual_fallback = _conceptual_workflow_fallback_answer(prompt) if _looks_like_conceptual_workflow_question(prompt) else ""
                    direct_error_text = conceptual_fallback or "The direct answer backend did not complete this request. Try again after the text model finishes loading or switch to a workflow only if you want tool-backed execution."
                    assistant = _service_assistant_message(db, pid, sid, direct_error_text, client_msg_id=str(body.client_msg_id or ""), meta={"service_direct_model_failed": True, "service_conceptual_fallback": bool(conceptual_fallback)})
                    return {
                        "ok": bool(conceptual_fallback),
                        "mode": "chat",
                        "project_id": pid,
                        "session_id": sid,
                        "assistant_response": direct_error_text,
                        "assistant_message": assistant,
                        "result": {"mode": "chat", "assistant_message": assistant, "direct_model_failed": True, "conceptual_fallback": bool(conceptual_fallback)},
                    }
                elif status_code == 504:
                    if direct_model_chat:
                        try:
                            retry_result = await _run_standard_service_turn(
                                pid,
                                sid,
                                prompt,
                                body,
                                router_cfg,
                                request,
                                direct_model_only=False,
                                text_model_prechecked=bool(text_model_available),
                            )
                            if isinstance(retry_result, dict):
                                retry_result["direct_model_retry_fallback"] = True
                            result = retry_result
                        except HTTPException:
                            if no_flow_selected and not _local_builtin_candidate(prompt):
                                try:
                                    builtin_general = await _run_autoflow_builtin_direct_answer(
                                        pid,
                                        sid,
                                        prompt,
                                        body,
                                        router_cfg,
                                        request,
                                        flow_name="__autoflow_builtin_general_answer__",
                                        candidate={
                                            "name": "__autoflow_builtin_general_answer__",
                                            "reason": "builtin_direct_general_answer; timeout_recovery",
                                        },
                                        reason="builtin_direct_general_answer; timeout_recovery",
                                    )
                                    if isinstance(builtin_general, dict):
                                        builtin_general["direct_model_timeout_recovery"] = True
                                        builtin_assistant = builtin_general.get("assistant_message") if isinstance(builtin_general.get("assistant_message"), dict) else None
                                        builtin_text = _strip_reasoning_artifacts(str((builtin_assistant or {}).get("content") or "")).strip() if isinstance(builtin_assistant, dict) else ""
                                        if isinstance(builtin_general.get("state"), dict):
                                            builtin_text = _strip_reasoning_artifacts(str((builtin_general.get("state") or {}).get("final_result") or builtin_text)).strip()
                                        return {
                                            "ok": True,
                                            "mode": "chat",
                                            "project_id": pid,
                                            "session_id": sid,
                                            "selected_flow": "",
                                            "assistant_response": builtin_text,
                                            "assistant_message": builtin_assistant,
                                            "result": builtin_general,
                                        }
                                except Exception:
                                    pass
                            timeout_text = "The assistant backend did not respond in time. Try again after the text model finishes loading."
                            assistant = _service_assistant_message(db, pid, sid, timeout_text, client_msg_id=str(body.client_msg_id or ""), meta={"service_timeout": True})
                            return {
                                "ok": False,
                                "mode": "chat",
                                "project_id": pid,
                                "session_id": sid,
                                "assistant_response": timeout_text,
                                "assistant_message": assistant,
                                "result": {"mode": "chat", "assistant_message": assistant, "timeout": True},
                            }
                        except Exception:
                            if no_flow_selected and not _local_builtin_candidate(prompt):
                                try:
                                    builtin_general = await _run_autoflow_builtin_direct_answer(
                                        pid,
                                        sid,
                                        prompt,
                                        body,
                                        router_cfg,
                                        request,
                                        flow_name="__autoflow_builtin_general_answer__",
                                        candidate={
                                            "name": "__autoflow_builtin_general_answer__",
                                            "reason": "builtin_direct_general_answer; timeout_recovery",
                                        },
                                        reason="builtin_direct_general_answer; timeout_recovery",
                                    )
                                    if isinstance(builtin_general, dict):
                                        builtin_general["direct_model_timeout_recovery"] = True
                                        builtin_assistant = builtin_general.get("assistant_message") if isinstance(builtin_general.get("assistant_message"), dict) else None
                                        builtin_text = _strip_reasoning_artifacts(str((builtin_assistant or {}).get("content") or "")).strip() if isinstance(builtin_assistant, dict) else ""
                                        if isinstance(builtin_general.get("state"), dict):
                                            builtin_text = _strip_reasoning_artifacts(str((builtin_general.get("state") or {}).get("final_result") or builtin_text)).strip()
                                        return {
                                            "ok": True,
                                            "mode": "chat",
                                            "project_id": pid,
                                            "session_id": sid,
                                            "selected_flow": "",
                                            "assistant_response": builtin_text,
                                            "assistant_message": builtin_assistant,
                                            "result": builtin_general,
                                        }
                                except Exception:
                                    pass
                            timeout_text = "The assistant backend did not respond in time. Try again after the text model finishes loading."
                            assistant = _service_assistant_message(db, pid, sid, timeout_text, client_msg_id=str(body.client_msg_id or ""), meta={"service_timeout": True})
                            return {
                                "ok": False,
                                "mode": "chat",
                                "project_id": pid,
                                "session_id": sid,
                                "assistant_response": timeout_text,
                                "assistant_message": assistant,
                                "result": {"mode": "chat", "assistant_message": assistant, "timeout": True},
                            }
                    else:
                        timeout_text = "The assistant backend did not respond in time. Try again after the text model finishes loading."
                        assistant = _service_assistant_message(db, pid, sid, timeout_text, client_msg_id=str(body.client_msg_id or ""), meta={"service_timeout": True})
                        return {
                            "ok": False,
                            "mode": "chat",
                            "project_id": pid,
                            "session_id": sid,
                            "assistant_response": timeout_text,
                            "assistant_message": assistant,
                            "result": {"mode": "chat", "assistant_message": assistant, "timeout": True},
                        }
                else:
                    raise
        assistant = result.get("assistant_message") if isinstance(result, dict) else None
        assistant_text = _strip_reasoning_artifacts(str((assistant or {}).get("content") or ""))
        if isinstance(result, dict):
            state = result.get("state") if isinstance(result.get("state"), dict) else {}
            final_result_text = _strip_reasoning_artifacts(str(state.get("final_result") or ""))
            if final_result_text.strip():
                assistant_text = final_result_text
        stream_text = ""
        if isinstance(result, dict):
            stream_text = _strip_reasoning_artifacts(_repair_common_mojibake(str(((result.get("stream") or {}).get("text") or ""))))
        if stream_text.strip():
            status_like = assistant_text.strip().lower().startswith("autoflow ") or assistant_text.strip().lower().startswith("[agent_flow]")
            if not assistant_text.strip() or status_like or (str((result or {}).get("mode") or "").strip().lower() == "chat" and assistant_text.strip() != stream_text.strip()):
                assistant_text = stream_text
        if assistant_text.strip():
            current_assistant_text = _strip_reasoning_artifacts(str((assistant or {}).get("content") or "")).strip() if isinstance(assistant, dict) else ""
            if current_assistant_text != assistant_text.strip():
                if isinstance(assistant, dict):
                    assistant = dict(assistant)
                    assistant["content"] = assistant_text
                else:
                    assistant = _service_assistant_message(db, pid, sid, assistant_text, client_msg_id=str(body.client_msg_id or ""), meta={"service_result_proxy": True})
        if isinstance(result, dict):
            result["assistant_message"] = assistant
        response_mode = str((result or {}).get("mode") or "chat")
        selected_flow = ""
        if isinstance(result, dict) and response_mode == "agent_flow":
            selected_flow = str(
                (result.get("flow_name") or ((result.get("autoflow") or {}).get("selected_flow")) or "")
            ).strip()
        return {
            "ok": True,
            "mode": response_mode,
            "project_id": pid,
            "session_id": sid,
            "selected_flow": selected_flow,
            "assistant_response": assistant_text,
            "assistant_message": assistant,
            "result": result,
        }


    @r.post("/v1/auth/change_password")
    def change_password(req: ChangePasswordRequest, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)

        # verify old password
        ok = db.verify_login(u.username, req.old_password)
        if not ok:
            raise HTTPException(status_code=401, detail="Invalid current password")

        # set new password
        salt_hex = secrets.token_bytes(16).hex()
        iters = int(os.environ.get("MODEL_LOADER_PW_ITERS") or 200_000)
        pw_hash_hex = _pbkdf2_sha256(req.new_password, salt_hex, iters)

        cur_tok = _token_from_headers(request)

        with db._lock:
            con = db._connect()
            try:
                con.execute(
                    "UPDATE users SET pw_salt_hex=?, pw_hash_hex=?, pw_iters=?, must_change_pw=0 WHERE lower(username)=lower(?)",
                    (salt_hex, pw_hash_hex, iters, u.username),
                )
                # revoke other tokens for this user (keep current token so GUI doesn't instantly log out)
                if cur_tok:
                    con.execute(
                        "DELETE FROM tokens WHERE lower(username)=lower(?) AND token<>?",
                        (u.username, cur_tok),
                    )
                else:
                    con.execute("DELETE FROM tokens WHERE lower(username)=lower(?)", (u.username,))
                con.commit()
            finally:
                con.close()

        return {"ok": True}

    @r.post("/v1/auth/ensure_starter_session")
    def ensure_starter_session(req: EnsureStarterSessionRequest, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        if u.role != "admin":
            raise HTTPException(status_code=403, detail="Admin only")

        pid = (req.pid or "default").strip() or "default"
        pid = "".join(ch for ch in pid if ch.isalnum() or ch in "-_:.")[:80]
        sid = (req.sid or "chat").strip() or "chat"
        sid = "".join(ch for ch in sid if ch.isalnum() or ch in "-_:.")[:80]
        if not pid or not sid:
            raise HTTPException(status_code=400, detail="Invalid starter project/session id")

        project_name = (req.project_name or "Default").strip() or "Default"
        title = (req.title or "Chat").strip() or "Chat"
        db.ensure_project(pid, project_name, u.username)
        db.ensure_session(pid, sid, title, u.username, is_public=False)
        db.set_session_public(pid, sid, False)

        return {
            "ok": True,
            "project": {"pid": pid, "name": project_name},
            "session": {"pid": pid, "sid": sid, "title": title, "is_public": 0},
        }

    # Admin: create/update users (so multiple clients can collaborate)
    class UpsertUserRequest(BaseModel):
        username: str = Field(..., min_length=1)
        password: str = Field(..., min_length=1)
        role: str = "user"  # user|admin
        projects: Optional[List[str]] = None

    @r.get("/v1/auth/users/{username}")
    def get_user(username: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        if u.role != "admin":
            raise HTTPException(status_code=403, detail="Admin only")

        uname = (username or "").strip()
        if not uname:
            raise HTTPException(status_code=400, detail="Invalid username")

        with db._lock:
            con = db._connect()
            try:
                row = con.execute(
                    "SELECT username, role, created_ts, scope_all FROM users WHERE lower(username)=lower(?)",
                    (uname,),
                ).fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="User not found")

                scope_all = bool(int(row["scope_all"] or 0))
                projects: List[str] = []
                if not scope_all:
                    rows = con.execute(
                        "SELECT pid FROM project_members WHERE lower(username)=lower(?) ORDER BY pid",
                        (str(row["username"]),),
                    ).fetchall()
                    projects = [str(r["pid"]) for r in rows]

                return {
                    "ok": True,
                    "user": {
                        "username": str(row["username"]),
                        "role": str(row["role"]),
                        "scope_all": scope_all,
                        "projects": projects,
                    },
                }
            finally:
                con.close()

    @r.get("/v1/auth/users")
    def list_users(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        if u.role != "admin":
            raise HTTPException(status_code=403, detail="Admin only")

        with db._lock:
            con = db._connect()
            try:
                rows = con.execute(
                    "SELECT username, role, created_ts FROM users ORDER BY lower(username)"
                ).fetchall()
                return {"ok": True, "users": [dict(r) for r in rows]}
            finally:
                con.close()


    @r.delete("/v1/auth/users/{username}")
    def delete_user(username: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        if u.role != "admin":
            raise HTTPException(status_code=403, detail="Admin only")

        uname = (username or "").strip()
        if not uname:
            raise HTTPException(status_code=400, detail="Invalid username")
        if uname.lower() == "admin":
            raise HTTPException(status_code=400, detail="Cannot delete admin")

        with db._lock:
            con = db._connect()
            try:
                row = con.execute(
                    "SELECT username FROM users WHERE lower(username)=lower(?)",
                    (uname,),
                ).fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="User not found")
                real = str(row["username"])

                # remove tokens + memberships + user row
                con.execute("DELETE FROM tokens WHERE lower(username)=lower(?)", (real,))
                con.execute("DELETE FROM project_members WHERE lower(username)=lower(?)", (real,))
                con.execute("DELETE FROM users WHERE lower(username)=lower(?)", (real,))
                con.commit()
            finally:
                con.close()

        return {"ok": True}


    @r.post("/v1/auth/users")
    def upsert_user(req: Any = Body(None), request: Request = None):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        if u.role != "admin":
            raise HTTPException(status_code=403, detail="Admin only")

        data: Dict[str, Any] = {}
        if isinstance(req, BaseModel):
            try:
                data = req.model_dump()
            except Exception:
                data = {}
        elif isinstance(req, dict):
            data = req

        username = str(data.get("username") or "").strip()
        if not username:
            raise HTTPException(status_code=422, detail="username required")

        password = str(data.get("password") or "").strip()
        if not password:
            raise HTTPException(status_code=422, detail="password required")

        role = _normalize_user_role(str(data.get("role") or "user").strip() or "user")

        projects_raw = data.get("projects", None)
        projects: Optional[List[str]] = None
        if projects_raw is None:
            projects = None
        elif isinstance(projects_raw, list):
            projects = [str(p).strip() for p in projects_raw if str(p).strip()]
        elif isinstance(projects_raw, str):
            projects = [s.strip() for s in projects_raw.split(",") if s.strip()]
        else:
            raise HTTPException(status_code=422, detail="projects must be list or string")

        salt_hex = secrets.token_bytes(16).hex()
        iters = int(os.environ.get("MODEL_LOADER_PW_ITERS") or 200_000)
        pw_hash_hex = _pbkdf2_sha256(password, salt_hex, iters)

        with db._lock:
            con = db._connect()
            try:
                con.execute(
                    "INSERT OR REPLACE INTO users(username, role, pw_salt_hex, pw_hash_hex, pw_iters, created_ts, must_change_pw) VALUES(?,?,?,?,?,?,1)",
                    (username, _normalize_user_role(role), salt_hex, pw_hash_hex, iters, _now_ts()),
                )
                con.commit()
            finally:
                con.close()

        # Apply project scope rules (admins always unscoped)
        if _normalize_user_role(role) == "admin":
            db.set_scope_all(username, True)
        else:
            db.set_user_project_scope(username, projects)

        return {"ok": True, "username": username, "role": role}


    @r.get("/v1/collab_prompts")
    def list_collab_prompts(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        if u.role != "admin":
            raise HTTPException(status_code=403, detail="Admin only")
        return {"ok": True, "prompts": db.list_collab_prompts()}

    @r.post("/v1/collab_prompts")
    def upsert_collab_prompt(
        request: Request,
        req: Any = Body(None),
        prompt_id: Optional[str] = Query(None),
        name: Optional[str] = Query(None),
        prompt: Optional[str] = Query(None),
    ):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        if u.role != "admin":
            raise HTTPException(status_code=403, detail="Admin only")
        data = req if isinstance(req, dict) else {}
        if prompt_id is None and isinstance(data, dict) and "prompt_id" in data:
            prompt_id = data.get("prompt_id")
        if name is None and isinstance(data, dict) and "name" in data:
            name = data.get("name")
        if prompt is None and isinstance(data, dict) and "prompt" in data:
            prompt = data.get("prompt")
        name = (name or "").strip()
        prompt = (prompt or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="name required")
        if not prompt:
            raise HTTPException(status_code=422, detail="prompt required")
        pid = db.upsert_collab_prompt(prompt_id or "", name, prompt, u.username)
        return {"ok": True, "prompt_id": pid}

    @r.put("/v1/projects/{pid}/collab_settings")
    def put_project_collab_settings(
        pid: str,
        request: Request,
        req: Any = Body(None),
        ai_default: Optional[bool] = Query(None),
        collab_prompt_id: Optional[str] = Query(None),
    ):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        if u.role != "admin":
            raise HTTPException(status_code=403, detail="Admin only")
        data = req if isinstance(req, dict) else {}
        if ai_default is None and isinstance(data, dict):
            if "ai_default" in data:
                ai_default = data.get("ai_default")
        if collab_prompt_id is None and isinstance(data, dict):
            if "collab_prompt_id" in data:
                collab_prompt_id = data.get("collab_prompt_id")
        if ai_default is not None:
            ai_default = bool(ai_default)
        if collab_prompt_id is not None:
            collab_prompt_id = str(collab_prompt_id) if collab_prompt_id is not None else None
        db.set_project_collab_settings(pid, ai_default, collab_prompt_id)
        return {"ok": True}

    @r.put("/v1/projects/{pid}/sessions/{sid}/collab_settings")
    def put_session_collab_settings(
        pid: str,
        sid: str,
        request: Request,
        req: Any = Body(None),
        ai_default: Optional[bool] = Query(None),
        collab_prompt_id: Optional[str] = Query(None),
        allow_guest: Optional[bool] = Query(None),
    ):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        if u.role != "admin":
            raise HTTPException(status_code=403, detail="Admin only")
        data = req if isinstance(req, dict) else {}
        if ai_default is None and isinstance(data, dict):
            if "ai_default" in data:
                ai_default = data.get("ai_default")
        if collab_prompt_id is None and isinstance(data, dict):
            if "collab_prompt_id" in data:
                collab_prompt_id = data.get("collab_prompt_id")
        if allow_guest is None and isinstance(data, dict):
            if "allow_guest" in data:
                allow_guest = data.get("allow_guest")
        if ai_default is not None:
            ai_default = bool(ai_default)
        if collab_prompt_id is not None:
            collab_prompt_id = str(collab_prompt_id) if collab_prompt_id is not None else None
        if allow_guest is not None:
            allow_guest = bool(allow_guest)
        db.set_session_collab_settings(pid, sid, ai_default, collab_prompt_id, allow_guest)
        return {"ok": True, "allow_guest": allow_guest}


    # --- Projects ---
    @r.get("/v1/projects")
    def list_projects(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _optional_user(app, request)
        if not u:
            with db._lock:
                con = db._connect()
                try:
                    rows = con.execute(
                        """
                        SELECT DISTINCT p.pid, p.name, p.created_by, p.created_ts, p.is_public, p.ai_default, p.collab_prompt_id
                        FROM projects p
                        JOIN sessions s ON s.pid = p.pid
                        WHERE p.is_public=1 AND s.is_public=1 AND s.allow_guest=1
                        ORDER BY p.pid
                        """
                    ).fetchall()
                    return {"ok": True, "projects": [dict(r) for r in rows]}
                finally:
                    con.close()
        return {"ok": True, "projects": db.list_projects(u)}

    @r.post("/v1/projects")
    def create_project(req: CreateProjectRequest, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_named_permission(app, request, "projects.create", "Project creation is not allowed for this user")
        u = _require_user(app, request)
        pid = (req.pid or "").strip() or (req.name.strip().lower().replace(" ", "-")[:40])
        pid = "".join(ch for ch in pid if ch.isalnum() or ch in "-_:." )
        if not pid:
            raise HTTPException(status_code=400, detail="Invalid pid")
        db.ensure_project(pid, req.name.strip(), u.username)
        return {"ok": True, "pid": pid, "name": req.name.strip()}

    # Optional: membership management (admin-only)
    class UpsertMemberRequest(BaseModel):
        username: str
        role: str = "user"  # user|admin

    @r.post("/v1/projects/{pid}/members")
    def upsert_member(pid: str, req: UpsertMemberRequest, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_named_permission(app, request, "projects.members.manage", "Project member management is not allowed for this user")
        u = _require_user(app, request)
        _require_project_admin(app, u, pid)
        with db._lock:
            con = db._connect()
            try:
                # ensure user exists
                row = con.execute("SELECT username FROM users WHERE lower(username)=lower(?)", (req.username,)).fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="User not found")
                con.execute(
                    "INSERT OR REPLACE INTO project_members(pid, username, role) VALUES(?,?,?)",
                    (pid, str(row["username"]), (req.role or "user")),
                )
                con.commit()
            finally:
                con.close()
        return {"ok": True}
    
    @r.get("/v1/projects/{pid}/members")
    def list_members(pid: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        # allow global admin OR project admin/owner
        # _require_project_admin(app, u, pid)
        _require_project_admin(u, pid)

        with db._lock:
            con = db._connect()
            try:
                rows = con.execute(
                    """
                    SELECT m.username as username, m.role as role
                    FROM project_members m
                    WHERE m.pid=?
                    ORDER BY lower(m.username)
                    """,
                    (pid,),
                ).fetchall()
                return {"ok": True, "members": [dict(r) for r in rows]}
            finally:
                con.close()


    @r.delete("/v1/projects/{pid}/members/{username}")
    def delete_member(pid: str, username: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_project_admin(app, u, pid)

        uname = (username or "").strip()
        if not uname:
            raise HTTPException(status_code=400, detail="Invalid username")

        with db._lock:
            con = db._connect()
            try:
                con.execute(
                    "DELETE FROM project_members WHERE pid=? AND lower(username)=lower(?)",
                    (pid, uname),
                )
                con.commit()
            finally:
                con.close()

        return {"ok": True}

    @r.delete("/v1/projects/{pid}")
    def delete_project(pid: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_named_permission(app, request, "projects.delete", "Project deletion is not allowed for this user")
        u = _require_user(app, request)
        _require_project_admin(u, pid)
        db.delete_project(pid)
        return {"ok": True}

    @r.delete("/v1/projects/{pid}/sessions/{sid}")
    def delete_session(pid: str, sid: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_named_permission(app, request, "sessions.delete", "Session deletion is not allowed for this user")
        u = _require_user(app, request)
        _require_project_admin(u, pid)
        db.delete_session(pid, sid)
        return {"ok": True}

    # --- Sessions ---
    # @r.get("/v1/projects/{pid}/sessions")
    # def list_sessions(pid: str, request: Request):
    #     require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
    #     u = _require_user(app, request)
    #     _require_project_access(app, u, pid)

    #     sessions = db.list_sessions(pid)
    #     if u.role == "admin":
    #         return {"ok": True, "sessions": sessions}

    #     out = []
    #     for s in sessions:
    #         is_public = int(s.get("is_public") or 0) == 1
    #         created_by = (s.get("created_by") or "")
    #         if is_public or created_by.lower() == (u.username or "").lower():
    #             out.append(s)
    #     return {"ok": True, "sessions": out}

    # @r.get("/v1/projects/{pid}/sessions")
    # def list_sessions(pid: str, request: Request):
    #     require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
    #     _ = _require_user(app, request)
    #     return {"ok": True, "sessions": db.list_sessions(pid)}

    @r.get("/v1/projects/{pid}/sessions")
    def list_sessions(pid: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _optional_user(app, request)

        if not u:
            proj = _get_project_row(db, pid)
            if not proj or int(proj.get("is_public") or 0) != 1:
                raise HTTPException(status_code=403, detail="Project not in scope")
            sessions = [
                s for s in db.list_sessions(pid)
                if int(s.get("is_public") or 0) == 1 and int(s.get("allow_guest") or 0) == 1
            ]
            return {"ok": True, "sessions": sessions}

        # Admin always ok
        if u.role == "admin":
            return {"ok": True, "sessions": db.list_sessions(pid)}

        role = _project_member_role(db, pid, u.username)
        if role:
            return {"ok": True, "sessions": db.list_sessions(pid)}

        # Not a member: allow listing only public sessions if project is public.
        proj = _get_project_row(db, pid)
        if not proj or int(proj.get("is_public") or 0) != 1:
            raise HTTPException(status_code=403, detail="Project not in scope")

        sessions = [s for s in db.list_sessions(pid) if int(s.get("is_public") or 0) == 1]
        return {"ok": True, "sessions": sessions}

    # @r.post("/v1/projects/{pid}/sessions")
    # def create_session(pid: str, req: CreateSessionRequest, request: Request):
    #     require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
    #     u = _require_user(app, request)
    #     _require_project_access(app, u, pid)
    #     sid = (req.sid or "").strip() or secrets.token_hex(4)
    #     title = (req.title or sid).strip() or sid
    #     is_public = bool(req.is_public) if req.is_public is not None else False  # DEFAULT PRIVATE
    #     db.ensure_session(pid, sid, title, u.username, is_public=is_public)
    #     return {"ok": True, "pid": pid, "sid": sid, "title": title, "is_public": (1 if is_public else 0)}

    @r.post("/v1/projects/{pid}/sessions")
    def create_session(pid: str, req: CreateSessionRequest, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_named_permission(app, request, "sessions.create", "Session creation is not allowed for this user")
        u = _require_user(app, request)

        proj = _get_project_row(db, pid)
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")

        ppub = int(proj.get("is_public") or 0) == 1
        if (u.role != "admin") and (not ppub):
            # private project => only members can create sessions
            if not _project_member_role(db, pid, u.username):
                raise HTTPException(status_code=403, detail="Project is private")

        sid = (req.sid or "").strip() or secrets.token_hex(4)
        title = (req.title or sid).strip() or sid

        # session default visibility:
        # - private project: forced private
        # - public project: default public unless explicitly set false
        sess_public = False if not ppub else (True if req.is_public is None else bool(req.is_public))

        db.ensure_session(pid, sid, title, u.username)
        db.set_session_public(pid, sid, sess_public)

        return {"ok": True, "pid": pid, "sid": sid, "title": title, "is_public": int(sess_public)}
    
    class SetVisibilityRequest(BaseModel):
        is_public: bool


    def _coerce_is_public(req: Any, query_value: Optional[bool]) -> Optional[bool]:
        if isinstance(req, BaseModel) and hasattr(req, "is_public"):
            return bool(getattr(req, "is_public"))
        if isinstance(req, dict):
            if "is_public" in req:
                return bool(req.get("is_public"))
        if isinstance(req, bool):
            return bool(req)
        if query_value is not None:
            return bool(query_value)
        return None


    def _require_project_admin(u: UserInfo, pid: str) -> None:
        if u.role == "admin":
            return
        role = _project_member_role(db, pid, u.username)
        proj = _get_project_row(db, pid)
        if proj and (proj.get("created_by") or "").lower() == u.username.lower():
            return
        if role and role.lower() == "admin":
            return
        raise HTTPException(status_code=403, detail="Admin/owner only")


    @r.put("/v1/projects/{pid}/visibility")
    def set_project_visibility(
        pid: str,
        request: Request,
        req: Any = Body(None),
        is_public: Optional[bool] = Query(None),
    ):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_named_permission(app, request, "projects.visibility.manage", "Project visibility changes are not allowed for this user")
        u = _require_user(app, request)
        _require_project_admin(u, pid)
        value = _coerce_is_public(req, is_public)
        if value is None:
            raise HTTPException(status_code=422, detail="is_public required")
        db.set_project_public(pid, bool(value))
        return {"ok": True, "pid": pid, "is_public": int(bool(value))}


    @r.get("/v1/projects/{pid}/sessions/{sid}/access")
    def session_access(pid: str, sid: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        proj = _get_project_row(db, pid)
        sess = _get_session_row(db, pid, sid)
        if not proj or not sess:
            raise HTTPException(status_code=404, detail="Not found")

        guest_allowed = _session_allows_guest(proj, sess)
        token = _token_from_headers(request)
        u = db.resolve_token(token)
        if not u:
            return {
                "ok": True,
                "can_access": bool(guest_allowed),
                "reason": "ok" if guest_allowed else "Not authenticated",
                "project_is_public": int(proj.get("is_public") or 0),
                "session_is_public": int(sess.get("is_public") or 0),
                "effective_public": int(1 if _effective_public(proj, sess) else 0),
                "allow_guest": int(1 if guest_allowed else 0),
                "can_request_join": 0,
                "is_project_member": 0,
                "is_session_member": 0,
                "is_owner": 0,
                "is_guest": 1,
            }

        role = _project_member_role(db, pid, u.username)
        is_project_member = bool(role)
        is_session_member = _is_session_member(db, pid, sid, u.username)
        is_owner = (sess.get("created_by") or "").lower() == (u.username or "").lower()
        is_member = bool(is_project_member or is_session_member or is_owner or u.role == "admin")

        can_access = True
        reason = "ok"
        try:
            require_session_access(db, u, pid, sid)
        except HTTPException as e:
            can_access = False
            reason = str(e.detail or "forbidden")

        eff_public = _effective_public(proj, sess)
        return {
            "ok": True,
            "can_access": can_access,
            "reason": reason,
            "project_is_public": int(proj.get("is_public") or 0),
            "session_is_public": int(sess.get("is_public") or 0),
            "effective_public": int(1 if eff_public else 0),
            "allow_guest": int(1 if guest_allowed else 0),
            "can_request_join": int(0 if is_member else 1),
            "is_project_member": int(1 if is_project_member else 0),
            "is_session_member": int(1 if is_session_member else 0),
            "is_owner": int(1 if is_owner else 0),
            "is_guest": 0,
        }


    @r.post("/v1/projects/{pid}/sessions/{sid}/join_requests")
    def request_join(pid: str, sid: str, request: Request, force: Optional[bool] = Query(None)):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)

        proj = _get_project_row(db, pid)
        sess = _get_session_row(db, pid, sid)
        if not proj or not sess:
            raise HTTPException(status_code=404, detail="Not found")

        role = _project_member_role(db, pid, u.username)
        is_project_member = bool(role)
        is_session_member = _is_session_member(db, pid, sid, u.username)
        is_owner = (sess.get("created_by") or "").lower() == (u.username or "").lower()
        if is_project_member or is_session_member or is_owner or u.role == "admin":
            return {"ok": True, "req_id": None, "status": "not_needed"}

        if _effective_public(proj, sess):
            if force:
                try:
                    db.add_session_member(pid, sid, u.username, role="user")
                except Exception:
                    pass
                return {"ok": True, "req_id": None, "status": "joined"}
            req_id = db.add_join_request(pid, sid, u.username)
            return {"ok": True, "req_id": req_id, "status": "pending"}

        req_id = db.add_join_request(pid, sid, u.username)
        return {"ok": True, "req_id": req_id, "status": "pending"}


    # @r.get("/v1/projects/{pid}/sessions/{sid}/join_requests")
    # def list_join_requests(pid: str, sid: str, request: Request):
    #     require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
    #     u = _require_user(app, request)

    #     sess = _get_session_row(db, pid, sid)
    #     if not sess:
    #         raise HTTPException(status_code=404, detail="Session not found")

    #     # owner/admin or project admin
    #     if u.role != "admin":
    #         if (sess.get("created_by") or "").lower() != u.username.lower():
    #             _require_project_admin(u, pid)

    #     return {"ok": True, "requests": db.list_join_requests(pid, sid, status="pending")}


    # @r.post("/v1/projects/{pid}/sessions/{sid}/join_requests/{req_id}/approve")
    # def approve_join(pid: str, sid: str, req_id: str, request: Request):
    #     require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
    #     u = _require_user(app, request)

    #     sess = _get_session_row(db, pid, sid)
    #     proj = _get_project_row(db, pid)
    #     if not sess or not proj:
    #         raise HTTPException(status_code=404, detail="Not found")

    #     if u.role != "admin":
    #         if (sess.get("created_by") or "").lower() != u.username.lower():
    #             _require_project_admin(u, pid)

    #     # resolve request
    #     pending = db.list_join_requests(pid, sid, status="pending")
    #     tgt = next((x for x in pending if (x.get("req_id") == req_id)), None)
    #     if not tgt:
    #         raise HTTPException(status_code=404, detail="Join request not found")

    #     username = str(tgt.get("username") or "").strip()
    #     if not username:
    #         raise HTTPException(status_code=400, detail="Invalid request")

    #     # If project is private => approval grants project membership
    #     if int(proj.get("is_public") or 0) == 0:
    #         db.upsert_project_member(pid, username, role="user")
    #     else:
    #         # public project + private session => session-level membership
    #         db.add_session_member(pid, sid, username, role="user")

    #     db.set_join_request_status(req_id, "approved", u.username)
    #     return {"ok": True}


    # @r.post("/v1/projects/{pid}/sessions/{sid}/join_requests/{req_id}/deny")
    # def deny_join(pid: str, sid: str, req_id: str, request: Request):
    #     require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
    #     u = _require_user(app, request)

    #     sess = _get_session_row(db, pid, sid)
    #     if not sess:
    #         raise HTTPException(status_code=404, detail="Session not found")

    #     if u.role != "admin":
    #         if (sess.get("created_by") or "").lower() != u.username.lower():
    #             _require_project_admin(u, pid)

    #     db.set_join_request_status(req_id, "denied", u.username)
    #     return {"ok": True}

    @r.get("/v1/projects/{pid}/sessions/{sid}/join_requests")
    def list_join_requests(pid: str, sid: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        # Only admin/owner can view pending requests
        _require_project_admin_or_owner(db, u, pid, sid)
        return {"ok": True, "requests": db.list_join_requests(pid, sid, status="pending")}


    @r.post("/v1/projects/{pid}/sessions/{sid}/join_requests/{req_id}/approve")
    def approve_join(pid: str, sid: str, req_id: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_project_admin_or_owner(db, u, pid, sid)

        # Find request
        pending = db.list_join_requests(pid, sid, status="pending")
        tgt = next((x for x in pending if (x.get("req_id") == req_id)), None)
        if not tgt:
            raise HTTPException(status_code=404, detail="Join request not found")

        username = str(tgt.get("username") or "").strip()
        if not username:
            raise HTTPException(status_code=400, detail="Invalid request")

        proj = _get_project_row(db, pid)
        sess = _get_session_row(db, pid, sid)
        if not proj or not sess:
            raise HTTPException(status_code=404, detail="Not found")

        # Private project => grant project membership; public project + private session => grant session membership
        if int(proj.get("is_public") or 0) == 0:
            db.upsert_project_member(pid, username, role="user")
        else:
            db.add_session_member(pid, sid, username, role="user")

        db.set_join_request_status(req_id, "approved", u.username)

        # notify listeners
        try:
            app.state.collab_hub.publish(pid, sid, event="join_request", data={"req_id": req_id, "status": "approved", "username": username})
        except Exception:
            pass

        return {"ok": True}


    @r.post("/v1/projects/{pid}/sessions/{sid}/join_requests/{req_id}/deny")
    def deny_join(pid: str, sid: str, req_id: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_project_admin_or_owner(db, u, pid, sid)

        db.set_join_request_status(req_id, "denied", u.username)

        try:
            app.state.collab_hub.publish(pid, sid, event="join_request", data={"req_id": req_id, "status": "denied"})
        except Exception:
            pass

        return {"ok": True}
    
    class TypingRequest(BaseModel):
        is_typing: bool


    @r.get("/v1/projects/{pid}/sessions/{sid}/roster")
    def get_roster(pid: str, sid: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_user_or_guest(app, request, pid, sid)
        pres: _PresenceStore = app.state.collab_presence
        return {"ok": True, "roster": pres.roster(pid, sid)}


    @r.post("/v1/projects/{pid}/sessions/{sid}/typing")
    def set_typing(pid: str, sid: str, req: TypingRequest, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        actor = _require_user_or_guest(app, request, pid, sid)
        u = actor["user"]
        pres: _PresenceStore = app.state.collab_presence
        row = pres.set_typing(pid, sid, u.username, bool(req.is_typing))
        if row is None:
            # user not in roster yet; treat as join+typing
            alias = actor.get("alias") or (request.headers.get("X-User-Alias") or u.username).strip()
            pres.join(pid, sid, u.username, alias)
            row = pres.set_typing(pid, sid, u.username, bool(req.is_typing)) or {"username": u.username, "alias": alias, "is_typing": bool(req.is_typing)}

        try:
            app.state.collab_hub.publish(pid, sid, event="typing", data={"username": row["username"], "alias": row.get("alias") or row["username"], "is_typing": bool(req.is_typing), "ts": _now_ts()})
        except Exception:
            pass

        return {"ok": True}
    
    @r.get("/v1/projects/{pid}/sessions/{sid}")
    def get_session_meta(pid: str, sid: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        # _require_project_access(app, u, pid)
        s = _require_session_access(app, u, pid, sid)
        return {"ok": True, "session": s}

    @r.put("/v1/projects/{pid}/sessions/{sid}/visibility")
    def set_session_visibility(
        pid: str,
        sid: str,
        request: Request,
        req: Any = Body(None),
        is_public: Optional[bool] = Query(None),
    ):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_named_permission(app, request, "sessions.visibility.manage", "Session visibility changes are not allowed for this user")
        u = _require_user(app, request)
        # _require_project_access(app, u, pid)
        _require_session_access(app, u, pid, sid)

        s = db.get_session(pid, sid)
        if not s:
            raise HTTPException(status_code=404, detail="Session not found")

        # Only owner (creator) can change visibility (global admin override)
        if u.role != "admin":
            created_by = (s.get("created_by") or "")
            if created_by.lower() != (u.username or "").lower():
                raise HTTPException(status_code=403, detail="Only session owner can change visibility")

        value = _coerce_is_public(req, is_public)
        if value is None:
            raise HTTPException(status_code=422, detail="is_public required")
        db.set_session_visibility(pid, sid, bool(value))

        # Broadcast best-effort (so collaborators can update UI)
        try:
            hub: _SessionHub = app.state.collab_hub
            hub.publish(pid, sid, event="session_meta", data={"sid": sid, "pid": pid, "is_public": (1 if value else 0)})
        except Exception:
            pass

        return {"ok": True, "pid": pid, "sid": sid, "is_public": (1 if value else 0)}



    # --- GUI Prefs ---
    # @r.get("/v1/projects/{pid}/gui_prefs")
    # def get_gui_prefs(pid: str, request: Request):
    #     require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
    #     u = _require_user(app, request)
    #     # _require_project_access(app, u, pid)

    #     proj = _get_project_row(db, pid)
    #     if not proj:
    #         raise HTTPException(status_code=404, detail="Project not found")

    #     ppub = int(proj.get("is_public") or 0) == 1
    #     if (u.role != "admin") and (not ppub):
    #         # private project => only members can create sessions
    #         if not _project_member_role(db, pid, u.username):
    #             raise HTTPException(status_code=403, detail="Project is private")
            
    #     prefs = db.get_gui_prefs(pid, u.username)
    #     return {"ok": True, "prefs": prefs}

    @r.get("/v1/projects/{pid}/gui_prefs")
    def get_gui_prefs(pid: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        try:
            u = _require_user(app, request)
        except HTTPException as exc:
            if int(getattr(exc, "status_code", 0) or 0) in {401, 403}:
                # GUI prefs are optional client state. Let settings panels open
                # even before auth/bootstrap has completed; saving still
                # requires a user in the PUT route.
                return {
                    "ok": True,
                    "prefs": {},
                    "default_prefs": {},
                    "user_prefs": {},
                    "unauthenticated": True,
                }
            raise

        proj = _get_project_row(db, pid)
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")

        ppub = int(proj.get("is_public") or 0) == 1
        if (u.role != "admin") and (not ppub):
            if not _project_member_role(db, pid, u.username):
                raise HTTPException(status_code=403, detail="Project is private")

        default_prefs = db.get_gui_prefs_default(pid)
        user_prefs = db.get_gui_prefs_user(pid, u.username)
        prefs = db.get_gui_prefs_effective(pid, u.username)
        return {"ok": True, "prefs": prefs, "default_prefs": default_prefs, "user_prefs": user_prefs}

    # @r.put("/v1/projects/{pid}/gui_prefs")
    # def put_gui_prefs(pid: str, req: PutGuiPrefsRequest, request: Request):
    #     require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
    #     u = _require_user(app, request)
    #     # _require_project_access(app, u, pid)
    #     proj = _get_project_row(db, pid)
    #     if not proj:
    #         raise HTTPException(status_code=404, detail="Project not found")

    #     ppub = int(proj.get("is_public") or 0) == 1
    #     if (u.role != "admin") and (not ppub):
    #         # private project => only members can create sessions
    #         if not _project_member_role(db, pid, u.username):
    #             raise HTTPException(status_code=403, detail="Project is private")
            
    #     db.put_gui_prefs(pid, u.username, req.prefs or {})
    #     return {"ok": True}

    @r.put("/v1/projects/{pid}/gui_prefs")
    def put_gui_prefs(pid: str, req: PutGuiPrefsRequest, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)

        proj = _get_project_row(db, pid)
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")

        ppub = int(proj.get("is_public") or 0) == 1
        if (u.role != "admin") and (not ppub):
            if not _project_member_role(db, pid, u.username):
                raise HTTPException(status_code=403, detail="Project is private")

        scope = (req.scope or "user").lower().strip()

        # Admin can set project-wide defaults. Everyone can set their own user prefs.
        if scope == "project":
            if u.role != "admin":
                raise HTTPException(status_code=403, detail="Admin required for project defaults")
            db.put_gui_prefs(pid, GUI_PREFS_DEFAULT_USER, req.prefs or {})
        else:
            db.put_gui_prefs(pid, u.username, req.prefs or {})

        return {"ok": True}

    # --- Messages ---
    @r.get("/v1/projects/{pid}/sessions/{sid}/messages")
    def get_messages(
        pid: str,
        sid: str,
        request: Request,
        after: Optional[str] = None,
        since_ts: Optional[int] = None,
        limit: int = 200,
        tail: bool = Query(False),
        order: Optional[str] = Query(None),
    ):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        actor = _require_user_or_guest(app, request, pid, sid)
        order_desc = bool(tail)
        if order:
            if str(order).strip().lower() in ("desc", "latest", "newest"):
                order_desc = True
        msgs = db.list_messages(
            pid=pid,
            sid=sid,
            after_msg_id=after,
            since_ts=since_ts,
            limit=limit,
            order_desc=order_desc,
        )
        # print("msgs: ", msgs)
        return {"ok": True, "messages": msgs, "transcript_cache": db.get_transcript_cache(pid, sid)}

    @r.get("/v1/projects/{pid}/sessions/{sid}/transcript_cache")
    def get_transcript_cache(pid: str, sid: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_user_or_guest(app, request, pid, sid)
        return {"ok": True, "transcript_cache": db.get_transcript_cache(pid, sid)}

    @r.put("/v1/projects/{pid}/sessions/{sid}/transcript_cache")
    def put_transcript_cache(pid: str, sid: str, req: TranscriptCacheRequest, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_user_or_guest(app, request, pid, sid)
        payload = dict(req.payload or {})
        try:
            blob = json.dumps(payload, ensure_ascii=False)
        except Exception:
            raise HTTPException(status_code=400, detail="invalid_payload")
        if len(blob.encode("utf-8")) > 2_000_000:
            raise HTTPException(status_code=413, detail="transcript_cache_too_large")
        db.set_transcript_cache(pid, sid, payload)
        return {"ok": True}

    @r.post("/v1/projects/{pid}/sessions/{sid}/messages")
    def post_message(pid: str, sid: str, req: PostMessageRequest, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        actor = _require_user_or_guest(app, request, pid, sid, alias_value=req.alias)
        u = actor["user"]
        prefs = db.get_gui_prefs_effective(pid, u.username) if actor["kind"] == "user" else {}

        pref_alias = None
        try:
            pref_alias = (prefs.get("alias") if isinstance(prefs, dict) else None)
        except Exception:
            pref_alias = None
        alias = actor.get("alias") if actor["kind"] == "guest" else ((req.alias or pref_alias or u.username).strip() or u.username)

        msg_id = secrets.token_hex(12)
        ts = _now_ts()
        meta = dict(req.meta or {})
        if req.client_msg_id:
            meta.setdefault("client_msg_id", req.client_msg_id)
        if actor["kind"] == "guest":
            meta["is_guest"] = True

        db.add_message(
            msg_id=msg_id,
            pid=pid,
            sid=sid,
            ts=ts,
            role=(req.role or "user"),
            kind=(req.kind or "human"),
            author_username=u.username,
            author_alias=alias,
            content=req.content,
            meta=meta,
        )

        # Broadcast to live collaborators (best-effort)
        try:
            hub: _SessionHub = app.state.collab_hub
            hub.publish(
                pid,
                sid,
                event="message",
                data={
                    "msg": {
                        "msg_id": msg_id,
                        "pid": pid,
                        "sid": sid,
                        "ts": ts,
                        "role": (req.role or "user"),
                        "kind": (req.kind or "human"),
                        "author_username": u.username,
                        "author_alias": alias,
                        "content": req.content,
                        "meta": meta,
                    }
                },
            )
        except Exception:
            pass
        return {"ok": True, "msg_id": msg_id}
    

    @r.post("/v1/projects/{pid}/sessions/{sid}/messages_no_ai")
    def post_message_no_ai(pid: str, sid: str, req: PostMessageRequest, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        actor = _require_user_or_guest(app, request, pid, sid, alias_value=req.alias)
        u = actor["user"]
        prefs = db.get_gui_prefs_effective(pid, u.username) if actor["kind"] == "user" else {}

        pref_alias = None
        try:
            pref_alias = (prefs.get("alias") if isinstance(prefs, dict) else None)
        except Exception:
            pref_alias = None
        alias = actor.get("alias") if actor["kind"] == "guest" else ((req.alias or pref_alias or u.username).strip() or u.username)

        msg_id = secrets.token_hex(12)
        ts = _now_ts()
        meta = dict(req.meta or {})
        if req.client_msg_id:
            meta.setdefault("client_msg_id", req.client_msg_id)
        meta["no_ai"] = True
        meta.setdefault("via", "messages_no_ai")
        if actor["kind"] == "guest":
            meta["is_guest"] = True

        db.add_message(
            msg_id=msg_id,
            pid=pid,
            sid=sid,
            ts=ts,
            role=(req.role or "user"),
            kind=(req.kind or "human"),
            author_username=u.username,
            author_alias=alias,
            content=req.content,
            meta=meta,
        )

        try:
            hub: _SessionHub = app.state.collab_hub
            hub.publish(
                pid,
                sid,
                event="message",
                data={
                    "msg": {
                        "msg_id": msg_id,
                        "pid": pid,
                        "sid": sid,
                        "ts": ts,
                        "role": (req.role or "user"),
                        "kind": (req.kind or "human"),
                        "author_username": u.username,
                        "author_alias": alias,
                        "content": req.content,
                        "meta": meta,
                    }
                },
            )
        except Exception:
            pass

        return {"ok": True, "msg_id": msg_id}

    # --- Live events (SSE) ---
    @r.get("/v1/projects/{pid}/sessions/{sid}/events")
    async def session_events(pid: str, sid: str, request: Request):
        """Subscribe to a live event stream for a session.

        Events:
        - message: a new persisted message
        - token: streamed assistant token for an in-flight model turn
        - done: end-of-turn marker
        - ping: keepalive
        """

        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        actor = _require_user_or_guest(app, request, pid, sid)
        u = actor["user"]
        pres: _PresenceStore = app.state.collab_presence
        alias = actor.get("alias") or (request.headers.get("X-User-Alias") or u.username).strip()
        token = (request.headers.get("X-Events-Token") or request.query_params.get("token") or secrets.token_hex(8)).strip()
        joined = pres.join(pid, sid, u.username, alias)
        try:
            print(f"[collab_events] open pid={pid} sid={sid} user={u.username} alias={alias} token={token}", flush=True)
        except Exception:
            pass

        try:
            app.state.collab_hub.publish(pid, sid, event="presence", data={"action": "join", "username": u.username, "alias": alias, "ts": _now_ts()})
        except Exception:
            pass

        # if EventSourceResponse is None:
        #     raise HTTPException(status_code=500, detail="SSE not available")

        hub: _SessionHub = app.state.collab_hub
        q = hub.subscribe(pid, sid)
        # print("subscribed to: ", pid, "__", sid)

        async def _gen():
            try:
                # hello
                yield _sse("ping", {"ok": True, "ts": _now_ts()})
                while True:
                    try:
                        stop_tokens = app.state.collab_stop_tokens
                        if stop_tokens.pop((pid, sid, token), None) is not None:
                            break
                    except Exception:
                        pass
                    if await request.is_disconnected():
                        break
                    try:
                        item = await asyncio.to_thread(lambda: q.get(timeout=5))
                    except queue.Empty:
                        yield _sse("ping", {"ok": True, "ts": _now_ts()})
                        continue

                    if not isinstance(item, dict):
                        continue
                    ev = (item.get("event") or "message")
                    data = item.get("data") or {}
                    yield _sse(str(ev), data)
                    # pres.touch(pid, sid, u.username)
            finally:
                try:
                    hub.unsubscribe(pid, sid, q)
                except Exception:
                    pass
                try:
                    print(f"[collab_events] close pid={pid} sid={sid} user={u.username} alias={alias} token={token}", flush=True)
                except Exception:
                    pass
                try:
                    pres.leave(pid, sid, u.username)
                    app.state.collab_hub.publish(pid, sid, event="presence", data={"action": "leave", "username": u.username, "alias": alias, "ts": _now_ts()})
                except Exception:
                    pass
                try:
                    app.state.collab_stop_tokens.pop((pid, sid, token), None)
                except Exception:
                    pass

        # return EventSourceResponse(_gen())
        return StreamingResponse(
            _gen(),
            media_type="text/event-stream",
            headers=dict(_SSE_STREAM_HEADERS),
        )

    @r.post("/v1/projects/{pid}/sessions/{sid}/events/leave")
    async def leave_events(pid: str, sid: str, request: Request):
        """Force-close an SSE subscription for a specific pid/sid/token."""
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_user_or_guest(app, request, pid, sid)
        token = (request.headers.get("X-Events-Token") or request.query_params.get("token") or "").strip()
        if token:
            try:
                app.state.collab_stop_tokens[(pid, sid, token)] = _now_ts()
            except Exception:
                pass
        return {"ok": True}

    # --- Model turns (streaming, persisted, broadcast to collaborators) ---
    # class ModelTurnRequest(BaseModel):
    #     prompt: str = Field(..., min_length=1)
    #     alias: Optional[str] = None
    #     client_msg_id: Optional[str] = None

    #     # Optional generation knobs (keep minimal so client can pass-through)
    #     temperature: Optional[float] = None
    #     max_tokens: Optional[int] = None
    #     top_p: Optional[float] = None
    #     stop: Optional[Any] = None

    #     # Optional: override system prompt
    #     system: Optional[str] = None

    # class ModelTurnRequest(BaseModel):
    #     prompt: Optional[str] = None
    #     alias: Optional[str] = None
    #     client_msg_id: Optional[str] = None

    #     # Optional generation knobs (keep minimal so client can pass-through)
    #     temperature: Optional[float] = None
    #     max_tokens: Optional[int] = None
    #     top_p: Optional[float] = None
    #     stop: Optional[Any] = None

    #     # Optional: override system prompt
    #     system: Optional[str] = None
    



        
    # ModelTurnRequest.model_rebuild()

    def _build_model_messages(
        *,
        pid: str,
        sid: str,
        system_prompt: str,
        limit: int = 80,
    ) -> List[Dict[str, str]]:
        """Build ChatCompletion-style messages from the persisted DB log."""
        msgs = db.list_messages(pid=pid, sid=sid, after_msg_id=None, since_ts=None, limit=limit)

        # detect multi-author user chat and prefix usernames for clarity
        authors = []
        for m in msgs:
            if (m.get("role") or "") == "user":
                au = (m.get("author_alias") or m.get("author_username") or "").strip()
                if au:
                    authors.append(au.lower())
        multi_author = len(set(authors)) > 1

        out: List[Dict[str, str]] = []
        sys_txt = (system_prompt or "").strip()
        if sys_txt:
            out.append({"role": "system", "content": sys_txt})

        for m in msgs:
            role = (m.get("role") or "user").strip() or "user"
            if role not in ("user", "assistant", "system"):
                role = "user"
            if role == "system":
                # avoid duplicating system prompts from clients (we manage it above)
                continue

            content = (m.get("content") or "")
            if role == "user" and multi_author:
                alias = (m.get("author_alias") or m.get("author_username") or "").strip()
                if alias:
                    content = f"{alias}: {content}"
            out.append({"role": role, "content": content})

        return out
    
    # @r.post("/v1/projects/{pid}/sessions/{sid}/model_turn_stream")
    # # async def model_turn_stream(body: ModelTurnRequest, pid: str, sid: str, request: Request):
    # async def model_turn_stream(body: ModelTurnRequest):
    #     print(235235234234)
    #     print(34324324324)
    #     print(23423523523)
    #     hub: _SessionHub = app.state.collab_hub
    #     turn_id = secrets.token_hex(10)



    @r.post("/v1/projects/{pid}/sessions/{sid}/model_turn_stream")
    async def model_turn_stream(body: ModelTurnRequest, pid: str, sid: str, request: Request):
    # async def model_turn_stream1(pid: str, sid: str, body: ModelTurnRequest):
        # print(235235234234)
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        actor = _require_user_or_guest(app, request, pid, sid, alias_value=body.alias)
        u = actor["user"]

        # if EventSourceResponse is None:
        #     raise HTTPException(status_code=500, detail="SSE not available")
        # print(34324324324)
        prompt = (body.prompt or "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="Empty prompt")

        # print(23423523523)
        hub: _SessionHub = app.state.collab_hub
        turn_id = secrets.token_hex(10)

        # Persist the user's message first (so late joiners will see it)
        user_msg_id = secrets.token_hex(12)
        ts_u = _now_ts()
        meta_u: Dict[str, Any] = {"turn_id": turn_id}
        if body.client_msg_id:
            meta_u["client_msg_id"] = body.client_msg_id
        alias_u = actor.get("alias") if actor["kind"] == "guest" else ((body.alias or "").strip() or u.username)
        if actor["kind"] == "guest":
            meta_u["is_guest"] = True

        db.add_message(
            msg_id=user_msg_id,
            pid=pid,
            sid=sid,
            ts=ts_u,
            role="user",
            kind="human",
            author_username=u.username,
            author_alias=alias_u,
            content=prompt,
            meta=meta_u,
        )

        # Broadcast the persisted user message
        try:
            hub.publish(
                pid,
                sid,
                event="message",
                data={
                    "msg": {
                        "msg_id": user_msg_id,
                        "pid": pid,
                        "sid": sid,
                        "ts": ts_u,
                        "role": "user",
                        "kind": "human",
                        "author_username": u.username,
                        "author_alias": alias_u,
                        "content": prompt,
                        "meta": meta_u,
                    }
                },
            )
        except Exception:
            pass

        prefs = db.get_gui_prefs_effective(pid, u.username) if actor["kind"] == "user" else {}
        router_cfg = _extract_router_config_from_prefs(prefs, pid, sid)
        settings_map = router_cfg.get("settings") if isinstance(router_cfg.get("settings"), dict) else {}
        agent_settings = settings_map.get("agent_flow") if isinstance(settings_map.get("agent_flow"), dict) else {}
        raw_active = str(agent_settings.get("agent_flow_active_flow") or "").strip()
        llm_autoflow_selected = raw_active == LLM_AUTOFLOW_FLOW_VALUE
        llm_skill_autoflow_selected = raw_active == LLM_SKILL_AUTOFLOW_FLOW_VALUE
        no_flow_selected = raw_active == NO_FLOW_VALUE or ("agent_flow_active_flow" in agent_settings and raw_active == "")
        active_flow = raw_active if raw_active and raw_active not in {NO_FLOW_VALUE, LLM_AUTOFLOW_FLOW_VALUE, LLM_SKILL_AUTOFLOW_FLOW_VALUE} else ""
        if not active_flow and not llm_autoflow_selected and not llm_skill_autoflow_selected:
            no_flow_selected = True
        llm_autoflow_cfg = settings_map.get("llm_autoflow") if isinstance(settings_map.get("llm_autoflow"), dict) else {}
        llm_skill_autoflow_cfg = settings_map.get("llm_skill_autoflow") if isinstance(settings_map.get("llm_skill_autoflow"), dict) else {}
        header_enabled = _parse_enabled_header(request.headers.get("X-Gui-Enabled-Plugins")) or set()
        llm_autoflow_enabled = (("llm_autoflow" in set(router_cfg.get("enabled") or [])) or ("llm_autoflow" in header_enabled)) and llm_autoflow_cfg.get("llm_autoflow_enabled", True) is not False
        llm_skill_autoflow_enabled = (("llm_skill_autoflow" in set(router_cfg.get("enabled") or [])) or ("llm_skill_autoflow" in header_enabled)) and llm_skill_autoflow_cfg.get("llm_skill_autoflow_enabled", True) is not False
        if llm_skill_autoflow_selected and llm_skill_autoflow_enabled:
            svc = ServiceChatRequest(
                message=prompt,
                alias=body.alias,
                client_msg_id=body.client_msg_id,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
                top_p=body.top_p,
            )
            asst_msg_id = secrets.token_hex(12)
            notice_ts = ts_u + 1
            ts_a0 = ts_u + 2
            meta_a: Dict[str, Any] = {"turn_id": turn_id, "streamed": True, "partial": True, "llm_skill_autoflow": True, "skills": True}
            if body.client_msg_id:
                meta_a["client_msg_id"] = str(body.client_msg_id)
            db.add_message(
                msg_id=asst_msg_id,
                pid=pid,
                sid=sid,
                ts=ts_a0,
                role="assistant",
                kind="model",
                author_username="assistant",
                author_alias="assistant",
                content="",
                meta=meta_a,
            )
            try:
                hub.publish(
                    pid,
                    sid,
                    event="message",
                    data={
                        "msg": {
                            "msg_id": asst_msg_id,
                            "pid": pid,
                            "sid": sid,
                            "ts": ts_a0,
                            "role": "assistant",
                            "kind": "model",
                            "author_username": "assistant",
                            "author_alias": "assistant",
                            "content": "",
                            "meta": meta_a,
                        }
                    },
                )
            except Exception:
                pass

            def _iter_chunks(text: str, size: int = 72):
                s = str(text or "")
                if not s:
                    return
                start_idx = 0
                n = len(s)
                while start_idx < n:
                    end_idx = min(n, start_idx + size)
                    if end_idx < n:
                        split = s.rfind(" ", start_idx, end_idx)
                        if split > start_idx:
                            end_idx = split + 1
                    piece = s[start_idx:end_idx]
                    if piece:
                        yield piece
                    start_idx = end_idx

            loop = asyncio.get_running_loop()
            q: asyncio.Queue = asyncio.Queue(maxsize=4096)

            def _worker_llm_skill_autoflow():
                full = ""
                notice_sent = False
                saw_live_tokens = False
                try:
                    def _forward_token(piece: str) -> None:
                        nonlocal full, saw_live_tokens
                        text_piece = str(piece or "")
                        if not text_piece:
                            return
                        saw_live_tokens = True
                        full += text_piece
                        evt_data = {
                            "turn_id": turn_id,
                            "pid": pid,
                            "sid": sid,
                            "role": "assistant",
                            "origin": u.username,
                            "text": text_piece,
                            "msg_id": asst_msg_id,
                        }
                        try:
                            hub.publish(pid, sid, event="token", data=evt_data)
                        except Exception:
                            pass
                        try:
                            loop.call_soon_threadsafe(q.put_nowait, ("token", text_piece))
                        except Exception:
                            pass
                        try:
                            if len(full) == len(text_piece) or (len(full) % 256) < len(text_piece):
                                db.set_message_content(msg_id=asst_msg_id, content=full)
                        except Exception:
                            pass

                    def _on_internal_event(event_name: str, payload: Any) -> None:
                        nonlocal notice_sent
                        if event_name == "token" and isinstance(payload, dict):
                            _forward_token(str(payload.get("text") or ""))
                            return
                        if event_name != "diag" or not isinstance(payload, dict):
                            return
                        status_text = str(payload.get("router_status") or "").strip()
                        if status_text.startswith("skill_notice:"):
                            notice_text = status_text.split(":", 1)[1].strip()
                            if not notice_text or notice_sent:
                                return
                            notice_sent = True
                            diag_payload = {"router_status": notice_text, "route_id": "llm_skill_autoflow", "skill_notice": True}
                            try:
                                hub.publish(pid, sid, event="diag", data=dict(diag_payload))
                            except Exception:
                                pass
                            try:
                                loop.call_soon_threadsafe(q.put_nowait, ("diag", dict(diag_payload)))
                            except Exception:
                                pass
                            return
                        try:
                            hub.publish(pid, sid, event="diag", data=dict(payload))
                        except Exception:
                            pass
                        try:
                            loop.call_soon_threadsafe(q.put_nowait, ("diag", dict(payload)))
                        except Exception:
                            pass

                    computed = asyncio.run_coroutine_threadsafe(
                        _compute_llm_skill_autoflow_result(pid, sid, prompt, svc, router_cfg, request, on_event=_on_internal_event),
                        loop,
                    ).result()
                    assistant_text = str(computed.get("assistant_text") or "").strip()
                    rr = computed.get("router_result") if isinstance(computed.get("router_result"), dict) else {}
                    if not notice_sent:
                        pre_tool_message = str(computed.get("pre_tool_message") or "").strip()
                        if pre_tool_message and pre_tool_message != assistant_text:
                            _on_internal_event("diag", {"router_status": f"skill_notice:{pre_tool_message}"})
                    if not saw_live_tokens:
                        try:
                            retry_count = 0
                            action_history = list(rr.get("action_history") or [])
                            if action_history:
                                stream_iter = _stream_llm_skill_autoflow_verified_answer(
                                    app=app,
                                    user_text=prompt,
                                    settings=dict(computed.get("llm_skill_settings") or {}),
                                    selected_categories=list(rr.get("selected_categories") or []),
                                    action_history=action_history,
                                    fallback_text=assistant_text,
                                )
                            else:
                                stream_iter = _stream_llm_skill_autoflow_direct_answer(
                                    app=app,
                                    user_text=prompt,
                                    settings=dict(computed.get("llm_skill_settings") or {}),
                                    draft_text=assistant_text,
                                )
                            for piece in stream_iter or []:
                                retry_count += 1
                                _forward_token(piece)
                        except Exception:
                            pass
                    if not saw_live_tokens and assistant_text:
                        for piece in _iter_chunks(assistant_text, size=24):
                            _forward_token(piece)
                    if not saw_live_tokens:
                        full = assistant_text
                    elif assistant_text and assistant_text != full:
                        full = assistant_text
                    db.set_message_content(msg_id=asst_msg_id, content=full)
                    try:
                        hub.publish(
                            pid,
                            sid,
                            event="message",
                            data={
                                "msg": {
                                    "msg_id": asst_msg_id,
                                    "pid": pid,
                                    "sid": sid,
                                    "ts": _now_ts(),
                                    "role": "assistant",
                                    "kind": "model",
                                    "author_username": "assistant",
                                    "author_alias": "assistant",
                                    "content": full,
                                    "meta": {"turn_id": turn_id, "streamed": True, "partial": False, "llm_skill_autoflow": True, "skills": True},
                                }
                            },
                        )
                    except Exception:
                        pass
                    try:
                        hub.publish(pid, sid, event="done", data={"turn_id": turn_id, "ok": True, "msg_id": asst_msg_id})
                    except Exception:
                        pass
                    try:
                        loop.call_soon_threadsafe(q.put_nowait, ("done", None))
                    except Exception:
                        pass
                except Exception as exc:
                    err = str(exc) or "llm_skill_autoflow_failed"
                    try:
                        db.set_message_content(msg_id=asst_msg_id, content=full)
                    except Exception:
                        pass
                    try:
                        hub.publish(pid, sid, event="done", data={"turn_id": turn_id, "ok": False, "error": err, "msg_id": asst_msg_id})
                    except Exception:
                        pass
                    try:
                        loop.call_soon_threadsafe(q.put_nowait, ("error", err))
                    except Exception:
                        pass

            threading.Thread(target=_worker_llm_skill_autoflow, daemon=True).start()

            async def _gen_llm_skill_autoflow():
                try:
                    yield _sse("turn", {"turn_id": turn_id, "origin": u.username, "ts": _now_ts(), "msg_id": asst_msg_id})
                    while True:
                        typ, payload = await q.get()
                        if typ == "token":
                            yield _sse(
                                "token",
                                {
                                    "turn_id": turn_id,
                                    "pid": pid,
                                    "sid": sid,
                                    "role": "assistant",
                                    "origin": u.username,
                                    "text": str(payload or ""),
                                    "msg_id": asst_msg_id,
                                },
                            )
                            continue
                        if typ == "message":
                            yield _sse("message", {"msg": payload if isinstance(payload, dict) else {}})
                            continue
                        if typ == "diag":
                            yield _sse("diag", payload if isinstance(payload, dict) else {"msg": str(payload or "")})
                            continue
                        if typ == "error":
                            yield _sse("diag", {"turn_id": turn_id, "error": str(payload or "llm_skill_autoflow_failed"), "msg_id": asst_msg_id})
                            yield _sse("done", {"turn_id": turn_id, "ok": False, "msg_id": asst_msg_id})
                            break
                        yield _sse("done", {"turn_id": turn_id, "ok": True, "msg_id": asst_msg_id})
                        break
                finally:
                    pass

            return StreamingResponse(_gen_llm_skill_autoflow(), media_type="text/event-stream")
        if llm_autoflow_selected and llm_autoflow_enabled:
            svc = ServiceChatRequest(
                message=prompt,
                alias=body.alias,
                client_msg_id=body.client_msg_id,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
                top_p=body.top_p,
            )
            asst_msg_id = secrets.token_hex(12)
            ts_a0 = _now_ts()
            meta_a = {"turn_id": turn_id, "streamed": True, "partial": True, "llm_autoflow": True, "flow": True}
            db.add_message(
                msg_id=asst_msg_id,
                pid=pid,
                sid=sid,
                ts=ts_a0,
                role="assistant",
                kind="model",
                author_username="assistant",
                author_alias="assistant",
                content="",
                meta=meta_a,
            )
            try:
                hub.publish(
                    pid,
                    sid,
                    event="message",
                    data={
                        "msg": {
                            "msg_id": asst_msg_id,
                            "pid": pid,
                            "sid": sid,
                            "ts": ts_a0,
                            "role": "assistant",
                            "kind": "model",
                            "author_username": "assistant",
                            "author_alias": "assistant",
                            "content": "",
                            "meta": meta_a,
                        }
                    },
                )
            except Exception:
                pass

            q = asyncio.Queue(maxsize=4096)

            def _worker_llm_autoflow():
                full = ""
                saw_live_tokens = False
                try:
                    settings_map = router_cfg.get("settings") if isinstance(router_cfg.get("settings"), dict) else {}
                    llm_autoflow_cfg = settings_map.get("llm_autoflow") if isinstance(settings_map.get("llm_autoflow"), dict) else {}
                    llm_autoflow_cfg = {**llm_autoflow_cfg, "llm_autoflow_enabled": True}
                    ext = {
                        "last_user_content": prompt,
                        "llm_autoflow_settings": llm_autoflow_cfg,
                        "project_id": pid,
                        "session_id": sid,
                        "session-id": sid,
                        "sid": sid,
                    }
                    if settings_map:
                        ext["router_plugin_settings"] = settings_map

                    def _forward_token(piece: str) -> None:
                        nonlocal full, saw_live_tokens
                        text_piece = str(piece or "")
                        if not text_piece:
                            return
                        saw_live_tokens = True
                        full += text_piece
                        evt_data = {
                            "turn_id": turn_id,
                            "pid": pid,
                            "sid": sid,
                            "role": "assistant",
                            "origin": u.username,
                            "text": text_piece,
                            "msg_id": asst_msg_id,
                        }
                        try:
                            hub.publish(pid, sid, event="token", data=evt_data)
                        except Exception:
                            pass
                        try:
                            loop.call_soon_threadsafe(q.put_nowait, ("token", text_piece))
                        except Exception:
                            pass
                        try:
                            if len(full) == len(text_piece) or (len(full) % 256) < len(text_piece):
                                db.set_message_content(msg_id=asst_msg_id, content=full)
                        except Exception:
                            pass

                    def _on_internal_event(event_name: str, payload: Any) -> None:
                        if event_name == "token" and isinstance(payload, dict):
                            _forward_token(str(payload.get("text") or ""))
                            return
                        if event_name != "diag" or not isinstance(payload, dict):
                            return
                        try:
                            hub.publish(pid, sid, event="diag", data=dict(payload))
                        except Exception:
                            pass
                        try:
                            loop.call_soon_threadsafe(q.put_nowait, ("diag", dict(payload)))
                        except Exception:
                            pass

                    select_res = asyncio.run_coroutine_threadsafe(
                        _internal_sse_request(
                            app,
                            method="POST",
                            path="/v1/chat/completions_stream",
                            headers=_internal_service_headers(request, pid=pid, sid=sid, enabled_plugins=["llm_autoflow", "autoflow", "agent_flow"], suppress_persist=True),
                            body={
                                "model": "",
                                "messages": [{"role": "user", "content": prompt}],
                                "backend_type": "auto",
                                "route_id": "llm_autoflow",
                                "router_enabled_plugins": ["llm_autoflow"],
                                "ext": ext,
                                "sid": sid,
                            },
                            timeout_s=240.0,
                            on_event=_on_internal_event,
                        ),
                        loop,
                    ).result()
                    rr = {}
                    router_evt = select_res.get("router") if isinstance(select_res, dict) else {}
                    if isinstance(router_evt, dict):
                        rr = router_evt.get("router_result") if isinstance(router_evt.get("router_result"), dict) else {}
                    rr = rr if isinstance(rr, dict) else {}
                    assistant_text = _strip_reasoning_artifacts(_repair_common_mojibake(str(rr.get("assistant_response") or rr.get("text") or ""))).strip()
                    if not assistant_text:
                        action_history = rr.get("action_history") if isinstance(rr.get("action_history"), list) else []
                        if action_history:
                            last_action = action_history[-1] if isinstance(action_history[-1], dict) else {}
                            assistant_text = _strip_reasoning_artifacts(_repair_common_mojibake(str(last_action.get("result_text") or ""))).strip()
                    if not saw_live_tokens and assistant_text:
                        try:
                            for piece in _stream_llm_autoflow_direct_answer(
                                app=app,
                                user_text=prompt,
                                settings=llm_autoflow_cfg,
                                draft_text=assistant_text,
                            ) or []:
                                _forward_token(piece)
                        except Exception:
                            pass
                    if not saw_live_tokens:
                        full = assistant_text
                    elif assistant_text and assistant_text != full:
                        full = assistant_text
                    db.set_message_content(msg_id=asst_msg_id, content=full)
                    try:
                        hub.publish(
                            pid,
                            sid,
                            event="message",
                            data={
                                "msg": {
                                    "msg_id": asst_msg_id,
                                    "pid": pid,
                                    "sid": sid,
                                    "ts": _now_ts(),
                                    "role": "assistant",
                                    "kind": "model",
                                    "author_username": "assistant",
                                    "author_alias": "assistant",
                                    "content": full,
                                    "meta": {"turn_id": turn_id, "streamed": True, "partial": False, "llm_autoflow": True, "flow": True},
                                }
                            },
                        )
                    except Exception:
                        pass
                    try:
                        hub.publish(pid, sid, event="done", data={"turn_id": turn_id, "ok": True, "msg_id": asst_msg_id})
                    except Exception:
                        pass
                    try:
                        loop.call_soon_threadsafe(q.put_nowait, ("done", None))
                    except Exception:
                        pass
                except Exception as exc:
                    err = str(exc) or "llm_autoflow_failed"
                    try:
                        db.set_message_content(msg_id=asst_msg_id, content=full)
                    except Exception:
                        pass
                    try:
                        hub.publish(pid, sid, event="done", data={"turn_id": turn_id, "ok": False, "error": err, "msg_id": asst_msg_id})
                    except Exception:
                        pass
                    try:
                        loop.call_soon_threadsafe(q.put_nowait, ("error", err))
                    except Exception:
                        pass

            threading.Thread(target=_worker_llm_autoflow, daemon=True).start()

            async def _gen_llm_autoflow():
                try:
                    yield _sse("turn", {"turn_id": turn_id, "origin": u.username, "ts": _now_ts(), "msg_id": asst_msg_id})
                    while True:
                        typ, payload = await q.get()
                        if typ == "token":
                            yield _sse(
                                "token",
                                {
                                    "turn_id": turn_id,
                                    "pid": pid,
                                    "sid": sid,
                                    "role": "assistant",
                                    "origin": u.username,
                                    "text": str(payload or ""),
                                    "msg_id": asst_msg_id,
                                },
                            )
                            continue
                        if typ == "diag":
                            yield _sse("diag", payload if isinstance(payload, dict) else {"msg": str(payload or "")})
                            continue
                        if typ == "error":
                            yield _sse("diag", {"turn_id": turn_id, "error": str(payload or "llm_autoflow_failed"), "msg_id": asst_msg_id})
                            yield _sse("done", {"turn_id": turn_id, "ok": False, "msg_id": asst_msg_id})
                            break
                        yield _sse("done", {"turn_id": turn_id, "ok": True, "msg_id": asst_msg_id})
                        break
                finally:
                    pass

            return StreamingResponse(_gen_llm_autoflow(), media_type="text/event-stream")

        # Create a placeholder assistant message immediately so the turn exists server-side
        # even if the requesting client disconnects mid-stream.
        asst_msg_id = secrets.token_hex(12)
        ts_a0 = _now_ts()
        meta_a: Dict[str, Any] = {"turn_id": turn_id, "streamed": True, "partial": True}
        db.add_message(
            msg_id=asst_msg_id,
            pid=pid,
            sid=sid,
            ts=ts_a0,
            role="assistant",
            kind="model",
            author_username="assistant",
            author_alias="assistant",
            content="",
            meta=meta_a,
        )

        # Broadcast the placeholder assistant message (clients can render a streaming bubble)
        try:
            hub.publish(
                pid,
                sid,
                event="message",
                data={
                    "msg": {
                        "msg_id": asst_msg_id,
                        "pid": pid,
                        "sid": sid,
                        "ts": ts_a0,
                        "role": "assistant",
                        "kind": "model",
                        "author_username": "assistant",
                        "author_alias": "assistant",
                        "content": "",
                        "meta": meta_a,
                    }
                },
            )
        except Exception:
            pass

        # Build messages for the model from persisted history
        settings_fn = getattr(app.state, "settings", None)
        settings = settings_fn() if callable(settings_fn) else {}
        sys_default = str(settings.get("default_system") or settings.get("system") or "You are a helpful assistant.")
        system_prompt = (body.system or sys_default)
        model_msgs = _build_model_messages(pid=pid, sid=sid, system_prompt=system_prompt, limit=90)

        # Pull the active model from app.state (same instance used by /v1/chat/...)
        model_fn = getattr(app.state, "model", None)
        model_obj = model_fn() if callable(model_fn) else None
        if model_obj is None or not hasattr(model_obj, "stream_chat"):
            raise HTTPException(status_code=503, detail="Model not available")

        # Stream tokens from the model in a background thread
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue(maxsize=4096)

        # def _worker():
        #     try:
        #         stream_iter = model_obj.stream_chat(
        #             messages=model_msgs,
        #             max_new_tokens=int(req.max_tokens or settings.get("max_tokens", 512)),
        #             temperature=float(req.temperature if req.temperature is not None else settings.get("temperature", 0.2)),
        #             top_p=float(req.top_p if req.top_p is not None else settings.get("top_p", 0.95)),
        #             stop=req.stop,
        #             cancel_cb=lambda: False,
        #         )
        #         for piece in stream_iter:
        #             if not piece:
        #                 continue
        #             loop.call_soon_threadsafe(q.put_nowait, ("token", piece))
        #         loop.call_soon_threadsafe(q.put_nowait, ("done", None))
        #     except Exception as e:
        #         loop.call_soon_threadsafe(q.put_nowait, ("error", str(e)))

        def _worker():
            full = ""
            last_flush = time.time()
            last_saved_len = 0

            try:
                lock_fn = getattr(app.state, "get_model_lock", None)
                model_key = f"inst:{id(model_obj)}"
                lock = lock_fn(model_key) if callable(lock_fn) else None
                def _stream():
                    return model_obj.stream_chat(
                        messages=model_msgs,
                        max_new_tokens=int(body.max_tokens or settings.get("max_tokens", 512)),
                        temperature=float(body.temperature if body.temperature is not None else settings.get("temperature", 0.2)),
                        top_p=float(body.top_p if body.top_p is not None else settings.get("top_p", 0.95)),
                        stop=body.stop,
                        cancel_cb=lambda: False,
                    )

                stream_iter = _stream() if lock is None else (piece for piece in _locked_stream(lock, _stream))

                for piece in stream_iter:
                    if not piece:
                        continue

                    txt = str(piece)
                    full += txt

                    # Broadcast tokens to collaborators immediately (independent of the requester SSE connection)
                    evt_data = {
                        "turn_id": turn_id,
                        "pid": pid,
                        "sid": sid,
                        "role": "assistant",
                        "origin": u.username,
                        "text": txt,
                        "msg_id": asst_msg_id,
                    }
                    try:
                        hub.publish(pid, sid, event="token", data=evt_data)
                    except Exception:
                        pass

                    # Feed the requester stream (best-effort)
                    try:
                        loop.call_soon_threadsafe(q.put_nowait, ("token", txt))
                    except Exception:
                        pass

                    # Periodically persist partial content so it's never lost
                    now = time.time()
                    if (len(full) - last_saved_len) >= 256 or (now - last_flush) >= 0.5:
                        try:
                            db.set_message_content(msg_id=asst_msg_id, content=full)
                            last_saved_len = len(full)
                            last_flush = now
                        except Exception:
                            pass

                # Final persist + finalize meta (meta stays as-is in DB; we mark completion via events)
                try:
                    db.set_message_content(msg_id=asst_msg_id, content=full)
                except Exception:
                    pass

                # Broadcast final full assistant message (clients can update the bubble deterministically)
                try:
                    hub.publish(
                        pid,
                        sid,
                        event="message",
                        data={
                            "msg": {
                                "msg_id": asst_msg_id,
                                "pid": pid,
                                "sid": sid,
                                "ts": _now_ts(),
                                "role": "assistant",
                                "kind": "model",
                                "author_username": "assistant",
                                "author_alias": "assistant",
                                "content": full,
                                "meta": {"turn_id": turn_id, "streamed": True, "partial": False},
                            }
                        },
                    )
                except Exception:
                    pass

                # Broadcast done
                try:
                    hub.publish(pid, sid, event="done", data={"turn_id": turn_id, "ok": True, "msg_id": asst_msg_id})
                except Exception:
                    pass

                try:
                    loop.call_soon_threadsafe(q.put_nowait, ("done", None))
                except Exception:
                    pass

            except Exception as e:
                err = str(e) or "model_error"

                # Persist whatever we have so far (best-effort)
                try:
                    db.set_message_content(msg_id=asst_msg_id, content=full)
                except Exception:
                    pass

                try:
                    hub.publish(pid, sid, event="done", data={"turn_id": turn_id, "ok": False, "error": err, "msg_id": asst_msg_id})
                except Exception:
                    pass

                try:
                    loop.call_soon_threadsafe(q.put_nowait, ("error", err))
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True).start()

        # async def _gen():
        #     acc: List[str] = []
        #     try:
        #         yield _sse("turn", {"turn_id": turn_id, "origin": u.username, "ts": _now_ts()})
        #         while True:
        #             typ, payload = await q.get()
        #             if typ == "token":
        #                 txt = str(payload)
        #                 acc.append(txt)

        #                 evt_data = {
        #                     "turn_id": turn_id,
        #                     "pid": pid,
        #                     "sid": sid,
        #                     "role": "assistant",
        #                     "origin": u.username,
        #                     "text": txt,
        #                 }
        #                 # broadcast to other clients
        #                 try:
        #                     hub.publish(pid, sid, event="token", data=evt_data)
        #                 except Exception:
        #                     pass
        #                 yield _sse("token", evt_data)
        #                 continue

        #             if typ == "error":
        #                 err = str(payload or "model_error")
        #                 yield _sse("diag", {"turn_id": turn_id, "error": err})
        #                 # also broadcast an end marker to unblock clients
        #                 try:
        #                     hub.publish(pid, sid, event="done", data={"turn_id": turn_id, "ok": False, "error": err})
        #                 except Exception:
        #                     pass
        #                 break

        #             # done
        #             full = "".join(acc)

        #             # persist assistant
        #             if full:
        #                 asst_msg_id = secrets.token_hex(12)
        #                 ts_a = _now_ts()
        #                 meta_a = {"turn_id": turn_id, "streamed": True}
        #                 db.add_message(
        #                     msg_id=asst_msg_id,
        #                     pid=pid,
        #                     sid=sid,
        #                     ts=ts_a,
        #                     role="assistant",
        #                     kind="model",
        #                     author_username=u.username,
        #                     author_alias=(alias_u or u.username),
        #                     content=full,
        #                     meta=meta_a,
        #                 )
        #                 try:
        #                     hub.publish(
        #                         pid,
        #                         sid,
        #                         event="message",
        #                         data={
        #                             "msg": {
        #                                 "msg_id": asst_msg_id,
        #                                 "pid": pid,
        #                                 "sid": sid,
        #                                 "ts": ts_a,
        #                                 "role": "assistant",
        #                                 "kind": "model",
        #                                 "author_username": u.username,
        #                                 "author_alias": (alias_u or u.username),
        #                                 "content": full,
        #                                 "meta": meta_a,
        #                             }
        #                         },
        #                     )
        #                 except Exception:
        #                     pass

        #             # broadcast done
        #             try:
        #                 hub.publish(pid, sid, event="done", data={"turn_id": turn_id, "ok": True})
        #             except Exception:
        #                 pass
        #             yield _sse("done", {"turn_id": turn_id, "ok": True})
        #             break
        #     finally:
        #         # ensure UI can reuse streaming block
        #         pass

        async def _gen():
            try:
                yield _sse("turn", {"turn_id": turn_id, "origin": u.username, "ts": _now_ts(), "msg_id": asst_msg_id})
                while True:
                    typ, payload = await q.get()
                    if typ == "token":
                        yield _sse(
                            "token",
                            {
                                "turn_id": turn_id,
                                "pid": pid,
                                "sid": sid,
                                "role": "assistant",
                                "origin": u.username,
                                "text": str(payload),
                                "msg_id": asst_msg_id,
                            },
                        )
                        continue

                    if typ == "error":
                        yield _sse("diag", {"turn_id": turn_id, "error": str(payload or "model_error"), "msg_id": asst_msg_id})
                        yield _sse("done", {"turn_id": turn_id, "ok": False, "msg_id": asst_msg_id})
                        break

                    # done
                    yield _sse("done", {"turn_id": turn_id, "ok": True, "msg_id": asst_msg_id})
                    break
            finally:
                pass

        # return EventSourceResponse(_gen())
        return StreamingResponse(
                _gen(),
                media_type="text/event-stream",
            )

    app.include_router(r)



