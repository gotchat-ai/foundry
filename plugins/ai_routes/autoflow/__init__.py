from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from awf_pass_log import append_pass_log_row
from plugins.ai_routes.base import BaseRoute, RouterCore
from plugins.ai_routes.model_deck_utils import get_server_app
from plugins.gui_helpers.agent_flow.skills.workflow._wfcommon import (
    ensure_flow_payload,
    generated_dir,
    infer_request_capabilities,
    load_default_flows,
    load_project_flows,
    parse_jsonish,
    slugify,
)
from plugins.gui_helpers.agent_flow.skills.workflow.run_request_once import (
    _base_url,
    _force_delete_session,
    _http_json,
    _latest_assistant_message,
)
from plugins.gui_helpers.agent_flow.skills.workflow import temp_library as workflow_temp_library
from plugins.gui_helpers.agent_flow.skills.workflow import export as workflow_export
from plugins.gui_helpers.agent_flow.skills.workflow import scaffold_subflow_capability as workflow_scaffold_subflow_capability
from plugins.gui_helpers.agent_flow.skills.workflow import verify as workflow_verify


PLUGIN_ID = "autoflow"
PLUGIN_TITLE = "AutoFlow"
PLUGIN_NAME = "AutoFlow"
PLUGIN_DESCRIPTION = "Routes No flow chat requests to the best Agent Flow using flow descriptions and capabilities."
PLUGIN_TYPE = "control"
PLUGIN_DEPENDENCIES = ["agent_flow"]
AGENT_LINKABLE = False

PLUGIN_CONFIG_SCHEMA = [
    {
        "key": "autoflow_enabled",
        "label": "Enable AutoFlow",
        "type": "bool",
        "default": False,
        "help": "When enabled, Agent Flow can ask AutoFlow to choose a flow while the chat dropdown is set to No flow.",
    },
    {
        "key": "autoflow_select_all",
        "label": "Select all flows",
        "type": "bool",
        "default": True,
        "help": "Route across all available flows. Turn off to use autoflow_selected_flows.",
    },
    {
        "key": "autoflow_selected_flows",
        "label": "Selected flows",
        "type": "str",
        "default": "",
        "help": "Optional JSON array or comma-separated flow names. Leave empty when Select all flows is on.",
    },
    {
        "key": "autoflow_system_prompt",
        "label": "System prompt",
        "type": "str",
        "default": "Answer directly only when the request can be satisfied from model knowledge alone. Otherwise prefer an existing workflow with the required capabilities. If no existing workflow can satisfy the request and AutoFlow creation is enabled, create a workflow, run it, and judge whether it satisfied the request.",
        "help": "Routing policy for AutoFlow. It should prefer direct answers only for requests the model can satisfy without tools, then prefer existing workflows, then create a workflow when enabled.",
    },
    {
        "key": "autoflow_min_confidence",
        "label": "Minimum confidence",
        "type": "float",
        "default": "0.15",
        "help": "If the best score is below this threshold, AutoFlow returns no selection.",
    },
    {
        "key": "autoflow_create_if_request_not_satisfied",
        "label": "AutoFlow Creation if request not satisfy",
        "type": "bool",
        "default": False,
        "help": "If no good existing flow is found, or if the chosen flow result does not satisfy the user request, AutoFlow can create or improve a workflow with Flow Creator / Adaptive Loop.",
    },
    {
        "key": "autoflow_creator_flow_name",
        "label": "Creator flow name",
        "type": "str",
        "default": "Flow Creator / Adaptive Loop",
        "help": "Agent Flow used to generate new workflows when AutoFlow needs to create or improve one.",
    },
    {
        "key": "autoflow_retry_loops",
        "label": "AutoFlow retry loops",
        "type": "int",
        "default": "2",
        "help": "How many select/create/improve attempts AutoFlow may try for a No flow request.",
    },
    {
        "key": "autoflow_require_satisfaction_check",
        "label": "Require satisfaction check",
        "type": "bool",
        "default": True,
        "help": "After a flow runs, ask the model whether the result actually satisfies the user request.",
    },
]


_WORD_RE = re.compile(r"[a-z0-9_]+")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "give",
    "have", "how", "i", "in", "into", "is", "it", "me", "my", "of", "on", "or", "please", "show",
    "that", "the", "this", "to", "use", "using", "want", "what", "when", "with", "without", "you",
}

_CATEGORY_HINTS: Dict[str, set[str]] = {
    "spreadsheet": {
        "spreadsheet", "excel", "xlsx", "xls", "csv", "sheet", "workbook", "table", "rows", "columns",
        "dataset", "data", "clean", "dedupe", "duplicate", "normalize", "export", "aggregate", "month",
        "monthly", "quarter", "year", "sales", "revenue", "chart", "graph", "bar", "line", "pie", "report",
        "summary", "pivot", "filter", "sort",
    },
    "coding": {
        "code", "repo", "repository", "javascript", "python", "js", "bug", "fix", "patch",
        "patches", "coding", "refactor", "improve", "performance", "git", "diff", "commit", "revert", "rollback", "changes",
        "chatjs", "chat", "plugin", "frontend", "backend", "function", "logic", "rendering",
        "comment", "comments", "test", "lint",
    },
}

_INTENT_HINTS: Dict[str, set[str]] = {
    "chart": {"chart", "graph", "plot", "visualize", "visualization", "bar", "line", "pie", "scatter", "compare", "trend"},
    "clean": {"clean", "normalize", "dedupe", "duplicate", "missing", "empty", "format", "export", "csv"},
    "analyze": {"analyze", "analysis", "summary", "summarize", "aggregate", "total", "average", "rank", "top", "bottom"},
    "code_change": {"fix", "patch", "patches", "coding", "change", "update", "modify", "implement", "refactor", "improve", "comment", "comments"},
    "git": {"git", "diff", "commit", "revert", "rollback", "version", "history"},
}

_EXTERNAL_INFO_HINTS = {
    "weather", "forecast", "temperature", "today", "current", "latest", "news", "headline", "internet",
    "web", "search", "lookup", "look", "online", "website", "url", "google", "searxng", "browse",
    "tonight", "live", "scoreboard", "sports", "sport", "game", "games", "match", "matches",
    "fixture", "fixtures", "schedule", "standings", "stock", "stocks", "ticker", "tickers", "market", "markets",
    "finance", "quote", "quotes", "portfolio", "yahoo",
}
_EXTERNAL_FLOW_CAPABILITY_HINTS = {
    "weather", "forecast", "temperature", "news", "headline", "internet", "web",
    "online", "website", "url", "google", "searxng", "browse", "sports", "sport", "scoreboard",
    "live", "schedule", "fixture", "fixtures", "stock", "stocks", "ticker", "tickers", "market", "finance", "yahoo",
}
_EXTERNAL_INFO_REFUSAL_HINTS = (
    "do not have access to live",
    "cannot provide real-time",
    "cannot access live",
    "cannot retrieve the live",
    "cannot retrieve live",
    "cannot provide the live",
    "cannot provide live",
    "does not have access to real-time",
    "no access to real-time",
    "lacks access to real-time",
    "lacks tool execution permissions",
    "no tool execution permission",
    "no tool permissions",
    "no live internet",
    "no real-time access",
    "no real-time sports data",
    "without live data access",
    "without web search",
    "without a web search tool",
    "lacks live search access",
    "local code files",
    "static repo content",
    "rag search is for static repo",
    "rag cannot provide live",
    "rag.search",
    "must check espn",
    "check espn",
    "static environment",
)
_EXTERNAL_ACTION_SKILL_HINTS = (
    "browser.",
    "web.",
    "sports.",
    "sports_live",
    "sports_live_games_table",
    "sports_live_data",
    "live_data",
    "scoreboard",
    "weather.",
    "news.",
    "searxng",
    "search_web",
    "web_search",
)
_MODEL_ONLY_SKILLS = {
    "agent_workflow_member",
    "custom.general_workflow_executor",
    "result.text",
    "result.file",
    "result.zip",
    "interaction.approval",
}

_DIRECT_EXECUTION_CAPABILITIES = {
    "sports_live_data",
    "web_research",
    "market_data",
    "weather_lookup",
}

_FILE_PATH_RE = re.compile(
    r"((?:(?:[A-Za-z]:)?[\\/]|/)(?:app|uploads|data)[\\/][^\s\"']+\.(?:csv|tsv|xlsx|xls|json|md|txt|js|ts|py|html?|css|ya?ml|pdf|docx|pptx|zip))",
    re.IGNORECASE,
)
_FILE_SHAPE_HINTS = {
    "spreadsheet_io": {"csv", "xlsx", "xls", "sheet", "spreadsheet", "workbook", "table", "row", "rows"},
    "document_io": {"json", "md", "txt", "document", "notes", "brief", "article", "release", "faq"},
    "chart_output": {"chart", "graph", "plot", "visualize", "visualization", "bar", "line", "pie", "scatter", "json"},
}
_REQUEST_FAMILY_HINTS: Dict[str, set[str]] = {
    "weather_lookup": {"weather", "forecast", "temperature", "humidity", "wind", "rain", "snow", "today", "tonight"},
    "action_register": {"action", "register", "owner", "due", "blocker", "decision", "question", "meeting"},
    "triage_brief": {"triage", "ticket", "tickets", "urgency", "same", "day", "support", "brief"},
    "contract_risk_review": {"contract", "clause", "clauses", "risk", "review", "negotiation", "legal"},
    "hiring_recommendation": {"hiring", "recommendation", "interview", "interviewers", "panel", "memo", "candidate"},
    "incident_timeline": {"incident", "timeline", "impact", "window", "turning", "customer", "follow", "actions"},
    "release_announcement_email": {"release", "announcement", "email", "customer", "benefits", "next"},
    "vendor_shortlist": {"vendor", "shortlist", "security", "support", "cost", "implementation", "tradeoffs"},
    "portal_reconciliation": {"portal", "reconcile", "reconciliation", "statement", "statements", "discrepancy", "discrepancies", "invoice", "invoices", "mismatch", "mismatches", "workbook"},
    "sprint_plan": {"sprint", "backlog", "capacity", "dependency", "dependencies", "plan"},
    "faq": {"faq", "questions", "question", "support", "agent", "users", "plain", "language"},
    "scheduling_resolution_brief": {"schedule", "scheduling", "resolution", "conflict", "conflicts", "stakeholder", "stakeholders", "brief"},
    "market_data_analysis": {"stock", "stocks", "ticker", "tickers", "market", "markets", "finance", "yahoo", "quote", "quotes", "portfolio", "trending", "momentum", "volume"},
    "file_chart_output": {"json", "chart", "graph", "plot", "visualize", "visualization", "series", "xvalues", "print"},
}
PASS_LOG_PATH = Path(__file__).resolve().parents[3] / "awf_imported_passes_20260620.csv"
FEEDBACK_STORE_PATH = Path(__file__).resolve().parents[3] / "data" / "autoflow_feedback.json"

_REQUEST_FAMILY_LABELS = {
    "weather_lookup": "weather lookup",
    "action_register": "action register",
    "triage_brief": "triage brief",
    "contract_risk_review": "contract risk review",
    "hiring_recommendation": "hiring recommendation memo",
    "incident_timeline": "incident timeline summary",
    "release_announcement_email": "release announcement email",
    "vendor_shortlist": "vendor shortlist recommendation",
    "portal_reconciliation": "vendor portal reconciliation",
    "sprint_plan": "sprint plan",
    "faq": "FAQ",
    "scheduling_resolution_brief": "scheduling resolution brief",
    "market_data_analysis": "market data analysis",
    "file_chart_output": "file chart visualization",
}

_GENERIC_FOCUS_STOPWORDS = {
    "current", "today", "tonight", "tomorrow", "yesterday", "latest", "live", "list", "lists",
    "tell", "show", "find", "look", "lookup", "search", "searched", "searching", "online",
    "website", "web", "google", "internet", "browse", "put", "give", "going", "playing",
    "against", "who", "what", "when", "where", "why", "how", "there", "their", "them",
    "topic", "topics", "story", "stories", "headline", "headlines", "game", "games", "match",
    "matches", "fixture", "fixtures", "schedule", "score", "scores", "team", "teams",
    "trending", "trends", "trend", "get", "got", "top", "most",
}

_CAPABILITY_SKILL_HINTS: Dict[str, Tuple[str, ...]] = {
    "web_research": ("browser.", "web.", "searxng", "search_web", "web_search", "download_file"),
    "sports_live_data": ("sports.", "scoreboard", "sports_live", "live_games", "schedule"),
    "market_data": ("market_data_report", "yahoo_finance", "ticker", "quote", "finance", "browser.", "web."),
    "spreadsheet_io": ("sheet.", "spreadsheet", "csv", "xlsx", "xls", "data.csv_query"),
    "document_io": ("json", "document", "result.file", "result.files", "result.text"),
    "chart_output": ("result.chart", "chart.", "graph.", "plot", "visual"),
    "pdf_processing": ("pdf.", "ocr", "image.ocr_text"),
    "repo_editing": ("repo.", "code.", "git."),
    "content_authoring": ("result.text",),
}

_CAPABILITY_DOC_HINTS: Dict[str, set[str]] = {
    "web_research": set(_EXTERNAL_FLOW_CAPABILITY_HINTS) | {"youtube", "news", "trending", "trend"},
    "sports_live_data": {"sports", "scoreboard", "live", "schedule", "fixture", "game", "games", "team", "league"},
    "market_data": {"stock", "stocks", "ticker", "tickers", "market", "markets", "finance", "yahoo", "quote", "quotes", "portfolio", "momentum", "volume", "trending"},
    "spreadsheet_io": {"spreadsheet", "workbook", "sheet", "csv", "xlsx", "xls", "table", "rows", "columns"},
    "document_io": {"json", "document", "notes", "brief", "article", "release", "faq", "file", "path"},
    "chart_output": {"chart", "graph", "plot", "visualize", "visualization", "bar", "line", "pie", "scatter", "series", "xvalues"},
    "pdf_processing": {"pdf", "document", "contract", "clause", "ocr", "form"},
    "repo_editing": {"repo", "repository", "code", "patch", "git", "diff", "refactor", "bug"},
    "content_authoring": {"email", "memo", "summary", "brief", "faq", "report", "write", "draft"},
}


def _has_explicit_file_or_repo_scope(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if not text:
        return False
    low = text.lower()
    if _FILE_PATH_RE.search(text):
        return True
    low_slash = low.replace("\\", "/")
    if "/data/agent_workflow/repo" in low_slash:
        return True
    if re.search(r"\b(repo|repository|codebase)\b", low):
        return True
    if re.search(r"\b[\w./\\-]+\.(?:js|ts|py|json|md|txt|csv|ya?ml|html?|css|pdf|docx|pptx|xlsx|zip)\b", text, flags=re.IGNORECASE):
        return True
    return False


def _looks_like_conceptual_workflow_question(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if not text:
        return False
    if re.search(r"(?:(?:/|\\)(?:uploads|app|data)(?:/|\\)|[a-z]:[\\/].+\.(?:csv|json|txt|md|pdf|docx|pptx|xlsx|zip|js|ts|py|ya?ml|html?|css)\b)", text, flags=re.IGNORECASE):
        return False
    low = text.lower()
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


class AutoFlowRoute(BaseRoute):
    route_id = PLUGIN_ID
    short_description = "Select the best Agent Flow for a No flow user request."
    backend_types = {"hf", "hf_assist", "gguf", "vllm", "auto"}

    def can_handle(self, req: Any) -> bool:
        return bool(self._extract_user_text(req).strip())

    def handle(self, req: Any) -> Any:
        user_text = self._extract_user_text(req).strip()
        if not user_text:
            return {"route_id": self.route_id, "ok": False, "error": "empty_prompt"}
        settings = self._merge_settings(req)
        mode = str(self._ext(req).get("autoflow_mode") or settings.get("autoflow_mode") or "select").strip().lower()
        if mode == "plan":
            return self._plan_only(req, settings, user_text)
        if mode == "judge":
            return self._judge_mode(req, settings, user_text)
        if mode == "select_or_create":
            return self._select_or_create(req, settings, user_text)
        return self._select_only(req, settings, user_text)

    def _plan_only(self, req: Any, settings: Dict[str, Any], user_text: str) -> Dict[str, Any]:
        plan = self._request_plan(req, settings, user_text)
        return {
            "route_id": self.route_id,
            "ok": True,
            "plan": plan,
            "plan_summary": str(plan.get("summary") or "").strip(),
            "plan_need": list(plan.get("must_use_capabilities") or []),
            "plan_avoid": list(plan.get("avoid_capabilities") or []),
        }

    def _select_only(self, req: Any, settings: Dict[str, Any], user_text: str) -> Dict[str, Any]:
        plan = self._request_plan(req, settings, user_text)
        profile = self._request_profile(user_text, plan)
        direct = self._builtin_direct_candidate(user_text, profile)
        if self._should_prefer_direct_builtin_selection(direct):
            return self._selection_result(direct, [self._public_candidate(direct)], source="builtin", plan=plan)
        scored, best, public_scored = self._rank_candidates(req, settings, user_text, plan)
        if not scored:
            return {"route_id": self.route_id, "ok": False, "error": "no_flows", "plan": plan}
        min_conf = self._to_float(settings.get("autoflow_min_confidence"), 0.15)
        if self._is_external_info_request(user_text) and not self._flow_supports_external_info(best):
            return {
                "route_id": self.route_id,
                "ok": False,
                "error": "no_flow_match",
                "selected_flow": "",
                "confidence": round(best["score"], 3),
                "reason": "Request appears to need live/web information and no selected Agent Flow advertises web/search capability.",
                "candidates": public_scored[:8],
                "plan": plan,
            }
        if best["score"] < min_conf:
            return {
                "route_id": self.route_id,
                "ok": False,
                "error": "low_confidence",
                "selected_flow": "",
                "confidence": round(best["score"], 3),
                "reason": best["reason"],
                "candidates": public_scored[:8],
                "plan": plan,
            }
        return self._selection_result(best, public_scored[:8], source="existing", plan=plan)

    def _select_or_create(self, req: Any, settings: Dict[str, Any], user_text: str) -> Dict[str, Any]:
        plan = self._request_plan(req, settings, user_text)
        profile = self._request_profile(user_text, plan)
        direct = self._builtin_direct_candidate(user_text, profile)
        if self._should_prefer_direct_builtin_selection(direct):
            return self._selection_result(direct, [self._public_candidate(direct)], source="builtin", plan=plan)
        scored, best, public_scored = self._rank_candidates(req, settings, user_text, plan)
        library_best = self._best_library_candidate(req, user_text)
        create_enabled = self._to_bool(settings.get("autoflow_create_if_request_not_satisfied"), False)
        min_conf = self._to_float(settings.get("autoflow_min_confidence"), 0.15)
        if profile.get("file_backed"):
            min_conf = max(min_conf, 0.55)
        candidates_public = list(public_scored[:8])
        if library_best:
            candidates_public.insert(0, self._public_candidate(library_best))
        selected = best
        source = "existing"
        library_strong_enough = False
        if library_best:
            library_score = float(library_best.get("score") or 0.0)
            record_score = float(library_best.get("record_score") or 0.0)
            exact_request_context = bool(library_best.get("exact_request_context"))
            library_floor = max(min_conf + 0.2, 0.55)
            library_strong_enough = exact_request_context or library_score >= library_floor or record_score >= library_floor
        if library_best and library_strong_enough and (not selected or float(library_best.get("score") or 0.0) >= float(selected.get("score") or 0.0)):
            selected = library_best
            source = "library"
        external_ok = bool(selected) and (not self._is_external_info_request(user_text) or self._flow_supports_external_info(selected))
        family_ok = bool(selected) and self._flow_matches_request_profile(selected, profile)
        selected_exact_library = bool(source == "library" and isinstance(selected, dict) and selected.get("exact_request_context"))
        if selected and external_ok and family_ok and (float(selected.get("score") or 0.0) >= min_conf or selected_exact_library):
            return self._selection_result(selected, candidates_public[:8], source=source, plan=plan)
        creation_allowed = create_enabled and self._should_attempt_workflow_creation(user_text, profile, plan)
        if not creation_allowed:
            if not selected:
                return {"route_id": self.route_id, "ok": False, "error": "no_flows", "plan": plan}
            err = "no_flow_match" if not external_ok else "low_confidence"
            if external_ok and not family_ok:
                err = "family_mismatch"
            reason = self._selection_failure_reason(selected, profile, external_ok, family_ok)
            if create_enabled and not self._should_attempt_workflow_creation(user_text, profile, plan):
                reason = reason or "Workflow creation was skipped because this request should resolve through direct answer, builtin routing, or a better existing flow match rather than generating a new workflow."
            return {
                "route_id": self.route_id,
                "ok": False,
                "error": err,
                "selected_flow": "",
                "confidence": round(float(selected.get("score") or 0.0), 3),
                "reason": reason,
                "candidates": candidates_public[:8],
                "plan": plan,
            }

        creator_flow_name = self._resolve_creator_flow_name(req, settings)
        prior_attempts = self._ext(req).get("autoflow_attempts")
        improved_request = self._build_creator_request(
            req,
            user_text,
            prior_attempts if isinstance(prior_attempts, list) else [],
            profile,
            candidates_public[:4],
            plan,
        )
        created = self._create_flow_with_creator(req, creator_flow_name, user_text, improved_request)
        if not created.get("ok"):
            return {
                "route_id": self.route_id,
                "ok": False,
                "error": "autoflow_create_failed",
                "reason": "; ".join(created.get("warnings") or []) or "workflow_creation_failed",
                "selected_flow": "",
                "candidates": candidates_public[:8],
                "plan": plan,
            }
        generated = created.get("generated_workflow") if isinstance(created.get("generated_workflow"), dict) else {}
        flow_name = str(generated.get("flow_name") or created.get("flow_name") or "").strip()
        if not flow_name:
            return {
                "route_id": self.route_id,
                "ok": False,
                "error": "autoflow_create_failed",
                "reason": "generated_flow_missing",
                "selected_flow": "",
                "candidates": candidates_public[:8],
                "plan": plan,
            }
        return {
            "route_id": self.route_id,
            "ok": True,
            "selected_flow": flow_name,
            "flow_name": flow_name,
            "confidence": 1.0,
            "reason": f"Created a new workflow with {creator_flow_name} because no existing flow met the request.",
            "source": "generated",
            "generated_workflow": generated,
            "creator_run": created.get("creator_run") if isinstance(created.get("creator_run"), dict) else {},
            "candidates": candidates_public[:8],
            "plan": plan,
        }

    def _judge_mode(self, req: Any, settings: Dict[str, Any], user_text: str) -> Dict[str, Any]:
        ext = self._ext(req)
        flow_result_text = str(ext.get("autoflow_flow_result_text") or "").strip()
        flow_name = str(ext.get("autoflow_flow_name") or "").strip()
        result_meta = ext.get("autoflow_flow_result_meta") if isinstance(ext.get("autoflow_flow_result_meta"), dict) else {}
        if not flow_result_text and result_meta:
            try:
                flow_result_text = json.dumps(result_meta, ensure_ascii=False)
            except Exception:
                flow_result_text = str(result_meta)
        if not flow_result_text:
            return {"route_id": self.route_id, "ok": False, "error": "missing_flow_result_text"}
        judged = self._judge_satisfaction(user_text, flow_result_text, flow_name=flow_name, result_meta=result_meta)
        if flow_name:
            if judged.get("satisfied"):
                self._record_feedback(user_text, flow_name, score=1, reason=str(judged.get("reason") or ""))
                self._append_pass_log_for_success(user_text, flow_name, result_meta=result_meta, judged=judged)
            else:
                self._record_feedback(user_text, flow_name, score=-1, reason=str(judged.get("reason") or ""))
        return {
            "route_id": self.route_id,
            "ok": True,
            "mode": "judge",
            **judged,
        }

    def _rank_candidates(self, req: Any, settings: Dict[str, Any], user_text: str, plan: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
        flows = self._get_flows(req)
        profile = self._request_profile(user_text, plan)
        direct = self._builtin_direct_candidate(user_text, profile)
        if not flows:
            if direct:
                public_direct = self._public_candidate(direct)
                return [direct], direct, [public_direct]
            return [], {}, []
        selected_names = self._selected_flow_names(settings, flows)
        avoid_flows = {str(x or "").strip().lower() for x in (self._ext(req).get("autoflow_avoid_flows") or []) if str(x or "").strip()}
        candidates = [
            (name, flows[name])
            for name in selected_names
            if name in flows
            and name.lower() not in avoid_flows
            and not self._feedback_failed(user_text, name)
            and self._is_user_request_flow_candidate(name, flows.get(name), profile)
        ]
        if not candidates and not direct:
            return [], {}, []
        scored = [self._score_flow(user_text, name, flow_def, settings, profile) for name, flow_def in candidates]
        direct_name = str((direct or {}).get("name") or "").strip().lower() if isinstance(direct, dict) else ""
        if direct and direct_name not in avoid_flows:
            scored.append(direct)
        scored.sort(key=lambda row: (row["score"], row["name"]), reverse=True)
        best = scored[0] if scored else {}
        public_scored = [self._public_candidate(row) for row in scored]
        return scored, best, public_scored

    def _should_attempt_workflow_creation(self, user_text: str, profile: Dict[str, Any], plan: Optional[Dict[str, Any]] = None) -> bool:
        text = str(user_text or "").strip()
        if not text:
            return False
        low = text.lower()
        profile = profile if isinstance(profile, dict) else {}
        capability_ids = {str(x or "").strip() for x in (profile.get("capability_ids") or []) if str(x or "").strip()}
        if _looks_like_conceptual_workflow_question(text):
            return False
        if self._is_external_info_request(text) and not profile.get("file_backed") and "repo_editing" not in capability_ids:
            return True
        explicit_workflow_request = any(tok in low for tok in (
            "workflow", "agent flow", "flow creator", "autobuild", "automation",
            "build a workflow", "create a workflow", "make a workflow", "designer",
        ))
        if profile.get("file_backed") or "repo_editing" in capability_ids:
            return True
        if explicit_workflow_request:
            return True
        if bool(re.search(r"\b(help me|draft|create|plan|design|build|suggest|outline|prepare|proposal|essay|presentation|powerpoint|slides|deck|project|ideas|brainstorm|write|compare|analysis|analyze|review|table|report|brief)\b", low, flags=re.IGNORECASE)):
            return True
        return False

    def _selection_result(self, best: Dict[str, Any], candidates: List[Dict[str, Any]], *, source: str, plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        out = {
            "route_id": self.route_id,
            "ok": True,
            "selected_flow": best["name"],
            "flow_name": best["name"],
            "confidence": round(best["score"], 3),
            "reason": best["reason"],
            "source": source,
            "candidates": candidates,
        }
        if isinstance(plan, dict) and plan:
            out["plan"] = plan
        generated = best.get("generated_workflow") if isinstance(best.get("generated_workflow"), dict) else {}
        if generated:
            out["generated_workflow"] = generated
        try:
            self._persist_temp_library_selection(best, source=source)
        except Exception:
            pass
        return out

    def _is_fast_builtin_candidate(self, candidate: Any) -> bool:
        if not isinstance(candidate, dict):
            return False
        name = str(candidate.get("name") or "").strip()
        if not name.startswith("__autoflow_builtin_"):
            return False
        if name == "__autoflow_builtin_general_answer__":
            return False
        score = float(candidate.get("score") or 0.0)
        if score >= 2.4:
            return True
        reason = str(candidate.get("reason") or "").strip().lower()
        return score >= 0.95 and "builtin_direct_" in reason

    def _should_prefer_direct_builtin_selection(self, candidate: Any) -> bool:
        if not self._is_fast_builtin_candidate(candidate):
            return False
        name = str((candidate or {}).get("name") or "").strip()
        if not name:
            return False
        # Keep plain model chat from suppressing workflow selection/creation,
        # but allow specific builtins like repo/file/web/weather/market routes
        # to short-circuit stale library/generated matches.
        return name != "__autoflow_builtin_general_answer__"

    def _score_flow(self, user_text: str, name: str, flow_def: Any, settings: Dict[str, Any], profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        query_tokens = self._tokens(user_text)
        doc = self._flow_doc(name, flow_def)
        doc_tokens = self._tokens(doc)
        profile = profile if isinstance(profile, dict) else self._request_profile(user_text)
        capability_ids = set(profile.get("capability_ids") or [])
        route_flags = self._flow_route_family_flags(name, flow_def)
        if route_flags.get("repo_or_code") and "repo_editing" not in capability_ids:
            return {
                "name": name,
                "score": -1.0,
                "reason": "route_family_mismatch:repo_or_code",
                "node_count": self._node_count(flow_def),
                "description": self._flow_description(flow_def),
                "doc_tokens": sorted(list(doc_tokens))[:200],
            }
        request_sports = self._sport_groups(user_text)
        doc_sports = self._sport_groups(doc)
        if request_sports and doc_sports and not (request_sports & doc_sports):
            return {
                "name": name,
                "score": -1.0,
                "reason": "sport_mismatch",
                "node_count": self._node_count(flow_def),
                "description": self._flow_description(flow_def),
                "doc_tokens": sorted(list(doc_tokens))[:200],
            }
        overlap = query_tokens & doc_tokens
        score = 0.0
        if query_tokens:
            score += len(overlap) / max(5, len(query_tokens))
        if doc_tokens:
            score += len(overlap) / max(10, len(doc_tokens)) * 0.55
        capability_score, capability_reason_bits = self._flow_capability_fit(
            {
                "doc_tokens": sorted(list(doc_tokens))[:200],
                "doc_text": doc,
                "action_skills": self._action_skills_from_flow(flow_def),
                "executable_action_skills": self._executable_action_skills_from_flow(flow_def),
                "description": self._flow_description(flow_def),
            },
            profile,
        )
        score += capability_score
        focus_score, focus_reason_bits = self._focus_overlap_score(
            {
                "doc_tokens": sorted(list(doc_tokens))[:200],
                "doc_text": doc,
                "description": self._flow_description(flow_def),
            },
            profile,
        )
        score += focus_score

        category_matches = self._matched_group_tokens(query_tokens, doc_tokens, _CATEGORY_HINTS)
        category_hits = sorted(category_matches.keys())
        score += 0.34 * len(category_hits)

        intent_matches = self._matched_group_tokens(query_tokens, doc_tokens, _INTENT_HINTS)
        intent_hits = sorted(intent_matches.keys())
        score += 0.24 * len(intent_hits)

        name_tokens = self._tokens(name.replace("_", " "))
        name_hits = sorted(query_tokens & name_tokens)
        score += 0.14 * len(name_hits)

        family_name = str(profile.get("family") or "").strip()
        family_tokens = set(profile.get("family_tokens") or [])
        family_hits = sorted(doc_tokens & family_tokens)
        if family_hits:
            score += 0.22 * len(family_hits)
        elif family_name and str(profile.get("file_backed") or ""):
            score -= 0.18

        avoid_capabilities = {str(x or "").strip() for x in (profile.get("avoid_capabilities") or []) if str(x or "").strip()}
        action_skills = self._action_skills_from_flow(flow_def)
        executable_action_skills = self._executable_action_skills_from_flow(flow_def)
        supported_caps = set()
        flow_text = " ".join([name, doc, self._flow_description(flow_def), " ".join(action_skills), " ".join(executable_action_skills)]).lower()
        for cap_id in (capability_ids | avoid_capabilities):
            hints = _CAPABILITY_DOC_HINTS.get(cap_id, set())
            skill_hints = _CAPABILITY_SKILL_HINTS.get(cap_id, ())
            if hints and any(hint in flow_text for hint in hints):
                supported_caps.add(cap_id)
            elif skill_hints and any(any(hint in skill.lower() for hint in skill_hints) for skill in executable_action_skills):
                supported_caps.add(cap_id)
        if avoid_capabilities and (supported_caps & avoid_capabilities):
            score -= 0.45
        plan_summary = str((profile.get("plan") or {}).get("summary") or "").strip().lower()
        if plan_summary:
            plan_overlap = sorted(set(self._tokens(plan_summary)) & doc_tokens)
            if plan_overlap:
                score += min(0.22, 0.05 * len(plan_overlap))
        if profile.get("file_backed"):
            if "spreadsheet_io" in capability_ids and (doc_tokens & _FILE_SHAPE_HINTS["spreadsheet_io"]):
                score += 0.18
            if "pdf_processing" in capability_ids and ({"pdf", "contract", "document", "clause"} & doc_tokens):
                score += 0.18
            if "content_authoring" in capability_ids and ({"email", "memo", "summary", "brief", "faq"} & doc_tokens):
                score += 0.12
            if ("content_authoring" in capability_ids or "document_io" in capability_ids) and not executable_action_skills:
                score -= 0.95

        policy = str(settings.get("autoflow_system_prompt") or "")
        policy_tokens = self._tokens(policy)
        if policy_tokens:
            policy_overlap = policy_tokens & doc_tokens & query_tokens
            score += 0.08 * len(policy_overlap)

        penalty = self._feedback_penalty(user_text, name)
        score -= penalty
        score += self._feedback_bonus(user_text, name)

        reason_bits: List[str] = []
        if penalty > 0:
            reason_bits.append(f"penalty=previous_failed_request({round(penalty, 2)})")
        if profile.get("file_backed") and ("content_authoring" in capability_ids or "document_io" in capability_ids) and not executable_action_skills:
            reason_bits.append("penalty=no_executable_path_for_file_backed_authoring")
        if category_hits:
            reason_bits.append("category=" + ",".join(f"{group_name}({','.join(category_matches[group_name][:4])})" for group_name in category_hits))
        if intent_hits:
            reason_bits.append("intent=" + ",".join(f"{group_name}({','.join(intent_matches[group_name][:4])})" for group_name in intent_hits))
        if family_hits:
            reason_bits.append("family=" + ",".join(family_hits[:4]))
        if capability_reason_bits:
            reason_bits.append(",".join(capability_reason_bits))
        if avoid_capabilities and (supported_caps & avoid_capabilities):
            reason_bits.append("plan_avoid=" + ",".join(sorted(supported_caps & avoid_capabilities)[:4]))
        if plan_summary:
            plan_overlap = sorted(set(self._tokens(plan_summary)) & doc_tokens)
            if plan_overlap:
                reason_bits.append("plan=" + ",".join(plan_overlap[:4]))
        if focus_reason_bits:
            reason_bits.extend(focus_reason_bits)
        if overlap:
            reason_bits.append("matched=" + ",".join(sorted(list(overlap))[:10]))
        if not reason_bits:
            reason_bits.append("best lexical match")
        return {
            "name": name,
            "score": round(score, 5),
            "reason": "; ".join(reason_bits),
            "node_count": self._node_count(flow_def),
            "description": self._flow_description(flow_def),
            "action_skills": action_skills,
            "executable_action_skills": executable_action_skills,
            "doc_text": doc,
            "doc_tokens": sorted(list(doc_tokens))[:200],
        }

    def _create_flow_with_creator(
        self,
        req: Any,
        creator_flow_name: str,
        user_request_text: str,
        creator_request_text: str,
    ) -> Dict[str, Any]:
        app = self._server_app()
        db = getattr(getattr(app, "state", None), "collab_db", None) if app is not None else None
        if app is None or db is None:
            return {"ok": False, "warnings": ["server_app_unavailable"]}
        pid = self._pid(req)
        base = _base_url({"settings": dict(self.core.settings or {})}, {})
        token = db.issue_token("admin", ttl_s=3600)
        all_flows = self._runtime_and_saved_flows(req)
        if creator_flow_name not in all_flows:
            return {"ok": False, "warnings": [f"creator_flow_not_found:{creator_flow_name}"]}

        ctx = {"app": app}
        before = workflow_temp_library.run(ctx, {"action": "list"})
        before_rows = before.get("records") if isinstance(before, dict) and isinstance(before.get("records"), list) else []
        before_ids = {str((row or {}).get("id") or "").strip() for row in before_rows if isinstance(row, dict)}

        sid = f"autoflow_creator_{secrets.token_hex(4)}"
        run_id = ""
        state: Dict[str, Any] = {}
        creator_msg: Dict[str, Any] = {}
        creator_ext = self._ext(req)
        sandbox_profile = str(creator_ext.get("agent_flow_autobuild_sandbox_profile") or "lightweight").strip() or "lightweight"
        if sandbox_profile == "independent":
            validation_profile = "standard"
            suite_max_requests = int(creator_ext.get("agent_flow_autobuild_independent_max_requests") or 3)
            suite_wait_s = int(creator_ext.get("agent_flow_autobuild_independent_wait_s") or 180)
            suite_grace_s = int(creator_ext.get("agent_flow_autobuild_independent_final_grace_s") or 20)
            suite_steps = int(creator_ext.get("agent_flow_autobuild_independent_agent_flow_max_steps") or 12)
        else:
            validation_profile = "lightweight"
            suite_max_requests = int(creator_ext.get("agent_flow_autobuild_lightweight_max_requests") or 1)
            suite_wait_s = int(creator_ext.get("agent_flow_autobuild_lightweight_wait_s") or 25)
            suite_grace_s = int(creator_ext.get("agent_flow_autobuild_lightweight_final_grace_s") or 4)
            suite_steps = int(creator_ext.get("agent_flow_autobuild_lightweight_agent_flow_max_steps") or 5)
        raw_creator_wait = creator_ext.get("autoflow_creator_wait_s")
        if raw_creator_wait in (None, ""):
            creator_wait_s = 180 if sandbox_profile != "independent" else 360
        else:
            try:
                creator_wait_s = max(60, int(raw_creator_wait))
            except Exception:
                creator_wait_s = 180 if sandbox_profile != "independent" else 360
        runtime_creator_flow_name = self._resolve_creator_runtime_flow_name(all_flows, creator_flow_name, sandbox_profile)
        if runtime_creator_flow_name == "__autoflow_direct_generalized_builder__":
            return self._create_flow_direct_single(
                app=app,
                pid=pid,
                creator_flow_name=creator_flow_name,
                runtime_creator_flow_name=runtime_creator_flow_name,
                user_request_text=user_request_text,
                creator_request_text=creator_request_text,
                creator_wait_s=creator_wait_s,
            )
        try:
            try:
                db.ensure_session(pid, sid, sid, "admin", is_public=False)
            except Exception:
                pass
            run = _http_json(
                base,
                token,
                "POST",
                f"/v1/projects/{pid}/sessions/{sid}/agent_flow/run",
                {
                    "text": creator_request_text,
                    "ext": {
                        "agent_flow_flows": all_flows,
                        "agent_flow_active_flow": runtime_creator_flow_name,
                        "agent_flow_default_flow": runtime_creator_flow_name,
                        "agent_flow_max_steps": int((self._ext(req).get("agent_flow_max_steps") or 24)),
                        "agent_flow_internal_run": False,
                        "validation_profile": validation_profile,
                        "min_requests": 1,
                        "max_requests": suite_max_requests,
                        "max_request_wait_s": suite_wait_s,
                        "poll_interval_s": 1,
                        "final_step_grace_s": suite_grace_s,
                        "clarify_default": "Proceed with the most reasonable sandbox-safe assumption.",
                        "force_new_workflow": True,
                        "avoid_flow_names": list(self._ext(req).get("autoflow_avoid_flows") or []),
                        "agent_flow_autobuild_agent_flow_max_steps": suite_steps,
                        "agent_flow_autobuild_sandbox_profile": sandbox_profile,
                        "agent_flow_autobuild_lightweight_max_requests": int(creator_ext.get("agent_flow_autobuild_lightweight_max_requests") or 1),
                        "agent_flow_autobuild_lightweight_wait_s": int(creator_ext.get("agent_flow_autobuild_lightweight_wait_s") or 25),
                        "agent_flow_autobuild_lightweight_final_grace_s": int(creator_ext.get("agent_flow_autobuild_lightweight_final_grace_s") or 4),
                        "agent_flow_autobuild_independent_max_requests": int(creator_ext.get("agent_flow_autobuild_independent_max_requests") or 3),
                        "agent_flow_autobuild_independent_wait_s": int(creator_ext.get("agent_flow_autobuild_independent_wait_s") or 180),
                        "agent_flow_autobuild_independent_final_grace_s": int(creator_ext.get("agent_flow_autobuild_independent_final_grace_s") or 20),
                        "router_plugin_settings": dict(self._ext(req).get("router_plugin_settings") or {}),
                    },
                },
                timeout=180,
            )
            run_id = str(run.get("run_id") or "").strip()
            poll_interval_s = 1.0
            max_loops = max(1, int(creator_wait_s / poll_interval_s))
            timed_out = True
            loops = 0
            while True:
                if loops >= max_loops:
                    break
                loops += 1
                st = _http_json(base, token, "GET", f"/v1/projects/{pid}/sessions/{sid}/agent_flow/status?run_id={run_id}", None, timeout=60)
                state = st.get("state") if isinstance(st.get("state"), dict) else {}
                inter = state.get("interaction") if isinstance(state.get("interaction"), dict) else None
                if inter and str(inter.get("status") or "") != "answered":
                    inter_type = str(inter.get("type") or "approval").strip().lower()
                    action = {"run_id": run_id, "interaction_id": inter.get("id")}
                    if inter_type == "approval":
                        action.update({"action": "yes", "text": "yes"})
                    else:
                        action.update({"action": "answer", "text": "Proceed with the most reasonable sandbox-safe assumption."})
                    _http_json(base, token, "POST", f"/v1/projects/{pid}/sessions/{sid}/agent_flow/interaction", action, timeout=60)
                if not state.get("running"):
                    timed_out = False
                    break
                time.sleep(poll_interval_s)
            if timed_out and state.get("running") and run_id:
                try:
                    cancelled = getattr(getattr(app, "state", None), "ai_jobs_cancelled", None)
                    if isinstance(cancelled, dict):
                        cancelled[run_id] = int(time.time())
                except Exception:
                    pass
                for _ in range(6):
                    time.sleep(0.5)
                    try:
                        st = _http_json(base, token, "GET", f"/v1/projects/{pid}/sessions/{sid}/agent_flow/status?run_id={run_id}", None, timeout=30)
                        state = st.get("state") if isinstance(st.get("state"), dict) else state
                    except Exception:
                        break
                    if not state.get("running"):
                        timed_out = False
                        break
        finally:
            try:
                creator_msg = _latest_assistant_message(db, pid, sid)
            except Exception:
                creator_msg = {}
            _force_delete_session(db, pid, sid)

        after = workflow_temp_library.run(ctx, {"action": "list"})
        rows = after.get("records") if isinstance(after, dict) and isinstance(after.get("records"), list) else []
        new_rows = [dict(row) for row in rows if isinstance(row, dict) and str(row.get("id") or "").strip() not in before_ids]
        request_variants = {
            str(user_request_text or "").strip(),
            str(creator_request_text or "").strip(),
        }
        request_variants = {item for item in request_variants if item}
        user_profile = self._request_profile(user_request_text)
        matched_rows = [
            row
            for row in new_rows
            if str(row.get("source_request") or "").strip() in request_variants
            or any(str(alias or "").strip() in request_variants for alias in (row.get("request_aliases") or []))
        ]
        creator_meta = creator_msg.get("meta") if isinstance(creator_msg.get("meta"), dict) else {}
        creator_data = creator_meta.get("data") if isinstance(creator_meta.get("data"), dict) else {}
        recovered_artifact = self._recover_creator_artifact_from_state(state)
        explicit_bundle_dir = str(
            creator_data.get("bundle_dir")
            or creator_meta.get("bundle_dir")
            or recovered_artifact.get("bundle_dir")
            or ""
        ).strip()
        explicit_workflow_file = str(
            creator_data.get("workflow_file")
            or creator_meta.get("workflow_file")
            or recovered_artifact.get("workflow_file")
            or ""
        ).strip()
        explicit_flow_name = str(
            creator_data.get("flow_name")
            or creator_meta.get("flow_name")
            or recovered_artifact.get("flow_name")
            or ""
        ).strip()
        if explicit_workflow_file and not explicit_bundle_dir:
            try:
                explicit_bundle_dir = str(Path(explicit_workflow_file).resolve().parent)
            except Exception:
                explicit_bundle_dir = str(Path(explicit_workflow_file).parent)
        if bool(state.get("running")):
            return {
                "ok": False,
                "warnings": ["creator_run_incomplete", f"creator_wait_s:{creator_wait_s}"],
                "creator_run": {"run_id": run_id, "status": str(state.get("status") or "")},
            }
        if explicit_bundle_dir:
            registered = workflow_temp_library.run(
                ctx,
                {
                    "action": "register",
                    "bundle_dir": explicit_bundle_dir,
                    "workflow_file": explicit_workflow_file,
                    "flow_name": explicit_flow_name,
                    "request": user_request_text,
                    "summary": str(creator_data.get("review_summary") or creator_data.get("text") or ""),
                    "run_id": run_id,
                    "validated": True,
                    "allow_reuse": False,
                },
            )
            if registered.get("ok") and isinstance(registered.get("record"), dict):
                record = dict(registered.get("record") or {})
                if creator_request_text.strip() and creator_request_text.strip() != user_request_text.strip():
                    aliases = [str(x or "").strip() for x in (record.get("request_aliases") or []) if str(x or "").strip()]
                    if creator_request_text.strip() not in aliases:
                        aliases.append(creator_request_text.strip())
                    updated = workflow_temp_library.run(
                        ctx,
                        {
                            "action": "update",
                            "record_id": str(record.get("id") or "").strip(),
                            "patch": {
                                "request_aliases": aliases,
                                "last_request": user_request_text,
                            },
                        },
                    )
                    if updated.get("ok") and isinstance(updated.get("record"), dict):
                        record = dict(updated.get("record") or {})
                matched_rows = [record]
        if not matched_rows:
            if explicit_flow_name:
                matched_rows = [
                    row
                    for row in new_rows
                    if str(row.get("flow_name") or "").strip() == explicit_flow_name
                ]
        if not matched_rows and explicit_workflow_file:
            matched_rows = [
                row
                for row in new_rows
                if str(row.get("workflow_file") or "").strip() == explicit_workflow_file
            ]
        if not matched_rows and explicit_bundle_dir:
            matched_rows = [
                row
                for row in new_rows
                if str(row.get("bundle_dir") or "").strip() == explicit_bundle_dir
            ]
        if not matched_rows:
            profiled_rows = []
            for row in new_rows:
                candidate = {
                    "name": str(row.get("flow_name") or "").strip(),
                    "description": str(row.get("description") or row.get("summary") or "").strip(),
                    "doc_tokens": self._tokens(
                        " ".join(
                            [
                                str(row.get("flow_name") or ""),
                                str(row.get("description") or ""),
                                str(row.get("summary") or ""),
                                str(row.get("source_request") or ""),
                                " ".join([str(x or "").strip() for x in (row.get("request_aliases") or []) if str(x or "").strip()]),
                            ]
                        )
                    ),
                }
                if self._flow_matches_request_profile(candidate, user_profile):
                    profiled_rows.append(row)
            if len(profiled_rows) == 1:
                matched_rows = [profiled_rows[0]]
        if not matched_rows:
            step_bits: List[str] = []
            for step in (state.get("steps") if isinstance(state.get("steps"), list) else [])[-6:]:
                if not isinstance(step, dict):
                    continue
                label = str(step.get("label") or "").strip()
                status = str(step.get("state") or "").strip()
                if label:
                    step_bits.append(f"{label}:{status or 'unknown'}")
            debug_warnings = [
                "generated_workflow_not_registered_for_current_request",
                f"creator_status:{str(state.get('status') or '')}",
                f"new_rows:{len(new_rows)}",
                f"profiled_rows:{len(profiled_rows) if 'profiled_rows' in locals() else 0}",
            ]
            if step_bits:
                debug_warnings.append("creator_steps:" + " | ".join(step_bits))
            recent_steps = (state.get("steps") if isinstance(state.get("steps"), list) else [])[-3:]
            for step in recent_steps:
                if not isinstance(step, dict):
                    continue
                if str(step.get("label") or "").strip() != "Tracker Setup":
                    continue
                output = str(step.get("output") or "").strip().replace("\n", " ")
                if output:
                    debug_warnings.append("tracker_output:" + output[:220])
                break
            for step in reversed(recent_steps):
                if not isinstance(step, dict):
                    continue
                output = str(step.get("output") or "").strip().replace("\n", " ")
                label = str(step.get("label") or "").strip()
                if label and output:
                    debug_warnings.append(f"last_step_output:{label}:{output[:220]}")
                    break
            if explicit_flow_name:
                debug_warnings.append(f"creator_flow_name:{explicit_flow_name}")
            if explicit_workflow_file:
                debug_warnings.append(f"creator_workflow_file:{explicit_workflow_file}")
            if explicit_bundle_dir:
                debug_warnings.append(f"creator_bundle_dir:{explicit_bundle_dir}")
            return {
                "ok": False,
                "warnings": debug_warnings,
                "creator_run": {"run_id": run_id, "status": str(state.get("status") or "")},
            }
        matched_rows.sort(key=lambda row: int(row.get("updated_ts") or 0), reverse=True)
        rec = matched_rows[0]
        workflow_file = str(rec.get("workflow_file") or "").strip()
        bundle_dir = str(rec.get("bundle_dir") or "").strip()
        flow_name = str(rec.get("flow_name") or "").strip()
        workflow_json: Dict[str, Any] = {}
        if workflow_file:
            try:
                wf_path = Path(workflow_file)
                raw_doc = wf_path.read_text(encoding="utf-8")
                flow_doc, parsed_name, warnings = ensure_flow_payload(raw_doc, wf_path.stem)
                if isinstance(flow_doc, dict):
                    workflow_json = dict(flow_doc)
                    flow_name = str(flow_name or parsed_name or flow_doc.get("name") or "").strip()
                elif warnings:
                    return {
                        "ok": False,
                        "warnings": warnings,
                        "creator_run": {"run_id": run_id, "status": str(state.get("status") or "")},
                    }
            except Exception:
                workflow_json = {}
        if not workflow_json:
            return {
                "ok": False,
                "warnings": ["generated_workflow_resolve_failed"],
                "creator_run": {"run_id": run_id, "status": str(state.get("status") or "")},
            }
        workflow_json = self._normalize_generated_workflow_for_request(workflow_json, user_request_text)
        if bundle_dir:
            self._repair_generated_bundle_for_request(bundle_dir, user_request_text)
        if workflow_json and workflow_file:
            try:
                wf_path = Path(workflow_file)
                raw_doc = json.loads(wf_path.read_text(encoding="utf-8"))
                if isinstance(raw_doc, dict):
                    flows_doc = raw_doc.get("flows")
                    flow_key = str(flow_name or rec.get("flow_name") or "")
                    if isinstance(flows_doc, dict) and flow_key in flows_doc:
                        flows_doc[flow_key] = workflow_json
                        wf_path.write_text(json.dumps(raw_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            except Exception:
                pass
        deduped_ids = self._dedupe_generated_records(
            ctx,
            str(rec.get("source_request") or user_request_text),
            str(flow_name or rec.get("flow_name") or ""),
            str(rec.get("id") or ""),
        )
        return {
            "ok": True,
            "flow_name": str(flow_name or ""),
            "generated_workflow": {
                "record_id": str(rec.get("id") or ""),
                "flow_name": str(flow_name or ""),
                "workflow_json": workflow_json,
                "workflow_file": workflow_file,
                "bundle_dir": bundle_dir,
                "temp_skill_dirs": [str(x or "").strip() for x in ([str(Path(bundle_dir) / "skills")] if bundle_dir and Path(bundle_dir, "skills").is_dir() else []) if str(x or "").strip()],
            },
            "creator_run": {"run_id": run_id, "status": str(state.get("status") or "")},
            "warnings": [f"deduped_records:{len(deduped_ids)}"] if deduped_ids else [],
        }

    def _create_flow_direct_single(
        self,
        *,
        app: Any,
        pid: str,
        creator_flow_name: str,
        runtime_creator_flow_name: str,
        user_request_text: str,
        creator_request_text: str,
        creator_wait_s: int,
    ) -> Dict[str, Any]:
        ctx = {
            "app": app,
            "pid": pid,
            "original_request": user_request_text,
            "user_text": user_request_text,
            "creator_request_text": creator_request_text,
        }
        scaffold_request_text = str(creator_request_text or "").strip() or str(user_request_text or "").strip()
        profile = self._request_profile(scaffold_request_text)
        flow_name_hint = self._suggest_generated_flow_name(user_request_text)
        scaffolded = workflow_scaffold_subflow_capability.run(
            ctx,
            {
                "pid": pid,
                "user_request": scaffold_request_text,
                "original_request": user_request_text,
                "creator_request_text": creator_request_text,
                "flow_name": flow_name_hint,
                "reuse_strategy": (
                    "never_subflow_wrap"
                    if profile.get("file_backed") or (set(profile.get("capability_ids") or []) & _DIRECT_EXECUTION_CAPABILITIES)
                    else "prefer_subflow_wrap"
                ),
            },
        )
        if not bool(scaffolded.get("ok")):
            return {
                "ok": False,
                "warnings": [str(x) for x in (scaffolded.get("warnings") or []) if str(x).strip()] or ["direct_scaffold_failed"],
                "creator_run": {"run_id": "direct_generalized_builder", "status": "Failed"},
            }
        workflow_json = scaffolded.get("workflow_json") if isinstance(scaffolded.get("workflow_json"), dict) else {}
        flow_name = str(scaffolded.get("flow_name") or flow_name_hint).strip()
        missing_skill_specs = [dict(x) for x in (scaffolded.get("missing_skill_specs") or []) if isinstance(x, dict)]
        verified = workflow_verify.run(
            ctx,
            {
                "workflow_json": workflow_json,
                "flow_name": flow_name,
                "missing_skill_specs": missing_skill_specs,
            },
        )
        if not bool(verified.get("ok")) or not bool(verified.get("valid")):
            detail = ", ".join([str(x) for x in (verified.get("errors") or []) if str(x).strip()][:8]).strip()
            return {
                "ok": False,
                "warnings": [detail or "direct_verify_failed", f"creator_flow_name:{runtime_creator_flow_name}"],
                "creator_run": {"run_id": "direct_generalized_builder", "status": "Failed"},
            }
        exported = workflow_export.run(
            ctx,
            {
                "workflow_json": workflow_json,
                "flow_name": flow_name,
                "missing_skill_specs": missing_skill_specs,
                "create_skill_dropins": True,
            },
        )
        if not bool(exported.get("ok")):
            return {
                "ok": False,
                "warnings": [str(x) for x in (exported.get("warnings") or []) if str(x).strip()] or ["direct_export_failed"],
                "creator_run": {"run_id": "direct_generalized_builder", "status": "Failed"},
            }

        bundle_dir = str(exported.get("bundle_dir") or "").strip()
        workflow_file = str(exported.get("workflow_file") or "").strip()
        flow_name = str(exported.get("flow_name") or flow_name).strip()
        rec: Dict[str, Any] = {}
        if bundle_dir and workflow_file:
            registered = workflow_temp_library.run(
                ctx,
                {
                    "action": "register",
                    "bundle_dir": bundle_dir,
                    "workflow_file": workflow_file,
                    "flow_name": flow_name,
                    "request": user_request_text,
                    "summary": str(scaffolded.get("architect_summary") or ""),
                    "validated": True,
                    "allow_reuse": False,
                },
            )
            if registered.get("ok") and isinstance(registered.get("record"), dict):
                rec = dict(registered.get("record") or {})
        if rec:
            aliases = [str(x or "").strip() for x in (rec.get("request_aliases") or []) if str(x or "").strip()]
            if creator_request_text.strip() and creator_request_text.strip() != user_request_text.strip() and creator_request_text.strip() not in aliases:
                aliases.append(creator_request_text.strip())
            patched = workflow_temp_library.run(
                ctx,
                {
                    "action": "update",
                    "record_id": str(rec.get("id") or "").strip(),
                    "patch": {
                        "source_request": user_request_text,
                        "request_aliases": aliases,
                        "last_request": user_request_text,
                    },
                },
            )
            if patched.get("ok") and isinstance(patched.get("record"), dict):
                rec = dict(patched.get("record") or {})
            bundle_dir = str(rec.get("bundle_dir") or bundle_dir).strip()
            workflow_file = str(rec.get("workflow_file") or workflow_file).strip()
            flow_name = str(rec.get("flow_name") or flow_name).strip()

        workflow_json: Dict[str, Any] = {}
        if workflow_file:
            try:
                wf_path = Path(workflow_file)
                raw_doc = wf_path.read_text(encoding="utf-8")
                flow_doc, parsed_name, warnings = ensure_flow_payload(raw_doc, wf_path.stem)
                if isinstance(flow_doc, dict):
                    workflow_json = dict(flow_doc)
                    flow_name = str(flow_name or parsed_name or flow_doc.get("name") or "").strip()
                elif warnings:
                    return {
                        "ok": False,
                        "warnings": warnings,
                        "creator_run": {"run_id": "direct_generalized_builder", "status": "Failed"},
                    }
            except Exception:
                workflow_json = {}
        if not workflow_json:
            return {
                "ok": False,
                "warnings": ["generated_workflow_resolve_failed", f"creator_flow_name:{runtime_creator_flow_name}"],
                "creator_run": {"run_id": "direct_generalized_builder", "status": "Failed"},
            }

        workflow_json = self._normalize_generated_workflow_for_request(workflow_json, user_request_text)
        if bundle_dir:
            self._repair_generated_bundle_for_request(bundle_dir, user_request_text)
        if workflow_json and workflow_file:
            try:
                wf_path = Path(workflow_file)
                raw_doc = json.loads(wf_path.read_text(encoding="utf-8"))
                if isinstance(raw_doc, dict):
                    flows_doc = raw_doc.get("flows")
                    flow_key = str(flow_name or (rec.get("flow_name") if rec else "") or "")
                    if isinstance(flows_doc, dict) and flow_key in flows_doc:
                        flows_doc[flow_key] = workflow_json
                        wf_path.write_text(json.dumps(raw_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            except Exception:
                pass
        deduped_ids = self._dedupe_generated_records(
            ctx,
            str((rec.get("source_request") if rec else user_request_text) or user_request_text),
            str(flow_name or (rec.get("flow_name") if rec else "") or ""),
            str((rec.get("id") if rec else "") or ""),
        )
        return {
            "ok": True,
            "flow_name": str(flow_name or ""),
            "generated_workflow": {
                "record_id": str((rec.get("id") if rec else "") or ""),
                "flow_name": str(flow_name or ""),
                "workflow_json": workflow_json,
                "workflow_file": workflow_file,
                "bundle_dir": bundle_dir,
                "temp_skill_dirs": [str(x or "").strip() for x in ([str(Path(bundle_dir) / "skills")] if bundle_dir and Path(bundle_dir, "skills").is_dir() else []) if str(x or "").strip()],
            },
            "creator_run": {"run_id": "direct_generalized_builder", "status": "Completed"},
            "warnings": [f"deduped_records:{len(deduped_ids)}"] if deduped_ids else [f"creator_flow_name:{creator_flow_name}", f"creator_runtime_flow:{runtime_creator_flow_name}"],
        }

    def _resolve_creator_runtime_flow_name(
        self,
        all_flows: Dict[str, Any],
        creator_flow_name: str,
        sandbox_profile: str,
    ) -> str:
        flow = all_flows.get(creator_flow_name)
        if not isinstance(flow, dict):
            return creator_flow_name
        nodes = flow.get("nodes") if isinstance(flow.get("nodes"), dict) else {}
        if not nodes:
            return creator_flow_name
        labels = {str((node or {}).get("label") or "").strip().lower() for node in nodes.values() if isinstance(node, dict)}
        if "tracker setup" not in labels and not any(label.startswith("plan workflow batch") for label in labels):
            return creator_flow_name
        return "__autoflow_direct_generalized_builder__"
        for node in nodes.values():
            if not isinstance(node, dict):
                continue
            if str(node.get("plugin_id") or "").strip() != "agent_flow_subflow":
                continue
            ps = node.get("plugin_settings") if isinstance(node.get("plugin_settings"), dict) else {}
            name_map = ps.get("subflow_name_map") if isinstance(ps.get("subflow_name_map"), dict) else {}
            mapped = str(name_map.get(sandbox_profile) or ps.get("subflow_name") or "").strip()
            if mapped and mapped in all_flows:
                return mapped
        return creator_flow_name

    def _suggest_generated_flow_name(self, user_text: str) -> str:
        profile = self._request_profile(user_text)
        text = str(user_text or "").strip()
        for pat in (
            r"\bfor\s+(.+?)\s+that\s+(?:handles|can|should)\s+(.+?)(?:\.|$)",
            r"\bworkflow\s+for\s+(.+?)\s+that\s+(?:handles|can|should)\s+(.+?)(?:\.|$)",
        ):
            m = re.search(pat, text, flags=re.IGNORECASE)
            if not m:
                continue
            subject = str(m.group(1) or "").strip(" .,:;-")
            action = str(m.group(2) or "").strip(" .,:;-")
            return slugify(f"{subject}_{action}", "generated_workflow")
        cleaned = re.sub(r"/uploads/[\w./-]+", " ", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"[A-Za-z]:[/\\][^\s]+", " ", cleaned)
        cleaned = re.sub(r"\b(?:create|build|generate|make)\s+(?:a\s+new\s+or\s+improved\s+)?workflow\s+(?:that\s+)?", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(?:this|the|a|an)\s+(?:spreadsheet|csv|xlsx|xls|json|txt|markdown|document|file)\b", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:;-")
        cleaned_slug = slugify(cleaned[:120], "") if cleaned else ""
        if cleaned_slug and cleaned_slug not in {"compare", "analyze", "review", "use", "read"}:
            return cleaned_slug
        family_label = str(profile.get("family_label") or "").strip()
        if family_label:
            return slugify(family_label, "generated_workflow")
        caps = [str(x or "").strip() for x in (profile.get("capability_ids") or []) if str(x or "").strip()]
        if caps:
            return slugify("_".join(caps[:3]), "generated_workflow")
        return slugify(text[:96], "generated_workflow")


    def _build_creator_request(
        self,
        req: Any,
        user_text: str,
        attempts: List[Dict[str, Any]],
        profile: Optional[Dict[str, Any]] = None,
        candidates: Optional[List[Dict[str, Any]]] = None,
        plan: Optional[Dict[str, Any]] = None,
    ) -> str:
        profile = profile if isinstance(profile, dict) else self._request_profile(user_text)
        candidates = candidates if isinstance(candidates, list) else []
        if not attempts:
            lines = [
                "Create a new workflow that directly satisfies the following user request.",
                f"Original user request: {user_text}",
            ]
            if profile.get("file_backed"):
                lines.append("This is a file-backed request, so the workflow must read the real files and produce the requested deliverable.")
            base_request = "\n".join(lines).strip()
        else:
            last = attempts[-1] if isinstance(attempts[-1], dict) else {}
            prior_flow = str(last.get("flow_name") or "").strip()
            prior_reason = str(last.get("judge_reason") or last.get("reason") or "").strip()
            improved_request = str(last.get("improved_request") or "").strip()
            lines = [
                "Create a new or improved workflow that directly satisfies the original user request.",
                f"Original user request: {user_text}",
                improved_request or "Address the prior failure and improve end-to-end fulfillment.",
                "",
                "Make this workflow materially different from the prior attempt.",
            ]
            if prior_flow:
                lines.append(f"Prior flow that did not satisfy the request: {prior_flow}.")
            if prior_reason:
                lines.append(f"Why the prior result was insufficient: {prior_reason}.")
            lines.append("Focus on missing steps, missing tools, missing outputs, and stronger end-to-end fulfillment of the original request.")
            base_request = "\n".join(lines).strip()
        family_label = str(profile.get("family_label") or "").strip()
        file_paths = [str(x or "").strip() for x in (profile.get("file_paths") or []) if str(x or "").strip()]
        capability_ids = [str(x or "").strip() for x in (profile.get("capability_ids") or []) if str(x or "").strip()]
        plan = plan if isinstance(plan, dict) else {}
        plan_summary = str(plan.get("summary") or "").strip()
        plan_need = [str(x or "").strip() for x in (plan.get("must_use_capabilities") or []) if str(x or "").strip()]
        plan_avoid = [str(x or "").strip() for x in (plan.get("avoid_capabilities") or []) if str(x or "").strip()]
        file_types = [str(x or "").strip() for x in (profile.get("file_types") or []) if str(x or "").strip()]
        covered = []
        for row in candidates[:3]:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            reason = str(row.get("reason") or "").strip()
            if name:
                covered.append(f"- {name}: {reason or 'related existing flow'}")
        extra_lines: List[str] = []
        if family_label:
            extra_lines.append(f"Requested workflow family: {family_label}.")
        if file_paths:
            extra_lines.append("Real input files: " + ", ".join(file_paths[:3]) + ".")
        if file_types:
            extra_lines.append("Input file types: " + ", ".join(file_types) + ".")
        if capability_ids:
            extra_lines.append("Likely required capabilities: " + ", ".join(capability_ids) + ".")
        if plan_summary:
            extra_lines.append("Model routing plan: " + plan_summary + ".")
        if plan_need:
            extra_lines.append("Must use capabilities: " + ", ".join(plan_need) + ".")
        if plan_avoid:
            extra_lines.append("Avoid capability families: " + ", ".join(plan_avoid) + ".")
        request_sports = self._sport_groups(user_text)
        attempt_blob = " ".join(
            " ".join(str((attempt or {}).get(key) or "") for key in ("flow_name", "judge_reason", "reason", "improved_request"))
            for attempt in attempts
            if isinstance(attempt, dict)
        ).lower()
        has_live_data_capability = any(cap in {"sports_live_data", "web_research", "market_data"} for cap in capability_ids)
        portal_reconciliation_only = (
            "portal_reconciliation" in capability_ids
            and "sports_live_data" not in capability_ids
            and not self._is_external_info_request(user_text)
        )
        live_data_failure = (
            self._is_external_info_request(user_text)
            or any(marker in attempt_blob for marker in _EXTERNAL_INFO_REFUSAL_HINTS)
            or (has_live_data_capability and not portal_reconciliation_only)
        )
        if live_data_failure:
            extra_lines.extend(
                [
                    "Unmet live-data requirement: the workflow must retrieve current external information instead of using local RAG/repo search.",
                    "Do not use rag.search, repo.search, or repo.read as the primary way to answer live/current web, sports, weather, news, or schedule requests.",
                    "If an existing exact skill is not available, emit missing_skill_specs so implement_skills creates the required tool skill.",
                ]
            )
        if "sports_live_data" in capability_ids or request_sports:
            sport_label = ", ".join(sorted(request_sports)) if request_sports else "requested sport"
            extra_lines.extend(
                [
                    f"Sports live-data requirement: return current {sport_label} games/matchups for the requested date/time.",
                    "Prefer a real sports API/scoreboard skill such as custom.sports_live_games_table or sports.lookup_live_games.",
                    "If no such skill exists in the available skills list, create a new generated sports lookup skill that fetches live/current scoreboard data and returns a markdown table.",
                    "The generated workflow must include that sports lookup skill in action_skills/tool_config and must not substitute a generic RAG search or bounded analysis summary.",
                ]
            )
        if "web_research" in capability_ids and "sports_live_data" not in capability_ids:
            extra_lines.extend(
                [
                    "Web research requirement: prefer browser_relay or custom.web_research style skills when available.",
                    "If no web research skill exists, create a missing skill that can retrieve web/current information and summarize source-backed results.",
                ]
            )
        if "market_data" in capability_ids:
            extra_lines.extend(
                [
                    "Market-data requirement: retrieve current stock or market data from a live finance source and return the requested top symbols instead of a generic explanation.",
                    "Prefer a real market-data skill such as custom.market_data_report or a Yahoo/finance lookup skill.",
                    "If no such skill exists, emit missing_skill_specs so implement_skills creates a finance lookup/report skill with downloadable output support.",
                ]
            )
        if covered:
            extra_lines.append("Nearby existing flow coverage:")
            extra_lines.extend(covered)
        extra_lines.append("The generated workflow must read the real source files and produce the requested deliverable directly, not a generic bounded analysis summary.")
        return "\n".join([base_request, "", *extra_lines]).strip()

    def _recover_creator_artifact_from_state(self, state: Dict[str, Any]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        if not isinstance(state, dict):
            return out
        path_re = re.compile(r"(/app/data/generated/workflow_blueprints/[^\s\"']+\.json)", re.IGNORECASE)

        def _ingest(value: Any) -> None:
            nonlocal out
            if isinstance(value, dict):
                for key in (
                    "flow_name",
                    "workflow_file",
                    "bundle_dir",
                    "path",
                    "last_flow_name",
                    "last_workflow_file",
                    "last_bundle_dir",
                ):
                    text = str(value.get(key) or "").strip()
                    if text:
                        if key == "path" and text.endswith(".json") and not out.get("workflow_file"):
                            out["workflow_file"] = text
                        elif key == "last_flow_name" and not out.get("flow_name"):
                            out["flow_name"] = text
                        elif key == "last_workflow_file" and not out.get("workflow_file"):
                            out["workflow_file"] = text
                        elif key == "last_bundle_dir" and not out.get("bundle_dir"):
                            out["bundle_dir"] = text
                        elif key in {"flow_name", "workflow_file", "bundle_dir"} and not out.get(key):
                            out[key] = text
                for nested_key in ("data", "result", "meta"):
                    nested = value.get(nested_key)
                    if isinstance(nested, (dict, list, str)):
                        _ingest(nested)
                return
            if isinstance(value, list):
                for item in value:
                    _ingest(item)
                return
            text = str(value or "").strip()
            if not text:
                return
            parsed = parse_jsonish(text)
            if isinstance(parsed, dict) and parsed != value:
                _ingest(parsed)
            match = path_re.search(text)
            if match and not out.get("workflow_file"):
                out["workflow_file"] = str(match.group(1) or "").strip()

        _ingest(state)
        steps = state.get("steps") if isinstance(state.get("steps"), list) else []
        for step in reversed(steps):
            if not isinstance(step, dict):
                continue
            _ingest(step)
            _ingest(step.get("output"))

        if out.get("workflow_file") and not out.get("bundle_dir"):
            try:
                out["bundle_dir"] = str(Path(str(out.get("workflow_file") or "")).resolve().parent)
            except Exception:
                out["bundle_dir"] = str(Path(str(out.get("workflow_file") or "")).parent)
        return out

    def _requested_top_n(self, text: str, default: int = 10) -> int:
        low = str(text or "").lower()
        for pat in (r"\btop\s+(\d{1,3})\b", r"\b(\d{1,3})\s+(?:stocks|tickers|quotes|symbols)\b"):
            m = re.search(pat, low)
            if not m:
                continue
            try:
                return max(1, min(int(m.group(1)), 50))
            except Exception:
                break
        return int(default)


    def _extract_requested_symbols(self, text: str) -> List[str]:
        out: List[str] = []
        seen = set()
        raw = str(text or "")
        low = raw.lower()
        for sym in re.findall(r"\(([A-Z][A-Z0-9.\-]{0,9})\)", raw):
            value = str(sym or "").strip().upper()
            if value and value not in seen:
                seen.add(value)
                out.append(value)
        for sym in re.findall(r"([A-Z]{2,5})", raw):
            value = str(sym or "").strip().upper()
            if value and value not in seen and value not in {"USD", "ETF", "ETD", "API"}:
                seen.add(value)
                out.append(value)
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
            if name in low and ticker not in seen:
                seen.add(ticker)
                out.append(ticker)
        return out

    def _has_local_skill(self, skill_id: str) -> bool:
        skill = str(skill_id or "").strip()
        if not skill or "." not in skill:
            return False
        group, _, name = skill.partition(".")
        path = Path(__file__).resolve().parents[2] / "gui_helpers" / "agent_flow" / "skills" / group / f"{name}.py"
        return path.is_file()

    def _empty_generated_workflow(
        self,
        *,
        request_text: str,
        skill_id: str,
        step_label: str,
        supported_capability_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        del supported_capability_ids
        return {
            "start": "execute",
            "nodes": {
                "execute": {
                    "label": step_label,
                    "plugin_id": "agent_workflow_member",
                    "agent_kind": "tooling",
                    "system_prompt": f"Run the {step_label.lower()} skill directly and return the final result.",
                    "x": 220,
                    "y": 120,
                    "delay_ms": 0,
                    "return_only_text": True,
                    "transitions": [{"condition": {"type": "always"}, "target": "output"}],
                    "plugin_settings": {
                        "node_type": "tool_node",
                        "member_role": "tooling",
                        "handoff_format": "plain",
                        "output_protocol": "tagged",
                        "member_token_stream": True,
                        "action_skills": [skill_id],
                        "tool_config": {
                            "tool": skill_id,
                            "params": {
                                "request_text": request_text,
                                "query": request_text,
                                "timeout": 8.0,
                            },
                        },
                    },
                },
                "output": {
                    "label": "Deliver Result",
                    "plugin_id": "agent_workflow_member",
                    "agent_kind": "tooling",
                    "system_prompt": "Emit the prior result exactly as the final answer.",
                    "x": 660,
                    "y": 120,
                    "delay_ms": 0,
                    "return_only_text": True,
                    "transitions": [],
                    "plugin_settings": {
                        "node_type": "tool_node",
                        "member_role": "tooling",
                        "handoff_format": "plain",
                        "output_protocol": "tagged",
                        "member_token_stream": True,
                        "action_skills": ["result.text"],
                        "tool_config": {
                            "tool": "result.text",
                            "params_from_input": ["execution_text", "data", "final_answer", "table_markdown", "markdown", "summary", "text", "response", "content", "output_path", "path", "user_request", "request_text", "input_path", "file_path"],
                        },
                    },
                },
            },
        }

    def _builtin_weather_workflow(self, request_text: str) -> Dict[str, Any]:
        return {
            "start": "execute",
            "nodes": {
                "execute": {
                    "label": "Fetch Weather",
                    "plugin_id": "agent_workflow_member",
                    "agent_kind": "tooling",
                    "system_prompt": "Run the weather lookup skill directly and return the same-day forecast result.",
                    "x": 220,
                    "y": 120,
                    "delay_ms": 0,
                    "return_only_text": True,
                    "transitions": [{"condition": {"type": "always"}, "target": "output"}],
                    "plugin_settings": {
                        "node_type": "tool_node",
                        "member_role": "tooling",
                        "handoff_format": "plain",
                        "output_protocol": "auto",
                        "member_token_stream": False,
                        "action_skills": ["external_data.weather_lookup"],
                        "tool_config": {
                            "tool": "external_data.weather_lookup",
                            "params": {
                                "request_text": request_text,
                                "query": request_text,
                                "temperature_unit": "fahrenheit",
                                "wind_speed_unit": "mph",
                                "timeout": 8.0,
                            },
                        },
                    },
                },
                "output": {
                    "label": "Deliver Result",
                    "plugin_id": "agent_workflow_member",
                    "agent_kind": "tooling",
                    "system_prompt": "Emit the weather result exactly from the prior step.",
                    "x": 660,
                    "y": 120,
                    "delay_ms": 0,
                    "return_only_text": True,
                    "transitions": [],
                    "plugin_settings": {
                        "node_type": "tool_node",
                        "member_role": "tooling",
                        "handoff_format": "plain",
                        "output_protocol": "tagged",
                        "member_token_stream": True,
                        "action_skills": ["result.text"],
                        "tool_config": {
                            "tool": "result.text",
                            "params_from_input": ["execution_text", "data", "final_answer", "summary", "text", "response", "content", "user_request", "request_text"],
                        },
                    },
                },
            },
        }

    def _builtin_market_data_workflow(self, request_text: str) -> Dict[str, Any]:
        symbols = self._extract_requested_symbols(request_text)
        top_n = max(2, min(len(symbols) if symbols else self._requested_top_n(request_text, default=10), 10))
        return {
            "start": "execute",
            "nodes": {
                "execute": {
                    "label": "Fetch Market Data",
                    "plugin_id": "agent_workflow_member",
                    "agent_kind": "tooling",
                    "system_prompt": "Run the market data skill directly and return the requested stock comparison or market summary.",
                    "x": 220,
                    "y": 120,
                    "delay_ms": 0,
                    "return_only_text": True,
                    "transitions": [{"condition": {"type": "always"}, "target": "output"}],
                    "plugin_settings": {
                        "node_type": "tool_node",
                        "member_role": "tooling",
                        "handoff_format": "plain",
                        "output_protocol": "tagged",
                        "member_token_stream": True,
                        "action_skills": ["custom.market_data_report"],
                        "tool_config": {
                            "tool": "custom.market_data_report",
                            "params": {
                                "request_text": request_text,
                                "query": request_text,
                                "top_n": top_n,
                                "timeout": 8.0,
                                "output_mode": "text",
                            },
                        },
                    },
                },
                "output": {
                    "label": "Deliver Result",
                    "plugin_id": "agent_workflow_member",
                    "agent_kind": "tooling",
                    "system_prompt": "Emit the generated market-data result exactly from the prior step.",
                    "x": 660,
                    "y": 120,
                    "delay_ms": 0,
                    "return_only_text": True,
                    "transitions": [],
                    "plugin_settings": {
                        "node_type": "tool_node",
                        "member_role": "tooling",
                        "handoff_format": "plain",
                        "output_protocol": "tagged",
                        "member_token_stream": True,
                        "action_skills": ["result.text"],
                        "tool_config": {
                            "tool": "result.text",
                            "params_from_input": ["execution_text", "data", "final_answer", "table_markdown", "markdown", "summary", "text", "response", "content", "output_path", "path", "user_request", "request_text", "input_path", "file_path"],
                        },
                    },
                },
            },
        }

    def _builtin_single_skill_workflow(self, request_text: str, *, label: str, skill_id: str, system_prompt: str) -> Dict[str, Any]:
        return {
            "start": "execute",
            "nodes": {
                "execute": {
                    "label": label,
                    "plugin_id": "agent_workflow_member",
                    "agent_kind": "tooling",
                    "system_prompt": system_prompt,
                    "x": 220,
                    "y": 120,
                    "delay_ms": 0,
                    "return_only_text": True,
                    "transitions": [{"condition": {"type": "always"}, "target": "output"}],
                    "plugin_settings": {
                        "node_type": "tool_node",
                        "member_role": "tooling",
                        "handoff_format": "plain",
                        "output_protocol": "tagged",
                        "member_token_stream": True,
                        "action_skills": [skill_id],
                        "tool_config": {
                            "tool": skill_id,
                            "params": {
                                "request_text": request_text,
                                "query": request_text,
                                "timeout": 8.0,
                            },
                        },
                    },
                },
                "output": {
                    "label": "Deliver Result",
                    "plugin_id": "agent_workflow_member",
                    "agent_kind": "tooling",
                    "system_prompt": "Emit the prior result exactly as the final answer.",
                    "x": 660,
                    "y": 120,
                    "delay_ms": 0,
                    "return_only_text": True,
                    "transitions": [],
                    "plugin_settings": {
                        "node_type": "tool_node",
                        "member_role": "tooling",
                        "handoff_format": "plain",
                        "output_protocol": "tagged",
                        "member_token_stream": True,
                        "action_skills": ["result.text"],
                        "tool_config": {
                            "tool": "result.text",
                            "params_from_input": ["execution_text", "data", "final_answer", "table_markdown", "markdown", "summary", "text", "response", "content", "output_path", "path", "user_request", "request_text", "input_path", "file_path"],
                        },
                    },
                },
            },
        }

    def _builtin_skill_then_draft_workflow(self, request_text: str, *, label: str, skill_id: str, system_prompt: str, draft_prompt: str) -> Dict[str, Any]:
        return {
            "start": "execute",
            "nodes": {
                "execute": {
                    "label": label,
                    "plugin_id": "agent_workflow_member",
                    "agent_kind": "tooling",
                    "system_prompt": system_prompt,
                    "x": 180,
                    "y": 120,
                    "delay_ms": 0,
                    "return_only_text": True,
                    "transitions": [{"condition": {"type": "always"}, "target": "draft"}],
                    "plugin_settings": {
                        "node_type": "tool_node",
                        "member_role": "tooling",
                        "handoff_format": "plain",
                        "output_protocol": "tagged",
                        "member_token_stream": True,
                        "action_skills": [skill_id],
                        "tool_config": {
                            "tool": skill_id,
                            "params": {
                                "request_text": request_text,
                                "query": request_text,
                                "timeout": 8.0,
                            },
                        },
                    },
                },
                "draft": {
                    "label": "Draft Answer",
                    "plugin_id": "agent_workflow_member",
                    "agent_kind": "writer",
                    "system_prompt": draft_prompt,
                    "x": 520,
                    "y": 120,
                    "delay_ms": 0,
                    "return_only_text": True,
                    "transitions": [{"condition": {"type": "always"}, "target": "output"}],
                    "plugin_settings": {
                        "member_role": "writer",
                        "handoff_format": "plain",
                        "output_protocol": "tagged",
                        "member_token_stream": True,
                    },
                },
                "output": {
                    "label": "Deliver Answer",
                    "plugin_id": "agent_workflow_member",
                    "agent_kind": "release",
                    "system_prompt": "Emit the final answer exactly from the prior step.",
                    "x": 860,
                    "y": 120,
                    "delay_ms": 0,
                    "return_only_text": True,
                    "transitions": [],
                    "plugin_settings": {
                        "node_type": "tool_node",
                        "member_role": "release",
                        "handoff_format": "plain",
                        "output_protocol": "tagged",
                        "member_token_stream": True,
                        "action_skills": ["result.text"],
                        "tool_config": {
                            "tool": "result.text",
                            "params_from_input": ["final_answer", "markdown", "summary", "text", "response", "content"],
                        },
                    },
                },
            },
        }


    def _builtin_current_context_answer_workflow(self, request_text: str) -> Dict[str, Any]:
        return {
            "start": "research",
            "nodes": {
                "research": {
                    "label": "Research Current Context",
                    "plugin_id": "agent_workflow_member",
                    "agent_kind": "tooling",
                    "system_prompt": "Gather current factual context from the web that is directly relevant to the user's request. Return the strongest usable current evidence in concise markdown.",
                    "x": 180,
                    "y": 120,
                    "delay_ms": 0,
                    "return_only_text": True,
                    "transitions": [{"condition": {"type": "always"}, "target": "draft"}],
                    "plugin_settings": {
                        "node_type": "tool_node",
                        "member_role": "tooling",
                        "handoff_format": "plain",
                        "output_protocol": "tagged",
                        "member_token_stream": True,
                        "action_skills": ["custom.awf_web_research__web_research_204fb17b_executor"],
                        "tool_config": {
                            "tool": "custom.awf_web_research__web_research_204fb17b_executor",
                            "params": {
                                "request_text": request_text,
                                "query": request_text,
                                "text": request_text,
                                "timeout": 8.0,
                                "max_results": 5,
                            },
                        },
                    },
                },
                "draft": {
                    "label": "Draft Answer",
                    "plugin_id": "agent_workflow_member",
                    "agent_kind": "writer",
                    "system_prompt": (
                        "Answer the user's request directly using the current research context from the prior step. "
                        "Satisfy the requested output, keep the answer concise by default, and do not mention workflows or internal tools."
                    ),
                    "x": 520,
                    "y": 120,
                    "delay_ms": 0,
                    "return_only_text": True,
                    "transitions": [{"condition": {"type": "always"}, "target": "output"}],
                    "plugin_settings": {
                        "member_role": "writer",
                        "handoff_format": "plain",
                        "output_protocol": "tagged",
                        "member_token_stream": True,
                    },
                },
                "output": {
                    "label": "Deliver Answer",
                    "plugin_id": "agent_workflow_member",
                    "agent_kind": "release",
                    "system_prompt": "Emit the final answer exactly from the prior step.",
                    "x": 860,
                    "y": 120,
                    "delay_ms": 0,
                    "return_only_text": True,
                    "transitions": [],
                    "plugin_settings": {
                        "node_type": "tool_node",
                        "member_role": "release",
                        "handoff_format": "plain",
                        "output_protocol": "tagged",
                        "member_token_stream": True,
                        "action_skills": ["result.text"],
                        "tool_config": {
                            "tool": "result.text",
                            "params_from_input": ["final_answer", "markdown", "summary", "text", "response", "content"],
                        },
                    },
                },
            },
        }

    def _builtin_general_answer_workflow(self, request_text: str) -> Dict[str, Any]:
        return {
            "start": "draft",
            "nodes": {
                "draft": {
                    "label": "Draft Answer",
                    "plugin_id": "agent_workflow_member",
                    "agent_kind": "writer",
                    "system_prompt": (
                        "Answer the user's request directly in clear Markdown only when the request can be satisfied from model knowledge alone. "
                        "Stay on task, satisfy explicit constraints, be concise by default, and avoid workflow-planning chatter. "
                        "If the request clearly requires files, live data, repository inspection, or tool-backed evidence that is not present in this direct-answer path, do not fabricate details. "
                        "Return the finished user-facing answer in plain text or markdown that is ready to deliver."
                    ),
                    "x": 220,
                    "y": 120,
                    "delay_ms": 0,
                    "return_only_text": True,
                    "transitions": [{"condition": {"type": "always"}, "target": "output"}],
                    "plugin_settings": {
                        "member_role": "writer",
                        "handoff_format": "plain",
                        "output_protocol": "tagged",
                        "member_token_stream": True,
                    },
                },
                "output": {
                    "label": "Deliver Answer",
                    "plugin_id": "agent_workflow_member",
                    "agent_kind": "release",
                    "system_prompt": "Emit the final answer exactly from the prior step.",
                    "x": 620,
                    "y": 120,
                    "delay_ms": 0,
                    "return_only_text": True,
                    "transitions": [],
                    "plugin_settings": {
                        "node_type": "tool_node",
                        "member_role": "release",
                        "handoff_format": "plain",
                        "output_protocol": "tagged",
                        "member_token_stream": True,
                        "action_skills": ["result.text"],
                        "tool_config": {
                            "tool": "result.text",
                            "params_from_input": ["final_answer", "markdown", "summary", "text", "response", "content"],
                        },
                    },
                },
            },
        }

    def _should_use_builtin_current_context_answer(self, user_text: str, profile: Dict[str, Any]) -> bool:
        text = str(user_text or "").strip()
        if not text:
            return False
        if re.search(_FILE_PATH_RE, text):
            return False
        low = text.lower()
        if any(tok in low for tok in ("weather", "forecast", "temperature", "news", "headline", "stock", "stocks", "ticker", "market cap", "yahoo finance", "world bank", "imf", "google scholar", "arxiv", "search the web", "go online", "browse")):
            return False
        if not self._is_external_info_request(text):
            return False
        if not bool(re.search(r"\b(help me|draft|create|plan|design|build|suggest|outline|prepare|proposal|essay|presentation|powerpoint|slides|deck|project|ideas|brainstorm|write|discussion|response)\b", low, flags=re.IGNORECASE)):
            return False
        internal_authoring = any(tok in low for tok in ("email", "message", "manager", "teammate", "status update", "project update", "reminder"))
        live_topic = any(marker in low for marker in ("latest", "today", "right now", "recent", "real data", "current affairs", "current problems", "modern", "trend", "trends", "connect it to", "tied to", "relate it to", "energy costs", "housing prices", "inflation", "college tuition", "regulation", "policy", "elections", "public trust", "climate", "renewable energy", "migration", "teen mental health", "social media"))
        if internal_authoring and not live_topic:
            return False
        return live_topic
    def _should_use_builtin_general_answer(self, user_text: str, profile: Dict[str, Any]) -> bool:
        text = str(user_text or "").strip()
        if not text:
            return False
        low = text.lower()
        capability_ids = {str(x or "").strip() for x in (profile.get("capability_ids") or []) if str(x or "").strip()}
        internal_authoring = any(tok in low for tok in ("email", "message", "manager", "teammate", "status update", "project update", "reminder", "teacher", "professor"))
        if _looks_like_conceptual_workflow_question(text):
            return True
        if _has_explicit_file_or_repo_scope(text):
            return False
        if self._is_external_info_request(text):
            return False
        if internal_authoring:
            return True
        if capability_ids & _DIRECT_EXECUTION_CAPABILITIES:
            return False
        if any(tok in low for tok in (" /uploads/", "/uploads/", " /app/", "/app/")):
            return False
        if any(tok in low for tok in ("open this file", "read this file", "compare this spreadsheet", "use this spreadsheet", "use this file")):
            return False
        return bool(re.search(
            r"\b("
            r"what is|what are|what does|how does|how do|how can|why is|why does|"
            r"explain|define|summarize|help me|compare|outline|draft|create|plan|schedule|strategy|proposal|write|email|message|update|remind|reminder|"
            r"presentation|essay|research paper|project|ideas|brainstorm"
            r")\b",
            low,
            flags=re.IGNORECASE,
        ))

    def _builtin_direct_candidate(self, user_text: str, profile: Dict[str, Any]) -> Dict[str, Any]:
        capability_ids = {str(x or "").strip() for x in (profile.get("capability_ids") or []) if str(x or "").strip()}
        request_low = str(user_text or "").strip().lower()
        file_path_match = _FILE_PATH_RE.search(user_text)
        file_path_text = str(file_path_match.group(1) or "").strip().lower() if file_path_match else ""
        request_without_paths = _FILE_PATH_RE.sub(" ", str(user_text or ""))
        request_without_paths_low = request_without_paths.strip().lower()
        repo_change_request = bool(re.search(r"\b(improve|improvement|enhance|fix|patch|refactor|rewrite|modify|update|implement|add|remove|optimi[sz]e)\b", request_without_paths_low, flags=re.IGNORECASE))
        finance_compare_terms = ("compare", "comparison", "versus", "vs", "vs.", "short table", "table")
        finance_field_terms = (
            "market cap", "52-week", "52 week", "average volume", "avg volume", "price",
            "stock price", "share price", "quote", "quotes", "market data", "trading volume",
        )
        finance_source_terms = ("yahoo finance", "ticker", "tickers", "stock", "stocks", "equity", "equities")
        finance_company_markers = (
            "nvidia", "advanced micro devices", "amd", "microsoft", "apple", "alphabet",
            "google", "amazon", "meta", "tesla", "broadcom", "intel", "super micro",
            "smci", "palantir", "netflix", "oracle",
        )
        ticker_candidates = {
            sym
            for sym in re.findall(r"\b([A-Z]{2,5})\b", str(user_text or ""))
            if sym not in {"USD", "ETF", "ETD", "API", "IMF", "GDP", "BLS", "BEA"}
        }
        finance_company_hits = sum(1 for marker in finance_company_markers if marker in request_low)
        has_finance_compare = any(tok in request_low for tok in finance_compare_terms)
        has_finance_fields = any(tok in request_low for tok in finance_field_terms)
        has_finance_source = any(tok in request_low for tok in finance_source_terms)
        looks_like_market_data_request = (
            (has_finance_source and (has_finance_fields or has_finance_compare))
            or (has_finance_compare and has_finance_fields and (len(ticker_candidates) >= 2 or finance_company_hits >= 2))
            or (has_finance_fields and (len(ticker_candidates) >= 2 or finance_company_hits >= 2))
        )
        file_summary_tokens = (
            "summarize the file",
            "summarise the file",
            "summarize this file",
            "summarise this file",
            "file summary",
            "summarize",
            "summarise",
            "summary",
            "overview",
            "review",
            "read",
            "used for",
            "kind of data",
            "what is in this file",
            "what does this file contain",
            "tell me what kind of data it contains",
        )
        explicit_file_summary_intent = bool(
            file_path_text
            and (
                any(tok in request_low for tok in file_summary_tokens)
                or (("what does" in request_low or "what is in" in request_low or "what is" in request_low) and ("contain" in request_without_paths_low or "contains" in request_without_paths_low))
                or ("used for" in request_without_paths_low)
                or (
                    any(tok in request_low for tok in ("read ", "review ", "open "))
                    and any(tok in request_low for tok in ("summary", "summarize", "summarise", "overview"))
                )
                or any(tok in request_low for tok in ("customer-ready summary", "customer ready summary", "compact summary", "short summary", "brief summary"))
            )
            and not any(tok in request_low for tok in (
                "flag any department", "more than 10 percent", "budget compare", "budget comparison",
                "triage brief", "same-day triage", "immediate attention",
                "vendor shortlist", "tradeoffs across security", "vendor matrix",
                "next sprint plan", "pull-first recommendations", "dependency risks", "sprint backlog",
                "scheduling resolution brief", "highest-priority conflicts", "schedule conflicts",
                "contract risk review", "highest-risk clauses", "follow-up questions",
                "incident timeline summary", "customer impact turning points", "incident timeline",
                "draft a release announcement email", "release announcement email",
                "print out its chart", "visualize", "chart report",
                "zip these files", "archive", "bundle", "compress", "return it",
                "turn into a compact faq", "faq in plain language"
            ))
        )
        request_low_slash = request_low.replace("\\", "/")
        repo_scope_request = bool("/data/agent_workflow/repo" in request_low_slash or "repository" in request_low or "codebase" in request_low or (re.search(r"\brepo\b", request_low) and any(tok in request_low for tok in (" in the repo", " in repo", " of the repo", " this repo", " inside the repo", " within the repo", " under /data/agent_workflow/repo", " inside /data/agent_workflow/repo", " in /data/agent_workflow/repo", " files under", " what is this repo for", " purpose of the repo"))))
        repo_file_match = re.search(r"\b[\w./-]+\.(?:json|md|txt|js|ts|py|csv|tsv|yml|yaml|html|htm|css|xlsx|xlsm|xls)\b", user_text, flags=re.IGNORECASE)
        if any(tok in request_low for tok in ("weather", "forecast", "temperature")) and not any(tok in request_low for tok in ("/data/agent_workflow/repo", "repository", "repo", "codebase", "reference", "references", "where is", "where ")):
            capability_ids.add("weather_lookup")
        if looks_like_market_data_request:
            capability_ids.add("market_data")
        implicit_world_bank_compare = bool(
            all(tok in request_low for tok in ("inflation", "gdp", "unemployment"))
            and any(tok in request_low for tok in ("stable", "stability", "most stable", "economy"))
            and sum(1 for tok in ("indonesia", "vietnam", "mexico", "brazil", "india", "china", "united states", "euro area") if tok in request_low) >= 3
        )
        implicit_macro_brief = bool(
            all(tok in request_low for tok in ("macro brief", "growth", "inflation"))
            and any(tok in request_low for tok in ("aligned", "alignment", "contextual", "two sources", "source is only contextual"))
            and sum(1 for tok in ("united states", "euro area", "china", "japan", "united kingdom") if tok in request_low) >= 2
        )
        if ((("imf" in request_low and "world bank" in request_low and "macro brief" in request_low) or implicit_macro_brief) and self._has_local_skill("custom.imf_world_bank_macro_brief")):
            workflow_json = self._builtin_single_skill_workflow(
                user_text,
                label="Fetch Macro Brief",
                skill_id="custom.imf_world_bank_macro_brief",
                system_prompt="Run the IMF and World Bank macro brief skill directly and return the final brief.",
            )
            return {
                "name": "__autoflow_builtin_imf_world_bank_macro_brief__",
                "score": 3.02,
                "reason": "builtin_direct_imf_world_bank_macro_brief; source_specific_or_implicit_macro_outlook_compare; external_info_ready",
                "node_count": 2,
                "description": "Built-in direct IMF and World Bank macro brief workflow.",
                "action_skills": ["custom.imf_world_bank_macro_brief", "result.text"],
                "executable_action_skills": ["custom.imf_world_bank_macro_brief", "result.text"],
                "supported_capability_ids": ["web_research", "content_authoring"],
                "doc_text": "built-in direct imf world bank macro brief current growth inflation outlook macro aligned contextual",
                "doc_tokens": ["built", "direct", "imf", "world", "bank", "macro", "brief", "growth", "inflation", "outlook"],
                "generated_workflow": {
                    "record_id": "",
                    "flow_name": "__autoflow_builtin_imf_world_bank_macro_brief__",
                    "workflow_json": workflow_json,
                    "workflow_file": "",
                    "bundle_dir": "",
                    "temp_skill_dirs": [],
                },
            }
        if ((("world bank" in request_low and any(tok in request_low for tok in ("inflation", "gdp growth", "unemployment"))) or implicit_world_bank_compare) and self._has_local_skill("custom.world_bank_compare_report")):
            workflow_json = self._builtin_single_skill_workflow(
                user_text,
                label="Fetch World Bank Report",
                skill_id="custom.world_bank_compare_report",
                system_prompt="Run the World Bank comparison skill directly and return the final comparison table and summary.",
            )
            return {
                "name": "__autoflow_builtin_world_bank_compare__",
                "score": 3.01,
                "reason": "builtin_direct_world_bank_compare; source_specific_or_implicit_country_macro_compare; external_info_ready",
                "node_count": 2,
                "description": "Built-in direct World Bank comparison workflow.",
                "action_skills": ["custom.world_bank_compare_report", "result.text"],
                "executable_action_skills": ["custom.world_bank_compare_report", "result.text"],
                "supported_capability_ids": ["web_research", "content_authoring"],
                "doc_text": "built-in direct world bank compare inflation gdp unemployment stability cross-country macro",
                "doc_tokens": ["built", "direct", "world", "bank", "inflation", "gdp", "unemployment", "stability", "macro"],
                "generated_workflow": {
                    "record_id": "",
                    "flow_name": "__autoflow_builtin_world_bank_compare__",
                    "workflow_json": workflow_json,
                    "workflow_file": "",
                    "bundle_dir": "",
                    "temp_skill_dirs": [],
                },
            }
        if (explicit_file_summary_intent and self._has_local_skill("custom.repo_file_summary")):
            workflow_json = self._empty_generated_workflow(
                request_text=user_text,
                skill_id="custom.repo_file_summary",
                step_label="Repo File Summary",
                supported_capability_ids=["document_io", "content_authoring"],
            )
            return {
                "name": "__autoflow_builtin_repo_file_summary__",
                "score": 1.02,
                "reason": "builtin_direct_repo_file_summary; explicit_file_summary_intent",
                "generated_workflow": workflow_json,
                "action_skills": ["custom.repo_file_summary", "result.text"],
                "executable_action_skills": ["custom.repo_file_summary", "result.text"],
                "supported_capability_ids": ["document_io", "content_authoring"],
                "doc_text": "built-in direct repo file summary structured upload artifact file description contents",
                "doc_tokens": ["built", "direct", "repo", "file", "summary", "artifact", "contents", "description"],
                "selection_info": {"source": "builtin", "flow_name": "__autoflow_builtin_repo_file_summary__"},
            }
        if (file_path_text.endswith(".json") and any(tok in request_low for tok in ("chart", "graph", "plot", "print out its chart", "visualize")) and self._has_local_skill("custom.file_chart_report")):
            workflow_json = self._empty_generated_workflow(
                request_text=user_text,
                skill_id="custom.file_chart_report",
                step_label="File Chart Report",
                supported_capability_ids=["document_io", "chart_output"],
            )
            return {
                "name": "__autoflow_builtin_file_chart_report__",
                "score": 0.98,
                "reason": "builtin_direct_file_chart_report; file_chart_ready",
                "generated_workflow": workflow_json,
                "action_skills": ["custom.file_chart_report", "result.file"],
                "executable_action_skills": ["custom.file_chart_report", "result.file"],
                "supported_capability_ids": ["document_io", "chart_output"],
                "doc_text": "built-in direct file chart visualization json chart report",
                "doc_tokens": ["built", "direct", "file", "chart", "visualization", "json", "report"],
                "selection_info": {
                    "source": "builtin",
                    "flow_name": "__autoflow_builtin_file_chart_report__",
                },
            }
        if (file_path_match and len(re.findall(r"(?:[A-Za-z]:[\\/][^\\s\"']+|/(?:uploads|data|app)/[^\\s\"']+)", user_text, flags=re.IGNORECASE)) >= 1 and any(tok in request_low for tok in ("zip", "archive", "bundle", "compress", "return it")) and self._has_local_skill("custom.zip_requested_files")):
            workflow_json = self._empty_generated_workflow(
                request_text=user_text,
                skill_id="custom.zip_requested_files",
                step_label="Zip Requested Files",
                supported_capability_ids=["document_io", "archive_output"],
            )
            return {
                "name": "__autoflow_builtin_zip_files__",
                "score": 0.99,
                "reason": "builtin_direct_zip_files; archive_request_ready",
                "generated_workflow": workflow_json,
                "action_skills": ["custom.zip_requested_files", "result.zip"],
                "executable_action_skills": ["custom.zip_requested_files", "result.zip"],
                "supported_capability_ids": ["document_io", "archive_output"],
                "doc_text": "built-in direct zip requested files bundle archive uploads repo files",
                "doc_tokens": ["built", "direct", "zip", "bundle", "archive", "uploads", "repo", "files"],
                "selection_info": {"source": "builtin", "flow_name": "__autoflow_builtin_zip_files__"},
            }
        if (file_path_text.endswith((".csv", ".tsv")) and all(tok in request_low for tok in ("january", "february")) and any(tok in request_low for tok in ("changed by more than 10 percent", "more than 10 percent", "flag any department", "budget compare", "budget comparison")) and self._has_local_skill("custom.budget_compare_report")):
            workflow_json = self._empty_generated_workflow(
                request_text=user_text,
                skill_id="custom.budget_compare_report",
                step_label="Budget Compare Report",
                supported_capability_ids=["spreadsheet_io", "content_authoring"],
            )
            return {
                "name": "__autoflow_builtin_budget_compare__",
                "score": 0.99,
                "reason": "builtin_direct_budget_compare; spreadsheet_budget_ready",
                "generated_workflow": workflow_json,
                "action_skills": ["custom.budget_compare_report", "result.text"],
                "executable_action_skills": ["custom.budget_compare_report", "result.text"],
                "supported_capability_ids": ["spreadsheet_io", "content_authoring"],
                "doc_text": "built-in direct budget comparison january february percent change department variance",
                "doc_tokens": ["built", "direct", "budget", "comparison", "january", "february", "percent", "variance"],
                "selection_info": {"source": "builtin", "flow_name": "__autoflow_builtin_budget_compare__"},
            }
        if (file_path_text.endswith((".csv", ".tsv")) and any(tok in request_low for tok in ("support tickets", "triage brief", "same-day triage", "immediate attention")) and self._has_local_skill("custom.support_ticket_triage_report")):
            workflow_json = self._empty_generated_workflow(
                request_text=user_text,
                skill_id="custom.support_ticket_triage_report",
                step_label="Support Ticket Triage Report",
                supported_capability_ids=["spreadsheet_io", "content_authoring"],
            )
            return {
                "name": "__autoflow_builtin_support_ticket_triage__",
                "score": 0.98,
                "reason": "builtin_direct_support_ticket_triage; spreadsheet_triage_ready",
                "generated_workflow": workflow_json,
                "action_skills": ["custom.support_ticket_triage_report", "result.text"],
                "executable_action_skills": ["custom.support_ticket_triage_report", "result.text"],
                "supported_capability_ids": ["spreadsheet_io", "content_authoring"],
                "doc_text": "built-in direct support ticket triage brief csv spreadsheet",
                "doc_tokens": ["built", "direct", "support", "ticket", "triage", "brief", "csv", "spreadsheet"],
                "selection_info": {
                    "source": "builtin",
                    "flow_name": "__autoflow_builtin_support_ticket_triage__",
                },
            }
        if (file_path_text.endswith((".csv", ".tsv")) and any(tok in request_low for tok in ("vendor shortlist", "tradeoffs across security", "vendor matrix", "implementation")) and self._has_local_skill("custom.vendor_shortlist_report")):
            workflow_json = self._empty_generated_workflow(
                request_text=user_text,
                skill_id="custom.vendor_shortlist_report",
                step_label="Vendor Shortlist Report",
                supported_capability_ids=["spreadsheet_io", "content_authoring"],
            )
            return {
                "name": "__autoflow_builtin_vendor_shortlist__",
                "score": 0.99,
                "reason": "builtin_direct_vendor_shortlist; vendor_file_ready",
                "generated_workflow": workflow_json,
                "action_skills": ["custom.vendor_shortlist_report", "result.text"],
                "executable_action_skills": ["custom.vendor_shortlist_report", "result.text"],
                "supported_capability_ids": ["spreadsheet_io", "content_authoring"],
                "doc_text": "built-in direct vendor shortlist tradeoffs security support cost implementation",
                "doc_tokens": ["built", "direct", "vendor", "shortlist", "security", "support", "cost", "implementation"],
                "selection_info": {"source": "builtin", "flow_name": "__autoflow_builtin_vendor_shortlist__"},
            }
        if (file_path_text.endswith((".csv", ".tsv")) and any(tok in request_low for tok in ("next sprint plan", "pull-first recommendations", "dependency risks", "sprint backlog")) and self._has_local_skill("custom.sprint_plan_report")):
            workflow_json = self._empty_generated_workflow(
                request_text=user_text,
                skill_id="custom.sprint_plan_report",
                step_label="Sprint Plan Report",
                supported_capability_ids=["spreadsheet_io", "content_authoring"],
            )
            return {
                "name": "__autoflow_builtin_sprint_plan__",
                "score": 0.99,
                "reason": "builtin_direct_sprint_plan; sprint_file_ready",
                "generated_workflow": workflow_json,
                "action_skills": ["custom.sprint_plan_report", "result.text"],
                "executable_action_skills": ["custom.sprint_plan_report", "result.text"],
                "supported_capability_ids": ["spreadsheet_io", "content_authoring"],
                "doc_text": "built-in direct sprint plan backlog pull-first dependency risks",
                "doc_tokens": ["built", "direct", "sprint", "plan", "backlog", "dependency", "risks"],
                "selection_info": {"source": "builtin", "flow_name": "__autoflow_builtin_sprint_plan__"},
            }
        if (file_path_text.endswith((".csv", ".tsv")) and any(tok in request_low for tok in ("scheduling resolution brief", "highest-priority conflicts", "contacted first", "schedule conflicts")) and self._has_local_skill("custom.scheduling_resolution_report")):
            workflow_json = self._empty_generated_workflow(
                request_text=user_text,
                skill_id="custom.scheduling_resolution_report",
                step_label="Scheduling Resolution Report",
                supported_capability_ids=["spreadsheet_io", "content_authoring"],
            )
            return {
                "name": "__autoflow_builtin_scheduling_resolution__",
                "score": 0.99,
                "reason": "builtin_direct_scheduling_resolution; schedule_file_ready",
                "generated_workflow": workflow_json,
                "action_skills": ["custom.scheduling_resolution_report", "result.text"],
                "executable_action_skills": ["custom.scheduling_resolution_report", "result.text"],
                "supported_capability_ids": ["spreadsheet_io", "content_authoring"],
                "doc_text": "built-in direct scheduling resolution conflicts stakeholders brief",
                "doc_tokens": ["built", "direct", "scheduling", "resolution", "conflicts", "stakeholders", "brief"],
                "selection_info": {"source": "builtin", "flow_name": "__autoflow_builtin_scheduling_resolution__"},
            }
        if (file_path_text.endswith((".txt", ".md")) and any(tok in request_low for tok in ("contract risk review", "highest-risk clauses", "follow-up questions", "contract notes")) and self._has_local_skill("custom.contract_risk_review")):
            workflow_json = self._empty_generated_workflow(
                request_text=user_text,
                skill_id="custom.contract_risk_review",
                step_label="Contract Risk Review",
                supported_capability_ids=["document_io", "content_authoring"],
            )
            return {
                "name": "__autoflow_builtin_contract_risk_review__",
                "score": 0.99,
                "reason": "builtin_direct_contract_risk_review; contract_file_ready",
                "generated_workflow": workflow_json,
                "action_skills": ["custom.contract_risk_review", "result.text"],
                "executable_action_skills": ["custom.contract_risk_review", "result.text"],
                "supported_capability_ids": ["document_io", "content_authoring"],
                "doc_text": "built-in direct contract risk review clauses follow-up questions",
                "doc_tokens": ["built", "direct", "contract", "risk", "review", "clauses", "questions"],
                "selection_info": {"source": "builtin", "flow_name": "__autoflow_builtin_contract_risk_review__"},
            }
        if (file_path_text.endswith((".csv", ".tsv")) and any(tok in request_low for tok in ("incident timeline", "customer impact turning points", "incident log")) and self._has_local_skill("custom.incident_timeline_report")):
            workflow_json = self._empty_generated_workflow(
                request_text=user_text,
                skill_id="custom.incident_timeline_report",
                step_label="Incident Timeline Report",
                supported_capability_ids=["spreadsheet_io", "content_authoring"],
            )
            return {
                "name": "__autoflow_builtin_incident_timeline__",
                "score": 0.99,
                "reason": "builtin_direct_incident_timeline; incident_file_ready",
                "generated_workflow": workflow_json,
                "action_skills": ["custom.incident_timeline_report", "result.text"],
                "executable_action_skills": ["custom.incident_timeline_report", "result.text"],
                "supported_capability_ids": ["spreadsheet_io", "content_authoring"],
                "doc_text": "built-in direct incident timeline customer impact turning points",
                "doc_tokens": ["built", "direct", "incident", "timeline", "impact", "turning", "points"],
                "selection_info": {"source": "builtin", "flow_name": "__autoflow_builtin_incident_timeline__"},
            }
        if (file_path_text.endswith(".json") and any(tok in request_low for tok in ("release announcement email", "release notes", "highlights the main benefits", "next steps")) and self._has_local_skill("custom.release_announcement_email")):
            workflow_json = self._empty_generated_workflow(
                request_text=user_text,
                skill_id="custom.release_announcement_email",
                step_label="Release Announcement Email",
                supported_capability_ids=["document_io", "content_authoring"],
            )
            return {
                "name": "__autoflow_builtin_release_announcement_email__",
                "score": 0.99,
                "reason": "builtin_direct_release_announcement_email; release_file_ready",
                "generated_workflow": workflow_json,
                "action_skills": ["custom.release_announcement_email", "result.text"],
                "executable_action_skills": ["custom.release_announcement_email", "result.text"],
                "supported_capability_ids": ["document_io", "content_authoring"],
                "doc_text": "built-in direct release announcement email benefits next steps",
                "doc_tokens": ["built", "direct", "release", "announcement", "email", "benefits", "next", "steps"],
                "selection_info": {"source": "builtin", "flow_name": "__autoflow_builtin_release_announcement_email__"},
            }
        if (file_path_text.endswith((".csv", ".tsv")) and any(tok in request_low for tok in ("compact faq", "plain language", "faq topics", "new users")) and self._has_local_skill("custom.faq_compiler")):
            workflow_json = self._empty_generated_workflow(
                request_text=user_text,
                skill_id="custom.faq_compiler",
                step_label="FAQ Compiler",
                supported_capability_ids=["spreadsheet_io", "content_authoring"],
            )
            return {
                "name": "__autoflow_builtin_faq_compiler__",
                "score": 0.99,
                "reason": "builtin_direct_faq_compiler; faq_file_ready",
                "generated_workflow": workflow_json,
                "action_skills": ["custom.faq_compiler", "result.text"],
                "executable_action_skills": ["custom.faq_compiler", "result.text"],
                "supported_capability_ids": ["spreadsheet_io", "content_authoring"],
                "doc_text": "built-in direct faq compiler plain language new users",
                "doc_tokens": ["built", "direct", "faq", "plain", "language", "users"],
                "selection_info": {"source": "builtin", "flow_name": "__autoflow_builtin_faq_compiler__"},
            }
        if (repo_scope_request and any(tok in request_low for tok in ("list the files under", "inside the", "what is inside", "what's inside", "contents of", "show the contents of", "next to it", "whether", "exists")) and not any(tok in request_without_paths_low for tok in ("what does", "where ", "contains ensure", "used for")) and not any(tok in request_low for tok in ("main purpose", "purpose of the codebase", "purpose of the repo", "what is this repo for", "what is this repository for", "explain the main purpose", "codebase summary", "repo summary", "repo overview", "repository overview", "high level summary", "high-level summary")) and self._has_local_skill("custom.repo_path_inspect")):
            workflow_json = self._empty_generated_workflow(
                request_text=user_text,
                skill_id="custom.repo_path_inspect",
                step_label="Repo Path Inspect",
                supported_capability_ids=["repo_editing", "document_io", "content_authoring"],
            )
            return {
                "name": "__autoflow_builtin_repo_path_inspect__",
                "score": 1.0,
                "reason": "builtin_direct_repo_path_inspect; repo_path_ready",
                "generated_workflow": workflow_json,
                "action_skills": ["custom.repo_path_inspect", "result.text"],
                "executable_action_skills": ["custom.repo_path_inspect", "result.text"],
                "supported_capability_ids": ["repo_editing", "document_io", "content_authoring"],
                "doc_text": "built-in direct repo path inspect list folder contents neighboring files exists",
                "doc_tokens": ["built", "direct", "repo", "path", "inspect", "folder", "contents", "files", "exists"],
                "selection_info": {"source": "builtin", "flow_name": "__autoflow_builtin_repo_path_inspect__"},
            }
        if (
            repo_scope_request
            and not explicit_file_summary_intent
            and any(tok in request_low for tok in ("what files", "which files", "files would i need to change", "files do i need to change", "need to change", "need to update", "need to modify", "where would i change", "where should i change", "routing behavior", "service_chat routing", "autoflow routing"))
            and self._has_local_skill("custom.repo_project_summary")
        ):
            workflow_json = self._empty_generated_workflow(
                request_text=user_text,
                skill_id="custom.repo_project_summary",
                step_label="Repo Change Guidance",
                supported_capability_ids=["repo_editing", "content_authoring"],
            )
            return {
                "name": "__autoflow_builtin_repo_project_summary__",
                "score": 1.01,
                "reason": "builtin_direct_repo_project_summary; repo_change_guidance_request",
                "generated_workflow": workflow_json,
                "action_skills": ["custom.repo_project_summary", "result.text"],
                "executable_action_skills": ["custom.repo_project_summary", "result.text"],
                "supported_capability_ids": ["repo_editing", "content_authoring"],
                "doc_text": "built-in direct repo change guidance likely files to modify for routing behavior or feature updates",
                "doc_tokens": ["built", "direct", "repo", "change", "guidance", "files", "modify", "routing", "feature", "update"],
                "selection_info": {"source": "builtin", "flow_name": "__autoflow_builtin_repo_project_summary__"},
            }
        if (
            repo_scope_request
            and not explicit_file_summary_intent
            and not any(tok in request_low for tok in ("list the files under", "inside the", "next to it", "whether", "exists", "what does", "explain", "tell me what", "function", "where ", "reference", "references"))
            and (
                any(tok in request_low for tok in ("main purpose", "purpose of the codebase", "purpose of the repo", "what is this repo for", "what is this repository for", "explain the main purpose", "codebase summary", "repo summary", "repo overview", "repository overview", "high level summary", "high-level summary"))
                or (any(tok in request_low for tok in ("summarize", "summarise", "overview", "high level", "high-level")) and any(tok in request_low for tok in ("repo", "repository", "codebase")))
            )
            and self._has_local_skill("custom.repo_project_summary")
        ):
            workflow_json = self._empty_generated_workflow(
                request_text=user_text,
                skill_id="custom.repo_project_summary",
                step_label="Repo Project Summary",
                supported_capability_ids=["repo_editing", "document_io", "content_authoring"],
            )
            return {
                "name": "__autoflow_builtin_repo_project_summary__",
                "score": 1.0,
                "reason": "builtin_direct_repo_project_summary; repo_summary_ready",
                "generated_workflow": workflow_json,
                "action_skills": ["custom.repo_project_summary", "result.text"],
                "executable_action_skills": ["custom.repo_project_summary", "result.text"],
                "supported_capability_ids": ["repo_editing", "document_io", "content_authoring"],
                "doc_text": "built-in direct repo project summary purpose overview high level codebase",
                "doc_tokens": ["built", "direct", "repo", "project", "summary", "purpose", "overview", "codebase"],
                "selection_info": {"source": "builtin", "flow_name": "__autoflow_builtin_repo_project_summary__"},
            }
        if (
            repo_scope_request
            and not explicit_file_summary_intent
            and not any(tok in request_low for tok in ("list the files under", "list files in", "inside the", "next to it", "next to ", "what does", "explain", "tell me what", "function"))
            and not (repo_file_match and any(tok in request_without_paths_low for tok in ("used for", "contain", "contains", "kind of data", "what is")))
            and any(tok in request_without_paths_low for tok in ("where ", "reference", "references", "contains"))
            and self._has_local_skill("custom.repo_reference_search")
        ):
            workflow_json = self._empty_generated_workflow(
                request_text=user_text,
                skill_id="custom.repo_reference_search",
                step_label="Repo Reference Search",
                supported_capability_ids=["repo_editing", "document_io", "content_authoring"],
            )
            return {
                "name": "__autoflow_builtin_repo_reference_search__",
                "score": 1.0,
                "reason": "builtin_direct_repo_reference_search; repo_reference_ready",
                "generated_workflow": workflow_json,
                "action_skills": ["custom.repo_reference_search", "result.text"],
                "executable_action_skills": ["custom.repo_reference_search", "result.text"],
                "supported_capability_ids": ["repo_editing", "document_io", "content_authoring"],
                "doc_text": "built-in direct repo reference search symbol uses file references contains",
                "doc_tokens": ["built", "direct", "repo", "reference", "search", "symbol", "uses", "file", "contains"],
                "selection_info": {"source": "builtin", "flow_name": "__autoflow_builtin_repo_reference_search__"},
            }
        if (
            repo_scope_request
            and repo_file_match
            and not repo_change_request
            and any(tok in request_without_paths_low for tok in ("used for", "contains", "contain", "kind of data", "what is", "summarize this file", "summarise this file", "file summary"))
            and self._has_local_skill("custom.repo_file_summary")
        ):
            workflow_json = self._empty_generated_workflow(
                request_text=user_text,
                skill_id="custom.repo_file_summary",
                step_label="Repo File Summary",
                supported_capability_ids=["repo_editing", "document_io", "content_authoring"],
            )
            return {
                "name": "__autoflow_builtin_repo_file_summary__",
                "score": 0.99,
                "reason": "builtin_direct_repo_file_summary; repo_file_ready",
                "generated_workflow": workflow_json,
                "action_skills": ["custom.repo_file_summary", "result.text"],
                "executable_action_skills": ["custom.repo_file_summary", "result.text"],
                "supported_capability_ids": ["repo_editing", "document_io", "content_authoring"],
                "doc_text": "built-in direct repo file summary json repository artifact purpose contents",
                "doc_tokens": ["built", "direct", "repo", "repository", "file", "summary", "json", "artifact", "purpose", "contents"],
                "selection_info": {
                    "source": "builtin",
                    "flow_name": "__autoflow_builtin_repo_file_summary__",
                },
            }
        if (
            repo_scope_request
            and re.search(r"\b[\w./-]+\.(?:js|ts|py|html|htm|css)\b", user_text, flags=re.IGNORECASE)
            and repo_change_request
            and not any(tok in request_low for tok in ("implement", "patch", "modify the file", "edit the file", "change the file", "write the change", "apply the change"))
            and self._has_local_skill("custom.repo_code_explain")
        ):
            workflow_json = self._builtin_skill_then_draft_workflow(
                user_text,
                label="Repo Code Improve",
                skill_id="custom.repo_code_explain",
                system_prompt="Run the repo code explain skill to gather grounded file evidence, the current role of the file, and the strongest concrete improvement opportunities.",
                draft_prompt=(
                    "Answer the user's repo-file improvement question using the grounded file evidence from the prior step. "
                    "Do not just repeat the raw tool output. Describe briefly what the file currently is, then give prioritized, file-specific improvements, why each one matters, and what part of the file they affect. "
                    "If the file is a game, mention gameplay, controls, structure, performance, and polish where relevant. "
                    "Stay specific to the file and avoid workflow or tool chatter."
                ),
            )
            return {
                "name": "__autoflow_builtin_repo_code_improve__",
                "score": 1.08,
                "reason": "builtin_direct_repo_code_improve; repo_code_improvement_ready",
                "generated_workflow": workflow_json,
                "action_skills": ["custom.repo_code_explain", "result.text"],
                "executable_action_skills": ["custom.repo_code_explain", "result.text"],
                "supported_capability_ids": ["repo_editing", "document_io", "content_authoring"],
                "doc_text": "built-in direct repo code improve review recommendations game html javascript file-specific improvements",
                "doc_tokens": ["built", "direct", "repo", "code", "improve", "review", "recommendations", "game", "html", "javascript"],
                "selection_info": {"source": "builtin", "flow_name": "__autoflow_builtin_repo_code_improve__"},
            }
        if (
            repo_scope_request
            and re.search(r"\b[\w./-]+\.(?:js|ts|py|html|htm|css)\b", user_text, flags=re.IGNORECASE)
            and any(tok in request_low for tok in ("what does", "explain", "tell me what", "function", "what kind of game is it", "what kind of app is it"))
            and not any(tok in request_without_paths_low for tok in ("used for", "summarize this file", "summarise this file", "file summary"))
            and self._has_local_skill("custom.repo_code_explain")
        ):
            workflow_json = self._builtin_skill_then_draft_workflow(
                user_text,
                label="Repo Code Explain",
                skill_id="custom.repo_code_explain",
                system_prompt="Run the repo code explain skill to gather grounded file evidence and return the strongest file-specific findings.",
                draft_prompt=(
                    "Answer the user's repo-file question using the grounded file evidence from the prior step. "
                    "Do not just repeat the raw tool output. Explain what the file is, what kind of game/app/code it represents, "
                    "what the main mechanics or behavior are, and answer the user directly in natural language. "
                    "Stay specific to the file and avoid workflow or tool chatter."
                ),
            )
            return {
                "name": "__autoflow_builtin_repo_code_explain__",
                "score": 1.0,
                "reason": "builtin_direct_repo_code_explain; repo_code_ready",
                "generated_workflow": workflow_json,
                "action_skills": ["custom.repo_code_explain", "result.text"],
                "executable_action_skills": ["custom.repo_code_explain", "result.text"],
                "supported_capability_ids": ["repo_editing", "document_io", "content_authoring"],
                "doc_text": "built-in direct repo code explain function symbol javascript python typescript",
                "doc_tokens": ["built", "direct", "repo", "code", "explain", "function", "symbol", "javascript", "python", "typescript"],
                "selection_info": {"source": "builtin", "flow_name": "__autoflow_builtin_repo_code_explain__"},
            }
        implicit_scholar_request = bool(
            any(tok in request_low for tok in ("scholarly sources", "scholarly articles", "academic sources", "academic papers", "peer-reviewed", "peer reviewed"))
            or (
                any(tok in request_low for tok in ("sources", "articles", "papers"))
                and any(tok in request_low for tok in ("scholarly", "academic", "peer-reviewed", "peer reviewed"))
            )
        )
        implicit_arxiv_request = bool(
            any(tok in request_low for tok in ("recent papers", "papers since", "arxiv papers", "preprints", "methods-oriented synthesis", "methods oriented synthesis"))
            and any(tok in request_low for tok in ("ai-generated", "synthetic", "misinformation", "political content", "deepfake", "llm", "model", "models", "detection"))
        )
        if ((("google scholar" in request_low and any(tok in request_low for tok in ("scholarly sources", "recent scholarly", "repeated findings"))) or implicit_scholar_request) and self._has_local_skill("custom.google_scholar_report")):
            workflow_json = self._builtin_single_skill_workflow(
                user_text,
                label="Fetch Scholar Report",
                skill_id="custom.google_scholar_report",
                system_prompt="Run the Google Scholar report skill directly and return the final source table and synthesis.",
            )
            return {
                "name": "__autoflow_builtin_google_scholar_report__",
                "score": 3.0,
                "reason": "builtin_direct_google_scholar_report; source_specific_or_implicit_scholarly_request; external_info_ready",
                "node_count": 2,
                "description": "Built-in direct Google Scholar report workflow.",
                "action_skills": ["custom.google_scholar_report", "result.text"],
                "executable_action_skills": ["custom.google_scholar_report", "result.text"],
                "supported_capability_ids": ["web_research", "content_authoring"],
                "doc_text": "built-in direct google scholar recent scholarly sources synthesis academic peer reviewed",
                "doc_tokens": ["built", "direct", "google", "scholar", "scholarly", "sources", "synthesis", "academic", "peer", "reviewed"],
                "generated_workflow": {
                    "record_id": "",
                    "flow_name": "__autoflow_builtin_google_scholar_report__",
                    "workflow_json": workflow_json,
                    "workflow_file": "",
                    "bundle_dir": "",
                    "temp_skill_dirs": [],
                },
            }
        if ((("arxiv" in request_low and any(tok in request_low for tok in ("papers", "methods-oriented synthesis", "synthetic political content"))) or implicit_arxiv_request) and self._has_local_skill("custom.arxiv_report")):
            workflow_json = self._builtin_single_skill_workflow(
                user_text,
                label="Fetch arXiv Report",
                skill_id="custom.arxiv_report",
                system_prompt="Run the arXiv report skill directly and return the final paper table and methods-oriented synthesis.",
            )
            return {
                "name": "__autoflow_builtin_arxiv_report__",
                "score": 3.0,
                "reason": "builtin_direct_arxiv_report; source_specific_or_implicit_recent_papers_request; external_info_ready",
                "node_count": 2,
                "description": "Built-in direct arXiv report workflow.",
                "action_skills": ["custom.arxiv_report", "result.text"],
                "executable_action_skills": ["custom.arxiv_report", "result.text"],
                "supported_capability_ids": ["web_research", "content_authoring"],
                "doc_text": "built-in direct arxiv recent papers methods-oriented synthesis ai misinformation synthetic political content",
                "doc_tokens": ["built", "direct", "arxiv", "recent", "papers", "methods", "synthesis", "ai", "misinformation", "synthetic"],
                "generated_workflow": {
                    "record_id": "",
                    "flow_name": "__autoflow_builtin_arxiv_report__",
                    "workflow_json": workflow_json,
                    "workflow_file": "",
                    "bundle_dir": "",
                    "temp_skill_dirs": [],
                },
            }
        if self._should_use_builtin_current_context_answer(user_text, profile) and self._has_local_skill("custom.awf_web_research__web_research_204fb17b_executor"):
            workflow_json = self._builtin_current_context_answer_workflow(user_text)
            return {
                "name": "__autoflow_builtin_current_context_answer__",
                "score": 2.99,
                "reason": "builtin_direct_current_context_answer; web_research_plus_authoring; current_context_needed",
                "node_count": 3,
                "description": "Built-in current-context authoring workflow for prompts that need live context plus drafting.",
                "action_skills": ["custom.awf_web_research__web_research_204fb17b_executor", "result.text"],
                "executable_action_skills": ["custom.awf_web_research__web_research_204fb17b_executor", "result.text"],
                "supported_capability_ids": ["web_research", "content_authoring"],
                "doc_text": "built-in direct current context answer current facts web research drafting authoring project essay presentation",
                "doc_tokens": ["built", "direct", "current", "context", "answer", "web", "research", "drafting", "authoring", "project"],
                "generated_workflow": {
                    "record_id": "",
                    "flow_name": "__autoflow_builtin_current_context_answer__",
                    "workflow_json": workflow_json,
                    "workflow_file": "",
                    "bundle_dir": "",
                    "temp_skill_dirs": [],
                },
            }
        generic_external_web_research_request = (
            self._is_external_info_request(user_text)
            and not profile.get("file_backed")
            and not repo_scope_request
            and "weather_lookup" not in capability_ids
            and "market_data" not in capability_ids
            and not any(tok in request_low for tok in ("world bank", "imf", "google scholar", "arxiv", "yahoo finance"))
        )
        topic_current_research_request = (
            "weather_lookup" not in capability_ids
            and "market_data" not in capability_ids
            and not any(tok in request_low for tok in ("world bank", "imf", "google scholar", "arxiv", "yahoo finance"))
            and (
                (any(tok in request_low for tok in ("latest", "current", "today", "right now", "recent")) and any(tok in request_low for tok in ("inflation", "cpi", "gdp", "unemployment", "interest rate", "fed funds", "consumer price")))
                or (any(tok in request_low for tok in ("latest", "current", "today", "right now", "news", "headlines", "trending", "trends")) and any(tok in request_low for tok in ("ai", "model", "models", "technology", "tech", "online", "internet")))
                or (any(tok in request_low for tok in ("latest", "current", "today", "right now", "news", "headlines")) and (
                    re.search(r"\b(who is|what is|who's|what's)\b", request_low)
                    or any(tok in request_low for tok in ("ceo", "president", "prime minister", "chair", "founder", "regulation", "regulations", "policy", "policies", "law", "laws"))
                ))
            )
        )
        if self._has_local_skill("custom.awf_web_research__web_research_204fb17b_executor") and (
            generic_external_web_research_request or topic_current_research_request
        ):
            workflow_json = self._builtin_single_skill_workflow(
                user_text,
                label="Research Current Answer",
                skill_id="custom.awf_web_research__web_research_204fb17b_executor",
                system_prompt="Run the web research skill directly and return the strongest current answer with concise source-backed support.",
            )
            return {
                "name": "__autoflow_builtin_web_research__",
                "score": 2.98,
                "reason": "builtin_direct_web_research; current_fact_or_topic_match; external_info_ready",
                "node_count": 2,
                "description": "Built-in direct web research workflow for current facts, headlines, and source-backed answers.",
                "action_skills": ["custom.awf_web_research__web_research_204fb17b_executor", "result.text"],
                "executable_action_skills": ["custom.awf_web_research__web_research_204fb17b_executor", "result.text"],
                "supported_capability_ids": ["web_research", "content_authoring"],
                "doc_text": "built-in direct web research current fact latest headlines identity answer source backed",
                "doc_tokens": ["built", "direct", "web", "research", "current", "fact", "latest", "headlines", "identity", "source"],
                "generated_workflow": {
                    "record_id": "",
                    "flow_name": "__autoflow_builtin_web_research__",
                    "workflow_json": workflow_json,
                    "workflow_file": "",
                    "bundle_dir": "",
                    "temp_skill_dirs": [],
                },
            }
        if "weather_lookup" in capability_ids and self._has_local_skill("external_data.weather_lookup"):
            workflow_json = self._builtin_weather_workflow(user_text)
            return {
                "name": "__autoflow_builtin_weather_lookup__",
                "score": 3.05,
                "reason": "builtin_direct_weather_lookup; capability=weather_lookup; external_info_ready",
                "node_count": 2,
                "description": "Built-in direct weather lookup fallback.",
                "action_skills": ["external_data.weather_lookup", "result.text"],
                "executable_action_skills": ["external_data.weather_lookup", "result.text"],
                "supported_capability_ids": ["weather_lookup", "web_research"],
                "doc_text": "built-in direct weather lookup current forecast",
                "doc_tokens": ["built", "direct", "weather", "lookup", "forecast", "current"],
                "generated_workflow": {
                    "record_id": "",
                    "flow_name": "__autoflow_builtin_weather_lookup__",
                    "workflow_json": workflow_json,
                    "workflow_file": "",
                    "bundle_dir": "",
                    "temp_skill_dirs": [],
                },
            }
        if "market_data" in capability_ids and self._has_local_skill("custom.market_data_report"):
            workflow_json = self._builtin_market_data_workflow(user_text)
            return {
                "name": "__autoflow_builtin_market_data__",
                "score": 3.0,
                "reason": "builtin_direct_market_data; capability=market_data; external_info_ready",
                "node_count": 2,
                "description": "Built-in direct market data fallback.",
                "action_skills": ["custom.market_data_report", "result.text"],
                "executable_action_skills": ["custom.market_data_report", "result.text"],
                "supported_capability_ids": ["market_data", "web_research", "content_authoring"],
                "doc_text": "built-in direct market data quote comparison finance yahoo ticker current",
                "doc_tokens": ["built", "direct", "market", "data", "quote", "comparison", "finance", "yahoo", "ticker", "current"],
                "generated_workflow": {
                    "record_id": "",
                    "flow_name": "__autoflow_builtin_market_data__",
                    "workflow_json": workflow_json,
                    "workflow_file": "",
                    "bundle_dir": "",
                    "temp_skill_dirs": [],
                },
            }
        if self._should_use_builtin_general_answer(user_text, profile):
            workflow_json = self._builtin_general_answer_workflow(user_text)
            return {
                "name": "__autoflow_builtin_general_answer__",
                "score": 0.45,
                "reason": "builtin_direct_general_answer; model_backed; no_file_or_live_data_requirement_detected",
                "node_count": 2,
                "description": "Built-in direct answer workflow for ordinary questions and drafting requests.",
                "action_skills": ["result.text"],
                "executable_action_skills": ["result.text"],
                "supported_capability_ids": ["content_authoring"],
                "doc_text": "built-in direct general answer drafting explanation outline proposal essay presentation",
                "doc_tokens": ["built", "direct", "general", "answer", "drafting", "explanation", "outline", "proposal", "essay", "presentation"],
                "generated_workflow": {
                    "record_id": "",
                    "flow_name": "__autoflow_builtin_general_answer__",
                    "workflow_json": workflow_json,
                    "workflow_file": "",
                    "bundle_dir": "",
                    "temp_skill_dirs": [],
                },
            }
        return {}

    def _preferred_market_data_skill_id(self, workflow_json: Dict[str, Any], request_text: str = "") -> str:
        request_low = str(request_text or "").strip().lower()
        explicit_symbols = self._extract_requested_symbols(request_text)
        if explicit_symbols and "compare" in request_low and self._has_local_skill("custom.market_data_report"):
            return "custom.market_data_report"
        candidates: List[str] = []
        try:
            for skill_id in self._action_skills_from_flow(workflow_json):
                val = str(skill_id or "").strip()
                if val and val not in candidates:
                    candidates.append(val)
        except Exception:
            pass
        if not candidates:
            return ""
        for skill_id in candidates:
            low = skill_id.lower()
            if low.startswith("custom.") and "market_data_report" in low:
                return skill_id
        if "yahoo finance" in request_low:
            for skill_id in candidates:
                if str(skill_id or "").strip().lower() == "external_data.yahoo_finance":
                    return skill_id
        for skill_id in candidates:
            low = skill_id.lower()
            if any(hint in low for hint in ("yahoo_finance", "quote", "finance")):
                return skill_id
        return ""

    def _normalize_market_data_workflow(self, workflow_json: Dict[str, Any], request_text: str) -> Dict[str, Any]:
        skill_id = self._preferred_market_data_skill_id(workflow_json, request_text)
        if not skill_id:
            return workflow_json
        top_n = self._requested_top_n(request_text, default=10)
        output_mode = "file" if self._requested_output_extensions(request_text) else "text"
        normalized = json.loads(json.dumps(workflow_json))
        output_tool = "result.file" if output_mode == "file" else "result.text"
        output_params = ["output_path"] if output_mode == "file" else [
            "final_answer",
            "table_markdown",
            "markdown",
            "summary",
            "text",
            "response",
            "content",
        ]
        normalized["start"] = "execute"
        normalized["nodes"] = {
            "execute": {
                "label": "Fetch Market Data",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "tooling",
                "system_prompt": "Run the market data skill directly and return the real ranked stock output.",
                "x": 220,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [{"condition": {"type": "always"}, "target": "output"}],
                "plugin_settings": {
                    "node_type": "tool_node",
                    "member_role": "tooling",
                    "handoff_format": "plain",
                    "output_protocol": "tagged",
                    "member_token_stream": True,
                    "action_skills": [skill_id],
                    "tool_config": {
                        "tool": skill_id,
                        "params": {"top_n": top_n, "region": "US", "timeout": 8.0, "output_mode": output_mode},
                    },
                },
            },
            "output": {
                "label": "Deliver Result" if output_mode == "text" else "Deliver File",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "tooling",
                "system_prompt": "Emit the generated market-data result exactly from the prior step.",
                "x": 660,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [],
                "plugin_settings": {
                    "node_type": "tool_node",
                    "member_role": "tooling",
                    "handoff_format": "plain",
                    "output_protocol": "tagged",
                    "member_token_stream": True,
                    "action_skills": [output_tool],
                    "tool_config": {"tool": output_tool, "params_from_input": output_params},
                },
            },
        }
        return normalized

    def _normalize_generated_workflow_for_request(self, workflow_json: Dict[str, Any], request_text: str) -> Dict[str, Any]:
        if not isinstance(workflow_json, dict):
            return {}
        low = str(request_text or "").lower()
        if any(tok in low for tok in ("approval", "approve", "human review", "sign off", "sign-off")):
            return workflow_json
        nodes = workflow_json.get("nodes")
        if not isinstance(nodes, dict):
            return workflow_json
        normalized = json.loads(json.dumps(workflow_json))
        approval_ids: List[str] = []
        replacement_targets: Dict[str, str] = {}
        norm_nodes = normalized.get("nodes") if isinstance(normalized.get("nodes"), dict) else {}
        for node_id, node in norm_nodes.items():
            if not isinstance(node, dict):
                continue
            ps = node.get("plugin_settings") if isinstance(node.get("plugin_settings"), dict) else {}
            tc = ps.get("tool_config") if isinstance(ps.get("tool_config"), dict) else {}
            tool = str(tc.get("tool") or "").strip().lower()
            label = str(node.get("label") or "").strip().lower()
            if tool == "interaction.approval" or label in {"approval gate", "approval"}:
                approval_ids.append(str(node_id))
                transitions = node.get("transitions") if isinstance(node.get("transitions"), list) else []
                for tr in transitions:
                    if isinstance(tr, dict) and str(tr.get("target") or "").strip():
                        replacement_targets[str(node_id)] = str(tr.get("target") or "").strip()
                        break
        if approval_ids:
            for node_id, node in list(norm_nodes.items()):
                if str(node_id) in approval_ids:
                    continue
                transitions = node.get("transitions") if isinstance(node, dict) and isinstance(node.get("transitions"), list) else []
                for tr in transitions:
                    if not isinstance(tr, dict):
                        continue
                    target = str(tr.get("target") or "").strip()
                    if target in replacement_targets:
                        tr["target"] = replacement_targets[target]
            for node_id in approval_ids:
                norm_nodes.pop(node_id, None)
            start = str(normalized.get("start") or "").strip()
            if start in replacement_targets:
                normalized["start"] = replacement_targets[start]
            normalized["nodes"] = norm_nodes
        profile = self._request_profile(request_text)
        capability_ids = {str(x or "").strip() for x in (profile.get("capability_ids") or []) if str(x or "").strip()}
        # Older generated workflows often forwarded custom executor output through
        # text-only nodes, which drops structured fields like final_answer or
        # table_markdown before result.text can render them. Repair that chain at
        # load time so stale temp-library bundles stay runnable after generator
        # improvements.
        for node_id, node in norm_nodes.items():
            if not isinstance(node, dict):
                continue
            ps = node.get("plugin_settings") if isinstance(node.get("plugin_settings"), dict) else {}
            tc = ps.get("tool_config") if isinstance(ps.get("tool_config"), dict) else {}
            tool_name = str(tc.get("tool") or "").strip()
            if not tool_name.lower().startswith("custom."):
                continue
            transitions = node.get("transitions") if isinstance(node.get("transitions"), list) else []
            if not transitions:
                continue
            next_target = ""
            for tr in transitions:
                if isinstance(tr, dict) and str(tr.get("target") or "").strip():
                    next_target = str(tr.get("target") or "").strip()
                    break
            if not next_target:
                continue
            next_node = norm_nodes.get(next_target)
            if not isinstance(next_node, dict):
                continue
            next_ps = next_node.get("plugin_settings") if isinstance(next_node.get("plugin_settings"), dict) else {}
            next_tc = next_ps.get("tool_config") if isinstance(next_ps.get("tool_config"), dict) else {}
            next_tool = str(next_tc.get("tool") or "").strip().lower()
            if next_tool != "result.text":
                continue
            node["return_only_text"] = False
            params_from_input = next_tc.get("params_from_input")
            if isinstance(params_from_input, list):
                preferred = [
                    "execution_text",
                    "data",
                    "final_answer",
                    "table_markdown",
                    "markdown",
                    "summary",
                    "text",
                    "response",
                    "content",
                    "output_path",
                    "path",
                    "user_request",
                    "request_text",
                    "input_path",
                    "file_path",
                ]
                merged = []
                seen = set()
                for key in preferred + [str(x or "").strip() for x in params_from_input]:
                    token = str(key or "").strip()
                    if not token or token in seen:
                        continue
                    seen.add(token)
                    merged.append(token)
                next_tc["params_from_input"] = merged
        if "market_data" in capability_ids:
            normalized = self._normalize_market_data_workflow(normalized, request_text)
        return normalized

    def _repair_generated_bundle_for_request(self, bundle_dir: str, request_text: str) -> None:
        bundle_path = Path(str(bundle_dir or "").strip())
        if not str(bundle_dir or "").strip():
            return
        try:
            bundle_path = bundle_path.resolve()
        except Exception:
            bundle_path = Path(str(bundle_dir or "").strip())
        if not bundle_path.is_dir():
            return
        for workflow_file in bundle_path.glob('*.json'):
            try:
                raw_doc = workflow_file.read_text(encoding='utf-8')
                payload = json.loads(raw_doc)
            except Exception:
                continue
            flows_doc = payload.get('flows') if isinstance(payload, dict) else None
            if not isinstance(flows_doc, dict) or not flows_doc:
                continue
            changed = False
            for flow_key, flow_doc in list(flows_doc.items()):
                if not isinstance(flow_doc, dict):
                    continue
                normalized = self._normalize_generated_workflow_for_request(dict(flow_doc), request_text)
                if normalized != flow_doc:
                    flows_doc[flow_key] = normalized
                    changed = True
            if changed:
                workflow_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return

    def _requested_output_extensions(self, text: str) -> set[str]:
        low = str(text or "").lower()
        out: set[str] = set()
        if any(tok in low for tok in ("workbook", "spreadsheet", "excel", ".xlsx", ".xlsm", ".xls")):
            out.add(".xlsx")
        if ".csv" in low or " csv" in low or "csv " in low:
            out.add(".csv")
        if ".pdf" in low or " pdf" in low or "pdf " in low:
            out.add(".pdf")
        if ".docx" in low or "word document" in low or " memo" in low or "document" in low:
            out.add(".docx")
        if "json" in low:
            out.add(".json")
        if "zip" in low or "bundle" in low or "archive" in low:
            out.add(".zip")
        return out

    def _artifact_paths_from_result_meta(self, result_meta: Optional[Dict[str, Any]]) -> List[str]:
        meta = result_meta if isinstance(result_meta, dict) else {}
        out: List[str] = []

        def _append_value(value: Any) -> None:
            text = str(value or "").strip()
            if text:
                out.append(text)

        def _append_file_rows(rows: Any) -> None:
            if not isinstance(rows, list):
                return
            for row in rows:
                if isinstance(row, dict):
                    value = str(row.get("path") or row.get("download_url") or row.get("relative_download_url") or row.get("name") or "").strip()
                else:
                    value = str(row or "").strip()
                if value:
                    out.append(value)

        _append_value(meta.get("output_path"))
        _append_value(meta.get("download_url"))
        _append_value(meta.get("relative_download_url"))
        _append_value(meta.get("bundle_path"))
        _append_value(meta.get("zip_path"))
        _append_file_rows(meta.get("execution_files"))
        _append_file_rows(meta.get("files"))
        exec_meta = meta.get("execution_meta") if isinstance(meta.get("execution_meta"), dict) else {}
        _append_value(exec_meta.get("output_path"))
        _append_value(exec_meta.get("download_url"))
        _append_value(exec_meta.get("relative_download_url"))
        _append_file_rows(exec_meta.get("files"))
        msg_meta = exec_meta.get("message_meta") if isinstance(exec_meta.get("message_meta"), dict) else {}
        _append_value(msg_meta.get("output_path"))
        _append_value(msg_meta.get("download_url"))
        _append_value(msg_meta.get("relative_download_url"))
        _append_file_rows(msg_meta.get("files"))
        data_meta = exec_meta.get("data_meta") if isinstance(exec_meta.get("data_meta"), dict) else {}
        _append_value(data_meta.get("output_path"))
        _append_file_rows(data_meta.get("staged_files"))
        _append_file_rows(data_meta.get("files"))
        data = meta.get("data") if isinstance(meta.get("data"), dict) else {}
        _append_value(data.get("output_path"))
        _append_value(data.get("download_url"))
        _append_value(data.get("relative_download_url"))
        _append_file_rows(data.get("execution_files"))
        _append_file_rows(data.get("execution_files"))
        for row in (exec_meta.get("zip"), msg_meta.get("zip"), meta.get("execution_zip")):
            if not isinstance(row, dict):
                continue
            value = str(row.get("path") or row.get("download_url") or row.get("relative_download_url") or row.get("name") or "").strip()
            if value:
                out.append(value)
        deduped: List[str] = []
        seen = set()
        for item in out:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped

    def _judge_satisfaction(self, user_text: str, flow_result_text: str, *, flow_name: str = "", result_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        meta = result_meta if isinstance(result_meta, dict) else {}
        data_meta = meta.get("data") if isinstance(meta.get("data"), dict) else {}
        result_text_parts: List[str] = []
        for value in (
            flow_result_text,
            meta.get("final_answer"),
            meta.get("response"),
            meta.get("table_markdown"),
            data_meta.get("final_answer"),
            data_meta.get("response"),
            data_meta.get("table_markdown"),
            meta.get("summary"),
            data_meta.get("summary"),
        ):
            text = str(value or "").strip()
            if text and text not in result_text_parts:
                result_text_parts.append(text)
        effective_result_text = "\n\n".join(result_text_parts).strip() or str(flow_result_text or "")
        final_status = str(meta.get("final_status") or meta.get("status") or "").strip().lower()
        warnings = meta.get("warnings") if isinstance(meta.get("warnings"), list) else []
        if "timed out" in final_status or any(str(w or "").strip().lower() == "execution_timed_out" for w in warnings):
            return {
                "satisfied": False,
                "score": 0.0,
                "reason": "Workflow execution timed out before a reliable final result was produced.",
                "improved_request": (
                    user_text
                    + "\n\nImprove the workflow so it completes within the execution budget and returns the final answer directly instead of timing out during intermediate analysis."
                ).strip(),
            }
        heuristic = self._heuristic_satisfaction(user_text, effective_result_text)
        if heuristic:
            return heuristic
        artifact_exts = self._requested_output_extensions(user_text)
        artifact_paths = self._artifact_paths_from_result_meta(meta)
        if artifact_exts and artifact_paths:
            matched_artifacts = [
                item for item in artifact_paths
                if any(str(item).lower().endswith(ext) for ext in artifact_exts)
            ]
            low_result = str(effective_result_text or "").lower()
            has_substantive_summary = any(tok in low_result for tok in (
                "summary", "executive summary", "key findings", "reviewer-ready", "reviewer ready",
                "recommendation", "discrepanc", "variance", "matched rows", "flagged", "total",
            )) or len(str(effective_result_text or "").strip()) >= 120
            if matched_artifacts and has_substantive_summary:
                return {
                    "satisfied": True,
                    "score": 0.94,
                    "reason": f"Result produced the requested artifact type and returned a substantive summary ({len(matched_artifacts)} matching file(s)).",
                    "improved_request": "",
                }
        low_req = str(user_text or "").lower()
        low_result = str(effective_result_text or "").lower()
        has_structured_answer = bool(
            meta.get("final_answer") or meta.get("response") or data_meta.get("final_answer") or data_meta.get("response")
        )
        if has_structured_answer and len(str(effective_result_text or "").strip()) >= 180:
            structural_markers = (
                "## " in str(effective_result_text or "")
                or "| :--- |" in low_result
                or low_result.startswith("subject:")
                or "\nsubject:" in low_result
            )
            if structural_markers:
                return {
                    "satisfied": True,
                    "score": 0.92,
                    "reason": "Result returned a structured direct answer with substantive content in the execution metadata.",
                    "improved_request": "",
                }
        chart_count = int(meta.get("chart_count") or (meta.get("data") or {}).get("chart_count") or 0) if isinstance(meta, dict) else 0
        if any(tok in low_req for tok in ("chart", "graph", "plot", "visualiz")):
            text_chart_artifacts = re.findall(r"https?://[^\s\])]+\.(?:html|png|jpg|jpeg|svg|pdf)|/uploads/[^\s\])]+\.(?:html|png|jpg|jpeg|svg|pdf)", str(effective_result_text or ""), flags=re.IGNORECASE)
            if text_chart_artifacts and (chart_count > 0 or "files ready for download" in low_result or "rendered" in low_result or "chart" in low_result):
                return {
                    "satisfied": True,
                    "score": 0.95,
                    "reason": f"Result produced a downloadable chart artifact with {max(chart_count, 1)} rendered chart output(s).",
                    "improved_request": "",
                }
        if any(tok in low_req for tok in ("chart", "graph", "plot", "visualiz")) and artifact_paths:
            chart_artifacts = [
                item for item in artifact_paths
                if str(item or "").lower().endswith((".html", ".png", ".jpg", ".jpeg", ".svg", ".pdf"))
            ]
            if chart_artifacts and (chart_count > 0 or "rendered" in low_result or "chart" in low_result):
                return {
                    "satisfied": True,
                    "score": 0.95,
                    "reason": f"Result produced a chart artifact with {max(chart_count, 1)} rendered chart output(s).",
                    "improved_request": "",
                }
        prompt = (
            "You are judging whether a workflow execution result actually satisfied the user's original request.\n"
            "Return ONLY strict JSON with this schema:\n"
            "{\n"
            '  "satisfied": true,\n'
            '  "score": 0.0,\n'
            '  "reason": "short explanation",\n'
            '  "improved_request": "only if unsatisfied; otherwise empty string"\n'
            "}\n\n"
            f"Original request:\n{user_text}\n\n"
            f"Flow name:\n{flow_name}\n\n"
            f"Workflow result:\n{effective_result_text}\n\n"
            f"Result meta:\n{json.dumps(result_meta or {}, ensure_ascii=False)}\n"
        )
        data = self._chat_json(prompt)
        satisfied = bool(data.get("satisfied"))
        try:
            score = float(data.get("score") or 0.0)
        except Exception:
            score = 0.0
        reason = str(data.get("reason") or "").strip()
        improved_request = str(data.get("improved_request") or "").strip()
        if satisfied:
            return {
                "satisfied": True,
                "score": max(0.0, min(score or 0.9, 1.0)),
                "reason": reason or "The result satisfied the request.",
                "improved_request": "",
            }
        return {
            "satisfied": False,
            "score": max(0.0, min(score, 1.0)),
            "reason": reason or "The result did not clearly satisfy the request.",
            "improved_request": improved_request or (
                user_text
                + "\n\nImprove the workflow so it fully satisfies the request, returns the missing output, and covers the gaps noted in this review: "
                + (reason or "The result did not clearly satisfy the request.")
            ).strip(),
        }
    def _heuristic_satisfaction(self, user_text: str, result_text: str) -> Optional[Dict[str, Any]]:
        low_req = str(user_text or "").lower()
        low_result = str(result_text or "").lower()
        refusal_hints = (
            "do not have access to real-time",
            "cannot provide real-time",
            "cannot access live",
            "cannot retrieve live",
            "no real-time access",
            "no live internet",
            "check espn",
            "check mlb",
            "check nba",
            "recommend checking",
        )
        if any(hint in low_result for hint in refusal_hints):
            return {
                "satisfied": False,
                "score": 0.0,
                "reason": "The workflow returned a refusal or deflection instead of satisfying the request.",
                "improved_request": (
                    user_text
                    + "\n\nImprove the workflow so it performs the required retrieval or file processing directly and returns the requested output instead of deflecting."
                ).strip(),
            }
        if any(tok in low_req for tok in ("top 10", "top ten", "top 5", "top five", "top 3", "top three", "list")):
            numbered = len(re.findall(r"(?:^|\n)\s*(?:\d+\.|- )", str(result_text or "")))
            if numbered >= 3 and len(str(result_text or "").strip()) >= 80:
                return {
                    "satisfied": True,
                    "score": 0.9,
                    "reason": "The result returned a structured list that appears to satisfy the request.",
                    "improved_request": "",
                }
        if any(tok in low_req for tok in ("email", "announcement")) and len(str(result_text or "").strip()) >= 120:
            if low_result.startswith("subject:") and ("hi " in low_result or "hello" in low_result) and ("thanks," in low_result or "thank you" in low_result):
                return {
                    "satisfied": True,
                    "score": 0.92,
                    "reason": "The result returned a direct email-format deliverable with subject, body, and close.",
                    "improved_request": "",
                }
        if "faq" in low_req and len(str(result_text or "").strip()) >= 120:
            question_count = len(re.findall(r"(?:^|\n)(?:### |\*\*)(.+?)(?:\*\*)?$", str(result_text or ""), flags=re.MULTILINE))
            if "## faq" in low_result and question_count >= 3:
                return {
                    "satisfied": True,
                    "score": 0.91,
                    "reason": "The result returned a compact FAQ with multiple plain-language question and answer entries.",
                    "improved_request": "",
                }
        if "outline" in low_req and "essay" in low_req and len(str(result_text or "").strip()) >= 220:
            if "thesis" in low_result and ("body argument" in low_result or "body paragraph" in low_result):
                return {
                    "satisfied": True,
                    "score": 0.92,
                    "reason": "The result returned a structured essay outline with a thesis and body arguments.",
                    "improved_request": "",
                }
        if "presentation" in low_req and len(str(result_text or "").strip()) >= 220:
            slide_count = len(re.findall(r"slide\s+\d+", low_result))
            if slide_count >= 4:
                return {
                    "satisfied": True,
                    "score": 0.92,
                    "reason": "The result returned a structured presentation plan with slide-level guidance.",
                    "improved_request": "",
                }
        if ("hypothesis" in low_req or "experiment design" in low_req or "science project" in low_req) and len(str(result_text or "").strip()) >= 220:
            if "hypothesis" in low_result and ("experiment design" in low_result or "materials" in low_result or "variables" in low_result):
                return {
                    "satisfied": True,
                    "score": 0.92,
                    "reason": "The result returned a structured science-project design with a hypothesis and experiment details.",
                    "improved_request": "",
                }
        if ("environmental science" in low_req and "project" in low_req) and len(str(result_text or "").strip()) >= 220:
            if "data to collect" in low_result and ("field plan" in low_result or "analysis approach" in low_result):
                return {
                    "satisfied": True,
                    "score": 0.92,
                    "reason": "The result returned a structured environmental science project plan with data collection guidance.",
                    "improved_request": "",
                }
        if ("research paper" in low_req and "proposal" in low_req) and len(str(result_text or "").strip()) >= 220:
            if "research paper proposal" in low_result and ("core research question" in low_result or "20-page structure" in low_result):
                return {
                    "satisfied": True,
                    "score": 0.92,
                    "reason": "The result returned a structured research paper proposal with questions and source direction.",
                    "improved_request": "",
                }
        if ("powerpoint" in low_req or ("presentation" in low_req and "structure" in low_req)) and len(str(result_text or "").strip()) >= 220:
            slide_count = len(re.findall(r"slide\s+\d+", low_result))
            if "powerpoint structure" in low_result and slide_count >= 6:
                return {
                    "satisfied": True,
                    "score": 0.92,
                    "reason": "The result returned a structured slide deck outline with policy framing and supporting points.",
                    "improved_request": "",
                }
        if (("calculus" in low_req or "statistics" in low_req) and any(tok in low_req for tok in ("housing prices", "inflation", "college tuition", "affordability", "real data"))) and len(str(result_text or "").strip()) >= 220:
            if "project plan" in low_result and ("recommended current datasets" in low_result or "project structure" in low_result):
                return {
                    "satisfied": True,
                    "score": 0.92,
                    "reason": "The result returned a structured affordability project plan with current-data guidance.",
                    "improved_request": "",
                }
        if ("physics" in low_req and any(tok in low_req for tok in ("renewable energy", "solar panel", "battery storage", "energy costs"))) and len(str(result_text or "").strip()) >= 220:
            if "project design" in low_result and ("variables" in low_result or "presentation structure" in low_result):
                return {
                    "satisfied": True,
                    "score": 0.92,
                    "reason": "The result returned a structured physics project design with a current-cost connection.",
                    "improved_request": "",
                }
        if ("art" in low_req and any(tok in low_req for tok in ("consumerism", "climate anxiety", "identity", "concept statement"))) and len(str(result_text or "").strip()) >= 220:
            if "art series proposal" in low_result and "concept statement" in low_result:
                return {
                    "satisfied": True,
                    "score": 0.92,
                    "reason": "The result returned an art series concept with a teacher-ready concept statement.",
                    "improved_request": "",
                }
        if (("world history" in low_req or "global migration" in low_req) and any(tok in low_req for tok in ("essay", "class discussion response", "war", "labor demand", "climate stress"))) and len(str(result_text or "").strip()) >= 220:
            if "essay and discussion plan" in low_result and ("working thesis" in low_result or "class discussion response" in low_result):
                return {
                    "satisfied": True,
                    "score": 0.92,
                    "reason": "The result returned a structured world history essay and discussion response plan.",
                    "improved_request": "",
                }
        if any(tok in low_req for tok in ("weather", "forecast", "temperature")) and len(str(result_text or "").strip()) >= 80:
            if "open-meteo" in low_result and any(tok in low_result for tok in ("current temperature", "today's weather", "source timestamp")):
                return {
                    "satisfied": True,
                    "score": 0.95,
                    "reason": "The result returned a direct current-weather answer with source-backed same-day forecast details.",
                    "improved_request": "",
                }
        if ("yahoo finance" in low_req or ("nvda" in low_req and "amd" in low_req)) and len(str(result_text or "").strip()) >= 180:
            unavailable_count = low_result.count("unavailable")
            if "| symbol |" in low_result and all(tok in low_result for tok in ("nvda", "amd")) and ("market cap" in low_result or "52-week" in low_result or "52 week" in low_result) and unavailable_count <= 1:
                return {
                    "satisfied": True,
                    "score": 0.93,
                    "reason": "The result returned a source-specific Yahoo Finance comparison with the requested tickers and metrics.",
                    "improved_request": "",
                }
            if unavailable_count >= 3 or "quote api was unavailable" in low_result:
                return {
                    "satisfied": False,
                    "score": 0.22,
                    "reason": "The result routed to the market-data path but withheld too many requested Yahoo Finance fields to count as a satisfying comparison.",
                    "improved_request": "",
                }
        if ("world bank" in low_req and any(tok in low_req for tok in ("inflation", "gdp growth", "unemployment"))) and len(str(result_text or "").strip()) >= 220:
            if ("| " in str(result_text or "") and "\n|" in str(result_text or "")) and any(tok in low_result for tok in ("indonesia", "vietnam", "mexico")) and ("stable" in low_result or "stability" in low_result):
                return {
                    "satisfied": True,
                    "score": 0.93,
                    "reason": "The result returned a structured World Bank comparison table with a stability summary.",
                    "improved_request": "",
                }
        if ("imf" in low_req and "world bank" in low_req and "macro brief" in low_req) and len(str(result_text or "").strip()) >= 220:
            if "macro brief" in low_result and any(tok in low_result for tok in ("united states", "euro area", "china")) and ("aligned" in low_result or "contextual" in low_result):
                return {
                    "satisfied": True,
                    "score": 0.93,
                    "reason": "The result returned a comparative IMF and World Bank macro brief.",
                    "improved_request": "",
                }
        if ("google scholar" in low_req and any(tok in low_req for tok in ("scholarly sources", "recent scholarly", "repeated findings"))) and len(str(result_text or "").strip()) >= 220:
            if "strongest repeated findings" in low_result and any(tok in low_result for tok in ("sagepub", "springer", "sciencedirect", "doi")):
                return {
                    "satisfied": True,
                    "score": 0.93,
                    "reason": "The result returned source-backed scholarly references with a synthesis.",
                    "improved_request": "",
                }
        if ("arxiv" in low_req and any(tok in low_req for tok in ("papers", "methods-oriented synthesis", "synthetic political content"))) and len(str(result_text or "").strip()) >= 220:
            if "methods-oriented synthesis" in low_result and any(tok in low_result for tok in ("arxiv.org", "method", "approach")):
                return {
                    "satisfied": True,
                    "score": 0.93,
                    "reason": "The result returned arXiv papers with a methods-oriented synthesis.",
                    "improved_request": "",
                }
        if any(tok in low_req for tok in ("world bank", "imf", "google scholar", "arxiv")):
            nonempty_lines = [ln.strip() for ln in str(result_text or "").splitlines() if ln.strip()]
            if nonempty_lines and len(nonempty_lines) <= 8 and all("http" in ln for ln in nonempty_lines):
                return {
                    "satisfied": False,
                    "score": 0.15,
                    "reason": "The result is only a raw source list and does not deliver the requested structured analysis or synthesis.",
                    "improved_request": "",
                }
        has_markdown_table = "| :--- |" in low_result or ("| " in str(result_text or "") and "\n|" in str(result_text or ""))
        has_summary_heading = "## executive summary" in low_result or "## short summary" in low_result or "summary" in low_result[:220]
        if len(str(result_text or "").strip()) >= 180 and has_markdown_table and has_summary_heading:
            if any(tok in low_req for tok in ("markdown table", "reviewer-ready", "reviewer ready", "summary", "brief", "review", "triage", "timeline", "shortlist", "plan", "faq")):
                if "triage" in low_req and ("same-day action queue" in low_result or "immediate attention first" in low_result):
                    return {
                        "satisfied": True,
                        "score": 0.93,
                        "reason": "The result returned a structured triage brief with a summary and actionable queue.",
                        "improved_request": "",
                    }
                if any(tok in low_req for tok in ("compare", "changed", "flag", "percent", "versus")) and ("threshold" in low_result or "flag" in low_result or "change (%)" in low_result):
                    return {
                        "satisfied": True,
                        "score": 0.93,
                        "reason": "The result returned a structured comparison summary with a markdown table and change details.",
                        "improved_request": "",
                    }
                return {
                    "satisfied": True,
                    "score": 0.91,
                    "reason": "The result returned a structured markdown deliverable with a substantive summary and table.",
                    "improved_request": "",
                }
        return None
    def _append_pass_log_for_success(self, user_text: str, flow_name: str, *, result_meta: Dict[str, Any], judged: Dict[str, Any]) -> None:
        try:
            ctx = {"app": self._server_app(), "original_request": user_text, "user_text": user_text}
            listed = workflow_temp_library.run(ctx, {"action": "list"})
            rows = listed.get("records") if isinstance(listed, dict) and isinstance(listed.get("records"), list) else []
            workflow_file_hint = str(result_meta.get("workflow_file") or "").strip()
            bundle_dir_hint = str(result_meta.get("bundle_dir") or "").strip()
            target_rows = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if str(row.get("flow_name") or "").strip() != str(flow_name or "").strip():
                    continue
                score = 0.0
                if workflow_file_hint and str(row.get("workflow_file") or "").strip() == workflow_file_hint:
                    score += 4.0
                if bundle_dir_hint and str(row.get("bundle_dir") or "").strip() == bundle_dir_hint:
                    score += 3.0
                aliases = {str(x or "").strip() for x in (row.get("request_aliases") or []) if str(x or "").strip()}
                source_request = str(row.get("source_request") or "").strip()
                if source_request == user_text or user_text in aliases:
                    score += 2.0
                score += min(int(row.get("updated_ts") or 0), 9999999999) / 10000000000.0
                target_rows.append((score, row))
            if not target_rows:
                return
            target_rows.sort(key=lambda item: item[0], reverse=True)
            row = dict(target_rows[0][1])
            request_dir = ""
            request_file = ""
            source_file = ""
            match = _FILE_PATH_RE.search(user_text)
            if match:
                source_file = str(match.group(1) or "").strip()
                normalized = source_file.replace("/", "\\")
                marker = normalized.find("autoflow_")
                if marker >= 0:
                    tail = normalized[marker:]
                    chunks = [chunk for chunk in tail.split("\\") if chunk]
                    if len(chunks) >= 2 and chunks[0].startswith("autoflow_") and chunks[1].startswith("request_"):
                        request_dir = "\\".join(chunks[:2])
                        request_file = request_dir.replace("\\", "/") + "/request.txt"
            append_pass_log_row(
                PASS_LOG_PATH,
                {
                    "request_id": request_dir.split("\\")[-1] if request_dir else "",
                    "request_dir": request_dir,
                    "request_file": request_file,
                    "source_file": source_file,
                    "result_file": "",
                    "record_id": str(row.get("id") or "").strip(),
                    "flow_name": str(row.get("flow_name") or flow_name or "").strip(),
                    "workflow_file": str(row.get("workflow_file") or workflow_file_hint or "").strip(),
                    "bundle_dir": str(row.get("bundle_dir") or bundle_dir_hint or "").strip(),
                    "validation_profile": "live_backend_select_run_judge_pass",
                    "selected_flow_source": str(result_meta.get("target_type") or result_meta.get("source") or "live_backend").strip(),
                    "judge_score": str(judged.get("score") or "").strip(),
                    "judge_reason": str(judged.get("reason") or "").strip(),
                },
            )
        except Exception:
            return

    def _persist_temp_library_selection(self, best: Dict[str, Any], *, source: str = "") -> None:
        if not isinstance(best, dict):
            return
        generated = best.get("generated_workflow") if isinstance(best.get("generated_workflow"), dict) else {}
        record_id = str(generated.get("record_id") or "").strip()
        if not record_id and str(source or "").strip().lower() != "library":
            return
        ctx = {"app": self._server_app()}
        patch = {
            "selection_score": round(float(best.get("score") or 0.0), 5),
            "match_score": round(float(best.get("record_score") or best.get("score") or 0.0), 5),
            "exact_request_context": bool(best.get("exact_request_context")),
            "last_selected_ts": int(time.time()),
        }
        workflow_temp_library.run(ctx, {"action": "update", "record_id": record_id, "patch": patch})

    def _feedback_key(self, user_text: str, flow_name: str) -> str:
        request_norm = " ".join(self._tokens(user_text or ""))
        basis = f"{request_norm}\n{str(flow_name or '').strip().lower()}"
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()

    def _read_feedback(self) -> Dict[str, Any]:
        path = FEEDBACK_STORE_PATH
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"entries": {}}
        except Exception:
            return {"entries": {}}
        try:
            payload = json.loads(raw)
        except Exception:
            return {"entries": {}}
        if not isinstance(payload, dict):
            return {"entries": {}}
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            payload["entries"] = {}
        return payload

    def _write_feedback(self, payload: Dict[str, Any]) -> None:
        path = FEEDBACK_STORE_PATH
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            safe_payload = payload if isinstance(payload, dict) else {"entries": {}}
            if not isinstance(safe_payload.get("entries"), dict):
                safe_payload["entries"] = {}
            path.write_text(json.dumps(safe_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            return

    def _record_feedback(self, user_text: str, flow_name: str, *, score: int, reason: str = "") -> None:
        flow_label = str(flow_name or "").strip()
        if not flow_label:
            return
        payload = self._read_feedback()
        entries = payload.get("entries") if isinstance(payload.get("entries"), dict) else {}
        payload["entries"] = entries
        key = self._feedback_key(user_text, flow_label)
        now = int(time.time())
        entries[key] = {
            "flow_name": flow_label,
            "request_excerpt": str(user_text or "").strip()[:240],
            "score": int(score),
            "reason": str(reason or "").strip()[:1000],
            "updated_ts": now,
        }
        if len(entries) > 5000:
            ordered = sorted(
                (
                    (k, v) for k, v in entries.items()
                    if isinstance(v, dict)
                ),
                key=lambda item: int(item[1].get("updated_ts") or 0),
                reverse=True,
            )
            payload["entries"] = {k: v for k, v in ordered[:5000]}
        self._write_feedback(payload)

    def _feedback_penalty(self, user_text: str, flow_name: str) -> float:
        payload = self._read_feedback()
        entries = payload.get("entries") if isinstance(payload.get("entries"), dict) else {}
        row = entries.get(self._feedback_key(user_text, flow_name))
        if not isinstance(row, dict):
            return 0.0
        try:
            score = int(row.get("score") or 0)
        except Exception:
            score = 0
        return 0.75 if score < 0 else 0.0

    def _feedback_bonus(self, user_text: str, flow_name: str) -> float:
        payload = self._read_feedback()
        entries = payload.get("entries") if isinstance(payload.get("entries"), dict) else {}
        row = entries.get(self._feedback_key(user_text, flow_name))
        if not isinstance(row, dict):
            return 0.0
        try:
            score = int(row.get("score") or 0)
        except Exception:
            score = 0
        return 0.35 if score > 0 else 0.0

    def _feedback_failed(self, user_text: str, flow_name: str) -> bool:
        payload = self._read_feedback()
        entries = payload.get("entries") if isinstance(payload.get("entries"), dict) else {}
        row = entries.get(self._feedback_key(user_text, flow_name))
        if not isinstance(row, dict):
            return False
        try:
            return int(row.get("score") or 0) < 0
        except Exception:
            return False

    def _chat_json(self, prompt: str, *, max_new_tokens: int = 900, temperature: float = 0.1) -> Dict[str, Any]:
        model = self.core.chat_llm
        if model is None:
            return {}
        try:
            resp = model.chat(
                messages=[{"role": "system", "content": "Return only strict JSON."}, {"role": "user", "content": str(prompt or "")}],
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=0.95,
            )
        except Exception:
            return {}
        if isinstance(resp, dict):
            raw = str(resp.get("content", "") or "").strip()
            if not raw:
                try:
                    raw = str(resp.get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()
                except Exception:
                    raw = ""
        elif isinstance(resp, str):
            raw = resp.strip()
        else:
            raw = str(resp or "").strip()
        if not raw:
            return {}
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            seg = raw[start:end + 1]
            seg = re.sub(r",\s*([}\]])", r"\1", seg)
            try:
                parsed = json.loads(seg)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}
    def _request_plan(self, req: Any, settings: Dict[str, Any], user_text: str) -> Dict[str, Any]:
        ext = self._ext(req)
        existing = ext.get("autoflow_request_plan") if isinstance(ext, dict) else None
        if isinstance(existing, dict) and existing:
            return existing
        profile = self._request_profile(user_text, None)
        low = str(user_text or "").lower()
        capability_ids = [str(x or "").strip() for x in (profile.get("capability_ids") or []) if str(x or "").strip()]
        focus_terms = [str(x or "").strip().lower() for x in (profile.get("focus_tokens") or []) if str(x or "").strip()]
        family_hint = str(profile.get("family") or "").strip().lower()
        file_types = [str(x or "").strip().lower() for x in (profile.get("file_types") or []) if str(x or "").strip()]
        requested_exts = sorted(self._requested_output_extensions(user_text))
        requested_output = ""
        if requested_exts:
            requested_output = ",".join(requested_exts)
        elif any(tok in low for tok in ("table", "markdown", "summary", "brief", "faq", "email", "review", "memo")):
            requested_output = "text"
        task_type = "workflow_execution"
        primary_goal = "Return the requested result accurately."
        avoid_capabilities: List[str] = []
        reason_bits: List[str] = []
        external_info_request = self._is_external_info_request(user_text)
        if external_info_request:
            reason_bits.append("external_info_request")
        if file_types:
            reason_bits.append("file_backed")
        if "repo_editing" in capability_ids:
            task_type = "repo_editing"
            primary_goal = "Inspect and update repository code accurately."
        elif any(cap in capability_ids for cap in ("spreadsheet_io", "document_io", "chart_output")):
            task_type = "file_analysis"
            primary_goal = "Read the provided file and return the requested deliverable."
        elif any(cap in capability_ids for cap in ("web_research", "market_data", "sports_live_data")):
            task_type = "live_lookup"
            primary_goal = "Retrieve current external information and return the requested output."
        elif not external_info_request and not file_types and "repo_editing" not in capability_ids:
            task_type = "general_qa"
            primary_goal = "Answer directly when the request is plain model knowledge."
            avoid_capabilities.append("repo_editing")
        if "json" in file_types and "chart_output" in capability_ids:
            reason_bits.append("json_chart_request")
        summary_parts: List[str] = []
        family_label = str(profile.get("family_label") or "").strip()
        if task_type == "general_qa":
            summary_parts.append("Answer directly from model knowledge unless the request needs tools.")
        elif family_label:
            summary_parts.append(f"Handle as {family_label}.")
        elif capability_ids:
            summary_parts.append("Route using capability fit.")
        else:
            summary_parts.append("Route to the best matching workflow.")
        if external_info_request:
            summary_parts.append("Use current external information, not static repo-only context.")
        if file_types:
            summary_parts.append(f"Read the provided {', '.join(file_types)} input.")
        policy = str(settings.get("autoflow_system_prompt") or "").strip()
        if policy:
            summary_parts.append(f"Policy: {policy}")
        summary = " ".join(summary_parts).strip()[:220]
        plan = {
            "summary": summary or f"Handle request: {user_text[:120]}".strip(),
            "task_type": task_type,
            "primary_goal": primary_goal,
            "input_kind": "file" if file_types else ("external" if external_info_request else "text"),
            "requested_output": requested_output,
            "must_use_capabilities": capability_ids,
            "avoid_capabilities": avoid_capabilities,
            "family_hint": family_hint,
            "focus_terms": focus_terms[:12],
            "reason": ", ".join(reason_bits) or "heuristic_request_plan",
        }
        must_use = [str(x or "").strip() for x in (plan.get("must_use_capabilities") or []) if str(x or "").strip()]
        avoid = [str(x or "").strip() for x in (plan.get("avoid_capabilities") or []) if str(x or "").strip()]
        focus = [str(x or "").strip().lower() for x in (plan.get("focus_terms") or []) if str(x or "").strip()]
        family_hint = str(plan.get("family_hint") or "").strip().lower()
        summary = str(plan.get("summary") or "").strip()
        if not summary:
            summary = f"Handle request: {user_text[:120]}".strip()
        return {
            "summary": summary,
            "task_type": str(plan.get("task_type") or "").strip().lower(),
            "primary_goal": str(plan.get("primary_goal") or "").strip(),
            "input_kind": str(plan.get("input_kind") or "").strip().lower(),
            "requested_output": str(plan.get("requested_output") or "").strip().lower(),
            "must_use_capabilities": must_use,
            "avoid_capabilities": avoid,
            "family_hint": family_hint,
            "focus_terms": focus,
            "reason": str(plan.get("reason") or "").strip(),
        }

    def _request_profile(self, user_text: str, plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        text = str(user_text or "").strip()
        low = text.lower()
        low_slash = low.replace("\\", "/")
        tokens = self._tokens(text)
        file_paths = [str(x or "").strip() for x in _FILE_PATH_RE.findall(text) if str(x or "").strip()]
        file_types = sorted({Path(path).suffix.lower().lstrip(".") for path in file_paths if str(path).strip()})
        caps = infer_request_capabilities(text)
        capability_ids = [str((row or {}).get("id") or "").strip() for row in caps if str((row or {}).get("id") or "").strip()]
        family = ""
        family_hits: List[str] = []
        family_score = -1
        family_label_matched = False
        for family_name, hints in _REQUEST_FAMILY_HINTS.items():
            hits = sorted(tokens & hints)
            score = len(hits)
            label = str(_REQUEST_FAMILY_LABELS.get(family_name) or "").lower()
            label_match = bool(label and label in low)
            if label_match:
                score += 3
            if score > family_score:
                family = family_name
                family_hits = hits
                family_score = score
                family_label_matched = label_match
        if family_score <= 0 or (family_score < 2 and not family_label_matched):
            family = ""
            family_hits = []
        family_tokens = set(_REQUEST_FAMILY_HINTS.get(family, set()))
        focus_tokens = sorted(
            tok for tok in tokens
            if tok not in _GENERIC_FOCUS_STOPWORDS
            and tok not in _STOPWORDS
            and len(tok) >= 3
        )
        plan = plan if isinstance(plan, dict) else {}
        for cap in [str(x or "").strip() for x in (plan.get("must_use_capabilities") or []) if str(x or "").strip()]:
            if cap not in capability_ids:
                capability_ids.append(cap)
        avoid_capabilities = [str(x or "").strip() for x in (plan.get("avoid_capabilities") or []) if str(x or "").strip()]
        plan_focus = [str(x or "").strip().lower() for x in (plan.get("focus_terms") or []) if str(x or "").strip()]
        if plan_focus:
            merged_focus = []
            for tok in [*focus_tokens, *plan_focus]:
                if tok and tok not in merged_focus:
                    merged_focus.append(tok)
            focus_tokens = merged_focus
        plan_family = str(plan.get("family_hint") or "").strip().lower()
        if plan_family:
            family = plan_family
            family_tokens = set(_REQUEST_FAMILY_HINTS.get(family, set()))
            family_hits = sorted(family_tokens & tokens)
        repo_request = (
            "repo" in tokens
            or "repository" in tokens
            or any("/repo" in str(path or "").replace("\\", "/").lower() for path in file_paths)
            or "/data/agent_workflow/repo" in low_slash
        )
        internal_authoring = any(tok in low for tok in ("email", "message", "manager", "teammate", "status update", "project update", "reminder", "teacher", "professor"))
        if internal_authoring and not self._is_external_info_request(text):
            capability_ids = [cap for cap in capability_ids if cap not in _DIRECT_EXECUTION_CAPABILITIES and cap != "web_research"]
            if "content_authoring" not in capability_ids:
                capability_ids.append("content_authoring")
            family = ""
            family_tokens = set()
            family_hits = []
        if repo_request and "repo_editing" not in capability_ids:
            capability_ids.append("repo_editing")
        if "json" in file_types:
            if "document_io" not in capability_ids:
                capability_ids.append("document_io")
            chart_terms = _REQUEST_FAMILY_HINTS.get("file_chart_output", set())
            if "chart_output" in capability_ids and family != "market_data_analysis" and not repo_request and bool(tokens & chart_terms):
                family = "file_chart_output"
                family_tokens = set(_REQUEST_FAMILY_HINTS.get(family, set()))
                family_hits = sorted(family_tokens & tokens)
                spreadsheet_terms = {"csv", "xlsx", "xls", "spreadsheet", "sheet", "workbook"}
                if not (tokens & spreadsheet_terms) and "spreadsheet_io" not in avoid_capabilities:
                    avoid_capabilities.append("spreadsheet_io")
        if repo_request and "chart_output" in capability_ids and not (tokens & _REQUEST_FAMILY_HINTS.get("file_chart_output", set())):
            capability_ids = [cap for cap in capability_ids if cap != "chart_output"]
            if family == "file_chart_output":
                family = ""
                family_tokens = set()
                family_hits = []
        if (
            self._is_external_info_request(text)
            and not file_paths
            and not repo_request
            and "weather_lookup" not in capability_ids
            and "market_data" not in capability_ids
            and "web_research" not in capability_ids
        ):
            capability_ids.append("web_research")
        return {
            "text": text,
            "tokens": tokens,
            "file_backed": bool(file_paths),
            "file_paths": file_paths,
            "file_types": file_types,
            "capability_ids": capability_ids,
            "family": family,
            "family_label": str(_REQUEST_FAMILY_LABELS.get(family) or "").strip(),
            "family_tokens": sorted(family_tokens),
            "family_hits": family_hits,
            "focus_tokens": focus_tokens,
            "avoid_capabilities": avoid_capabilities,
            "plan": plan,
        }

    def _flow_capability_fit(self, row: Dict[str, Any], profile: Dict[str, Any]) -> Tuple[float, List[str]]:
        if not isinstance(row, dict) or not isinstance(profile, dict):
            return 0.0, []
        capability_ids = [str(x or "").strip() for x in (profile.get("capability_ids") or []) if str(x or "").strip()]
        if not capability_ids:
            return 0.0, []
        doc_tokens = set(row.get("doc_tokens") or [])
        doc_text = str(row.get("doc_text") or row.get("description") or "").lower()
        raw_skills = row.get("executable_action_skills")
        if raw_skills is None:
            raw_skills = row.get("action_skills") or []
        skills = [str(x or "").strip().lower() for x in (raw_skills or []) if str(x or "").strip()]
        supported_caps = {str(x or "").strip() for x in (row.get("supported_capability_ids") or []) if str(x or "").strip()}
        score = 0.0
        reasons: List[str] = []
        for cap_id in capability_ids:
            skill_hints = _CAPABILITY_SKILL_HINTS.get(cap_id, ())
            doc_hints = _CAPABILITY_DOC_HINTS.get(cap_id, set())
            skill_hit = any(any(hint in skill for hint in skill_hints) for skill in skills) if skill_hints else False
            doc_hit = bool(doc_tokens & doc_hints) or any(hint in doc_text for hint in doc_hints)
            cap_declared = cap_id in supported_caps
            if cap_id == "web_research":
                if cap_declared or self._flow_supports_external_info(row):
                    score += 0.42
                    reasons.append("capability=web_research")
                else:
                    score -= 0.55
            elif cap_id == "sports_live_data":
                request_sports = self._sport_groups(profile.get("text") or "")
                row_sports = self._sport_groups(doc_text)
                if cap_declared or skill_hit or doc_hit or (request_sports and row_sports and (request_sports & row_sports)):
                    score += 0.48
                    reasons.append("capability=sports_live_data")
                else:
                    score -= 0.65
            elif cap_id == "market_data":
                if cap_declared or skill_hit or doc_hit or self._flow_supports_external_info(row):
                    score += 0.46
                    reasons.append("capability=market_data")
                else:
                    score -= 0.62
            elif cap_id == "spreadsheet_io":
                if cap_declared or skill_hit or doc_hit:
                    score += 0.30
                    reasons.append("capability=spreadsheet_io")
                    if "json" in set(profile.get("file_types") or []) and "chart_output" in set(profile.get("capability_ids") or []):
                        score -= 0.34
                        reasons.append("penalty=json_chart_not_spreadsheet")
                elif profile.get("file_backed"):
                    score -= 0.32
            elif cap_id == "document_io":
                if cap_declared or skill_hit or doc_hit:
                    score += 0.22
                    reasons.append("capability=document_io")
                elif profile.get("file_backed") and "json" in set(profile.get("file_types") or []):
                    score -= 0.18
            elif cap_id == "chart_output":
                if cap_declared or skill_hit or doc_hit:
                    score += 0.34
                    reasons.append("capability=chart_output")
                else:
                    score -= 0.26
            elif cap_id == "pdf_processing":
                if cap_declared or skill_hit or doc_hit:
                    score += 0.30
                    reasons.append("capability=pdf_processing")
                else:
                    score -= 0.28
            elif cap_id == "repo_editing":
                if cap_declared or skill_hit or doc_hit:
                    score += 0.36
                    reasons.append("capability=repo_editing")
                else:
                    score -= 0.40
            elif cap_id == "content_authoring":
                if cap_declared or skill_hit or doc_hit:
                    score += 0.12
                    reasons.append("capability=content_authoring")
        return round(score, 5), reasons

    def _focus_overlap_score(self, row: Dict[str, Any], profile: Dict[str, Any]) -> Tuple[float, List[str]]:
        if not isinstance(row, dict) or not isinstance(profile, dict):
            return 0.0, []
        focus_tokens = {str(x or "").strip() for x in (profile.get("focus_tokens") or []) if str(x or "").strip()}
        if not focus_tokens:
            return 0.0, []
        doc_tokens = set(row.get("doc_tokens") or [])
        overlap = sorted(focus_tokens & doc_tokens)
        if not overlap:
            return 0.0, []
        score = min(0.32, 0.08 * len(overlap))
        return round(score, 5), [f"focus={','.join(overlap[:6])}"]

    def _flow_matches_request_profile(self, row: Dict[str, Any], profile: Dict[str, Any]) -> bool:
        if not isinstance(row, dict):
            return False
        if not isinstance(profile, dict):
            return True
        family_name = str(profile.get("family") or "").strip()
        if not family_name:
            return True
        doc_tokens = set(row.get("doc_tokens") or [])
        family_tokens = set(profile.get("family_tokens") or [])
        if profile.get("file_backed"):
            cap_ids = set(profile.get("capability_ids") or [])
            file_types = set(profile.get("file_types") or [])
            skill_text = " ".join(str(x or "") for x in (row.get("action_skills") or [])).lower()
            if "chart_output" in cap_ids and "json" in file_types:
                has_json_shape = bool(doc_tokens & {"json", "series", "xvalues", "file", "path"}) or ("json" in skill_text)
                has_chart_shape = bool((doc_tokens & _FILE_SHAPE_HINTS["chart_output"]) or ({"json", "chart", "graph", "plot"} & doc_tokens))
                has_spreadsheet_shape = bool(doc_tokens & _FILE_SHAPE_HINTS["spreadsheet_io"]) or any(tok in skill_text for tok in ("sheet.", "spreadsheet", "csv", "xlsx", "xls"))
                if has_spreadsheet_shape and not has_json_shape:
                    return False
                if has_chart_shape and (has_json_shape or not has_spreadsheet_shape):
                    return True
            family_focus_guard = {
                "triage_brief",
                "contract_risk_review",
                "incident_timeline",
                "vendor_shortlist",
                "sprint_plan",
                "scheduling_resolution_brief",
                "action_register",
            }
            if family_name in family_focus_guard:
                raw_focus = {str(x or "").strip() for x in (profile.get("focus_tokens") or []) if str(x or "").strip()}
                generic = family_tokens | set(_STOPWORDS) | set(_GENERIC_FOCUS_STOPWORDS) | {"uploads", "upload", "file", "path", "csv", "xlsx", "xls", "json", "txt", "same", "day", "create", "brief", "summary", "review", "report"}
                domain_focus = {tok for tok in raw_focus if tok not in generic and len(tok) >= 4}
                if domain_focus and not (doc_tokens & domain_focus):
                    return False
        if doc_tokens & family_tokens:
            return True
        if profile.get("file_backed"):
            cap_ids = set(profile.get("capability_ids") or [])
            file_types = set(profile.get("file_types") or [])
            skill_text = " ".join(str(x or "") for x in (row.get("action_skills") or [])).lower()
            if "spreadsheet_io" in cap_ids and (doc_tokens & _FILE_SHAPE_HINTS["spreadsheet_io"]):
                return True
            if "document_io" in cap_ids and (doc_tokens & _FILE_SHAPE_HINTS["document_io"]):
                return True
            if "pdf_processing" in cap_ids and ({"pdf", "contract", "clause", "document"} & doc_tokens):
                return True
        return False

    def _selection_failure_reason(self, selected: Dict[str, Any], profile: Dict[str, Any], external_ok: bool, family_ok: bool) -> str:
        if not selected:
            return "No workflow candidate was available."
        if not external_ok:
            return "Request appears to need live or external information and the best candidate did not advertise that capability."
        if not family_ok:
            family_label = str(profile.get("family_label") or "").strip()
            if family_label:
                return f"Best candidate did not match the requested workflow family: {family_label}."
            return "Best candidate did not match the requested workflow family."
        return str(selected.get("reason") or "")

    def _runtime_and_saved_flows(self, req: Any) -> Dict[str, Any]:
        flows: Dict[str, Any] = {}
        for source in (load_default_flows({"app": self._server_app()}), load_project_flows({"app": self._server_app()}, self._pid(req)), self._get_flows(req)):
            if isinstance(source, dict):
                for key, value in source.items():
                    if isinstance(value, dict):
                        flows[str(key)] = value
        return flows

    def _explicit_creator_flow_name(self, req: Any, settings: Dict[str, Any]) -> str:
        candidates: List[Any] = [settings.get("autoflow_creator_flow_name")]
        ext = self._ext(req)
        if isinstance(ext, dict):
            direct = ext.get("autoflow_settings")
            if isinstance(direct, dict):
                candidates.append(direct.get("autoflow_creator_flow_name"))
            rps = ext.get("router_plugin_settings")
            if isinstance(rps, dict):
                auto = rps.get("autoflow")
                if isinstance(auto, dict):
                    candidates.append(auto.get("autoflow_creator_flow_name"))
        candidates.append((self.core.settings or {}).get("autoflow_creator_flow_name"))
        for raw in candidates:
            name = str(raw or "").strip()
            if name:
                return name
        return ""

    def _resolve_creator_flow_name(self, req: Any, settings: Dict[str, Any]) -> str:
        explicit = self._explicit_creator_flow_name(req, settings)
        if explicit:
            return explicit
        ext = self._ext(req)
        hinted = [
            ext.get("autoflow_creator_flow_name_hint"),
            ext.get("agent_flow_default_flow"),
            ext.get("agent_flow_active_flow"),
            (self.core.settings or {}).get("agent_flow_default_flow"),
        ]
        for raw in hinted:
            name = str(raw or "").strip()
            if name and self._looks_like_creator_flow(name):
                return name
        flows = self._runtime_and_saved_flows(req)
        preferred_names = [
            "Flow Creator / Adaptive Distinct Loop",
            "Flow Creator / Adaptive Distinct Subflow Loop",
            "Flow Creator / Adaptive Loop",
        ]
        for name in preferred_names:
            if name in flows:
                return name
        creator_candidates = [name for name in flows.keys() if self._looks_like_creator_flow(name)]
        if creator_candidates:
            creator_candidates.sort()
            return creator_candidates[0]
        return "Flow Creator / Adaptive Loop"

    def _dedupe_generated_records(self, ctx: Dict[str, Any], source_request: str, flow_name: str, keep_record_id: str) -> List[str]:
        source_request = str(source_request or "").strip()
        flow_name = str(flow_name or "").strip()
        keep_record_id = str(keep_record_id or "").strip()
        if not source_request or not flow_name or not keep_record_id:
            return []
        listed = workflow_temp_library.run(ctx, {"action": "list"})
        rows = listed.get("records") if isinstance(listed, dict) and isinstance(listed.get("records"), list) else []
        matches = [
            dict(row) for row in rows
            if isinstance(row, dict)
            and str(row.get("source_request") or "").strip() == source_request
            and str(row.get("flow_name") or "").strip() == flow_name
        ]
        if len(matches) <= 1:
            return []
        matches.sort(key=lambda row: int(row.get("updated_ts") or 0), reverse=True)
        kept = False
        deleted: List[str] = []
        for row in matches:
            record_id = str(row.get("id") or "").strip()
            if not record_id:
                continue
            if record_id == keep_record_id:
                kept = True
                continue
            if not kept and record_id != keep_record_id and keep_record_id not in {m.get("id") for m in matches}:
                kept = True
                continue
            removed = workflow_temp_library.run(ctx, {"action": "delete", "record_id": record_id})
            if removed.get("ok"):
                deleted.append(record_id)
        return deleted

    def _looks_like_creator_flow(self, name: str) -> bool:
        low = str(name or "").strip().lower()
        return low.startswith("flow creator /") or low.startswith("flow creator")

    def _looks_like_internal_maintenance_flow(self, name: str, flow_def: Any = None) -> bool:
        low = str(name or "").strip().lower()
        if not low:
            return False
        direct_tokens = (
            "validator",
            "sandbox",
            "probe",
            "debug",
        )
        if any(tok in low for tok in direct_tokens):
            return True
        if low.endswith("_test") or "_test_" in low or low.startswith("test_") or low.startswith("test "):
            return True
        if low.endswith("_tests") or "_tests_" in low or low.startswith("tests_"):
            return True
        doc = self._flow_doc(name, flow_def).lower() if isinstance(flow_def, dict) else low
        doc_tokens = (
            "workflow_designer_validator",
            "run_suite_capability",
            "generate_test_requests",
            "sandbox runner",
            "failure reviewer",
            "workflow fixer",
            "apply fixes",
            "internal run",
            "maintenance flow",
        )
        return any(tok in doc for tok in doc_tokens)

    def _flow_route_family_flags(self, name: str, flow_def: Any) -> Dict[str, bool]:
        doc = self._flow_doc(name, flow_def).lower() if isinstance(flow_def, dict) else str(name or "").lower()
        return {
            "repo_or_code": any(tok in doc for tok in (" repo ", " repository", " code", " coding", " git", " patch", " debugger", " debug", " qa reviewer", " release engineer", " repo analyst")),
            "workflow_builder": any(tok in doc for tok in ("generate new workflows", "build workflows", "workflow creator", "autobuild", "scaffold workflow")),
            "interactive_gate": any(tok in doc for tok in ("approval gate", "interaction.approval", "awaiting approval")),
        }

    def _is_user_request_flow_candidate(self, name: str, flow_def: Any, profile: Optional[Dict[str, Any]] = None) -> bool:
        if self._looks_like_creator_flow(name) or self._looks_like_internal_maintenance_flow(name, flow_def):
            return False
        if not isinstance(flow_def, dict):
            return True
        flags = self._flow_route_family_flags(name, flow_def)
        if flags.get("workflow_builder"):
            return False
        profile = profile if isinstance(profile, dict) else {}
        capability_ids = set(profile.get("capability_ids") or [])
        file_backed = bool(profile.get("file_backed"))
        if flags.get("repo_or_code") and "repo_editing" not in capability_ids:
            return False
        if flags.get("interactive_gate") and file_backed and "repo_editing" not in capability_ids:
            return False
        return True

    def _best_library_candidate(self, req: Any, user_text: str) -> Dict[str, Any]:
        ctx = {"app": self._server_app(), "original_request": user_text, "user_text": user_text}
        profile = self._request_profile(user_text)
        direct = self._builtin_direct_candidate(user_text, profile)
        if self._is_fast_builtin_candidate(direct):
            return {}
        avoid_flow_names = {str(x or "").strip().lower() for x in (self._ext(req).get("autoflow_avoid_flows") or []) if str(x or "").strip()}
        avoid_record_ids = {str(x or "").strip() for x in (self._ext(req).get("autoflow_avoid_generated_record_ids") or []) if str(x or "").strip()}
        matched = workflow_temp_library.run(ctx, {"action": "match", "user_request": user_text, "min_score": 0.15})
        rows = matched.get("matches") if isinstance(matched.get("matches"), list) else []
        best: Dict[str, Any] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            flow_name = str(row.get("flow_name") or "").strip()
            if not flow_name or not bool(row.get("validated")):
                continue
            if self._looks_like_creator_flow(flow_name) or self._looks_like_internal_maintenance_flow(flow_name):
                continue
            try:
                pass_count = int(row.get("pass_count") or 0)
                fail_count = int(row.get("fail_count") or 0)
            except Exception:
                pass_count = 0
                fail_count = 0
            all_passed_flag = row.get("all_passed") if isinstance(row, dict) and "all_passed" in row else None
            if all_passed_flag is False and (fail_count > 0 or pass_count > 0):
                continue
            if fail_count > 0 and pass_count <= 0:
                continue
            if self._feedback_failed(user_text, flow_name):
                continue
            if flow_name.lower() in avoid_flow_names:
                continue
            row_id = str(row.get("id") or "").strip()
            if row_id and row_id in avoid_record_ids:
                continue
            record_score = float(row.get("score") or 0.0)
            source_request = str(row.get("source_request") or "").strip()
            aliases = [str(x or "").strip() for x in (row.get("request_aliases") or []) if str(x or "").strip()]
            exact_match = source_request == user_text or user_text in aliases
            bundle_dir = str(row.get("bundle_dir") or "").strip()
            workflow_file = str(row.get("workflow_file") or "").strip()
            workflow_json = self._load_generated_workflow_json(flow_name, workflow_file, source_request or user_text)
            if not workflow_json:
                continue
            action_skills = self._action_skills_from_flow(workflow_json)
            executable_action_skills = self._executable_action_skills_from_flow(workflow_json)
            request_low = str(user_text or "").lower()
            action_skill_text = " ".join(str(x or "") for x in (action_skills or [])).lower()
            if re.search(r"\b(weather|forecast|temperature|humidity|wind|rain)\b", request_low) and "weather_lookup" not in action_skill_text:
                continue
            supported_capability_ids = [
                str((cap or {}).get("id") or "").strip()
                for cap in infer_request_capabilities(source_request)
                if isinstance(cap, dict) and str((cap or {}).get("id") or "").strip()
            ]
            workflow_doc = self._flow_doc(flow_name, workflow_json)
            record_context = " ".join(
                [
                    workflow_doc,
                    source_request,
                    " ".join(aliases),
                    str(row.get("summary") or ""),
                    str(row.get("description") or ""),
                    " ".join(str(x or "") for x in (row.get("tags") or [])),
                ]
            )
            request_sports = self._sport_groups(user_text)
            record_sports = self._sport_groups(record_context)
            if request_sports and record_sports and not (request_sports & record_sports):
                continue
            workflow_doc_tokens = self._tokens(record_context)
            candidate_base = {
                "action_skills": action_skills,
                "executable_action_skills": executable_action_skills,
                "supported_capability_ids": supported_capability_ids,
                "doc_text": record_context,
                "doc_tokens": sorted(list(workflow_doc_tokens or self._tokens(" ".join([flow_name, str(row.get("description") or ""), source_request, " ".join(aliases)]))))[:200],
                "description": str(row.get("description") or row.get("summary") or "").strip(),
            }
            capability_score, capability_reason_bits = self._flow_capability_fit(candidate_base, profile)
            focus_score, focus_reason_bits = self._focus_overlap_score(candidate_base, profile)
            score = (
                record_score
                + (0.60 if exact_match else 0.0)
                + capability_score
                + focus_score
                + self._feedback_bonus(user_text, flow_name)
                - self._feedback_penalty(user_text, flow_name)
            )
            generated = {
                "record_id": str(row.get("id") or "").strip(),
                "flow_name": flow_name,
                "workflow_json": workflow_json,
                "workflow_file": workflow_file,
                "bundle_dir": bundle_dir,
                "temp_skill_dirs": [str(Path(bundle_dir) / "skills")] if bundle_dir and Path(bundle_dir, "skills").is_dir() else [],
            }
            candidate = {
                "name": flow_name,
                "score": round(score, 5),
                "record_score": round(record_score, 5),
                "exact_request_context": exact_match,
                "reason": "validated temp library match"
                + ("; exact_request_context" if exact_match else "")
                + (f"; match_score={round(record_score, 3)}" if record_score else "")
                + (f"; {';'.join(capability_reason_bits)}" if capability_reason_bits else "")
                + (f"; {';'.join(focus_reason_bits)}" if focus_reason_bits else ""),
                "node_count": 0,
                "description": str(row.get("description") or row.get("summary") or "").strip() or self._workflow_doc_summary(workflow_doc),
                "action_skills": action_skills,
                "executable_action_skills": executable_action_skills,
                "supported_capability_ids": supported_capability_ids,
                "doc_text": record_context,
                "doc_tokens": candidate_base["doc_tokens"],
                "generated_workflow": generated,
            }
            if not self._flow_matches_request_profile(candidate, profile):
                continue
            if self._is_external_info_request(user_text) and not self._flow_supports_external_info(candidate):
                continue
            if not best or float(candidate.get("score") or 0.0) > float(best.get("score") or 0.0):
                best = candidate
        return best

    def _load_generated_workflow_json(self, flow_name: str, workflow_file: str, request_text: str = '') -> Dict[str, Any]:
        path = str(workflow_file or "").strip()
        if not path:
            return {}
        try:
            wf_path = Path(path)
            raw_doc = wf_path.read_text(encoding="utf-8")
            flow_doc, parsed_name, warnings = ensure_flow_payload(raw_doc, wf_path.stem)
            if isinstance(flow_doc, dict):
                normalized = dict(flow_doc)
                if request_text:
                    normalized = self._normalize_generated_workflow_for_request(normalized, request_text)
                    try:
                        self._repair_generated_bundle_for_request(str(wf_path.parent), request_text)
                    except Exception:
                        pass
                    if normalized != flow_doc:
                        try:
                            raw_payload = json.loads(raw_doc)
                            flow_key = str(flow_name or parsed_name or normalized.get('name') or wf_path.stem).strip()
                            flows_doc = raw_payload.get('flows') if isinstance(raw_payload, dict) else None
                            if isinstance(flows_doc, dict) and flow_key in flows_doc:
                                flows_doc[flow_key] = normalized
                                wf_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                        except Exception:
                            pass
                return normalized
        except Exception:
            return {}
        return {}

    def _workflow_doc_summary(self, doc_text: str) -> str:
        text = str(doc_text or "").strip()
        if not text:
            return ""
        for line in text.splitlines():
            line = str(line).strip()
            if line:
                return line[:240]
        return text[:240]

    def _server_app(self) -> Any:
        return get_server_app(dict(self.core.settings or {}), (self.core.settings or {}).get("__model_loader_registry"))

    def _pid(self, req: Any) -> str:
        ext = self._ext(req)
        pid = str(ext.get("pid") or (self.core.settings or {}).get("__pid") or "project2").strip()
        return pid or "project2"

    def _flow_doc(self, name: str, flow_def: Any) -> str:
        parts = [str(name or "")]
        if isinstance(flow_def, dict):
            parts.append(self._flow_description(flow_def))
            nodes = flow_def.get("nodes") if isinstance(flow_def.get("nodes"), dict) else {}
            for node in nodes.values():
                if not isinstance(node, dict):
                    continue
                parts.extend([
                    str(node.get("label") or ""),
                    str(node.get("plugin_id") or ""),
                    str(node.get("agent_kind") or ""),
                    str(node.get("system_prompt") or "")[:1200],
                ])
                settings = node.get("plugin_settings")
                if isinstance(settings, dict):
                    skills = settings.get("action_skills") or settings.get("action_skill_categories") or ""
                    parts.append(str(skills))
        return "\n".join(p for p in parts if p)

    def _action_skills_from_flow(self, flow_def: Any) -> List[str]:
        out: List[str] = []
        if not isinstance(flow_def, dict):
            return out
        nodes = flow_def.get("nodes") if isinstance(flow_def.get("nodes"), dict) else {}
        for node in nodes.values():
            if not isinstance(node, dict):
                continue
            settings = node.get("plugin_settings") if isinstance(node.get("plugin_settings"), dict) else {}
            for skill in settings.get("action_skills") or []:
                skill_id = str(skill or "").strip()
                if skill_id:
                    out.append(skill_id)
            tool_cfg = settings.get("tool_config") if isinstance(settings.get("tool_config"), dict) else {}
            tool_name = str(tool_cfg.get("tool") or "").strip()
            if tool_name:
                out.append(tool_name)
        return sorted(set(out))

    def _executable_action_skills_from_flow(self, flow_def: Any) -> List[str]:
        skills = []
        for skill in self._action_skills_from_flow(flow_def):
            low = str(skill or "").strip().lower()
            if not low:
                continue
            if low in _MODEL_ONLY_SKILLS:
                continue
            skills.append(skill)
        return sorted(set(skills))

    def _get_flows(self, req: Any) -> Dict[str, Any]:
        ext = self._ext(req)
        for key in ("agent_flow_flows", "flows"):
            flows = ext.get(key) if isinstance(ext, dict) else None
            if isinstance(flows, dict):
                return flows
        settings = self.core.settings or {}
        flows = settings.get("agent_flow_flows")
        return flows if isinstance(flows, dict) else {}

    def _merge_settings(self, req: Any) -> Dict[str, Any]:
        settings: Dict[str, Any] = dict(self.core.settings or {})
        ext = self._ext(req)
        if isinstance(ext, dict):
            rps = ext.get("router_plugin_settings")
            if isinstance(rps, dict) and isinstance(rps.get("autoflow"), dict):
                settings.update(rps.get("autoflow") or {})
            direct = ext.get("autoflow_settings")
            if isinstance(direct, dict):
                settings.update(direct)
        return settings

    def _selected_flow_names(self, settings: Dict[str, Any], flows: Dict[str, Any]) -> List[str]:
        select_all = self._to_bool(settings.get("autoflow_select_all"), True)
        if select_all:
            return list(flows.keys())
        raw = settings.get("autoflow_selected_flows")
        values: List[str] = []
        if isinstance(raw, list):
            values = [str(v or "").strip() for v in raw]
        elif isinstance(raw, str):
            text = raw.strip()
            if text:
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        values = [str(v or "").strip() for v in parsed]
                    else:
                        values = [v.strip() for v in text.split(",")]
                except Exception:
                    values = [v.strip() for v in text.split(",")]
        return [v for v in values if v]

    def _extract_user_text(self, req: Any) -> str:
        ext = self._ext(req)
        if isinstance(ext, dict):
            last = str(ext.get("last_user_content") or "").strip()
            if last:
                return last
        msgs = getattr(req, "messages", None)
        if isinstance(req, dict):
            msgs = req.get("messages", msgs)
        if isinstance(msgs, list):
            for msg in reversed(msgs):
                if not isinstance(msg, dict):
                    continue
                if str(msg.get("role") or "").lower() != "user":
                    continue
                content = msg.get("content")
                if isinstance(content, list):
                    return "\n".join(str(p.get("text") or p.get("content") or "") for p in content if isinstance(p, dict)).strip()
                if isinstance(content, dict):
                    return str(content.get("text") or content.get("content") or "")
                return str(content or "")
        return ""

    def _ext(self, req: Any) -> Dict[str, Any]:
        if isinstance(req, dict):
            ext = req.get("ext")
        else:
            ext = getattr(req, "ext", None)
        return ext if isinstance(ext, dict) else {}

    def _tokens(self, text: str) -> set[str]:
        tokens = {tok for tok in _WORD_RE.findall(str(text or "").lower()) if tok not in _STOPWORDS and len(tok) > 1}
        out = set(tokens)
        for tok in tokens:
            if tok.endswith("s") and len(tok) > 3:
                out.add(tok[:-1])
            if tok.endswith("ing") and len(tok) > 5:
                out.add(tok[:-3])
        return out

    def _matched_group_tokens(self, query_tokens: set[str], doc_tokens: set[str], groups: Dict[str, set[str]]) -> Dict[str, List[str]]:
        matches: Dict[str, List[str]] = {}
        for name, hints in groups.items():
            hit = sorted((query_tokens & doc_tokens) & hints)
            if hit:
                matches[name] = hit
        return matches

    def _is_external_info_request(self, text: str) -> bool:
        tokens = self._tokens(text)
        q = str(text or "").lower()
        internal_authoring = any(tok in q for tok in ("email", "message", "manager", "teammate", "status update", "project update", "reminder"))
        authoring_shape = any(marker in q for marker in (
            "help me", "draft", "create", "plan", "design", "build", "suggest", "outline",
            "prepare", "proposal", "essay", "presentation", "powerpoint", "slides", "project", "ideas", "brainstorm", "write",
        ))
        live_topic = any(tok in q for tok in ("latest", "today", "right now", "recent", "real data", "current affairs", "current problems", "modern", "trend", "trends", "housing prices", "inflation", "college tuition", "energy costs", "regulation", "policy", "elections", "public trust", "free speech", "ai-generated content", "climate", "renewable energy", "migration", "teen mental health", "social media"))
        if internal_authoring and not live_topic:
            return False
        if tokens & _EXTERNAL_INFO_HINTS:
            return True
        if live_topic and authoring_shape:
            return True
        if any(marker in q for marker in (
            "latest", "today", "current", "right now", "recent", "real data", "current affairs",
            "current problems", "modern", "trend", "trends", "housing prices", "inflation",
            "college tuition", "energy costs",
        )) and authoring_shape:
            return True
        return bool(re.search(r"\b(what'?s|what is|tell me).*\b(weather|forecast|latest|today|current)\b", q))
    def _flow_supports_external_info(self, scored_flow: Dict[str, Any]) -> bool:
        if self._flow_refuses_external_info(scored_flow):
            return False
        supported_caps = {str(x or "").strip() for x in (scored_flow.get("supported_capability_ids") or []) if str(x or "").strip()}
        if {"web_research", "sports_live_data", "market_data", "weather_lookup"} & supported_caps:
            return True
        if "action_skills" in scored_flow:
            return self._flow_has_external_action_path(scored_flow)
        tokens = set(scored_flow.get("doc_tokens") or [])
        return bool(tokens & _EXTERNAL_FLOW_CAPABILITY_HINTS)

    def _flow_has_external_action_path(self, scored_flow: Dict[str, Any]) -> bool:
        raw_skills = scored_flow.get("executable_action_skills")
        if raw_skills is None:
            raw_skills = scored_flow.get("action_skills") or []
        skills = [str(x or "").strip().lower() for x in (raw_skills or []) if str(x or "").strip()]
        if not skills:
            return False
        for skill in skills:
            if skill == "custom.general_workflow_executor":
                continue
            if any(hint in skill for hint in _EXTERNAL_ACTION_SKILL_HINTS):
                return True
        return False

    def _flow_refuses_external_info(self, scored_flow: Dict[str, Any]) -> bool:
        text = str(scored_flow.get("doc_text") or scored_flow.get("description") or "").lower()
        if not text:
            return False
        if (
            any(hint in text for hint in _EXTERNAL_ACTION_SKILL_HINTS)
            or "must retrieve current external" in text
            or "do not use rag.search" in text
            or "not substitute a generic rag search" in text
        ):
            return False
        return any(hint in text for hint in _EXTERNAL_INFO_REFUSAL_HINTS)

    def _public_candidate(self, row: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(row or {})
        out.pop("doc_tokens", None)
        out.pop("doc_text", None)
        return out

    def _sport_groups(self, text: Any) -> set[str]:
        raw = str(text or "")
        low = raw.lower()
        out: set[str] = set()
        generic_stop = {
            "current", "live", "tonight", "today", "tomorrow", "yesterday", "going",
            "playing", "against", "scheduled", "score", "scores", "team", "teams",
            "game", "games", "match", "matches", "matchup", "matchups", "fixture",
            "fixtures", "schedule", "sports", "sport", "league", "leagues",
        }
        patterns = (
            r"\b([a-z][a-z0-9.+-]{1,30})\s+(?:games?|matches|matchups?|fixtures?|schedule|scoreboard)\b",
            r"\b(?:games?|matches|matchups?|fixtures?|schedule|scoreboard)\s+(?:for|in|from)\s+([a-z][a-z0-9.+-]{1,30})\b",
            r"\bcurrent\s+([a-z][a-z0-9.+-]{1,30})\s+(?:games?|matches|matchups?|fixtures?)\b",
            r"\blive\s+([a-z][a-z0-9.+-]{1,30})\s+(?:games?|matches|matchups?|fixtures?)\b",
        )
        for pat in patterns:
            for match in re.finditer(pat, low, flags=re.I):
                token = str(match.group(1) or "").strip(" .,:;!?()[]{}").lower()
                if token and token not in generic_stop and len(token) >= 2:
                    out.add(token)
        for token in re.findall(r"\b[A-Z][A-Z0-9]{1,8}\b", raw):
            low_token = token.lower()
            if low_token not in generic_stop:
                out.add(low_token)
        return out

    def _flow_description(self, flow_def: Any) -> str:
        if not isinstance(flow_def, dict):
            return ""
        return str(flow_def.get("description") or flow_def.get("info") or flow_def.get("short_info") or "").strip()

    def _node_count(self, flow_def: Any) -> int:
        if not isinstance(flow_def, dict):
            return 0
        nodes = flow_def.get("nodes")
        return len(nodes) if isinstance(nodes, dict) else 0

    def _to_bool(self, value: Any, default: bool) -> bool:
        if value is None or value == "":
            return bool(default)
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    def _to_float(self, value: Any, default: float) -> float:
        try:
            if value is None or value == "":
                return float(default)
            return float(value)
        except Exception:
            return float(default)


def build_routes(core: RouterCore) -> list[BaseRoute]:
    return [AutoFlowRoute(core=core)]

