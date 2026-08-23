from __future__ import annotations

from typing import Any, List, Tuple, Dict, Optional
import json

from plugins.ai_routes import load_routes
from plugins.ai_routes.worker_manager import RouterWorkerManager
from plugins.ai_routes.base import RouterCore, BaseRoute


class AIRouter:
    """Plugin router for special backends (OS-Atlas, VLM code, printing, etc.)."""

    def __init__(
        self,
        chat_llm: Any,
        backend_type: str = "auto",
        settings: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.core = RouterCore(
            chat_llm=chat_llm,
            backend_type=(backend_type or "auto").lower(),
            settings=dict(settings or {}),
            resource_factories={},
            resource_clients={},
            worker_manager=RouterWorkerManager(),
        )

        # Load *all* plugins once; enable/disable is per-request in try_route().
        self.routes: List[BaseRoute] = load_routes(self.core)

    def try_route(self, req: Any) -> Tuple[bool, Any]:
        """Try to route a request to one of the plugins.

        Returns:
            (handled, result)
        """
        def _handle_route(route: BaseRoute) -> Tuple[bool, Any]:
            if route._is_canceled():
                return True, {"route_id": "chat", "reason": "canceled"}
            self._emit_router_status(route.route_id, "Routing to plugin...")
            result = route.handle(req)
            if route._is_canceled():
                return True, {"route_id": "chat", "reason": "canceled"}
            return True, result
        route_id = (getattr(req, "route_id", None) or "auto").lower()
        backend_type = (getattr(req, "backend_type", None) or "auto").lower()

        # Figure out which plugins are enabled for *this* request
        enabled_ids = self._get_enabled_plugins_from_req(req)
        print(2342342)
        print(enabled_ids)
        if enabled_ids is not None:
            enabled_set = {rid.lower() for rid in enabled_ids}
            candidate_routes = [
                r for r in self.routes if r.route_id.lower() in enabled_set
            ]
        else:
            candidate_routes = list(self.routes)
        print(234234)
        # Explicit route selection
        
        print("route_id", route_id)
        if route_id != "auto":
            route = self._find_route_by_id(route_id, candidate_routes)
            if route is None:
                return False, None
            if not route.can_handle(req):
                return False, None
            return _handle_route(route)
        print(2342234234234)
        print("candidate_routes", candidate_routes)
        # Prefer attachment-capable routes when attachments are present,
        # but only auto-short-circuit on clear "read/describe" intent.
        att_kinds = self._extract_attachment_kinds(req)
        if att_kinds:
            att_routes = [
                r for r in candidate_routes
                if getattr(r, "attachment_kinds", set()) and (getattr(r, "attachment_kinds", set()) & att_kinds)
            ]
            if len(att_routes) == 1:
                route = att_routes[0]
                user_text = self._extract_user_text(req)
                if self._should_force_attachment_route(route.route_id, user_text):
                    if route.can_handle(req):
                        return _handle_route(route)

        # Only auto-route when using an "assist" style meta-backend
        if backend_type not in ("auto", "hf_assist"):
            return False, None
        if not candidate_routes:
            return False, None  # no plugins enabled
        decision = self._classify_route(req, candidate_routes)
        if not isinstance(decision, dict):
            decision = {"route_id": "chat", "reason": "invalid_decision"}
        rid = (decision.get("route_id") or "chat").lower()
        reason = str(decision.get("reason") or "").lower()

        # Fallback to web search when available and user likely needs fresh info.
        # If there is RAG then go to direct chat.
        if rid == "chat":
            web_route = self._find_web_search_route(candidate_routes)
            if web_route is not None:
                if self._has_rag_context(req):
                    return False, None
                user_text = self._extract_user_text(req)
                has_ctx = self._has_recent_assistant_context(req)
                is_followup = self._is_followup_query(user_text)
                if not (has_ctx and is_followup):
                    if self._needs_web_search(user_text):
                        rid = web_route.route_id
                    elif any(k in reason for k in ("not enough", "insufficient", "unknown", "not sure", "need more")):
                        rid = web_route.route_id

        if rid == "chat":
            return False, None
        route = self._find_route_by_id(rid, candidate_routes)
        if route is None:
            return False, None
        if not route.can_handle(req):
            return False, None
        return _handle_route(route)

    # ------------ helpers ------------ #
    # def _get_enabled_plugins_from_req(self, req: Any) -> Optional[List[str]]:
    #     """Read enabled plugin IDs from the *request* (not global settings).

    #     The GUI / client can send this as either:
    #       - req.router_enabled_plugins
    #       - or inside req.ext["router_enabled_plugins"]

    #     If not provided, all discovered plugins are considered enabled.
    #     """
    #     enabled = getattr(req, "router_enabled_plugins", None)
    #     if enabled is not None:
    #         if isinstance(enabled, (list, tuple, set)):
    #             return [str(rid) for rid in enabled]
    #         return [str(enabled)]

    #     ext = getattr(req, "ext", None)
    #     if isinstance(ext, dict) and "router_enabled_plugins" in ext:
    #         value = ext.get("router_enabled_plugins")
    #         if isinstance(value, (list, tuple, set)):
    #             return [str(rid) for rid in value]
    #         return [str(value)]

    #     return None

    def _get_enabled_plugins_from_req(self, req: Any) -> Optional[List[str]]:
        """Read enabled plugin IDs from the *request* (not global settings).

        The GUI / client can send this as either:
        - req.router_enabled_plugins
        - or inside req.ext["router_enabled_plugins"]

        If not provided, all discovered plugins are considered enabled.

        Optional per-request routing modes:
        ext["router_mode"] in {"all","agent_flow_only","exclude_agent_flow"}
        ext["agent_flow_only"]=True (alias of agent_flow_only)
        ext["disable_agent_flow"]=True or ext["no_agent_flow"]=True (alias of exclude_agent_flow)
        """
        ext = getattr(req, "ext", None)
        router_mode = None
        if isinstance(ext, dict):
            router_mode = (ext.get("router_mode") or "").strip().lower() or None
            if bool(ext.get("agent_flow_only")):
                router_mode = "agent_flow_only"
            if bool(ext.get("disable_agent_flow")) or bool(ext.get("no_agent_flow")):
                router_mode = "exclude_agent_flow"

        enabled = getattr(req, "router_enabled_plugins", None)
        if enabled is not None:
            if isinstance(enabled, (list, tuple, set)):
                enabled_list = [str(rid).strip() for rid in enabled]
            else:
                enabled_list = [str(enabled).strip()]
            enabled_list = [rid for rid in enabled_list if rid]

            if router_mode == "agent_flow_only":
                return ["agent_flow"]
            if router_mode == "exclude_agent_flow":
                return [rid for rid in enabled_list if rid.lower() != "agent_flow"]
            return enabled_list

        if isinstance(ext, dict) and "router_enabled_plugins" in ext:
            value = ext.get("router_enabled_plugins")
            if isinstance(value, (list, tuple, set)):
                enabled_list = [str(rid).strip() for rid in value]
            else:
                enabled_list = [str(value).strip()]
            enabled_list = [rid for rid in enabled_list if rid]

            if router_mode == "agent_flow_only":
                return ["agent_flow"]
            if router_mode == "exclude_agent_flow":
                return [rid for rid in enabled_list if rid.lower() != "agent_flow"]
            return enabled_list

        if router_mode == "agent_flow_only":
            return ["agent_flow"]
        if router_mode == "exclude_agent_flow":
            return [r.route_id for r in self.routes if r.route_id.lower() != "agent_flow"]

        return None

    def _find_route_by_id(
        self,
        route_id: str,
        candidates: List[BaseRoute],
    ) -> BaseRoute | None:
        for r in candidates:
            if r.route_id.lower() == route_id.lower():
                return r
        return None

    def _find_web_search_route(self, candidates: List[BaseRoute]) -> BaseRoute | None:
        for r in candidates:
            desc = (getattr(r, "short_description", "") or "").lower()
            if "web search" in desc or "search the web" in desc:
                return r
            if "search" in desc and "web" in desc:
                return r
        return None
    
    def _emit_router_status(self, route_id: str, status: str) -> None:
        cb = None
        try:
            cb = (self.core.settings or {}).get("__router_diag_cb")
        except Exception:
            cb = None
        if not callable(cb):
            return
        try:
            cb({"router_status": status, "route_id": route_id})
        except Exception:
            pass

    def _should_force_attachment_route(self, route_id: str, user_text: str) -> bool:
        rid = (route_id or "").lower().strip()
        if rid != "image_reader":
            return False
        return self._is_image_read_intent(user_text)

    def _is_image_read_intent(self, text: str) -> bool:
        t = (text or "").lower().strip()
        if not t:
            return True
        if any(w in t for w in ("generate", "create", "draw", "make", "render", "synthesize", "stylize", "edit", "transform", "inpaint", "outpaint", "variation", "variations")):
            return False
        for phrase in (
            "describe",
            "what is in",
            "what's in",
            "what is this",
            "what's this",
            "caption",
            "summarize the image",
            "summarize this image",
            "analyze the image",
            "analyze this image",
            "read this image",
            "read the image",
            "identify",
            "detect",
            "recognize",
            "explain the image",
            "explain this image",
            "see in this image",
            "see in the image",
        ):
            if phrase in t:
                return True
        return False

    def _needs_web_search(self, text: str) -> bool:
        t = (text or "").lower().strip()
        if not t:
            return False
        if self._is_followup_query(t):
            return False
        signals = (
            "search",
            "web search",
            "search the web",
            "look up",
            "find online",
            "on the web",
            "latest",
            "current",
            "today",
            "tonight",
            "tomorrow",
            "this evening",
            "yesterday",
            "this week",
            "this month",
            "this year",
            "recent",
            "news",
            "headline",
            "as of",
            "up to date",
            "update",
            "released",
            "release date",
            "stock",
            "price",
            "weather",
            "forecast",
            "temperature",
            "rain",
            "snow",
            "traffic",
            "road conditions",
            "commute",
            "delay",
            "politic",
            "politics",
            "current politic",
            "current politics",
            "election",
            "congress",
            "senate",
            "house of representatives",
            "parliament",
            "prime minister",
            "president",
            "governor",
            "mayor",
            "campaign",
            "polling",
            "score",
            "who won",
            "results",
            "schedule",
            "standings",
            "matchup",
            "playing tonight",
            "game tonight",
            "game today",
        )
        if any(s in t for s in signals):
            return True
        sports_terms = (
            "basketball",
            "nba",
            "wnba",
            "nfl",
            "mlb",
            "nhl",
            "soccer",
            "football",
            "baseball",
            "hockey",
            "tennis",
            "match",
            "game",
        )
        freshness_terms = (
            "today",
            "tonight",
            "tomorrow",
            "this week",
            "current",
            "latest",
            "score",
            "schedule",
            "standings",
            "who won",
            "playing",
        )
        if any(s in t for s in sports_terms) and any(f in t for f in freshness_terms):
            return True
        # Detect explicit years or dates that imply freshness.
        if any(str(y) in t for y in range(2023, 2031)):
            return True
        return False

    def _is_followup_query(self, text: str) -> bool:
        t = (text or "").lower().strip()
        if not t:
            return False
        follow_tokens = (
            "that",
            "this",
            "those",
            "these",
            "it",
            "they",
            "them",
            "above",
            "previous",
            "earlier",
            "from the answer",
            "from your answer",
            "from your response",
            "in the last",
            "in your last",
            "as you said",
            "as you mentioned",
        )
        return any(tok in t for tok in follow_tokens)

    def _has_recent_assistant_context(self, req: Any) -> bool:
        msgs = getattr(req, "messages", None)
        if not isinstance(msgs, list) or not msgs:
            return False
        for m in reversed(msgs):
            if not isinstance(m, dict):
                continue
            role = (m.get("role") or "").lower()
            if role != "assistant":
                continue
            content = m.get("content", "")
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, dict):
                        t = part.get("text") or part.get("content") or ""
                        if t:
                            text_parts.append(str(t))
                content = "\n".join(text_parts)
            if isinstance(content, dict):
                content = content.get("text") or content.get("content") or ""
            if str(content).strip():
                return True
        return False

    def _classify_route(
        self,
        req: Any,
        candidates: List[BaseRoute],
    ) -> Dict[str, Any]:
        """Ask the main chat LLM which route (if any) should handle this request."""
        options: List[Dict[str, str]] = []
        for r in candidates:
            options.append(
                {
                    "route_id": r.route_id,
                    "description": getattr(r, "short_description", "") or "",
                }
            )
        user_text = self._extract_user_text(req)

        system_content = (
            "You are a router that decides which specialized tool (route) "
            "should handle the user's request.\n\n"
            "You MUST respond with a JSON object ONLY, no extra text.\n"
            "Schema:\n"
            '{ \"route_id\": \"<route_id>\", \"reason\": \"<short explanation>\" }\n\n'
            "Valid route_id values:\n"
            "- \"chat\" to indicate the normal chat model should handle it.\n\n"
            "If the provided context (including any RAG context or prior assistant messages) "
            "already contains enough information to answer confidently, choose \"chat\".\n"
            "Please check the Rag context to see if the router_id has already answered in the results JSON \n"
            "then choose \"chat\" if the answer is in there and do not check any other route. \n"
            "If the user explicitly asks to search the web or look something up online, "
            "choose the web search route if available. Otherwise, choose web search only "
            "when the answer is time-sensitive or you lack enough information.\n"
            "Sports questions about games, scores, schedules, standings, matchups, or who is playing tonight/today/tomorrow "
            "should use the web search route if available because they are time-sensitive.\n"
            "Questions about news, weather, traffic, or current politics should use the web search route if available "
            "because they are usually current-event dependent.\n"
        )
        # system_content = (
        #     "You are a router that decides which specialized tool (route) "
        #     "should handle the user's request.\n\n"
        #     "You MUST respond with a JSON object ONLY, no extra text.\n"
        #     "Schema:\n"
        #     '{ \"route_id\": \"<route_id>\", \"reason\": \"<short explanation>\" }\n\n'
        #     "Valid route_id values:\n"
        #     "- \"chat\" to indicate the normal chat model should handle it.\n\n"
        #     "If the provided context (including any RAG context or prior assistant messages) "
        #     "already contains enough information to answer confidently, choose \"chat\".\n"
        #     "Please check the Rag context to see if the router_id has already answered in the results JSON \n"
        #     "then choose \"chat\" if the answer is in there and do not check any other route. \n"
        # )

        for opt in options:
            system_content += f'- "{opt["route_id"]}": {opt["description"]}\n'
        system_msg = {"role": "system", "content": system_content}
        print("32423423423----", req)
        context = self._extract_router_context(req)
        include_context = bool(context) and (
            self._is_followup_query(user_text) or self._has_rag_context(req)
        )
        if include_context:
            user_msg = {"role": "user", "content": f"User request: {user_text}\nRAG context:\n{context}"}
            print("router messages__________: ", user_msg)
        else:
            user_msg = {"role": "user", "content": user_text}
        print("3224324232")

        resp = self.core.chat_llm.chat(
            messages=[system_msg, user_msg],
            max_new_tokens=400,
            temperature=0.0,
            top_p=0.0,
        )

        if isinstance(resp, dict):
            raw = str(resp.get("content", "")).strip()
        else:
            raw = str(resp or "").strip()

        print("raw:", raw)
        if raw.startswith("```"):
            raw = raw.strip("`")
            if "\n" in raw:
                raw = raw.split("\n", 1)[1]
        if "<think>" in raw:
            # Strip known thinking tags and any leading content before JSON.
            raw = raw.replace("<think>", "").replace("</think>", "").strip()
        if not raw.strip():
            return {"route_id": "chat", "reason": "empty_response"}
        # If the model prepended commentary, keep only the JSON object.
        if "{" in raw:
            raw = raw[raw.find("{") :]
            if "}" in raw:
                raw = raw[: raw.rfind("}") + 1]
        try:
            decision = json.loads(raw)
            if not isinstance(decision, dict):
                raise ValueError("non-object JSON")
        except Exception:
            # Repair common invalid JSON: raw newlines inside quoted strings.
            def _escape_newlines_in_strings(text: str) -> str:
                out = []
                in_str = False
                escape = False
                for ch in text:
                    if escape:
                        out.append(ch)
                        escape = False
                        continue
                    if ch == "\\":
                        out.append(ch)
                        escape = True
                        continue
                    if ch == "\"":
                        in_str = not in_str
                        out.append(ch)
                        continue
                    if in_str and ch in ("\n", "\r"):
                        out.append("\\n")
                        continue
                    out.append(ch)
                return "".join(out)

            try:
                repaired = _escape_newlines_in_strings(raw)
                decision = json.loads(repaired)
                if not isinstance(decision, dict):
                    raise ValueError("non-object JSON")
            except Exception:
                # Final fallback: regex extraction for route_id/reason.
                import re

                rid_match = re.search(r'"route_id"\s*:\s*"([^"]+)"', raw)
                reason_match = re.search(r'"reason"\s*:\s*"([^"]+)"', raw, re.DOTALL)
                if rid_match:
                    decision = {
                        "route_id": rid_match.group(1),
                        "reason": reason_match.group(1).strip() if reason_match else "parse_error",
                    }
                else:
                    decision = {"route_id": "chat", "reason": "parse_error"}

        return decision

    def _try_parse_json_object(self, raw: str) -> Optional[Dict[str, Any]]:
        text = str(raw or "").strip()
        if not text:
            return None
        if text.startswith("```"):
            text = text.strip("`")
            if "\n" in text:
                text = text.split("\n", 1)[1]
        if "{" in text and "}" in text:
            text = text[text.find("{") : text.rfind("}") + 1]
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except Exception:
            return None
        return None

    def _extract_router_context(self, req: Any) -> str:
        ext = getattr(req, "ext", None)
        if isinstance(ext, dict) and isinstance(ext.get("router_context_messages"), list):
            msgs = ext.get("router_context_messages")
        else:
            msgs = getattr(req, "messages", None)
        if not isinstance(msgs, list) or not msgs:
            return ""
        rag_snippets: List[str] = []
        last_assistant = ""

        def _coerce_text(content: Any) -> str:
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, dict):
                        t = part.get("text") or part.get("content") or ""
                        if t:
                            text_parts.append(str(t))
                return "\n".join(text_parts).strip()
            if isinstance(content, dict):
                return str(content.get("text") or content.get("content") or "").strip()
            return str(content or "").strip()

        for m in msgs:
            if not isinstance(m, dict):
                continue
            role = (m.get("role") or "").lower()
            content = _coerce_text(m.get("content"))
            if not content:
                continue
            low = content.lower()
            if "[context]" in low or "[rag" in low or "user-rag" in low or "rag context" in low:
                rag_snippets.append(content)
            if role == "assistant":
                # payload = self._try_parse_json_object(content)
                # if isinstance(payload, dict) and str(payload.get("route_id") or "").strip():
                #     continue
                last_assistant = content

        parts: List[str] = []
        if last_assistant:
            parts.append(f"[last assistant]\n{last_assistant}")
        if rag_snippets:
            parts.append("[rag snippets]\n" + "\n\n".join(rag_snippets[-2:]))
        return "\n\n".join(parts).strip()

    def _has_rag_context(self, req: Any) -> bool:
        ext = getattr(req, "ext", None)
        if isinstance(ext, dict) and isinstance(ext.get("router_context_messages"), list):
            msgs = ext.get("router_context_messages")
        else:
            msgs = getattr(req, "messages", None)
        if not isinstance(msgs, list) or not msgs:
            return False
        for m in msgs:
            if not isinstance(m, dict):
                continue
            content = m.get("content")
            if isinstance(content, list):
                text = "\n".join(
                    str((part or {}).get("text") or (part or {}).get("content") or "")
                    for part in content
                    if isinstance(part, dict)
                ).lower()
            elif isinstance(content, dict):
                text = str(content.get("text") or content.get("content") or "").lower()
            else:
                text = str(content or "").lower()
            if "[context]" in text or "[rag" in text or "user-rag" in text or "rag context" in text:
                return True
        return False

    def _extract_attachment_kinds(self, req: Any) -> set[str]:
        kinds: set[str] = set()

        def _scan(items: Any) -> None:
            if not isinstance(items, list):
                return
            for a in items:
                if not isinstance(a, dict):
                    continue
                kind = str(a.get("kind") or "").lower()
                mime = str(a.get("mime") or a.get("content_type") or "").lower()
                if kind:
                    kinds.add(kind)
                if mime.startswith("image/"):
                    kinds.add("image")
                if mime.startswith("video/"):
                    kinds.add("video")

        if isinstance(req, dict):
            _scan(req.get("attachments"))
            ext = req.get("ext") or {}
            _scan((ext or {}).get("attachments"))
            _scan((ext or {}).get("media_attachments"))
            msgs = req.get("messages") or []
        else:
            _scan(getattr(req, "attachments", None))
            ext = getattr(req, "ext", None)
            if isinstance(ext, dict):
                _scan(ext.get("attachments"))
                _scan(ext.get("media_attachments"))
            msgs = getattr(req, "messages", None) or []

        if isinstance(msgs, list):
            for m in msgs:
                if not isinstance(m, dict):
                    continue
                meta = m.get("meta")
                if isinstance(meta, dict):
                    _scan(meta.get("attachments"))
                content = m.get("content")
                if isinstance(content, list):
                    for part in content:
                        if not isinstance(part, dict):
                            continue
                        ptype = str(part.get("type") or "").lower()
                        if ptype in ("image_url", "image"):
                            kinds.add("image")
                        if ptype == "video_url":
                            kinds.add("video")
        return kinds

    def _extract_user_text(self, req: Any) -> str:
        ext = None
        if isinstance(req, dict):
            ext = req.get("ext")
        else:
            ext = getattr(req, "ext", None)
        if isinstance(ext, dict):
            last = str(ext.get("last_user_content") or "").strip()
            if last:
                return last
        msgs = getattr(req, "messages", None)
        if isinstance(msgs, list) and msgs:
            last_user = None
            for m in msgs:
                if not isinstance(m, dict):
                    continue
                if (m.get("role") or "").lower() == "user":
                    last_user = m
            if last_user is None:
                last = msgs[-1]
                if isinstance(last, dict):
                    last_user = last
            if isinstance(last_user, dict):
                content = last_user.get("content", "")
                if isinstance(content, list):
                    parts = []
                    for part in content:
                        if isinstance(part, dict):
                            t = part.get("text") or part.get("content") or ""
                            if t:
                                parts.append(str(t))
                    return "\n".join(parts)
                if isinstance(content, dict):
                    return str(content.get("text") or content.get("content") or "")
                return str(content)
            try:
                return str(msgs[-1])
            except Exception:
                return ""

        try:
            if hasattr(req, "model_dump"):
                return json.dumps(req.model_dump(), ensure_ascii=False)
            if hasattr(req, "dict"):
                return json.dumps(req.dict(), ensure_ascii=False)
        except Exception:
            pass

        return str(req)
