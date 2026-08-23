from __future__ import annotations

from typing import Any, Dict, List
import difflib
import json
import logging
import os
import re
import inspect
import time

from plugins.ai_routes.base import BaseRoute, RouterCore
from plugins.ai_routes.model_deck_utils import ModelDeckRunner


PLUGIN_ID = "agent_workflow_member"
PLUGIN_TITLE = "Agent Workflow Member"
PLUGIN_NAME = "Agent Workflow Member"
PLUGIN_DESCRIPTION = "General-purpose team-member node for agent_workflow/agent_flow orchestration."
PLUGIN_TYPE = "coding"
PLUGIN_DEPENDENCIES = ["agent_flow", "model_deck"]
AGENT_LINKABLE = True

logger = logging.getLogger(__name__)

PLUGIN_CONFIG_SCHEMA = [
    {
        "key": "agent_workflow_member_max_tokens",
        "label": "Max tokens",
        "type": "int",
        "default": "700",
        "help": "Maximum output tokens for member-node generation and fallback artifact creation.",
    },
    {
        "key": "agent_workflow_member_temperature",
        "label": "Temperature",
        "type": "float",
        "default": "0.1",
        "help": "Generation temperature for member-node response.",
    },
    {
        "key": "handoff_format",
        "label": "Handoff format",
        "type": "enum",
        "options": ["concise_structured", "json", "plain"],
        "default": "concise_structured",
        "help": "Preferred output handoff format for this node.",
    },
    {
        "key": "output_protocol",
        "label": "Output protocol",
        "type": "enum",
        "options": ["auto", "json", "tagged"],
        "default": "auto",
        "help": "Structured output protocol for this node. Use tagged for large artifact creation.",
    },
    {
        "key": "member_token_stream",
        "label": "Token Stream",
        "type": "bool",
        "default": True,
        "help": "When enabled, stream model token chunks via agent_flow diagnostics if backend supports stream_chat.",
    },
    {
        "key": "action_skills",
        "label": "Action skills",
        "type": "multiselect",
        "options": [
            "auth.project_context",
            "collab.session_context",
            "repo.tree",
            "repo.context",
            "repo.find_file",
            "repo.read",
            "repo.write",
            "repo.ingest",
            "rag.search",
            "tests.smoke",
            "tests.run_project",
            "code.apply_patch",
            "code.generate_patch_candidates",
            "debug.fix_from_errors",
            "learning.capture_feedback",
            "learning.get_hints",
            "learning.list",
            "result.text",
            "result.chart",
            "result.files",
            "result.zip",
        ],
        "default": [],
        "help": "Allowed action skills this node may invoke via tool_calls.",
    },
    {
        "key": "action_skill_categories",
        "label": "Action skill categories",
        "type": "multiselect",
        "options": ["repo", "code", "rag", "pdf", "workflow", "tests", "debug", "learning", "result"],
        "default": [],
        "help": "Allowed drop-in skill categories. A category grants all Agent Flow skills registered under that category, such as repo.* or pdf.*.",
    },
]


class AgentWorkflowMemberRoute(BaseRoute):
    route_id = "agent_workflow_member"
    short_description = "Execute a team-member role prompt and return structured handoff text."
    backend_types = {"hf", "hf_assist", "gguf", "vllm", "auto"}

    def _default_skills_for_role(self, role: str) -> List[str]:
        r = str(role or "").strip().lower()
        role_skill_map = {
            "product": ["auth.project_context", "repo.context", "repo.find_file", "repo.read", "learning.get_hints"],
            "gui_designer": ["repo.context", "repo.find_file", "repo.read", "rag.search", "learning.get_hints"],
            "architect": ["repo.tree", "repo.context", "repo.find_file", "repo.read", "repo.ingest", "rag.search"],
            "coder": ["repo.tree", "repo.find_file", "repo.read", "repo.write", "repo.ingest", "rag.search", "code.generate_patch_candidates", "code.apply_patch"],
            "staff_engineer": ["repo.tree", "repo.find_file", "repo.read", "repo.write", "repo.ingest", "rag.search", "code.generate_patch_candidates", "code.apply_patch", "tests.run_project"],
            "qa": ["repo.find_file", "repo.read", "repo.ingest", "rag.search", "tests.run_project", "tests.smoke", "debug.fix_from_errors"],
            "docs": ["repo.context", "repo.find_file", "repo.read", "learning.get_hints"],
            "security": ["repo.tree", "repo.find_file", "repo.read", "repo.ingest", "rag.search"],
            "release": ["repo.find_file", "repo.read", "tests.run_project", "learning.list"],
        }
        return list(role_skill_map.get(r, ["repo.find_file", "repo.read", "repo.tree", "rag.search"]))

    def _expand_skill_categories(self, categories: Any) -> List[str]:
        if not isinstance(categories, list):
            return []
        normalized = []
        for raw in categories:
            val = str(raw or "").strip()
            if not val:
                continue
            normalized.append(val[:-2] if val.endswith(".*") else val)
        if not normalized:
            return []
        settings: Dict[str, Any] = dict(self.core.settings or {})
        registered = settings.get("__agent_flow_skill_categories")
        if not isinstance(registered, dict):
            return []
        out: List[str] = []
        for cat in normalized:
            rows = registered.get(cat)
            if isinstance(rows, list):
                out.extend(str(x or "").strip() for x in rows if str(x or "").strip())
        return sorted(set(out))

    def _role_display(self, role: str) -> str:
        r = str(role or "").strip().lower()
        labels = {
            "coder": "Coding Engineer",
            "qa": "QA Reviewer",
            "gui_designer": "GUI Designer",
            "architect": "Architecture Reviewer",
            "product": "Product Reviewer",
            "staff_engineer": "Staff Engineer Reviewer",
            "security": "Security Reviewer",
            "docs": "Docs Reviewer",
            "release": "Release Reviewer",
        }
        return labels.get(r, role or "Workflow Specialist")

    def _normalize_role(self, raw: str) -> str:
        s = str(raw or "").strip().lower().replace(" ", "_")
        aliases = {
            "staff": "staff_engineer",
            "engineer": "coder",
            "coding_engineer": "coder",
            "workflow_specialist": "",
            "specialist": "",
        }
        return aliases.get(s, s)

    def _infer_role_from_label(self, label: str) -> str:
        low = str(label or "").strip().lower()
        if "docs" in low:
            return "docs"
        if "release" in low:
            return "release"
        if "qa" in low:
            return "qa"
        if "security" in low:
            return "security"
        if "architect" in low:
            return "architect"
        if "product" in low:
            return "product"
        if "designer" in low or "gui" in low:
            return "gui_designer"
        if "staff" in low:
            return "staff_engineer"
        if "coder" in low or "engineer" in low:
            return "coder"
        return ""

    def _extract_target_path(self, user_text: str) -> str:
        raw = str(user_text or "")
        if not raw.strip():
            return ""
        explicit_patterns = [
            r"\b(?:file|path|target file|repo file)\s+[`'\"]?([A-Za-z0-9_./\\-]+\.(?:py|js|ts|tsx|jsx|json|md|html|css|rs|toml|ya?ml|ini|cfg))[`'\"]?",
            r"[`'\"]([A-Za-z0-9_./\\-]+\.(?:py|js|ts|tsx|jsx|json|md|html|css|rs|toml|ya?ml|ini|cfg))[`'\"]",
        ]
        for pattern in explicit_patterns:
            m = re.search(pattern, raw, flags=re.IGNORECASE)
            if not m:
                continue
            return str(m.group(1) or "").strip().replace("\\", "/")
        return ""

    def _tool_error_codes(self, row: Dict[str, Any]) -> List[str]:
        if not isinstance(row, dict):
            return []
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        codes: List[str] = []
        direct = str(row.get("error_code") or data.get("error_code") or "").strip()
        if direct:
            codes.append(direct)
        warnings = row.get("warnings") if isinstance(row.get("warnings"), list) else []
        for warning in warnings:
            w = str(warning or "").strip()
            if w.startswith("missing_file:"):
                codes.append("FILE_NOT_FOUND")
            elif w.startswith("path_outside_workspace:"):
                codes.append("PATH_OUTSIDE_SCOPE")
            elif w.startswith("target_repo_root_not_found"):
                codes.append("TARGET_REPO_ROOT_NOT_FOUND")
            elif w.startswith("base_prefix_missing:"):
                codes.append("BASE_PREFIX_MISSING")
        return sorted(set(codes))

    def _is_file_not_found_result(self, row: Dict[str, Any]) -> bool:
        return "FILE_NOT_FOUND" in self._tool_error_codes(row)

    def _recover_missing_repo_reads(self, tool_results: List[Dict[str, Any]], allowed: List[str], req: Any) -> List[Dict[str, Any]]:
        if not isinstance(tool_results, list):
            return []
        if "repo.find_file" not in allowed or "repo.read" not in allowed:
            return []
        recoveries: List[Dict[str, Any]] = []
        seen_queries = set()
        for row in tool_results[:8]:
            if not isinstance(row, dict):
                continue
            if str(row.get("skill") or "").strip() != "repo.read":
                continue
            if not self._is_file_not_found_result(row):
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            missing_path = str(data.get("path") or "").strip().replace("\\", "/")
            if not missing_path:
                warnings = row.get("warnings") if isinstance(row.get("warnings"), list) else []
                for warning in warnings:
                    w = str(warning or "").strip()
                    if w.startswith("missing_file:"):
                        missing_path = w.split(":", 1)[1].strip().replace("\\", "/")
                        break
            if not missing_path:
                continue
            query = os.path.basename(missing_path) or missing_path.rsplit("/", 1)[-1]
            search_path = os.path.dirname(missing_path).replace("\\", "/").strip()
            key = (query.lower(), search_path.lower())
            if key in seen_queries:
                continue
            seen_queries.add(key)
            self._emit_diag({"member_stream": f"Repo recovery: locating missing file {query}"})
            find_calls = [{"skill": "repo.find_file", "params": {"filename": query, "path": search_path or ".", "max_matches": 5}}]
            found_rows = self._run_tool_calls(find_calls, allowed, req)
            recoveries.extend(found_rows)
            found_path = ""
            for found in found_rows:
                if not isinstance(found, dict) or not bool(found.get("ok")):
                    continue
                found_data = found.get("data") if isinstance(found.get("data"), dict) else {}
                matches = found_data.get("matches") if isinstance(found_data.get("matches"), list) else []
                if matches and isinstance(matches[0], dict):
                    found_path = str(matches[0].get("path") or "").strip().replace("\\", "/")
                found_path = found_path or str(found.get("actual_output_path") or found.get("output_path") or "").strip().replace("\\", "/")
                if found_path:
                    break
            if found_path:
                read_rows = self._run_tool_calls([{"skill": "repo.read", "params": {"path": found_path, "max_chars": 20000}}], allowed, req)
                recoveries.extend(read_rows)
                break
        return recoveries

    def _infer_repo_probe_path(self, user_text: str) -> str:
        raw = str(user_text or "")
        low = raw.lower()
        ignored_literals = {
            "node.js",
            "nodejs",
            "express",
            "flask",
            "rust",
            "c#",
            ".net",
            "dotnet",
        }
        # Prefer exact user-named repo folder literals before any generic plugin probing.
        exact_folder_patterns = [
            r"\brepo folder\s+([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)\b",
            r"\bfolder\s+([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)\b",
            r"\bin the repo folder\s+([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)\b",
            r"\bcalled\s+([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)\b",
        ]
        for pattern in exact_folder_patterns:
            m_folder = re.search(pattern, raw, flags=re.IGNORECASE)
            if not m_folder:
                continue
            candidate = str(m_folder.group(1) or "").strip().replace("\\", "/").strip("/")
            if candidate and candidate.lower() not in ignored_literals and re.match(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$", candidate):
                return candidate
        explicit = self._extract_target_path(raw)
        if explicit:
            return explicit
        for token in re.findall(r"[A-Za-z0-9_.-]+", raw):
            token_low = token.lower()
            if (
                len(token) >= 4
                and "-" in token
                and token_low not in ignored_literals
                and token_low not in {"read-only", "analysis-only"}
                and not token_low.startswith(("http", "www"))
            ):
                return token
        codeish: List[str] = []
        for m in re.finditer(r"`([^`]+)`|\"([^\"]+)\"|'([^']+)'", raw):
            val = str(next((g for g in m.groups() if g), "")).strip().replace("\\", "/").strip("/")
            if val and re.match(r"^[A-Za-z0-9_./-]+$", val):
                codeish.append(val)
        if "plugin" in low:
            for cand in codeish:
                if "/" in cand:
                    return cand
                if re.match(r"^[A-Za-z0-9_-]+$", cand):
                    return f"plugin/{cand}"
            m_name = re.search(r"\bplugin name is\s+([A-Za-z0-9_-]+)\b", raw, flags=re.IGNORECASE)
            if m_name:
                return f"plugin/{str(m_name.group(1) or '').strip()}"
            return "plugin"
        if "plugins" in low:
            return "plugins"
        return ""

    def _pick_repo_probe_candidate(self, user_text: str, probe_results: List[Dict[str, Any]]) -> str:
        raw = str(user_text or "")
        low_user = raw.lower()
        terms = [t for t in re.findall(r"[A-Za-z0-9_/-]+", low_user) if len(t) >= 2]
        exact_hint = str(self._infer_repo_probe_path(raw) or "").strip().replace("\\", "/").strip("/").lower()
        plugin_intent = "plugin" in low_user or "plugins" in low_user
        best_path = ""
        best_score = -1
        for row in probe_results:
            if not isinstance(row, dict):
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            files = data.get("files") if isinstance(data.get("files"), list) else []
            for item in files[:400]:
                rel = str(item or "").strip().replace("\\", "/")
                if not rel:
                    continue
                low = rel.lower()
                score = 0
                if exact_hint:
                    if low == exact_hint or low.startswith(exact_hint + "/"):
                        score += 20
                    if low.endswith("/" + exact_hint):
                        score += 12
                if ("/plugin/" in f"/{low}" or low.startswith("plugin/")) and plugin_intent:
                    score += 2
                elif "/plugin/" in f"/{low}" or low.startswith("plugin/"):
                    score -= 4
                if (low.endswith("/plugin.js") or low.endswith("/manifest.json")) and plugin_intent:
                    score += 3
                elif low.endswith("/plugin.js") or low.endswith("/manifest.json"):
                    score -= 3
                if ("i18n" in low or "lang" in low or "locale" in low) and plugin_intent:
                    score += 6
                for term in terms:
                    if term and term in low:
                        score += 2
                if score > best_score:
                    best_score = score
                    best_path = rel
        if best_path.lower().endswith("/manifest.json"):
            return best_path[: -len("/manifest.json")]
        if best_path.lower().endswith("/plugin.js"):
            return best_path[: -len("/plugin.js")]
        if exact_hint and (best_score <= 0 or not best_path):
            return exact_hint
        return best_path or exact_hint

    def _repo_edit_request_already_satisfied(
        self,
        *,
        summary: str,
        analysis_text: str,
        response_text: str,
        handoff_text: str,
        actions: List[str],
        tool_results: List[Dict[str, Any]],
    ) -> bool:
        read_rows = [
            tr for tr in (tool_results or [])
            if isinstance(tr, dict)
            and bool(tr.get("ok"))
            and str(tr.get("skill") or "").strip() == "repo.read"
        ]
        if not read_rows:
            return False
        combined = "\n".join(
            [
                str(summary or "").strip(),
                str(analysis_text or "").strip(),
                str(response_text or "").strip(),
                str(handoff_text or "").strip(),
                "\n".join(str(a or "").strip() for a in (actions or []) if str(a or "").strip()),
            ]
        ).lower()
        satisfied_markers = [
            "already implemented",
            "already present",
            "already satisfied",
            "requested improvements are already implemented",
            "none required",
            "no files were changed",
            "changed files: none",
            "no further action needed",
        ]
        return any(marker in combined for marker in satisfied_markers)

    def _repo_probe_read_candidates(self, user_text: str, candidate_probe_path: str, probe_results: List[Dict[str, Any]]) -> List[str]:
        candidate = str(candidate_probe_path or "").strip().replace("\\", "/").strip("/")
        if not candidate:
            return []
        # If the candidate is already a concrete file path, read it directly.
        if re.search(r"\.(?:py|js|ts|tsx|jsx|json|md|html|css|rs|toml|ya?ml|ini|cfg|cs|java|go)$", candidate, flags=re.IGNORECASE):
            return [candidate]
        raw = str(user_text or "")
        exact_hint = str(self._infer_repo_probe_path(raw) or "").strip().replace("\\", "/").strip("/")
        preferred_names: List[str] = []
        low_user = raw.lower()
        if "cargo.toml" in low_user:
            preferred_names.append("cargo.toml")
        if "package.json" in low_user:
            preferred_names.append("package.json")
        if "src/main.rs" in low_user:
            preferred_names.append("src/main.rs")
        if "src/main.py" in low_user:
            preferred_names.append("src/main.py")
        if "src/index.js" in low_user:
            preferred_names.append("src/index.js")
        if "program.cs" in low_user:
            preferred_names.append("Program.cs")
        if "main.go" in low_user:
            preferred_names.append("main.go")
        repo_files: List[str] = []
        for row in probe_results:
            if not isinstance(row, dict):
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            files = data.get("files") if isinstance(data.get("files"), list) else []
            for item in files[:800]:
                rel = str(item or "").strip().replace("\\", "/").strip("/")
                if rel:
                    repo_files.append(rel)
        seen: set[str] = set()
        repo_files = [p for p in repo_files if not (p in seen or seen.add(p))]
        scoped_files = [
            p for p in repo_files
            if p == candidate or p.startswith(candidate + "/")
        ]
        if exact_hint:
            scoped_files = [
                p for p in scoped_files
                if p == exact_hint or p.startswith(exact_hint + "/")
            ] or scoped_files
        if not scoped_files:
            return []
        ordered: List[str] = []
        for name in preferred_names:
            target = f"{candidate.rstrip('/')}/{name}".strip("/")
            for p in scoped_files:
                if p.lower() == target.lower() and p not in ordered:
                    ordered.append(p)
        rank_patterns = [
            r"/cargo\.toml$",
            r"/package\.json$",
            r"/src/main\.(rs|py|ts|js)$",
            r"/src/index\.(ts|js)$",
            r"/program\.cs$",
            r"/main\.go$",
            r"/lib\.(rs|py|ts|js)$",
            r"\.(rs|py|ts|tsx|js|jsx|cs|go|java|toml|json|ya?ml|ini|cfg|md|html|css)$",
        ]
        for pattern in rank_patterns:
            for p in scoped_files:
                if p in ordered:
                    continue
                if re.search(pattern, "/" + p, flags=re.IGNORECASE):
                    ordered.append(p)
        return ordered[:4]

    def _resolve_target_repo_root(self, req: Any) -> str:
        ext = getattr(req, "ext", None)
        if isinstance(ext, dict):
            rps = ext.get("router_plugin_settings")
            if isinstance(rps, dict):
                aw = rps.get("agent_workflow")
                if isinstance(aw, dict):
                    tr = str(aw.get("target_repo_root") or "").strip()
                    if tr:
                        return tr
            tr2 = str(ext.get("agent_workflow_target_repo_root") or "").strip()
            if tr2:
                return tr2
            tr3 = str(ext.get("target_repo_root") or "").strip()
            if tr3:
                return tr3
        user_text = self._extract_user_text(req)
        original_request = str(self._extract_original_request(user_text) or "").strip()
        inferred = str(self._infer_repo_probe_path(original_request) or self._infer_repo_probe_path(user_text) or "").strip().replace("\\", "/").strip("/")
        if not inferred:
            return ""
        if re.search(r"\.(?:py|js|ts|tsx|jsx|json|md|html|css|rs|toml|ya?ml|ini|cfg)$", inferred, flags=re.IGNORECASE):
            inferred = inferred.rsplit("/", 1)[0] if "/" in inferred else ""
        if not inferred:
            return ""
        if inferred.lower().startswith("data/agent_workflow/repo/"):
            return inferred
        return f"data/agent_workflow/repo/{inferred}"

    def _extract_original_request(self, user_text: str) -> str:
        raw = str(user_text or "").strip()
        if not raw:
            return ""
        m = re.search(
            r"Original user request:\s*\n(?P<body>.*?)(?:\n\s*\n(?:Previous step context:|Changed files so far:|Current instruction:)|$)",
            raw,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if m:
            return str(m.group("body") or "").strip()
        return raw

    def _extract_section(self, text: str, header: str, next_headers: List[str]) -> str:
        raw = str(text or "")
        if not raw:
            return ""
        parts = [re.escape(str(h or "").strip()) for h in next_headers if str(h or "").strip()]
        tail = "|".join(parts)
        pattern = rf"{re.escape(header)}:\s*\n(?P<body>.*?)(?:\n\s*\n(?:{tail}):|\Z)" if tail else rf"{re.escape(header)}:\s*\n(?P<body>.*)$"
        m = re.search(pattern, raw, flags=re.DOTALL | re.IGNORECASE)
        if not m:
            return ""
        return str(m.group("body") or "").strip()

    def _truncate_structured_context(self, user_text: str, limit: int) -> str:
        raw = str(user_text or "").strip()
        if not raw or limit <= 0 or len(raw) <= limit:
            return raw
        if "Original user request:" not in raw:
            return raw[-limit:]
        original = self._extract_original_request(raw)
        changed = self._extract_section(raw, "Changed files so far", ["Current instruction"])
        current = self._extract_section(raw, "Current instruction", [])
        prev = self._extract_section(raw, "Previous step context", ["Changed files so far", "Current instruction"])
        blocks = []
        if original:
            blocks.append(("Original user request", original))
        if changed:
            blocks.append(("Changed files so far", changed))
        if current:
            blocks.append(("Current instruction", current))
        reserve = "\n\n".join(f"{k}:\n{v}" for k, v in blocks)
        remaining = max(0, limit - len(reserve) - (2 if reserve else 0))
        if prev and remaining > 120:
            prev = prev[-remaining:]
            blocks.insert(1 if original else 0, ("Previous step context", prev))
        text = "\n\n".join(f"{k}:\n{v}" for k, v in blocks).strip()
        return text if text else raw[-limit:]

    def _iter_stream_chat(
        self,
        *,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temp: float,
    ):
        model = self.core.chat_llm
        if not hasattr(model, "stream_chat"):
            raise RuntimeError("stream_chat_unavailable")
        fn = getattr(model, "stream_chat")
        # Try progressively simpler signatures for broad model compatibility.
        candidates = [
            {"messages": messages, "max_new_tokens": max_tokens, "temperature": temp, "top_p": 0.95, "token_chunk_size": 1},
            {"messages": messages, "max_new_tokens": max_tokens, "temperature": temp, "top_p": 0.95},
            {"messages": messages, "max_new_tokens": max_tokens, "temperature": temp},
            {"messages": messages, "max_new_tokens": max_tokens},
            {"messages": messages},
        ]
        last_exc: Exception | None = None
        for kwargs in candidates:
            try:
                out = fn(**kwargs)
                if inspect.isgenerator(out) or hasattr(out, "__iter__"):
                    return out
            except TypeError as exc:
                last_exc = exc
                continue
            except Exception as exc:
                last_exc = exc
                continue
        raise RuntimeError(f"stream_chat_invocation_failed:{last_exc}")

    def _chat_with_optional_cancel(
        self,
        *,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temp: float,
        cancel_cb: Any = None,
    ) -> Any:
        model = self.core.chat_llm
        if model is None:
            raise RuntimeError("chat_model_unavailable")
        fn = getattr(model, "chat", None)
        if not callable(fn):
            raise RuntimeError("chat_unavailable")
        candidates = [
            {
                "messages": messages,
                "max_new_tokens": max_tokens,
                "temperature": temp,
                "top_p": 0.95,
                "cancel_cb": cancel_cb,
            },
            {
                "messages": messages,
                "max_new_tokens": max_tokens,
                "temperature": temp,
                "top_p": 0.95,
            },
            {
                "messages": messages,
                "max_new_tokens": max_tokens,
                "temperature": temp,
            },
            {"messages": messages, "max_new_tokens": max_tokens},
            {"messages": messages},
        ]
        last_exc: Exception | None = None
        for kwargs in candidates:
            try:
                return fn(**kwargs)
            except TypeError as exc:
                last_exc = exc
                continue
            except Exception as exc:
                last_exc = exc
                continue
        raise RuntimeError(f"chat_invocation_failed:{last_exc}")

    def handle(self, req: Any) -> Any:
        deck_runner = None
        if self.core.chat_llm is None:
            try:
                resolver = (self.core.settings or {}).get("__resolve_chat_model")
                if callable(resolver):
                    self.core.chat_llm = resolver()
            except Exception:
                pass

        ext = getattr(req, "ext", None)
        settings: Dict[str, Any] = dict(self.core.settings or {})
        if isinstance(ext, dict):
            rps = ext.get("router_plugin_settings")
            if isinstance(rps, dict):
                route_settings = rps.get(self.route_id)
                if isinstance(route_settings, dict):
                    settings.update(route_settings)
            direct_settings = ext.get(f"{self.route_id}_settings")
            if isinstance(direct_settings, dict):
                settings.update(direct_settings)
        max_tokens_source = "agent_workflow_member_max_tokens"
        max_tokens_raw = settings.get("agent_workflow_member_max_tokens")
        if max_tokens_raw in (None, "", 0, "0"):
            max_tokens_raw = settings.get("max_tokens")
            max_tokens_source = "max_tokens"
        if max_tokens_raw in (None, "", 0, "0"):
            max_tokens_raw = 2048
            max_tokens_source = "default_2048"
        max_tokens = int(max_tokens_raw)
        temp = float(settings.get("agent_workflow_member_temperature", 0.1))

        node: Dict[str, Any] = {}
        if isinstance(ext, dict) and isinstance(ext.get("agent_flow_node"), dict):
            node = dict(ext.get("agent_flow_node") or {})
        plugin_settings = (node.get("plugin_settings") or {}) if isinstance(node.get("plugin_settings"), dict) else {}
        stream_tokens = bool(plugin_settings.get("member_token_stream", True))
        stream_max_seconds = int(
            plugin_settings.get("member_stream_max_seconds")
            or settings.get("agent_workflow_member_stream_max_seconds")
            or 75
        )

        role = str(
            plugin_settings.get("member_role")
            or node.get("agent_kind")
            or node.get("label")
            or "workflow specialist"
        ).strip()
        role_norm = self._normalize_role(role)
        if role_norm:
            role = role_norm
        else:
            inferred = self._infer_role_from_label(str(node.get("label") or ""))
            if inferred:
                role = inferred
        system_prompt = str(node.get("system_prompt") or "").strip()
        if not system_prompt:
            system_prompt = (
                f"You are the {role}. "
                "Work on your assigned step and produce concise structured output for the next node."
            )

        user_text = self._extract_user_text(req)
        node_context_chars = int(plugin_settings.get("member_context_chars") or 0)
        if node_context_chars > 0 and len(user_text) > node_context_chars:
            user_text = self._truncate_structured_context(user_text, node_context_chars)
        self._emit_diag({"member_stream": f"{self._role_display(role)}: starting analysis"})
        handoff = str(((node.get("plugin_settings") or {}).get("handoff_format") or "concise_structured")).strip()
        output_protocol = str(((node.get("plugin_settings") or {}).get("output_protocol") or "auto")).strip().lower()
        changed_files_runtime: List[str] = []
        if isinstance(ext, dict) and isinstance(ext.get("agent_flow_changed_files"), list):
            changed_files_runtime = [
                str(x or "").strip()
                for x in (ext.get("agent_flow_changed_files") or [])
                if str(x or "").strip()
            ]
        self._emit_diag(
            {
                "member_stream": (
                    f"{self._role_display(role)}: config: "
                    f"max_tokens={max_tokens} "
                    f"max_tokens_source={max_tokens_source} "
                    f"n_ctx={self._infer_n_ctx()} "
                    f"output_protocol={output_protocol or 'auto'} "
                    f"context_chars={node_context_chars or 'global'} "
                    f"stream_tokens={bool(stream_tokens)} "
                    f"changed_files={len(changed_files_runtime)}"
                )
            }
        )

        allowed_skills = plugin_settings.get("action_skills")
        if not isinstance(allowed_skills, list):
            allowed_skills = []
        allowed_skills = [str(x).strip() for x in allowed_skills if str(x).strip()]
        category_skills = self._expand_skill_categories(plugin_settings.get("action_skill_categories"))
        if not allowed_skills:
            allowed_skills = self._default_skills_for_role(role)
        if category_skills:
            allowed_skills = sorted(set(allowed_skills + category_skills))

        node_type = str(plugin_settings.get("node_type") or "").strip().lower()
        tool_config = plugin_settings.get("tool_config") if isinstance(plugin_settings.get("tool_config"), dict) else {}
        configured_tool = str(tool_config.get("tool") or "").strip()
        if not configured_tool and len(allowed_skills) == 1:
            configured_tool = str(allowed_skills[0] or "").strip()
        if node_type == "tool_node" and configured_tool:
            request_seed = str(original_request or user_text or "").strip()
            merged_params: Dict[str, Any] = {}
            cfg_params = tool_config.get("params") if isinstance(tool_config.get("params"), dict) else {}
            fallback_params = tool_config.get("fallback_params") if isinstance(tool_config.get("fallback_params"), dict) else {}
            merged_params.update(dict(cfg_params))
            merged_params.update(dict(fallback_params))
            params_from_input = tool_config.get("params_from_input") if isinstance(tool_config.get("params_from_input"), list) else []
            file_hint = ""
            if request_seed:
                m = re.search(
                    r"([A-Za-z]:[/\\\\][^\s\"']+\.(?:xlsx|xlsm|xls|csv|tsv|pdf|json|txt|js|ts|py|png|jpg|jpeg|webp|bmp|tif|tiff)|/[^\\s\"']+\.(?:xlsx|xlsm|xls|csv|tsv|pdf|json|txt|js|ts|py|png|jpg|jpeg|webp|bmp|tif|tiff)|[A-Za-z0-9_.\\/-]+\.(?:xlsx|xlsm|xls|csv|tsv|pdf|json|txt|js|ts|py|png|jpg|jpeg|webp|bmp|tif|tiff))",
                    request_seed,
                    flags=re.IGNORECASE,
                )
                if m:
                    file_hint = str(m.group(1) or "").strip().strip("'\"")
            step_input = node.get("input") if isinstance(node.get("input"), dict) else {}
            ext_dict = ext if isinstance(ext, dict) else {}
            prev_reports = []
            for report_key in ("agent_flow_previous_step_report_with_tools", "agent_flow_previous_step_report"):
                report_val = ext_dict.get(report_key)
                if isinstance(report_val, dict):
                    prev_reports.append(report_val)

            def _recover_param_from_prior_tools(name: str) -> Any:
                key = str(name or "").strip()
                if not key:
                    return None
                for report in prev_reports:
                    rows = report.get("tool_results") if isinstance(report.get("tool_results"), list) else []
                    for row in reversed(rows):
                        if not isinstance(row, dict):
                            continue
                        data = row.get("data") if isinstance(row.get("data"), dict) else {}
                        if key in data and data.get(key) not in (None, "", [], {}):
                            return data.get(key)
                        if key in row and row.get(key) not in (None, "", [], {}):
                            return row.get(key)
                return None

            for pkey0 in params_from_input:
                pkey = str(pkey0 or "").strip()
                if not pkey:
                    continue
                if pkey == "text":
                    if configured_tool == "result.text":
                        for alt_key in ("finalized_text", "execution_text", "response", "final_answer", "summary", "text"):
                            prior_value = _recover_param_from_prior_tools(alt_key)
                            if prior_value not in (None, "", [], {}):
                                merged_params[pkey] = prior_value
                                break
                        if pkey in merged_params:
                            continue
                    sourced = False
                    for source in (step_input, ext_dict):
                        if isinstance(source, dict) and source.get(pkey) not in (None, "", [], {}):
                            merged_params[pkey] = source.get(pkey)
                            sourced = True
                            break
                    if not sourced:
                        prior_value = _recover_param_from_prior_tools(pkey)
                        if prior_value not in (None, "", [], {}):
                            merged_params[pkey] = prior_value
                            sourced = True
                    if not sourced:
                        merged_params[pkey] = request_seed
                    continue
                if pkey in {"current_request_text", "request_text", "user_request", "request", "prompt", "query"}:
                    merged_params[pkey] = request_seed
                    continue
                for source in (ext_dict, step_input):
                    if isinstance(source, dict) and source.get(pkey) not in (None, "", [], {}):
                        merged_params[pkey] = source.get(pkey)
                        break
                if pkey not in merged_params:
                    prior_value = _recover_param_from_prior_tools(pkey)
                    if prior_value not in (None, "", [], {}):
                        merged_params[pkey] = prior_value
                if pkey not in merged_params and pkey in {"file", "path", "file_path", "input_path", "source_pdf_path"} and file_hint:
                    merged_params[pkey] = file_hint
            tool_results: List[Dict[str, Any]] = []
            temp_skill_dirs = []
            if isinstance(ext, dict) and isinstance(ext.get("agent_flow_temp_skill_dirs"), list):
                temp_skill_dirs = [str(x or "").strip() for x in (ext.get("agent_flow_temp_skill_dirs") or []) if str(x or "").strip()]
            reg_row: Dict[str, Any] | None = None
            if temp_skill_dirs:
                try:
                    from plugins.gui_helpers.agent_flow.skills import build_agent_flow_tool_registry

                    app_obj = getattr(req, "app", None)
                    if app_obj is not None:
                        built = build_agent_flow_tool_registry(app_obj, extra_skill_dirs=temp_skill_dirs)
                        reg = built.get("registry") if isinstance(built, dict) else None
                        if reg is not None and hasattr(reg, "call_tool"):
                            reg_row = reg.call_tool(
                                configured_tool,
                                {"app": app_obj, "pid": getattr(req, "pid", ""), "sid": getattr(req, "sid", ""), "ext": dict(ext or {}), "user_text": request_seed, "original_request": request_seed},
                                merged_params,
                            )
                except Exception:
                    reg_row = None
            if isinstance(reg_row, dict):
                tool_results = [{
                    "skill": configured_tool,
                    "ok": bool(reg_row.get("ok")) if "ok" in reg_row else True,
                    "warnings": list(reg_row.get("warnings") or []) if isinstance(reg_row.get("warnings"), list) else [],
                    "data": dict(reg_row.get("data") or {}) if isinstance(reg_row.get("data"), dict) else {},
                }]
                for k, v in reg_row.items():
                    if k in {"ok", "warnings", "data", "error"}:
                        continue
                    if k not in tool_results[0]["data"]:
                        tool_results[0]["data"][k] = v
            else:
                tool_results = self._run_tool_calls(
                    [{"skill": configured_tool, "reason": "Execute configured tool-node action.", "params": merged_params}],
                    allowed_skills or [configured_tool],
                    req,
                )
            first_ok = next((row for row in tool_results if isinstance(row, dict) and row.get("ok")), None)
            first_row = first_ok or (tool_results[0] if tool_results else {})
            data0 = first_row.get("data") if isinstance(first_row, dict) and isinstance(first_row.get("data"), dict) else {}
            response_text = str(
                data0.get("finalized_text")
                or data0.get("response")
                or data0.get("final_answer")
                or data0.get("summary")
                or data0.get("text")
                or first_row.get("text")
                or first_row.get("summary")
                or ""
            ).strip()
            summary = str(data0.get("summary") or response_text or f"Executed {configured_tool}.").strip()
            return {
                "ok": bool(first_ok or (tool_results and first_row.get("ok"))),
                "text": response_text,
                "tool_results": tool_results,
                "activity": {
                    "role": self._role_display(role),
                    "did": summary,
                    "plan": f"Execute configured tool node: {configured_tool}",
                    "analysis": "",
                    "response": response_text,
                    "bugs": [],
                    "fixes": [],
                    "actions": [f"tool_node:{configured_tool}"],
                    "skills_invoked": [configured_tool],
                    "handoff": response_text or summary,
                },
            }

        skill_clause = (
            "No action skills are enabled for this node."
            if not allowed_skills
            else "Allowed action skills: " + ", ".join(allowed_skills)
        )
        original_request = self._extract_original_request(user_text)
        request_low = str(original_request or user_text or "").lower()
        target_path_hint = self._extract_target_path(user_text)
        create_intent = bool(re.search(r"\b(create|generate|build|implement|write|make|develop)\b", request_low))
        edit_intent = bool(re.search(r"\b(add|update|modify|change|edit|fix|improve|patch|refactor|rename|support)\b", request_low))
        repo_scope_intent = bool(
            target_path_hint
            or re.search(r"\b(repo|repository|codebase|plugin|plugins|folder|directory|file|files)\b", request_low)
        )
        write_capable = any(s in allowed_skills for s in ["repo.write", "code.apply_patch"])
        build_role = role in {"coder", "staff_engineer", "gui_designer"}
        no_files_written_yet = not bool(changed_files_runtime)
        standalone_artifact_mode = bool(create_intent and not edit_intent and not repo_scope_intent)
        execution_clause = ""
        if write_capable and build_role and (create_intent or edit_intent):
            if repo_scope_intent:
                execution_clause = (
                    "- This request targets an existing repo, plugin, folder, or file.\n"
                    "- You MUST inspect the requested repo area first using repo tools before changing code.\n"
                    "- Prefer precise edits to existing files over creating standalone artifacts.\n"
                    "- If modifying code, emit write-capable tool calls (`repo.write` or `code.apply_patch`) against the real repo files.\n"
                    "- Do NOT create placeholder artifacts like `artifact.txt` for repo-edit requests.\n"
                    "- Do NOT invent a new root `index.html` unless the user explicitly asked for a new file.\n"
                )
            else:
                execution_clause = (
                    "- This is a create/build request and your role is part of implementation.\n"
                    "- You MUST emit at least one write-capable tool call (`repo.write` or `code.apply_patch`).\n"
                    "- Do NOT return only `repo.read` or verification-only actions when no artifact exists yet.\n"
                    "- If creating a file, create it directly instead of claiming it already exists.\n"
                    "- Prefer `code.apply_patch` over `repo.write` for large file creation.\n"
                    "- For large files, use one `write` op followed by multiple `append` ops instead of one giant content string.\n"
                    "- Keep each `content` chunk reasonably small.\n"
                    "- For large file output, prefer the TAGGED protocol instead of JSON tool_calls.\n"
                )
        elif create_intent and no_files_written_yet and role in {"qa", "security", "docs", "release", "architect"}:
            execution_clause = (
                "- No artifact has been written yet.\n"
                "- Do NOT claim to verify or inspect a file that has not been created.\n"
                "- If blocked, state that implementation must create the artifact first.\n"
            )

        protocol_clause = ""
        protocol_output_contract = ""
        if output_protocol == "tagged":
            protocol_clause = (
                "- You MUST use the TAGGED protocol for structured output in this node.\n"
                "- Do NOT emit JSON tool_calls unless recovery is absolutely necessary.\n"
            )
            protocol_output_contract = (
                "- Use TAGGED protocol for structured output:\n"
                "  <<<AW_SUMMARY>>>\n...\n<<<END_AW_SUMMARY>>>\n"
                "  <<<AW_PLAN>>>\n...\n<<<END_AW_PLAN>>>\n"
                "  <<<AW_ANALYSIS>>>\n...\n<<<END_AW_ANALYSIS>>>\n"
                "  <<<AW_RESPONSE>>>\n...\n<<<END_AW_RESPONSE>>>\n"
                "  <<<AW_ACTIONS>>>\n- item\n<<<END_AW_ACTIONS>>>\n"
                "  <<<AW_HANDOFF>>>\n...\n<<<END_AW_HANDOFF>>>\n"
                "  <<<AW_TOOL_CALL>>>\nskill: code.apply_patch\nreason: ...\npath: relative/file.html\nop: write\n<<<AW_CONTENT>>>\nraw file content here\n<<<END_AW_CONTENT>>>\n<<<END_AW_TOOL_CALL>>>\n"
                "- For large files, emit additional <<<AW_TOOL_CALL>>> blocks with op: append.\n"
                "- Do not wrap tagged output in markdown fences.\n"
            )
        elif output_protocol == "json":
            protocol_clause = (
                "- Use STRICT JSON for structured output in this node.\n"
            )
            protocol_output_contract = (
                "- Return STRICT JSON:\n"
                "  {\"plan\":\"...\",\"analysis\":\"...\",\"response\":\"...\",\"summary\":\"...\",\"bugs\":[...],\"fixes\":[...],\"actions\":[...],\"tool_calls\":[{\"skill\":\"name\",\"reason\":\"why needed\",\"params\":{}}],\"handoff\":\"...\"}\n"
                "- Return ONLY the JSON object when emitting tool_calls; do not wrap it in prose or markdown fences.\n"
                "- Escape all newlines and quotes inside JSON string values.\n"
            )
        else:
            protocol_clause = (
                "- Use TAGGED protocol for large artifact creation; otherwise JSON is acceptable.\n"
            )
            protocol_output_contract = (
                "- If you need a skill call, JSON is accepted:\n"
                "  {\"plan\":\"...\",\"analysis\":\"...\",\"response\":\"...\",\"summary\":\"...\",\"bugs\":[...],\"fixes\":[...],\"actions\":[...],\"tool_calls\":[{\"skill\":\"name\",\"reason\":\"why needed\",\"params\":{}}],\"handoff\":\"...\"}\n"
                "- Alternative accepted format for large artifacts is TAGGED protocol:\n"
                "  <<<AW_SUMMARY>>>\n...\n<<<END_AW_SUMMARY>>>\n"
                "  <<<AW_PLAN>>>\n...\n<<<END_AW_PLAN>>>\n"
                "  <<<AW_ANALYSIS>>>\n...\n<<<END_AW_ANALYSIS>>>\n"
                "  <<<AW_RESPONSE>>>\n...\n<<<END_AW_RESPONSE>>>\n"
                "  <<<AW_ACTIONS>>>\n- item\n<<<END_AW_ACTIONS>>>\n"
                "  <<<AW_HANDOFF>>>\n...\n<<<END_AW_HANDOFF>>>\n"
                "  <<<AW_TOOL_CALL>>>\nskill: code.apply_patch\nreason: ...\npath: relative/file.html\nop: write\n<<<AW_CONTENT>>>\nraw file content here\n<<<END_AW_CONTENT>>>\n<<<END_AW_TOOL_CALL>>>\n"
                "- Return ONLY the JSON object when emitting tool_calls; do not wrap it in prose or markdown fences.\n"
                "- Escape all newlines and quotes inside JSON string values.\n"
            )

        system = (
            f"{system_prompt}\n\n"
            "Output contract:\n"
            "- Include `plan:` one short line.\n"
            "- Include `analysis:` one short line.\n"
            "- Include `response:` one short line.\n"
            "- Start with `summary:` one short line.\n"
            "- Include `bugs:` with concrete findings when relevant.\n"
            "- Include `fixes:` with what will be changed/fixed.\n"
            "- Include `actions:` with 1-5 concrete bullets.\n"
            "- Include `handoff:` with what the next node needs.\n"
            f"- Handoff format preference: {handoff}\n"
            f"- {skill_clause}\n"
            f"{protocol_output_contract}"
            "- For file creation/edit skills use `params.path`, not `file_path`.\n"
            "- Use only allowed skills.\n"
            "- If this node is responsible for coding/building and `code.apply_patch` is allowed, you MUST emit tool_calls that create/modify files instead of only prose.\n"
            f"{protocol_clause}"
            f"{execution_clause}"
            "- Keep output plain text."
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ]
        cancel_cb = settings.get("__cancel_cb")
        def _is_canceled() -> bool:
            try:
                return bool(callable(cancel_cb) and cancel_cb())
            except Exception:
                return False
        text = ""
        try:
            if _is_canceled():
                return {"route_id": self.route_id, "ok": False, "error": "canceled"}
            if stream_tokens:
                parts: List[str] = []
                stream_started_at = time.monotonic()
                self._emit_diag({"member_stream": f"{self._role_display(role)}: token stream enabled"})
                if self.core.chat_llm is None:
                    deck_runner = ModelDeckRunner(
                        core=self.core,
                        settings=dict(self.core.settings or {}),
                        model_type="text_llm",
                        slot=f"{self.route_id}_stream",
                        prefer_worker=False,
                    )
                    if getattr(deck_runner, "error", None):
                        raise RuntimeError(f"chat_model_unavailable:{deck_runner.error}")
                    def _on_piece(piece: str) -> None:
                        nonlocal parts
                        if _is_canceled():
                            return
                        if stream_max_seconds > 0 and (time.monotonic() - stream_started_at) >= stream_max_seconds:
                            return
                        p = str(piece or "")
                        if not p:
                            return
                        parts.append(p)
                        self._emit_diag({"member_model_stream": {"text": p}})
                    sres = deck_runner.stream(
                        messages=messages,
                        params={
                            "max_new_tokens": max_tokens,
                            "temperature": temp,
                            "top_p": 0.95,
                            "token_chunk_size": 1,
                            "cancel_cb": cancel_cb,
                        },
                        token_cb=_on_piece,
                    )
                    if not isinstance(sres, dict) or not sres.get("ok"):
                        raise RuntimeError(f"stream_failed:{(sres or {}).get('error') if isinstance(sres, dict) else sres}")
                    raw = str((sres or {}).get("raw") or "").strip()
                    if raw and not parts:
                        parts.append(raw)
                        self._emit_diag({"member_model_stream": {"text": raw}})
                else:
                    for piece in self._iter_stream_chat(
                        messages=messages,
                        max_tokens=max_tokens,
                        temp=temp,
                    ):
                        if _is_canceled():
                            break
                        if stream_max_seconds > 0 and (time.monotonic() - stream_started_at) >= stream_max_seconds:
                            self._emit_diag({"member_stream": f"{self._role_display(role)}: stream guard reached ({stream_max_seconds}s); finalizing node"})
                            break
                        p = str(piece or "")
                        if not p:
                            continue
                        parts.append(p)
                        self._emit_diag({"member_model_stream": {"text": p}})
                if _is_canceled():
                    return {"route_id": self.route_id, "ok": False, "error": "canceled"}
                text = "".join(parts).strip()
            else:
                hidden_stream_parts: List[str] = []
                hidden_stream_started_at = time.monotonic()
                hidden_stream_timed_out = False
                if stream_max_seconds > 0:
                    try:
                        if self.core.chat_llm is None:
                            deck_runner = ModelDeckRunner(
                                core=self.core,
                                settings=dict(self.core.settings or {}),
                                model_type="text_llm",
                                slot=f"{self.route_id}_chat",
                                prefer_worker=False,
                            )
                            if getattr(deck_runner, "error", None):
                                return {"route_id": self.route_id, "ok": False, "error": f"chat_model_unavailable:{deck_runner.error}"}
                            def _on_hidden_piece(piece: str) -> None:
                                nonlocal hidden_stream_parts
                                if _is_canceled():
                                    return
                                if stream_max_seconds > 0 and (time.monotonic() - hidden_stream_started_at) >= stream_max_seconds:
                                    return
                                p = str(piece or "")
                                if p:
                                    hidden_stream_parts.append(p)
                            sres = deck_runner.stream(
                                messages=messages,
                                params={
                                    "max_new_tokens": max_tokens,
                                    "temperature": temp,
                                    "top_p": 0.95,
                                    "token_chunk_size": 1,
                                    "cancel_cb": cancel_cb,
                                },
                                token_cb=_on_hidden_piece,
                            )
                            if isinstance(sres, dict) and sres.get("ok"):
                                raw = str((sres or {}).get("raw") or "").strip()
                                if raw and not hidden_stream_parts:
                                    hidden_stream_parts.append(raw)
                        else:
                            for piece in self._iter_stream_chat(
                                messages=messages,
                                max_tokens=max_tokens,
                                temp=temp,
                            ):
                                if _is_canceled():
                                    break
                                if stream_max_seconds > 0 and (time.monotonic() - hidden_stream_started_at) >= stream_max_seconds:
                                    hidden_stream_timed_out = True
                                    break
                                p = str(piece or "")
                                if p:
                                    hidden_stream_parts.append(p)
                        if hidden_stream_timed_out:
                            self._emit_diag({"member_stream": f"{self._role_display(role)}: hidden stream guard reached ({stream_max_seconds}s); finalizing node"})
                        text = "".join(hidden_stream_parts).strip()
                    except Exception:
                        text = ""
                if not text:
                    if self.core.chat_llm is None:
                        if deck_runner is None:
                            deck_runner = ModelDeckRunner(
                                core=self.core,
                                settings=dict(self.core.settings or {}),
                                model_type="text_llm",
                                slot=f"{self.route_id}_chat",
                                prefer_worker=False,
                            )
                        if getattr(deck_runner, "error", None):
                            return {"route_id": self.route_id, "ok": False, "error": f"chat_model_unavailable:{deck_runner.error}"}
                        pres = deck_runner.plan(
                            messages=messages,
                            params={
                                "max_new_tokens": max_tokens,
                                "temperature": temp,
                                "top_p": 0.95,
                                "cancel_cb": cancel_cb,
                            },
                        )
                        if not isinstance(pres, dict) or not pres.get("ok"):
                            return {"route_id": self.route_id, "ok": False, "error": f"model_error:{(pres or {}).get('error') if isinstance(pres, dict) else pres}"}
                        text = self._extract_text((pres or {}).get("raw", "")).strip()
                    else:
                        if _is_canceled():
                            return {"route_id": self.route_id, "ok": False, "error": "canceled"}
                        resp = self._chat_with_optional_cancel(
                            messages=messages,
                            max_tokens=max_tokens,
                            temp=temp,
                            cancel_cb=cancel_cb,
                        )
                        text = self._extract_text(resp).strip()
            self._emit_diag({"member_stream": f"{self._role_display(role)}: model response received"})
        except Exception as exc:
            # Fallback to non-streaming chat when stream path is requested but unavailable.
            if stream_tokens:
                self._emit_diag({"member_stream": f"{self._role_display(role)}: token stream fallback to chat ({exc})"})
                try:
                    if _is_canceled():
                        return {"route_id": self.route_id, "ok": False, "error": "canceled"}
                    resp = self._chat_with_optional_cancel(
                        messages=messages,
                        max_tokens=max_tokens,
                        temp=temp,
                        cancel_cb=cancel_cb,
                    )
                    text = self._extract_text(resp).strip()
                    self._emit_diag({"member_stream": f"{self._role_display(role)}: model response received"})
                except Exception as exc2:
                    return {"route_id": self.route_id, "ok": False, "error": f"model_error:{exc2}"}
            else:
                return {"route_id": self.route_id, "ok": False, "error": f"model_error:{exc}"}
        finally:
            if deck_runner is not None:
                try:
                    deck_runner.close()
                except Exception:
                    pass
        if output_protocol == "tagged" and "<<<AW_" not in str(text or ""):
            self._emit_diag({"member_stream": f"{self._role_display(role)}: rewriting output to tagged protocol"})
            text = self._rewrite_to_tagged_protocol(messages, text, max_tokens=max_tokens, temp=temp)
        if text:
            preview_text = text
            if output_protocol == "tagged":
                preview_text = self._extract_tagged_block(text, "AW_SUMMARY") or self._extract_tagged_block(text, "AW_PLAN") or text
            self._emit_diag(
                {
                    "member_model_response": {
                        "text": str(preview_text or "")[:2000],
                        "truncated": len(str(preview_text or "")) > 2000,
                    }
                }
            )
        parsed = self._extract_tagged_protocol(text)
        if parsed is None:
            parsed = self._extract_json_block(text)
        if parsed is None:
            complete_json, truncated_json = self._json_completion_state(text)
            if truncated_json and not complete_json:
                self._emit_diag({"member_stream": f"{self._role_display(role)}: continuing truncated JSON payload"})
                text = self._continue_truncated_json(messages, text, max_tokens=max_tokens, temp=temp)
                parsed = self._extract_tagged_protocol(text)
                if parsed is None:
                    parsed = self._extract_json_block(text)
        if parsed is None and ("tool_calls" in str(text or "") or str(text or "").lstrip().startswith("{")):
            self._emit_diag({"member_stream": f"{self._role_display(role)}: repairing invalid tool-call payload"})
            repaired = self._repair_tool_call_payload(messages, text, allowed_skills, max_tokens=max_tokens)
            if isinstance(repaired, dict):
                parsed = repaired
        tool_results: List[Dict[str, Any]] = []
        summary = ""
        plan_text = ""
        analysis_text = ""
        response_text = ""
        bug_findings: List[str] = []
        fix_plan: List[str] = []
        actions: List[str] = []
        handoff_text = ""
        desired_artifact_path = ""
        deferred_repo_paths: List[str] = []
        if isinstance(parsed, dict):
            calls, schema_errors = self._normalize_tool_calls(parsed.get("tool_calls"), allowed_skills)
            for c0 in calls:
                if not isinstance(c0, dict):
                    continue
                p0 = c0.get("params") if isinstance(c0.get("params"), dict) else {}
                if str(c0.get("skill") or "").strip() == "code.apply_patch":
                    ops0 = p0.get("ops") if isinstance(p0, dict) else None
                    if isinstance(ops0, list) and ops0:
                        first_op = ops0[0] if isinstance(ops0[0], dict) else {}
                        cand = str(first_op.get("path") or "").strip()
                        if cand:
                            desired_artifact_path = cand.replace("\\", "/")
                            break
                    cand = str(p0.get("path") or "").strip()
                    if cand:
                        desired_artifact_path = cand.replace("\\", "/")
                        break
                cand = str(p0.get("path") or p0.get("target") or p0.get("file_path") or "").strip()
                if cand:
                    desired_artifact_path = cand.replace("\\", "/")
                    break
            if schema_errors and isinstance(parsed.get("tool_calls"), list):
                repaired = self._repair_tool_call_payload(messages, text, allowed_skills, max_tokens=max_tokens)
                if isinstance(repaired, dict):
                    parsed = repaired
                    calls, schema_errors = self._normalize_tool_calls(parsed.get("tool_calls"), allowed_skills)
            if calls:
                if repo_scope_intent:
                    safe_calls: List[Dict[str, Any]] = []
                    dropped = 0
                    for c in calls:
                        if self._is_risky_repo_full_write_call(c):
                            params_c = c.get("params") if isinstance(c.get("params"), dict) else {}
                            path_c = ""
                            if str(c.get("skill") or "").strip() == "code.apply_patch":
                                ops_c = params_c.get("ops") if isinstance(params_c.get("ops"), list) else []
                                for op_c in ops_c:
                                    if not isinstance(op_c, dict):
                                        continue
                                    path_c = str(op_c.get("path") or "").strip().replace("\\", "/")
                                    if path_c:
                                        break
                            else:
                                path_c = str(params_c.get("path") or params_c.get("target") or params_c.get("file_path") or "").strip().replace("\\", "/")
                            if create_intent and not edit_intent and path_c:
                                safe_calls.append(c)
                                continue
                            if path_c:
                                deferred_repo_paths.append(path_c)
                            dropped += 1
                            continue
                        safe_calls.append(c)
                    if dropped:
                        self._emit_diag({"member_stream": f"{self._role_display(role)}: deferred {dropped} risky full-file repo write call(s) in favor of safer fallback editing"})
                    calls = safe_calls
                call_items: List[Dict[str, Any]] = []
                for c in calls:
                    if not isinstance(c, dict):
                        continue
                    call_items.append(
                        {
                            "skill": str(c.get("skill") or ""),
                            "reason": str(c.get("reason") or c.get("why") or "").strip(),
                            "params": dict(c.get("params") or {}),
                        }
                    )
                self._emit_diag(
                    {
                        "member_stream": f"{self._role_display(role)}: invoking {len(calls)} skill call(s)",
                        "member_skill_calls": call_items,
                    }
                )
                tool_results = self._run_tool_calls(calls, allowed_skills, req)
                tool_results = self._merge_repo_read_chunks(tool_results, allowed_skills, req)
                # Emit focused OCR diagnostics from actual tool results so logs reflect real execution, not model narration.
                for tr in tool_results:
                    if not isinstance(tr, dict):
                        continue
                    if str(tr.get("skill") or "").strip() != "pdf.read_visual_labels":
                        continue
                    data_tr = tr.get("data") if isinstance(tr.get("data"), dict) else {}
                    diag = data_tr.get("diagnostics") if isinstance(data_tr.get("diagnostics"), dict) else {}
                    self._emit_diag(
                        {
                            "member_stream": (
                                f"{self._role_display(role)}: OCR diagnostics "
                                f"status={diag.get('ocr_status')} "
                                f"engine={diag.get('ocr_engine')} "
                                f"version={diag.get('ocr_engine_version')} "
                                f"attempted={diag.get('ocr_pages_attempted')} "
                                f"succeeded={diag.get('ocr_pages_succeeded')}"
                            ),
                            "member_ocr_diagnostics": {
                                "ok": bool(tr.get("ok")),
                                "warnings": tr.get("warnings") if isinstance(tr.get("warnings"), list) else [],
                                "error": tr.get("error"),
                                "diagnostics": diag,
                            },
                        }
                    )
                # If model produced structured response, preserve a readable handoff.
                summary = str(parsed.get("summary") or "").strip()
                plan_text = str(parsed.get("plan") or "").strip()
                analysis_text = str(parsed.get("analysis") or "").strip()
                response_text = str(parsed.get("response") or "").strip()
                bug_findings = [str(x) for x in (parsed.get("bugs") or []) if str(x).strip()] if isinstance(parsed.get("bugs"), list) else []
                fix_plan = [str(x) for x in (parsed.get("fixes") or []) if str(x).strip()] if isinstance(parsed.get("fixes"), list) else []
                actions = [str(a) for a in (parsed.get("actions") or []) if str(a).strip()] if isinstance(parsed.get("actions"), list) else []
                handoff_text = str(parsed.get("handoff") or "").strip()
                lines: List[str] = []
                if summary:
                    lines.append(f"summary: {summary}")
                if actions:
                    lines.append("actions:")
                    for a in actions[:8]:
                        lines.append(f"- {str(a)}")
                if tool_results:
                    lines.append("skill_results:")
                    for tr in tool_results[:8]:
                        if not isinstance(tr, dict):
                            continue
                        compact = {
                            "skill": tr.get("skill"),
                            "ok": bool(tr.get("ok")),
                            "data": tr.get("data") if isinstance(tr.get("data"), dict) else {},
                            "warnings": tr.get("warnings") if isinstance(tr.get("warnings"), list) else [],
                            "error": tr.get("error"),
                        }
                        try:
                            lines.append("- " + json.dumps(compact, ensure_ascii=False, default=str))
                        except Exception:
                            lines.append(f"- {tr.get('skill')}: ok={tr.get('ok')} data={tr.get('data')} warnings={tr.get('warnings')}")
                        data0 = tr.get("data") if isinstance(tr.get("data"), dict) else {}
                        if isinstance(data0, dict):
                            if "value" in data0:
                                lines.append(f"  result_value: {data0.get('value')}")
                            elif "row_count" in data0:
                                lines.append(f"  result_row_count: {data0.get('row_count')}")
                            elif isinstance(data0.get("records"), list) and len(data0.get("records")) == 1:
                                r0 = data0.get("records")[0]
                                if isinstance(r0, dict):
                                    for kk, vv in r0.items():
                                        if isinstance(vv, (int, float, str)):
                                            lines.append(f"  result_record_{kk}: {vv}")
                                            break
                if handoff_text:
                    lines.append(f"handoff: {handoff_text}")
                if lines:
                    text = "\n".join(lines).strip()
                self._emit_diag({"member_stream": f"{self._role_display(role)}: skill invocation complete"})
            elif schema_errors:
                # keep deterministic user-visible indication when strict schema was requested but invalid
                text = (text + "\n\nschema_error: invalid_tool_calls_payload").strip()
            else:
                summary = str(parsed.get("summary") or "").strip()
                plan_text = str(parsed.get("plan") or "").strip()
                analysis_text = str(parsed.get("analysis") or "").strip()
                response_text = str(parsed.get("response") or "").strip()
                bug_findings = [str(x) for x in (parsed.get("bugs") or []) if str(x).strip()] if isinstance(parsed.get("bugs"), list) else []
                fix_plan = [str(x) for x in (parsed.get("fixes") or []) if str(x).strip()] if isinstance(parsed.get("fixes"), list) else []
                actions = [str(a) for a in (parsed.get("actions") or []) if str(a).strip()] if isinstance(parsed.get("actions"), list) else []
                handoff_text = str(parsed.get("handoff") or "").strip()

        if tool_results:
            recovered_rows = self._recover_missing_repo_reads(tool_results, allowed_skills, req)
            if recovered_rows:
                tool_results.extend(recovered_rows)
                tool_results = self._merge_repo_read_chunks(tool_results, allowed_skills, req)

        tool_ok = any(bool((tr or {}).get("ok")) for tr in tool_results if isinstance(tr, dict))
        write_ok = any(
            isinstance(tr, dict)
            and bool(tr.get("ok"))
            and (
                str(tr.get("skill") or "").strip() in {"repo.write", "code.apply_patch", "pdf.fill_form_fields"}
                or bool((tr.get("data") if isinstance(tr.get("data"), dict) else {}).get("changed_files"))
                or bool((tr.get("data") if isinstance(tr.get("data"), dict) else {}).get("output_path"))
            )
            for tr in tool_results
        )
        changed_write_files: List[str] = []
        for tr in tool_results:
            if not isinstance(tr, dict):
                continue
            data_tr = tr.get("data") if isinstance(tr.get("data"), dict) else {}
            cfs = data_tr.get("changed_files") if isinstance(data_tr.get("changed_files"), list) else []
            if not cfs and str(data_tr.get("output_path") or "").strip():
                cfs = [str(data_tr.get("output_path") or "").strip()]
            for cf in cfs:
                cfv = str(cf or "").strip().replace("\\", "/")
                if cfv:
                    changed_write_files.append(cfv)
        auto_probe_results: List[Dict[str, Any]] = []
        if not tool_results and deferred_repo_paths and "repo.read" in allowed_skills:
            recover_path = str(deferred_repo_paths[0] or "").strip()
            if recover_path:
                self._emit_diag({"member_stream": f"{self._role_display(role)}: deferred write recovery read for {recover_path}"})
                recover_results = self._run_tool_calls(
                    [{"skill": "repo.read", "params": {"path": recover_path, "max_chars": 20000}}],
                    allowed_skills,
                    req,
                )
                recover_results = self._merge_repo_read_chunks(recover_results, allowed_skills, req)
                if recover_results:
                    tool_results.extend(recover_results)
        final_summary_role = role in {"release", "release_summary"}

        if (
            not tool_results
            and repo_scope_intent
            and not final_summary_role
            and any(s in allowed_skills for s in ["repo.tree", "repo.read"])
        ):
            probe_path = self._infer_repo_probe_path(user_text)
            auto_calls: List[Dict[str, Any]] = []
            if "repo.tree" in allowed_skills:
                auto_calls.append({"skill": "repo.tree", "params": {"path": probe_path or "plugin"}})
            if auto_calls:
                self._emit_diag({"member_stream": f"{self._role_display(role)}: auto repo probe for {probe_path or 'plugin'}"})
                auto_probe_results = self._run_tool_calls(auto_calls[:1], allowed_skills, req)
                candidate_probe_path = self._pick_repo_probe_candidate(user_text, auto_probe_results) or probe_path
                exact_probe_path = str(self._infer_repo_probe_path(user_text) or "").strip().replace("\\", "/").strip("/")
                candidate_probe_norm = str(candidate_probe_path or "").strip().replace("\\", "/").strip("/")
                candidate_matches_request = (
                    not exact_probe_path
                    or candidate_probe_norm == exact_probe_path
                    or candidate_probe_norm.startswith(exact_probe_path + "/")
                )
                if "repo.read" in allowed_skills and candidate_probe_path:
                    read_calls: List[Dict[str, Any]] = []
                    for read_path in self._repo_probe_read_candidates(user_text, candidate_probe_path, auto_probe_results):
                        read_calls.append({"skill": "repo.read", "params": {"path": read_path, "max_chars": 12000}})
                    auto_probe_results.extend(self._run_tool_calls(read_calls[:2], allowed_skills, req))
                auto_probe_results = self._merge_repo_read_chunks(auto_probe_results, allowed_skills, req)
                if auto_probe_results:
                    tool_results.extend(auto_probe_results)
                    tool_results = self._merge_repo_read_chunks(tool_results, allowed_skills, req)
                    tool_ok = any(bool((tr or {}).get("ok")) for tr in auto_probe_results if isinstance(tr, dict)) or tool_ok
                    write_ok = any(
                        isinstance(tr, dict)
                        and bool(tr.get("ok"))
                        and str(tr.get("skill") or "").strip() in {"repo.write", "code.apply_patch"}
                        for tr in auto_probe_results
                    ) or write_ok
                    for tr in auto_probe_results:
                        if not isinstance(tr, dict):
                            continue
                        if str(tr.get("skill") or "").strip() not in {"repo.write", "code.apply_patch"}:
                            continue
                        data_tr = tr.get("data") if isinstance(tr.get("data"), dict) else {}
                        cfs = data_tr.get("changed_files") if isinstance(data_tr.get("changed_files"), list) else []
                        for cf in cfs:
                            cfv = str(cf or "").strip().replace("\\", "/")
                            if cfv:
                                changed_write_files.append(cfv)
                    if not actions and candidate_matches_request:
                        actions = [f"Inspect repo scope: {candidate_probe_path or probe_path or 'plugin'}"]
                    if not summary and candidate_matches_request:
                        summary = f"Inspected repo scope '{candidate_probe_path or probe_path or 'plugin'}' to locate the requested implementation area."

        already_satisfied_repo_edit = (
            repo_scope_intent
            and build_role
            and write_capable
            and not write_ok
            and self._repo_edit_request_already_satisfied(
                summary=summary,
                analysis_text=analysis_text,
                response_text=response_text,
                handoff_text=handoff_text,
                actions=actions,
                tool_results=tool_results,
            )
        )
        if already_satisfied_repo_edit:
            self._emit_diag({"member_stream": f"{self._role_display(role)}: verified request already satisfied; skipping repo-edit fallback"})
            write_ok = True
            if not actions:
                actions = ["No repo edit required; verified the requested behavior in the exact target file."]
            if not handoff_text:
                handoff_text = "Proceed with verification and final summary; no code change was required."

        if repo_scope_intent and build_role and write_capable and not write_ok:
            self._emit_diag({"member_stream": f"{self._role_display(role)}: retrying repo-scope execution with stricter tool-call contract"})
            retry_text = self._retry_repo_scope_execution(
                messages,
                text,
                auto_probe_results or tool_results,
                allowed_skills,
                max_tokens=max_tokens,
                temp=temp,
            )
            if retry_text:
                reparsed = self._extract_tagged_protocol(retry_text)
                if reparsed is None:
                    reparsed = self._extract_json_block(retry_text)
                if isinstance(reparsed, dict):
                    retry_calls, _retry_schema_errors = self._normalize_tool_calls(reparsed.get("tool_calls"), allowed_skills)
                    if retry_calls:
                        self._emit_diag({"member_stream": f"{self._role_display(role)}: invoking retry skill call(s)"})
                        retry_results = self._run_tool_calls(retry_calls, allowed_skills, req)
                        if retry_results:
                            tool_results.extend(retry_results)
                            tool_results = self._merge_repo_read_chunks(tool_results, allowed_skills, req)
                            tool_ok = any(bool((tr or {}).get("ok")) for tr in retry_results if isinstance(tr, dict)) or tool_ok
                            write_ok = any(
                                isinstance(tr, dict)
                                and bool(tr.get("ok"))
                                and str(tr.get("skill") or "").strip() in {"repo.write", "code.apply_patch"}
                                for tr in retry_results
                            ) or write_ok
                            for tr in retry_results:
                                if not isinstance(tr, dict):
                                    continue
                                if str(tr.get("skill") or "").strip() not in {"repo.write", "code.apply_patch"}:
                                    continue
                                data_tr = tr.get("data") if isinstance(tr.get("data"), dict) else {}
                                cfs = data_tr.get("changed_files") if isinstance(data_tr.get("changed_files"), list) else []
                                for cf in cfs:
                                    cfv = str(cf or "").strip().replace("\\", "/")
                                    if cfv:
                                        changed_write_files.append(cfv)
                            if not summary:
                                summary = str(reparsed.get("summary") or "").strip() or summary
                            if not actions and isinstance(reparsed.get("actions"), list):
                                actions = [str(a) for a in (reparsed.get("actions") or []) if str(a).strip()]
                            if not handoff_text:
                                handoff_text = str(reparsed.get("handoff") or "").strip()
            if not write_ok:
                self._emit_diag({"member_stream": f"{self._role_display(role)}: retrying from repo.read content"})
                retry_text2 = self._retry_repo_edit_from_read_results(
                    messages,
                    tool_results,
                    allowed_skills,
                    max_tokens=max_tokens,
                    temp=temp,
                )
                if retry_text2:
                    reparsed2 = self._extract_tagged_protocol(retry_text2)
                    if reparsed2 is None:
                        reparsed2 = self._extract_json_block(retry_text2)
                    if isinstance(reparsed2, dict):
                        retry_calls2, _retry_schema_errors2 = self._normalize_tool_calls(reparsed2.get("tool_calls"), allowed_skills)
                        if retry_calls2:
                            self._emit_diag({"member_stream": f"{self._role_display(role)}: invoking repo-read retry skill call(s)"})
                            retry_results2 = self._run_tool_calls(retry_calls2, allowed_skills, req)
                            if retry_results2:
                                tool_results.extend(retry_results2)
                                tool_results = self._merge_repo_read_chunks(tool_results, allowed_skills, req)
                                tool_ok = any(bool((tr or {}).get("ok")) for tr in retry_results2 if isinstance(tr, dict)) or tool_ok
                                write_ok = any(
                                    isinstance(tr, dict)
                                    and bool(tr.get("ok"))
                                    and str(tr.get("skill") or "").strip() in {"repo.write", "code.apply_patch"}
                                    for tr in retry_results2
                                ) or write_ok
                                for tr in retry_results2:
                                    if not isinstance(tr, dict):
                                        continue
                                    if str(tr.get("skill") or "").strip() not in {"repo.write", "code.apply_patch"}:
                                        continue
                                    data_tr = tr.get("data") if isinstance(tr.get("data"), dict) else {}
                                    cfs = data_tr.get("changed_files") if isinstance(data_tr.get("changed_files"), list) else []
                                    for cf in cfs:
                                        cfv = str(cf or "").strip().replace("\\", "/")
                                        if cfv:
                                            changed_write_files.append(cfv)
                                if not summary:
                                    summary = str(reparsed2.get("summary") or "").strip() or summary
                                if not actions and isinstance(reparsed2.get("actions"), list):
                                    actions = [str(a) for a in (reparsed2.get("actions") or []) if str(a).strip()]
                                if not handoff_text:
                                    handoff_text = str(reparsed2.get("handoff") or "").strip()
            if not changed_write_files:
                self._emit_diag({"member_stream": f"{self._role_display(role)}: generating targeted replace ops from repo.read results"})
                gen_path, gen_ops = self._generate_repo_replace_ops_from_read_results(
                    original_request or user_text,
                    tool_results,
                    max_tokens=max_tokens,
                    temp=temp,
                )
                if not gen_ops:
                    self._emit_diag({"member_stream": f"{self._role_display(role)}: generating updated file content for mechanical diff fallback"})
                    upd_path, upd_text = self._generate_updated_repo_file_from_read_results(
                        original_request or user_text,
                        tool_results,
                        max_tokens=max_tokens,
                        temp=temp,
                    )
                    if upd_path and upd_text:
                        source_content = ""
                        for row in tool_results[:5]:
                            if not isinstance(row, dict):
                                continue
                            if str(row.get("skill") or "").strip() != "repo.read":
                                continue
                            data = row.get("data") if isinstance(row.get("data"), dict) else {}
                            path = str(data.get("path") or "").strip()
                            content = str(data.get("content") or "")
                            if path == upd_path and content:
                                source_content = content[:20000]
                                break
                        gen_path = upd_path
                        gen_ops = self._build_replace_ops_from_updated_content(upd_path, source_content, upd_text)
                        self._emit_diag(
                            {
                                "member_stream": (
                                    f"{self._role_display(role)}: mechanical diff fallback: "
                                    f"path={upd_path} "
                                    f"source_chars={len(source_content)} "
                                    f"updated_chars={len(upd_text)} "
                                    f"replace_ops={len(gen_ops)}"
                                )
                            }
                        )
                if gen_path and gen_ops:
                    fallback_edit_calls = [
                        {
                            "skill": "code.apply_patch",
                            "reason": "Apply targeted replace ops from backend edit fallback",
                            "params": {"ops": gen_ops},
                        }
                    ]
                    self._emit_diag({"member_stream": f"{self._role_display(role)}: invoking backend edit fallback replace ops"})
                    gen_results = self._run_tool_calls(fallback_edit_calls, allowed_skills, req)
                    if gen_results:
                        tool_results.extend(gen_results)
                        tool_ok = any(bool((tr or {}).get("ok")) for tr in gen_results if isinstance(tr, dict)) or tool_ok
                        write_ok = any(
                            isinstance(tr, dict)
                            and bool(tr.get("ok"))
                            and str(tr.get("skill") or "").strip() in {"repo.write", "code.apply_patch"}
                            for tr in gen_results
                        ) or write_ok
                        for tr in gen_results:
                            if not isinstance(tr, dict):
                                continue
                            if str(tr.get("skill") or "").strip() not in {"repo.write", "code.apply_patch"}:
                                continue
                            data_tr = tr.get("data") if isinstance(tr.get("data"), dict) else {}
                            cfs = data_tr.get("changed_files") if isinstance(data_tr.get("changed_files"), list) else []
                            for cf in cfs:
                                    cfv = str(cf or "").strip().replace("\\", "/")
                                    if cfv:
                                        changed_write_files.append(cfv)
                        if not summary:
                            summary = f"Updated repo file '{gen_path}' via backend replace-op fallback."
                        if not actions:
                            actions = [f"Modify {gen_path} with targeted replace ops to satisfy the repo-edit request."]
                        if not handoff_text:
                            handoff_text = "Verify the updated file and confirm the requested behavior."

        if standalone_artifact_mode and build_role and write_capable and no_files_written_yet and not tool_ok:
            artifact_path = str(desired_artifact_path or "").strip() or self._infer_artifact_path(original_request, user_text)
            self._emit_diag({"member_stream": f"{self._role_display(role)}: fallback artifact generation for {artifact_path}"})
            artifact_content = self._generate_artifact_content(
                original_request=original_request or user_text,
                artifact_path=artifact_path,
                max_tokens=max_tokens,
                temp=temp,
            )
            if artifact_content:
                fallback_calls = [
                    {
                        "skill": "code.apply_patch" if "code.apply_patch" in allowed_skills else "repo.write",
                        "reason": "Fallback write from raw artifact generation",
                        "params": (
                            {"ops": self._chunk_patch_write_ops(artifact_path, artifact_content)}
                            if "code.apply_patch" in allowed_skills
                            else {"path": artifact_path, "content": artifact_content}
                        ),
                    }
                ]
                extra_results = self._run_tool_calls(fallback_calls, allowed_skills, req)
                if extra_results:
                    tool_results.extend(extra_results)
                    tool_ok = any(bool((tr or {}).get("ok")) for tr in extra_results if isinstance(tr, dict)) or tool_ok
                    if not summary:
                        summary = f"Created artifact '{artifact_path}' via fallback generation."
                    if not actions:
                        actions = [f"Generate and write {artifact_path} directly."]
                    if not response_text:
                        response_text = f"Wrote {artifact_path} using backend fallback artifact generation."

        # Heuristic auto-skill path for older flows where the model does not emit tool_calls.
        # This keeps nodes useful for concrete file-inspection asks (e.g. "check plugins.py").
        reviewer_roles = {"qa", "docs", "release", "security", "architect"}
        role_for_review = self._normalize_role(role) or role
        if (
            not tool_results
            and "repo.read" in allowed_skills
            and role_for_review in reviewer_roles
            and not final_summary_role
            and not (create_intent and no_files_written_yet)
        ):
            tgt = self._extract_target_path(user_text)
            ext2 = getattr(req, "ext", None)
            changed_first = ""
            if isinstance(ext2, dict):
                changed = ext2.get("agent_flow_changed_files")
                if isinstance(changed, list) and changed:
                    changed_first = str(changed[0] or "").strip().replace("\\", "/")
            if changed_first and (not tgt or self._is_generic_artifact_name(tgt)):
                tgt = changed_first
            if tgt:
                auto_calls = [{"skill": "repo.read", "params": {"path": tgt, "max_chars": 6000}}]
                auto_results = self._run_tool_calls(auto_calls, allowed_skills, req)
                if auto_results:
                    tool_results.extend(auto_results)
                    if not actions:
                        actions = [f"Read target file: {tgt}"]
                    if not summary:
                        ok_auto = any(bool(x.get("ok")) for x in auto_results if isinstance(x, dict))
                        if ok_auto:
                            summary = f"Inspected file '{tgt}' for potential issues."
                        else:
                            missing = False
                            for ar in auto_results:
                                if not isinstance(ar, dict):
                                    continue
                                if self._is_file_not_found_result(ar):
                                    missing = True
                                    break
                            summary = (
                                f"artifact_not_created: expected file '{tgt}' is missing."
                                if missing
                                else f"Attempted to read '{tgt}' but access/read failed."
                            )
                    if not handoff_text:
                        handoff_text = "Provide bug findings with line-level evidence and suggested fixes."
            elif not summary:
                summary = "artifact_not_created: no readable target file available for review stage."
                if not actions:
                    actions = ["Wait for build/coding stage to produce files before docs/release review."]

        if not summary:
            summary = text.splitlines()[0].strip() if text else ""
        if final_summary_role:
            plan_text = ""
            analysis_text = ""
            bug_findings = []
            fix_plan = []
            actions = []
            handoff_text = ""
        response_low_final = str(response_text or "").strip().lower()
        final_summary_structured = bool(
            final_summary_role
            and response_low_final
            and "target folder:" in response_low_final
            and "verified files:" in response_low_final
        )
        if final_summary_structured:
            if summary and summary.lower().startswith("inspected repo scope"):
                summary = str(response_text or "").splitlines()[0].strip() or summary
            tool_results = []
        if summary or actions:
            self._emit_diag(
                {
                    "member_analysis": {
                        "plan": plan_text,
                        "analysis": analysis_text,
                        "response": response_text,
                        "summary": summary,
                        "bugs": bug_findings[:8],
                        "fixes": fix_plan[:8],
                        "actions": actions[:8],
                    }
                }
            )
        skill_calls = [str((x or {}).get("skill") or "") for x in tool_results if isinstance(x, dict)]
        skill_calls = [s for s in skill_calls if s]
        activity = {
            "role": self._role_display(role),
            "did": (
                (str(response_text or "").splitlines()[0].strip() if final_summary_structured else "")
                or summary
                or f"Processed node for role {role}."
            ),
            "plan": plan_text,
            "analysis": analysis_text,
            "response": response_text,
            "bugs": bug_findings[:8],
            "fixes": fix_plan[:8],
            "actions": actions[:8],
            "skills_invoked": skill_calls,
            "skills_invoked_count": len(skill_calls),
            "handoff": handoff_text,
        }
        # Deterministic human-readable step report so the transcript never shows only
        # a generic "task done" message.
        lines: List[str] = []
        lines.append(f"role: {activity['role']}")
        if activity["plan"]:
            lines.append(f"plan: {activity['plan']}")
        if activity["analysis"]:
            lines.append(f"analysis: {activity['analysis']}")
        if activity["response"]:
            lines.append(f"response: {activity['response']}")
        lines.append(f"did: {activity['did']}")
        if activity["actions"] and str(activity["role"] or "").strip().lower() != "release_summary":
            lines.append("actions:")
            for a in activity["actions"]:
                lines.append(f"- {a}")
        if activity["bugs"]:
            lines.append("bugs:")
            for b in activity["bugs"]:
                lines.append(f"- {b}")
        if activity["fixes"]:
            lines.append("fixes:")
            for f in activity["fixes"]:
                lines.append(f"- {f}")
        if activity["skills_invoked"]:
            lines.append("skills_invoked: " + ", ".join(activity["skills_invoked"]))
        if tool_results and str(activity["role"] or "").strip().lower() != "release_summary":
            lines.append("skill_results:")
            for tr in tool_results[:6]:
                if not isinstance(tr, dict):
                    continue
                skill = str(tr.get("skill") or "")
                ok = bool(tr.get("ok"))
                data = tr.get("data") if isinstance(tr.get("data"), dict) else {}
                note = ""
                if isinstance(data, dict):
                    p = str(data.get("path") or "")
                    if p:
                        note = f" ({p})"
                    elif any(k in data for k in ("pass_count", "fail_count", "all_passed")):
                        note = (
                            " (pass_count="
                            + str(data.get("pass_count"))
                            + " fail_count="
                            + str(data.get("fail_count"))
                            + " all_passed="
                            + str(data.get("all_passed"))
                            + ")"
                        )
                    elif "matches" in data and isinstance(data.get("matches"), list):
                        note = f" (matches={len(data.get('matches') or [])})"
                warn_note = ""
                warnings0 = tr.get("warnings") if isinstance(tr.get("warnings"), list) else []
                if warnings0:
                    warn_note = " warnings=" + ",".join(str(x or "") for x in warnings0[:2] if str(x or "").strip())
                lines.append(f"- {skill}: {'ok' if ok else 'failed'}{note}{warn_note}")
        if activity["handoff"] and str(activity["role"] or "").strip().lower() != "release_summary":
            lines.append(f"handoff: {activity['handoff']}")
        report_text = "\n".join(lines).strip()
        structured_response_text = str(activity["response"] or "").strip()
        structured_response_low = structured_response_text.lower()
        if (
            structured_response_text
            and "target folder:" in structured_response_low
            and "verified files:" in structured_response_low
        ):
            text = structured_response_text
        elif final_summary_role and structured_response_text:
            text = str(activity["response"] or "").strip()
        elif report_text:
            text = report_text
        if final_summary_structured:
            text = structured_response_text
        self._emit_diag(
            {
                "member_stream": f"{self._role_display(role)}: handoff prepared",
                "member_handoff": {
                    "to": handoff_text,
                    "summary": summary,
                },
                "member_tool_results": tool_results[:8],
            }
        )
        return {
            "route_id": self.route_id,
            "ok": bool(text),
            "text": text,
            "member_role": role,
            "node_id": str((ext or {}).get("agent_flow_node_id") or ""),
            "tool_results": tool_results,
            "activity": activity,
        }

    def _emit_diag(self, data: Dict[str, Any]) -> None:
        payload = dict(data or {})
        try:
            if payload.get("member_stream"):
                logger.warning("[agent_workflow_member] %s", str(payload.get("member_stream") or ""))
        except Exception:
            pass
        try:
            cb = (self.core.settings or {}).get("__router_diag_cb")
        except Exception:
            cb = None
        if callable(cb):
            try:
                cb(payload)
            except Exception:
                pass

    def _extract_user_text(self, req: Any) -> str:
        msgs = getattr(req, "messages", None)
        if isinstance(msgs, list) and msgs:
            last_user = None
            for m in msgs:
                try:
                    if (m.get("role") or "").lower() == "user":
                        last_user = m
                except AttributeError:
                    continue
            if last_user is None:
                last_user = msgs[-1]
            return str(last_user.get("content", ""))
        return ""

    def _extract_text(self, resp: Any) -> str:
        if isinstance(resp, str):
            return resp
        if isinstance(resp, dict):
            content = resp.get("content")
            if isinstance(content, str) and content.strip():
                return content
            try:
                return str(resp.get("choices", [{}])[0].get("message", {}).get("content", "") or "")
            except Exception:
                return ""
        return str(resp or "")

    def _is_risky_repo_full_write_call(self, call: Dict[str, Any]) -> bool:
        if not isinstance(call, dict):
            return False
        skill = str(call.get("skill") or "").strip()
        params = call.get("params") if isinstance(call.get("params"), dict) else {}
        if skill == "repo.write":
            path = str(params.get("path") or params.get("target") or params.get("file_path") or "").strip().replace("\\", "/")
            return bool(path and "/" in path)
        if skill != "code.apply_patch":
            return False
        ops = params.get("ops") if isinstance(params.get("ops"), list) else []
        if not ops:
            return False
        for op in ops:
            if not isinstance(op, dict):
                continue
            op_kind = str(op.get("op") or "").strip().lower()
            path = str(op.get("path") or "").strip().replace("\\", "/")
            if op_kind == "write" and path and "/" in path:
                return True
        return False

    def _chat_once(self, *, messages: List[Dict[str, Any]], max_tokens: int, temp: float, slot_suffix: str) -> str:
        if self.core.chat_llm is not None:
            try:
                resp = self.core.chat_llm.chat(
                    messages=messages,
                    max_new_tokens=max_tokens,
                    temperature=temp,
                    top_p=0.95,
                )
                return self._extract_text(resp).strip()
            except Exception:
                return ""
        deck_runner = ModelDeckRunner(
            core=self.core,
            settings=dict(self.core.settings or {}),
            model_type="text_llm",
            slot=f"{self.route_id}_{slot_suffix}",
            prefer_worker=False,
        )
        try:
            if getattr(deck_runner, "error", None):
                return ""
            pres = deck_runner.plan(
                messages=messages,
                params={"max_new_tokens": max_tokens, "temperature": temp, "top_p": 0.95},
            )
            if not isinstance(pres, dict) or not pres.get("ok"):
                return ""
            return self._extract_text((pres or {}).get("raw", "")).strip()
        finally:
            try:
                deck_runner.close()
            except Exception:
                pass

    def _run_tool_calls(self, calls: List[Any], allowed: List[str], req: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        settings: Dict[str, Any] = dict(self.core.settings or {})
        cb = settings.get("__agent_workflow_tool_call")
        if not callable(cb):
            return [{"ok": False, "skill": "", "error": "agent_workflow_tool_bridge_unavailable"}]

        ext = getattr(req, "ext", None)
        pid = ""
        sid = ""
        user_text = self._extract_user_text(req)
        original_request = self._extract_original_request(user_text)
        target_repo_root = self._resolve_target_repo_root(req)
        if isinstance(ext, dict):
            pid = str(ext.get("pid") or settings.get("__pid") or "").strip()
            sid = str(ext.get("sid") or settings.get("__sid") or "").strip()
        ctx = {
            "pid": pid,
            "sid": sid,
            "user_text": user_text,
            "original_request": original_request,
            "target_repo_root": target_repo_root,
            "ext": dict(ext or {}) if isinstance(ext, dict) else {},
        }

        for raw in calls[:5]:
            if not isinstance(raw, dict):
                continue
            skill = str(raw.get("skill") or "").strip()
            params = raw.get("params")
            if not isinstance(params, dict):
                params = {}
            params = dict(params)
            if not skill:
                continue
            if skill == "repo.read":
                # Be resilient to model outputs that omit path/target for repo.read.
                if not str(params.get("path") or params.get("target") or "").strip():
                    inferred = self._extract_target_path(user_text)
                    if inferred:
                        params["path"] = inferred
                if not str(params.get("max_chars") or "").strip():
                    params["max_chars"] = 20000
            if target_repo_root and not str(params.get("target_repo_root") or "").strip():
                params["target_repo_root"] = target_repo_root
            if original_request and not str(params.get("request_title") or "").strip():
                params["request_title"] = original_request
            original_low = str(original_request or user_text or "").lower()
            analysis_only_request = bool(
                re.search(
                    r"\b(analysis-only|analysis only|read-only|review only|without editing|without modifying|do not edit|do not modify|don't edit|don't modify|do not change|don't change|summarize|propose(?:\s+a)?\s+fix\s+before\s+editing)\b",
                    original_low,
                    flags=re.IGNORECASE,
                )
            )
            explicit_no_modify_request = bool(
                re.search(
                    r"\b(do not modify|don't modify|do not edit|don't edit|without modifying|without editing|read-only|review only)\b",
                    original_low,
                    flags=re.IGNORECASE,
                )
            )
            explicit_edit_request = bool(
                re.search(
                    r"\b(create|implement|write|patch|modify|edit|change|update|add|insert|rebind|document|comment)\b",
                    original_low,
                    flags=re.IGNORECASE,
                )
            )
            if skill == "git.commit" and ((analysis_only_request and not explicit_edit_request) or explicit_no_modify_request):
                out.append(
                    {
                        "ok": True,
                        "skill": skill,
                        "data": {
                            "root": str(params.get("target_repo_root") or target_repo_root or "").strip(),
                            "committed": False,
                            "skipped": True,
                            "reason": "analysis_only_no_commit",
                        },
                        "warnings": [],
                    }
                )
                continue
            if skill not in allowed:
                out.append({"ok": False, "skill": skill, "error": "skill_not_allowed"})
                continue
            try:
                res = cb(skill, ctx, params)
                if isinstance(res, dict):
                    row = {"skill": skill, **res}
                    # Normalize heterogeneous tool result shapes:
                    # if a tool returns payload keys at top-level (e.g. records/charts/profile),
                    # mirror them into row["data"] so downstream workflow context can read values.
                    if not isinstance(row.get("data"), dict):
                        payload = {}
                        for k, v in row.items():
                            if k in {"skill", "ok", "warnings", "error"}:
                                continue
                            payload[k] = v
                        row["data"] = payload
                    out.append(row)
                else:
                    out.append({"ok": True, "skill": skill, "data": {"result": res}, "warnings": []})
            except Exception as exc:
                out.append({"ok": False, "skill": skill, "error": f"skill_call_error:{exc}"})
        return out

    def _merge_repo_read_chunks(self, tool_results: List[Dict[str, Any]], allowed: List[str], req: Any) -> List[Dict[str, Any]]:
        if "repo.read" not in allowed or not isinstance(tool_results, list):
            return tool_results
        first_idx = -1
        base_row: Dict[str, Any] | None = None
        for i, row in enumerate(tool_results):
            if not isinstance(row, dict):
                continue
            if str(row.get("skill") or "").strip() != "repo.read":
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            path = str(data.get("path") or "").strip()
            content = str(data.get("content") or "")
            if path and content:
                first_idx = i
                base_row = row
                break
        if first_idx < 0 or not isinstance(base_row, dict):
            return tool_results
        data0 = base_row.get("data") if isinstance(base_row.get("data"), dict) else {}
        path0 = str(data0.get("path") or "").strip()
        content0 = str(data0.get("content") or "")
        truncated0 = bool(data0.get("truncated"))
        total_chars = int(data0.get("total_chars") or len(content0) or 0)
        start_char = int(data0.get("start_char") or 0)
        if not path0 or not content0 or not truncated0 or total_chars <= (start_char + len(content0)):
            return tool_results
        max_total = min(max(total_chars, len(content0)), 120000)
        chunk_chars = max(4000, int(data0.get("max_chars") or 20000))
        combined = content0
        next_start = start_char + len(content0)
        extra_results: List[Dict[str, Any]] = []
        while next_start < total_chars and len(combined) < max_total:
            self._emit_diag({"member_stream": f"repo.read continuation: path={path0} start={next_start}"})
            chunk_rows = self._run_tool_calls(
                [{"skill": "repo.read", "params": {"path": path0, "start_char": next_start, "max_chars": chunk_chars}}],
                allowed,
                req,
            )
            if not chunk_rows:
                break
            row = chunk_rows[0] if isinstance(chunk_rows[0], dict) else None
            if not isinstance(row, dict) or not bool(row.get("ok")):
                break
            datax = row.get("data") if isinstance(row.get("data"), dict) else {}
            chunk = str(datax.get("content") or "")
            if not chunk:
                break
            combined += chunk
            next_start = int(datax.get("start_char") or next_start) + len(chunk)
            extra_results.extend(chunk_rows)
            if not bool(datax.get("truncated")):
                break
        merged = list(tool_results)
        merged_row = dict(base_row)
        merged_data = dict(data0)
        merged_data["content"] = combined[:max_total]
        merged_data["truncated"] = (start_char + len(combined)) < total_chars
        merged_data["total_chars"] = total_chars
        merged_row["data"] = merged_data
        merged[first_idx] = merged_row
        if extra_results:
            self._emit_diag(
                {
                    "member_stream": (
                        f"repo.read merged: path={path0} "
                        f"chars={len(merged_data['content'])}/{total_chars} "
                        f"truncated={str(bool(merged_data['truncated'])).lower()}"
                    )
                }
            )
        return merged

    def _normalize_tool_calls(self, calls: Any, allowed: List[str]) -> tuple[List[Dict[str, Any]], List[str]]:
        if calls is None:
            return ([], [])
        if not isinstance(calls, list):
            return ([], ["tool_calls_not_list"])
        out: List[Dict[str, Any]] = []
        errs: List[str] = []
        for i, row in enumerate(calls[:8]):
            if not isinstance(row, dict):
                errs.append(f"tool_call_{i}_not_object")
                continue
            skill = str(row.get("skill") or "").strip()
            params = row.get("params")
            if not skill:
                errs.append(f"tool_call_{i}_skill_required")
                continue
            if not isinstance(params, dict):
                errs.append(f"tool_call_{i}_params_not_object")
                continue
            params = dict(params)
            if "file_path" in params and "path" not in params:
                params["path"] = params.get("file_path")
            if "target" in params and "path" not in params:
                params["path"] = params.get("target")
            if skill == "repo.write" and "code.apply_patch" in allowed:
                path = str(params.get("path") or params.get("target") or params.get("file_path") or "").strip()
                content = str(params.get("content") or "")
                patch_params: Dict[str, Any] = {"ops": self._chunk_patch_write_ops(path, content)}
                if str(params.get("target_repo_root") or "").strip():
                    patch_params["target_repo_root"] = str(params.get("target_repo_root") or "").strip()
                reason = row.get("reason")
                why = row.get("why")
                reason_s = str(reason if reason is not None else why if why is not None else "").strip()
                out.append({"skill": "code.apply_patch", "params": patch_params, "reason": reason_s or "Translated from repo.write"})
                continue
            if skill == "code.apply_patch":
                ops = params.get("ops")
                if not isinstance(ops, list):
                    path = str(params.get("path") or params.get("target") or params.get("file_path") or "").strip()
                    op_kind = str(params.get("op") or "write").strip().lower()
                    content = str(params.get("content") or "")
                    if path:
                        if op_kind == "write":
                            params["ops"] = self._chunk_patch_write_ops(path, content)
                        else:
                            params["ops"] = [{"op": op_kind or "write", "path": path, "content": content}]
                    ops = params.get("ops")
                if isinstance(ops, list):
                    new_ops: List[Dict[str, Any]] = []
                    for op in ops:
                        if not isinstance(op, dict):
                            continue
                        if str(op.get("op") or "").strip().lower() == "write":
                            path = str(op.get("path") or "").strip()
                            content = str(op.get("content") or "")
                            new_ops.extend(self._chunk_patch_write_ops(path, content))
                        else:
                            new_ops.append(dict(op))
                    params["ops"] = new_ops
            if skill not in allowed:
                errs.append(f"tool_call_{i}_skill_not_allowed:{skill}")
                continue
            reason = row.get("reason")
            why = row.get("why")
            reason_s = str(reason if reason is not None else why if why is not None else "").strip()
            out.append({"skill": skill, "params": dict(params), "reason": reason_s})
        return (out, errs)

    def _repair_tool_call_payload(
        self,
        base_messages: List[Dict[str, Any]],
        bad_text: str,
        allowed_skills: List[str],
        *,
        max_tokens: int,
    ) -> Any:
        allow = ", ".join(allowed_skills) if allowed_skills else "(none)"
        repair_system = (
            "Repair the previous assistant output into STRICT JSON.\n"
            "Return ONLY JSON object with keys: summary, actions, tool_calls, handoff.\n"
            "tool_calls must be an array of {skill, params}.\n"
            f"Allowed skills: {allow}\n"
            "If no valid tool call exists, return tool_calls as []."
        )
        repair_user = f"Original output to repair:\n{bad_text}"
        msgs = list(base_messages) + [
            {"role": "system", "content": repair_system},
            {"role": "user", "content": repair_user},
        ]
        repaired_text = self._chat_once(
            messages=msgs,
            max_tokens=max(200, min(max_tokens, 900)),
            temp=0.0,
            slot_suffix="repair",
        )
        if not repaired_text:
            return None
        return self._extract_json_block(repaired_text)

    def _retry_repo_scope_execution(
        self,
        base_messages: List[Dict[str, Any]],
        prior_text: str,
        probe_results: List[Dict[str, Any]],
        allowed_skills: List[str],
        *,
        max_tokens: int,
        temp: float,
    ) -> str:
        allow = ", ".join(allowed_skills) if allowed_skills else "(none)"
        probe_lines: List[str] = []
        for row in probe_results[:6]:
            if not isinstance(row, dict):
                continue
            skill = str(row.get("skill") or "").strip()
            ok = bool(row.get("ok"))
            probe_lines.append(f"- {skill}: ok={ok}")
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            path = str(data.get("path") or "").strip()
            if path:
                probe_lines.append(f"  path: {path}")
            files = data.get("files") if isinstance(data.get("files"), list) else []
            if files:
                for f in files[:6]:
                    probe_lines.append(f"  file: {str(f or '').strip()}")
            content = str(data.get("content") or "")
            if content:
                probe_lines.append(f"  content_preview: {content[:700]}")
        retry_system = (
            "You are handling an existing repo-edit request.\n"
            "Do not ask the user for more repo context.\n"
            "Return TAGGED protocol only.\n"
            f"Allowed skills: {allow}\n"
            "You MUST emit concrete tool calls now.\n"
            "If you already have enough repo context, emit code.apply_patch or repo.write for the real file path.\n"
            "If you still need one more inspection, emit repo.read for the exact file path.\n"
            "Do not create artifact.txt or any standalone artifact.\n"
            "Do not output prose outside the tagged blocks."
        )
        retry_user = (
            "Previous response did not complete the repo-edit task.\n\n"
            f"Previous response:\n{prior_text}\n\n"
            "Repo probe results:\n"
            + ("\n".join(probe_lines) if probe_lines else "- none")
        )
        return self._chat_once(
            messages=list(base_messages) + [
                {"role": "system", "content": retry_system},
                {"role": "user", "content": retry_user},
            ],
            max_tokens=max_tokens,
            temp=temp,
            slot_suffix="repo_scope_retry",
        )

    def _retry_repo_edit_from_read_results(
        self,
        base_messages: List[Dict[str, Any]],
        read_results: List[Dict[str, Any]],
        allowed_skills: List[str],
        *,
        max_tokens: int,
        temp: float,
    ) -> str:
        file_blocks: List[str] = []
        for row in read_results[:3]:
            if not isinstance(row, dict):
                continue
            if str(row.get("skill") or "").strip() != "repo.read":
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            path = str(data.get("path") or "").strip()
            content = str(data.get("content") or "")
            if not path or not content:
                continue
            file_blocks.append(f"FILE: {path}\n---\n{content[:20000]}\n---")
        if not file_blocks:
            return ""
        allow = ", ".join(allowed_skills) if allowed_skills else "(none)"
        repair_system = (
            "You are editing an existing repo file.\n"
            "Return TAGGED protocol only.\n"
            f"Allowed skills: {allow}\n"
            "You MUST emit exactly one write-capable tool call now.\n"
            "Prefer skill: code.apply_patch.\n"
            "Use the actual repo file path from the provided FILE blocks.\n"
            "If the file is small, rewrite the full updated file using code.apply_patch with op: write.\n"
            "Do not ask for more context. Do not output analysis-only text. Do not create artifact.txt."
        )
        repair_user = "Edit the following repo file(s) to satisfy the request:\n\n" + "\n\n".join(file_blocks)
        return self._chat_once(
            messages=list(base_messages) + [
                {"role": "system", "content": repair_system},
                {"role": "user", "content": repair_user},
            ],
            max_tokens=max_tokens,
            temp=temp,
            slot_suffix="repo_edit_retry",
        )

    def _generate_updated_repo_file_from_read_results(
        self,
        original_request: str,
        read_results: List[Dict[str, Any]],
        *,
        max_tokens: int,
        temp: float,
    ) -> tuple[str, str]:
        target_path = ""
        source_content = ""
        source_total_chars = 0
        source_truncated = False
        for row in read_results[:5]:
            if not isinstance(row, dict):
                continue
            if str(row.get("skill") or "").strip() != "repo.read":
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            path = str(data.get("path") or "").strip()
            content = str(data.get("content") or "")
            if path and content and re.search(r"\.(?:js|ts|tsx|jsx|json|html|css|py|md)$", path, flags=re.IGNORECASE):
                target_path = path
                source_total_chars = int(data.get("total_chars") or 0)
                source_truncated = bool(data.get("truncated"))
                source_content = content[:20000]
                break
        if not target_path or not source_content:
            return ("", "")
        self._emit_diag(
            {
                "member_stream": (
                    "repo file generate input: "
                    f"path={target_path} "
                    f"source_chars={len(source_content)} "
                    f"total_chars={source_total_chars or len(source_content)} "
                    f"repo_read_truncated={source_truncated} "
                    f"model_max_tokens={max_tokens}"
                )
            }
        )
        system = (
            "You are editing an existing source file.\n"
            "Return ONLY the full updated file contents.\n"
            "Do not return JSON, tagged protocol, commentary, or markdown fences.\n"
            "Keep unrelated code unchanged.\n"
            "Apply only the requested modification."
        )
        user = (
            f"User request:\n{original_request}\n\n"
            f"File path:\n{target_path}\n\n"
            "Current file contents:\n"
            f"{source_content}\n"
        )
        text = self._chat_once(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temp=temp,
            slot_suffix="repo_file_generate",
        )
        if not text:
            return (target_path, "")
        text = re.sub(r"^```[A-Za-z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        self._emit_diag(
            {
                "member_stream": (
                    "repo file generate output: "
                    f"path={target_path} "
                    f"output_chars={len(text)} "
                    f"model_max_tokens={max_tokens}"
                )
            }
        )
        return (target_path, text)

    def _build_replace_ops_from_updated_content(
        self,
        target_path: str,
        source_content: str,
        updated_content: str,
    ) -> List[Dict[str, Any]]:
        if not target_path or not source_content or not updated_content or updated_content == source_content:
            return []
        old_lines = source_content.splitlines(keepends=True)
        new_lines = updated_content.splitlines(keepends=True)
        sm = difflib.SequenceMatcher(a=old_lines, b=new_lines)
        ops: List[Dict[str, Any]] = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            search = "".join(old_lines[i1:i2])
            replace = "".join(new_lines[j1:j2])
            if not search:
                if i1 > 0:
                    anchor = old_lines[i1 - 1]
                    search = anchor
                    replace = anchor + replace
                elif i2 < len(old_lines):
                    anchor = old_lines[i2]
                    search = anchor
                    replace = replace + anchor
                else:
                    continue
            if search == replace:
                continue
            ops.append({"op": "replace", "path": target_path, "search": search, "replace": replace, "count": 1})
            if len(ops) >= 24:
                break
        return ops

    def _generate_repo_replace_ops_from_read_results(
        self,
        original_request: str,
        read_results: List[Dict[str, Any]],
        *,
        max_tokens: int,
        temp: float,
    ) -> tuple[str, List[Dict[str, Any]]]:
        target_path = ""
        source_content = ""
        source_total_chars = 0
        source_truncated = False
        for row in read_results[:5]:
            if not isinstance(row, dict):
                continue
            if str(row.get("skill") or "").strip() != "repo.read":
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            path = str(data.get("path") or "").strip()
            content = str(data.get("content") or "")
            if path and content and re.search(r"\.(?:js|ts|tsx|jsx|json|html|css|py|md)$", path, flags=re.IGNORECASE):
                target_path = path
                source_total_chars = int(data.get("total_chars") or 0)
                source_truncated = bool(data.get("truncated"))
                source_content = content[:20000]
                break
        if not target_path or not source_content:
            return ("", [])
        replace_ops_max_tokens = max(300, min(max_tokens, 2200))
        self._emit_diag(
            {
                "member_stream": (
                    "repo replace-op input: "
                    f"path={target_path} "
                    f"source_chars={len(source_content)} "
                    f"total_chars={source_total_chars or len(source_content)} "
                    f"repo_read_truncated={source_truncated} "
                    f"model_max_tokens={replace_ops_max_tokens}"
                )
            }
        )
        system = (
            "You are editing an existing source file.\n"
            "Return STRICT JSON only.\n"
            "Schema: {\"ops\":[{\"search\":\"exact existing substring\",\"replace\":\"updated substring\"}]}.\n"
            "Rules:\n"
            "- Use 1 to 6 replace ops.\n"
            "- Each `search` MUST be copied exactly from the current file.\n"
            "- Each `replace` must be the full updated replacement for that exact block.\n"
            "- Prefer replacing the smallest complete blocks necessary.\n"
            "- Do not include explanations or markdown fences.\n"
            "- Do not rewrite the whole file."
        )
        user = (
            f"User request:\n{original_request}\n\n"
            f"File path:\n{target_path}\n\n"
            "Current file contents:\n"
            f"{source_content}\n"
        )
        base_msgs = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        raw = self._chat_once(
            messages=base_msgs,
            max_tokens=replace_ops_max_tokens,
            temp=0.0,
            slot_suffix="repo_replace_ops",
        )
        if not raw:
            self._emit_diag({"member_stream": f"repo replace-op output: path={target_path} raw_chars=0 ops=0"})
            return (target_path, [])
        parsed = self._extract_json_block(raw)
        if parsed is None:
            repair_system = (
                "Repair the previous assistant output into STRICT JSON only.\n"
                "Schema: {\"ops\":[{\"search\":\"exact existing substring\",\"replace\":\"updated substring\"}]}.\n"
                "Return ONLY the JSON object.\n"
            )
            repaired = self._chat_once(
                messages=base_msgs + [
                    {"role": "system", "content": repair_system},
                    {"role": "user", "content": f"Original output to repair:\n{raw}"},
                ],
                max_tokens=max(200, min(max_tokens, 1000)),
                temp=0.0,
                slot_suffix="repo_replace_ops_repair",
            )
            if repaired:
                parsed = self._extract_json_block(repaired)
        if not isinstance(parsed, dict):
            self._emit_diag(
                {
                    "member_stream": (
                        "repo replace-op output: "
                        f"path={target_path} "
                        f"raw_chars={len(raw)} "
                        "ops=0 json_parse_failed=true"
                    )
                }
            )
            return (target_path, [])
        raw_ops = parsed.get("ops")
        if not isinstance(raw_ops, list):
            self._emit_diag(
                {
                    "member_stream": (
                        "repo replace-op output: "
                        f"path={target_path} "
                        f"raw_chars={len(raw)} "
                        "ops=0 schema_invalid=true"
                    )
                }
            )
            return (target_path, [])
        ops: List[Dict[str, Any]] = []
        for row in raw_ops[:6]:
            if not isinstance(row, dict):
                continue
            search = str(row.get("search") or "")
            replace = str(row.get("replace") or "")
            if not search or search not in source_content:
                continue
            ops.append({"op": "replace", "path": target_path, "search": search, "replace": replace, "count": 1})
        self._emit_diag(
            {
                "member_stream": (
                    "repo replace-op output: "
                    f"path={target_path} "
                    f"raw_chars={len(raw)} "
                    f"ops={len(ops)}"
                )
            }
        )
        return (target_path, ops)

    def _json_completion_state(self, raw: str) -> tuple[bool, bool]:
        s = str(raw or "")
        if not s.strip():
            return (False, False)
        depth_obj = 0
        depth_arr = 0
        in_str = False
        esc = False
        saw_json = False
        for ch in s:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
                continue
            if ch == "{":
                depth_obj += 1
                saw_json = True
            elif ch == "}":
                depth_obj = max(0, depth_obj - 1)
            elif ch == "[":
                depth_arr += 1
                saw_json = True
            elif ch == "]":
                depth_arr = max(0, depth_arr - 1)
        complete = bool(saw_json and not in_str and depth_obj == 0 and depth_arr == 0)
        truncated = bool(saw_json and not complete)
        return (complete, truncated)

    def _continue_truncated_json(
        self,
        base_messages: List[Dict[str, Any]],
        partial_text: str,
        *,
        max_tokens: int,
        temp: float,
    ) -> str:
        if self.core.chat_llm is None:
            return str(partial_text or "")
        combined = str(partial_text or "")
        for _ in range(2):
            complete_json, truncated_json = self._json_completion_state(combined)
            if complete_json or not truncated_json:
                break
            cont_messages = list(base_messages) + [
                {"role": "assistant", "content": combined},
                {
                    "role": "user",
                    "content": (
                        "Continue exactly from where you stopped.\n"
                        "Output ONLY the remaining text needed to complete the same JSON object.\n"
                        "Do not repeat prior content. Do not restart the object. Do not add markdown fences."
                    ),
                },
            ]
            try:
                resp = self.core.chat_llm.chat(
                    messages=cont_messages,
                    max_new_tokens=max(256, min(max_tokens, 4000)),
                    temperature=temp,
                    top_p=0.95,
                )
            except Exception:
                break
            tail = self._extract_text(resp).strip()
            if not tail:
                break
            combined += tail
        return combined

    def _chunk_patch_write_ops(self, path: str, content: str, *, chunk_size: int = 2200) -> List[Dict[str, Any]]:
        rel = str(path or "").strip()
        txt = str(content or "")
        if not rel:
            return []
        if len(txt) <= chunk_size:
            return [{"op": "write", "path": rel, "content": txt}]
        ops: List[Dict[str, Any]] = [{"op": "write", "path": rel, "content": txt[:chunk_size]}]
        idx = chunk_size
        while idx < len(txt):
            ops.append({"op": "append", "path": rel, "content": txt[idx : idx + chunk_size]})
            idx += chunk_size
        return ops

    def _extract_tagged_block(self, text: str, name: str) -> str:
        s = str(text or "")
        # Accept both canonical triple-angle tags and tolerant single-angle tags.
        m = re.search(
            rf"(?:<<<|<){re.escape(name)}(?:>>>|>)\s*(.*?)\s*(?:<<<|<)END_{re.escape(name)}(?:>>>|>)",
            s,
            flags=re.DOTALL | re.IGNORECASE,
        )
        return str(m.group(1) or "").strip() if m else ""

    def _extract_tagged_protocol(self, text: str) -> Dict[str, Any] | None:
        raw = str(text or "")
        if "<<<AW_" not in raw and "<AW_" not in raw:
            return None
        out: Dict[str, Any] = {}
        summary = self._extract_tagged_block(raw, "AW_SUMMARY")
        plan = self._extract_tagged_block(raw, "AW_PLAN")
        analysis = self._extract_tagged_block(raw, "AW_ANALYSIS")
        response = self._extract_tagged_block(raw, "AW_RESPONSE")
        actions_block = self._extract_tagged_block(raw, "AW_ACTIONS")
        handoff = self._extract_tagged_block(raw, "AW_HANDOFF")
        bugs_block = self._extract_tagged_block(raw, "AW_BUGS")
        fixes_block = self._extract_tagged_block(raw, "AW_FIXES")
        if summary:
            out["summary"] = summary
        if plan:
            out["plan"] = plan
        if analysis:
            out["analysis"] = analysis
        if response:
            out["response"] = response
        if handoff:
            out["handoff"] = handoff
        if actions_block:
            out["actions"] = [ln[2:].strip() for ln in actions_block.splitlines() if ln.strip().startswith("- ")]
        if bugs_block:
            out["bugs"] = [ln[2:].strip() for ln in bugs_block.splitlines() if ln.strip().startswith("- ")]
        if fixes_block:
            out["fixes"] = [ln[2:].strip() for ln in fixes_block.splitlines() if ln.strip().startswith("- ")]
        tool_calls: List[Dict[str, Any]] = []
        for m in re.finditer(
            r"(?:<<<|<)AW_TOOL_CALL(?:>>>|>)\s*(.*?)\s*(?:<<<|<)END_AW_TOOL_CALL(?:>>>|>)",
            raw,
            flags=re.DOTALL | re.IGNORECASE,
        ):
            body = str(m.group(1) or "")
            content = self._extract_tagged_block(body, "AW_CONTENT")
            body_wo_content = re.sub(
                r"(?:<<<|<)AW_CONTENT(?:>>>|>).*?(?:<<<|<)END_AW_CONTENT(?:>>>|>)",
                "",
                body,
                flags=re.DOTALL | re.IGNORECASE,
            )
            meta: Dict[str, str] = {}
            for ln in body_wo_content.splitlines():
                if ":" not in ln:
                    continue
                k, v = ln.split(":", 1)
                meta[str(k).strip().lower()] = str(v).strip()
            skill = str(meta.get("skill") or "").strip()
            if not skill:
                continue
            reason = str(meta.get("reason") or "").strip()
            path = str(
                meta.get("path")
                or meta.get("file_path")
                or meta.get("target")
                or meta.get("file")
                or ""
            ).strip()
            op = str(meta.get("op") or "write").strip().lower()
            if skill == "code.apply_patch":
                params: Dict[str, Any] = {"ops": [{"op": op or "write", "path": path, "content": content}]}
            else:
                params = {"path": path, "content": content}
                # If AW_CONTENT is JSON, merge it only for a narrow allowlist of
                # tools that intentionally accept structured payload bodies.
                # Do NOT merge for analytics tools (e.g. sheet.*), otherwise model-
                # invented blobs like {"count":1000} can pollute tool params.
                try:
                    parsed_content = self._extract_json_block(content) if content else None
                except Exception:
                    parsed_content = None
                content_merge_allow = {
                    "pdf.fill_form_fields",
                    "pdf.verify_filled_pdf",
                    "pdf.read_visual_labels",
                }
                if isinstance(parsed_content, dict) and skill in content_merge_allow:
                    params.update(parsed_content)
                # Parse simple key/value fields at the top level of the tagged tool call.
                # This supports model output such as:
                #   output_path: Sonny Mann.pdf
                #   expected_values:
                #     field: value
                for mk, mv in meta.items():
                    if mk in {"skill", "reason", "path", "file_path", "target", "file", "op"}:
                        continue
                    if mv != "":
                        params[mk] = mv

                # Parse nested YAML-like params blocks emitted by the model.
                # The previous parser ignored this block, so pdf.fill_form_fields
                # received only {path, content} and returned {} / no output file.
                nested = self._parse_tagged_tool_params(body_wo_content)
                if nested:
                    if isinstance(nested.get("params"), dict):
                        params.update(nested.get("params") or {})
                    for nk, nv in nested.items():
                        if nk == "params":
                            continue
                        if nk not in {"skill", "reason"}:
                            params[nk] = nv
            tool_calls.append({"skill": skill, "reason": reason, "params": params})
        if tool_calls:
            out["tool_calls"] = tool_calls
        return out or None

    def _parse_tagged_tool_params(self, body: str) -> Dict[str, Any]:
        """Parse a conservative YAML-like subset from an AW_TOOL_CALL body.

        This is intentionally small and dependency-free. It understands:
          key: value
          params:
            key: value
            values:
              field_name: field value
            fields:
              field_name: field value
        The model often emits PDF calls in this shape; without this parser the
        nested values are dropped and the PDF skill receives an empty payload.
        """
        lines = str(body or "").splitlines()
        out: Dict[str, Any] = {}
        stack: List[tuple[int, Any]] = [(-1, out)]

        def coerce(v: str) -> Any:
            val = str(v or "").strip()
            if len(val) >= 2 and ((val[0] == val[-1] == '"') or (val[0] == val[-1] == "'")):
                return val[1:-1]
            low = val.lower()
            if low == "true":
                return True
            if low == "false":
                return False
            if low == "null" or low == "none":
                return None
            # Parse inline JSON-like list/object literals often emitted in
            # tagged tool calls, e.g.:
            #   x: ["2024-01-01","2024-01-02"]
            #   y: [123.4, 456.7]
            # Without this, values stay strings and result.chart payloads
            # become invalid/blank after normalization.
            if (val.startswith("[") and val.endswith("]")) or (val.startswith("{") and val.endswith("}")):
                try:
                    parsed = json.loads(val)
                    if isinstance(parsed, (list, dict)):
                        return parsed
                except Exception:
                    pass
            return val

        list_hint_keys = {
            "aggregations",
            "aggregation",
            "metrics",
            "group_by",
            "fields",
            "values",
            "records",
            "aggregate_records",
            "series",
            "x",
            "y",
            "categories",
            "labels",
            "files",
            "paths",
            "changed_files",
            "final_paths",
            "requested_paths",
            "scoreboard_paths",
            "source_urls",
            "scoreboard_urls",
            "league_paths",
        }

        idx = 0
        while idx < len(lines):
            raw_line = lines[idx]
            if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                idx += 1
                continue
            indent = len(raw_line) - len(raw_line.lstrip(" "))
            while len(stack) > 1 and indent <= stack[-1][0]:
                stack.pop()
            parent = stack[-1][1]
            stripped = raw_line.strip()

            # YAML-like list item support: "- value" or "- key: value"
            if stripped.startswith("- "):
                if not isinstance(parent, list):
                    idx += 1
                    continue
                item_text = stripped[2:].strip()
                if ":" in item_text:
                    k, v = item_text.split(":", 1)
                    k = str(k or "").strip()
                    item: Dict[str, Any] = {}
                    if v.strip() == "":
                        child: Dict[str, Any] = {}
                        if k:
                            item[k] = child
                        parent.append(item)
                        stack.append((indent, item))
                        stack.append((indent + 1, child))
                    else:
                        if k:
                            item[k] = coerce(v)
                        parent.append(item)
                        stack.append((indent, item))
                else:
                    parent.append(coerce(item_text))
                idx += 1
                continue

            if ":" not in raw_line:
                idx += 1
                continue
            key, val = stripped.split(":", 1)
            key = str(key or "").strip()
            if not key:
                idx += 1
                continue
            if val.strip() == "":
                # Prefer list for known collection keys.
                child: Any = [] if key in list_hint_keys else {}
                if isinstance(parent, dict):
                    parent[key] = child
                elif isinstance(parent, list):
                    if parent and isinstance(parent[-1], dict):
                        parent[-1][key] = child
                    else:
                        item = {key: child}
                        parent.append(item)
                stack.append((indent, child))
                idx += 1
            else:
                val_text = str(val or "").strip()
                if val_text in {"|", "|-", ">", ">-"}:
                    block_lines: List[str] = []
                    block_indent: Optional[int] = None
                    consumed_until = idx
                    # Consume following indented lines as the scalar body.
                    for next_idx in range(idx + 1, len(lines)):
                        next_raw = lines[next_idx]
                        if not next_raw.strip():
                            if block_indent is not None:
                                block_lines.append("")
                            continue
                        next_indent = len(next_raw) - len(next_raw.lstrip(" "))
                        if next_indent <= indent:
                            break
                        consumed_until = next_idx
                        if block_indent is None:
                            block_indent = next_indent
                        slice_at = block_indent if block_indent is not None else next_indent
                        block_lines.append(next_raw[slice_at:])
                    block_text = "\n".join(block_lines)
                    if val_text.startswith(">"):
                        block_text = re.sub(r"\n+", " ", block_text).strip()
                    if isinstance(parent, dict):
                        parent[key] = block_text
                    elif isinstance(parent, list):
                        if parent and isinstance(parent[-1], dict):
                            parent[-1][key] = block_text
                        else:
                            parent.append({key: block_text})
                    idx = consumed_until + 1
                    continue
                if isinstance(parent, dict):
                    parent[key] = coerce(val)
                elif isinstance(parent, list):
                    if parent and isinstance(parent[-1], dict):
                        parent[-1][key] = coerce(val)
                    else:
                        parent.append({key: coerce(val)})
                idx += 1
        return out

    def _infer_artifact_path(self, original_request: str, user_text: str) -> str:
        src = " ".join([str(original_request or ""), str(user_text or "")])
        m = re.search(r"([A-Za-z0-9_./\\-]+\.(?:html|js|ts|css|py|md|json))", src, flags=re.IGNORECASE)
        if m:
            return str(m.group(1) or "").strip().replace("\\", "/")
        low = src.lower()
        if "html" in low or "single-file" in low or "single file" in low or "browser" in low or "canvas" in low or "game" in low:
            return "index.html"
        if "javascript" in low or "js" in low:
            return "main.js"
        return "artifact.txt"

    def _is_generic_artifact_name(self, path: str) -> bool:
        rel = str(path or "").strip().replace("\\", "/")
        if not rel:
            return False
        low = rel.lower().strip("/")
        return low in {
            "index.html",
            "index.js",
            "main.js",
            "main.html",
            "game.html",
            "game.js",
            "app.html",
            "app.js",
        }

    def _infer_n_ctx(self) -> str:
        try:
            model = self.core.chat_llm
        except Exception:
            model = None
        for attr in ("n_ctx", "ctx_len", "context_length", "max_context_length"):
            try:
                v = getattr(model, attr, None)
            except Exception:
                v = None
            if v is not None:
                return str(v)
        try:
            reg = (self.core.settings or {}).get("__model_loader_registry")
            gguf = reg.get("model_loader.gguf") if hasattr(reg, "get") else None
            st = getattr(gguf, "_state", {}) if gguf is not None else {}
            if isinstance(st, dict):
                for _k, row in st.items():
                    if not isinstance(row, dict):
                        continue
                    settings = row.get("settings") or {}
                    v = settings.get("n_ctx")
                    if v is not None:
                        return str(v)
        except Exception:
            pass
        return "unknown"

    def _continue_plain_text(
        self,
        base_messages: List[Dict[str, Any]],
        partial_text: str,
        *,
        max_tokens: int,
        temp: float,
    ) -> str:
        if self.core.chat_llm is None:
            return str(partial_text or "")
        combined = str(partial_text or "")
        for _ in range(2):
            try:
                resp = self.core.chat_llm.chat(
                    messages=list(base_messages) + [
                        {"role": "assistant", "content": combined},
                        {
                            "role": "user",
                            "content": (
                                "Continue exactly from where you stopped.\n"
                                "Output ONLY the remaining file content.\n"
                                "Do not repeat prior content. Do not add markdown fences or explanation."
                            ),
                        },
                    ],
                    max_new_tokens=max(512, min(max_tokens, 4000)),
                    temperature=temp,
                    top_p=0.95,
                )
            except Exception:
                break
            tail = self._extract_text(resp).strip()
            if not tail:
                break
            combined += tail
            if len(tail) < 200:
                break
        return combined

    def _generate_artifact_content(
        self,
        *,
        original_request: str,
        artifact_path: str,
        max_tokens: int,
        temp: float,
    ) -> str:
        ext = os.path.splitext(str(artifact_path or "").lower())[1]
        kind = {
            ".html": "a complete runnable HTML file with embedded CSS and JavaScript",
            ".js": "a complete runnable JavaScript file",
            ".css": "a complete CSS file",
            ".py": "a complete Python file",
        }.get(ext, "the complete file content")
        sys_msg = (
            "Generate the requested artifact content.\n"
            f"Output ONLY {kind} for path `{artifact_path}`.\n"
            "Do not wrap in markdown fences.\n"
            "Do not include explanations.\n"
            "Return the full file content directly."
        )
        user_msg = f"User request:\n{original_request}\n\nTarget path:\n{artifact_path}"
        msgs = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}]
        if self.core.chat_llm is not None:
            resp = self.core.chat_llm.chat(
                messages=msgs,
                max_new_tokens=max_tokens,
                temperature=temp,
                top_p=0.95,
            )
            out = self._extract_text(resp).strip()
            extracted = self._extract_artifact_body(out, artifact_path)
            complete = self._artifact_looks_complete(extracted, artifact_path)
            self._emit_diag(
                {
                    "member_stream": (
                        f"artifact draft: path={artifact_path} "
                        f"raw_len={len(out)} "
                        f"html_len={len(extracted)} "
                        f"complete={str(complete).lower()} "
                        f"max_tokens={max_tokens} "
                        f"n_ctx={self._infer_n_ctx()}"
                    )
                }
            )
            if len(out) >= max(1200, int(max_tokens * 0.7)) or not complete:
                self._emit_diag({"member_stream": f"artifact continuation: path={artifact_path}"})
                out = self._continue_plain_text(msgs, out, max_tokens=max_tokens, temp=temp)
                extracted = self._extract_artifact_body(out, artifact_path)
                complete = self._artifact_looks_complete(extracted, artifact_path)
                self._emit_diag(
                    {
                        "member_stream": (
                            f"artifact final: path={artifact_path} "
                            f"raw_len={len(out)} "
                            f"html_len={len(extracted)} "
                            f"complete={str(complete).lower()}"
                        )
                    }
                )
            return extracted
        deck_runner = ModelDeckRunner(
            core=self.core,
            settings=dict(self.core.settings or {}),
            model_type="text_llm",
            slot=f"{self.route_id}_artifact",
            prefer_worker=False,
        )
        try:
            if getattr(deck_runner, "error", None):
                return ""
            pres = deck_runner.plan(
                messages=msgs,
                params={"max_new_tokens": max_tokens, "temperature": temp, "top_p": 0.95},
            )
            if not isinstance(pres, dict) or not pres.get("ok"):
                return ""
            out = self._extract_text((pres or {}).get("raw", "")).strip()
            extracted = self._extract_artifact_body(out, artifact_path)
            complete = self._artifact_looks_complete(extracted, artifact_path)
            self._emit_diag(
                {
                    "member_stream": (
                        f"artifact draft: path={artifact_path} "
                        f"raw_len={len(out)} "
                        f"html_len={len(extracted)} "
                        f"complete={str(complete).lower()} "
                        f"max_tokens={max_tokens} "
                        f"n_ctx={self._infer_n_ctx()}"
                    )
                }
            )
            if len(out) >= max(1200, int(max_tokens * 0.7)) or not complete:
                self._emit_diag({"member_stream": f"artifact continuation: path={artifact_path}"})
                out = self._continue_plain_text(msgs, out, max_tokens=max_tokens, temp=temp)
                extracted = self._extract_artifact_body(out, artifact_path)
                complete = self._artifact_looks_complete(extracted, artifact_path)
                self._emit_diag(
                    {
                        "member_stream": (
                            f"artifact final: path={artifact_path} "
                            f"raw_len={len(out)} "
                            f"html_len={len(extracted)} "
                            f"complete={str(complete).lower()}"
                        )
                    }
                )
            return extracted
        finally:
            try:
                deck_runner.close()
            except Exception:
                pass

    def _extract_artifact_body(self, text: str, artifact_path: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        ext = os.path.splitext(str(artifact_path or "").lower())[1]
        fence_pref = {
            ".html": ["html", "htm"],
            ".js": ["javascript", "js"],
            ".css": ["css"],
            ".py": ["python", "py"],
            ".json": ["json"],
            ".md": ["markdown", "md"],
        }.get(ext, [])
        fence_matches = list(re.finditer(r"```([A-Za-z0-9_-]*)\s*\n(.*?)```", raw, flags=re.DOTALL))
        if fence_matches:
            for lang in fence_pref:
                for m in fence_matches:
                    if str(m.group(1) or "").strip().lower() == lang:
                        return str(m.group(2) or "").strip()
            return str(fence_matches[0].group(2) or "").strip()
        if ext == ".html":
            m = re.search(r"(?is)(<!DOCTYPE html>.*</html>)", raw)
            if m:
                return str(m.group(1) or "").strip()
            m = re.search(r"(?is)(<html.*</html>)", raw)
            if m:
                return str(m.group(1) or "").strip()
        return raw

    def _artifact_looks_complete(self, text: str, artifact_path: str) -> bool:
        body = str(text or "").strip()
        if not body:
            return False
        ext = os.path.splitext(str(artifact_path or "").lower())[1]
        if ext == ".html":
            low = body.lower()
            starts_ok = low.startswith("<!doctype html") or low.startswith("<html")
            ends_ok = ("</html>" in low) and ("</body>" in low or "<body" not in low) and ("</script>" in low or "<script" not in low)
            return starts_ok and ends_ok
        if ext == ".js":
            return not body.endswith(("=", "=>", "{", "[", "(", ",", ".", "const", "let", "var"))
        if ext == ".css":
            return body.count("{") == body.count("}")
        return len(body) > 0

    def _rewrite_to_tagged_protocol(
        self,
        base_messages: List[Dict[str, Any]],
        source_text: str,
        *,
        max_tokens: int,
        temp: float,
    ) -> str:
        rewrite_system = (
            "Rewrite the prior output into TAGGED protocol only.\n"
            "Do not use JSON.\n"
            "Use sections like <<<AW_SUMMARY>>> ... <<<END_AW_SUMMARY>>> and <<<AW_TOOL_CALL>>> blocks.\n"
            "For file writes, prefer skill: code.apply_patch with path/op and raw content inside <<<AW_CONTENT>>>.\n"
            "Do not add markdown fences."
        )
        rewrite_user = f"Rewrite this output into tagged protocol:\n{source_text}"
        rewritten = self._chat_once(
            messages=list(base_messages) + [
                {"role": "system", "content": rewrite_system},
                {"role": "user", "content": rewrite_user},
            ],
            max_tokens=max_tokens,
            temp=temp,
            slot_suffix="tagged_rewrite",
        )
        return rewritten or str(source_text or "")

    def _extract_json_block(self, text: str) -> Any:
        raw = str(text or "").strip()
        if not raw:
            return None
        repaired = self._repair_json_text(raw)
        if repaired:
            try:
                return json.loads(repaired)
            except Exception:
                pass
        try:
            return json.loads(raw)
        except Exception:
            return None

    def _repair_json_text(self, raw: str) -> str:
        s = str(raw or "").strip()
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
        seg = self._extract_balanced_json_segment(s)
        if seg:
            s = seg
        s = re.sub(r",\s*([}\]])", r"\1", s)
        return s

    def _extract_balanced_json_segment(self, raw: str) -> str:
        s = str(raw or "")
        start = -1
        opener = ""
        for i, ch in enumerate(s):
            if ch in "{[":
                start = i
                opener = ch
                break
        if start < 0:
            return ""
        closer = "}" if opener == "{" else "]"
        depth = 0
        in_str = False
        esc = False
        for j in range(start, len(s)):
            ch = s[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return s[start : j + 1]
        return ""


def build_routes(core: RouterCore) -> List[BaseRoute]:
    return [AgentWorkflowMemberRoute(core)]
