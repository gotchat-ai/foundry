from __future__ import annotations

import os
import re
import time
from typing import Any, Callable

from summarizer import classify_print_file_request, summarize_old_turns


class RepoContextService:
    def __init__(
        self,
        *,
        user_rag_getter: Callable[[], Any],
        sess_meta_getter: Callable[[], dict[str, Any]],
    ) -> None:
        self._user_rag_getter = user_rag_getter
        self._sess_meta_getter = sess_meta_getter
        self._repo_analyzer_cache: dict[tuple[str, str, str], dict[str, Any]] = {}

    def _extract_repo_info_from_hit(self, r: dict):
        meta = r.get("meta") or r.get("metadata") or {}

        repo_id = (
            meta.get("repo_id")
            or r.get("repo_id")
            or meta.get("repo")
            or r.get("repo")
            or None
        )

        path = (
            meta.get("path")
            or r.get("path")
            or meta.get("file")
            or r.get("file")
            or meta.get("rel_path")
            or r.get("rel_path")
            or None
        )

        version = meta.get("version") or r.get("version") or None
        kind = meta.get("kind") or r.get("kind") or ""
        role = meta.get("role") or r.get("role") or ""

        return repo_id, path, version, kind, role

    def _detect_print_file_intent(
        self,
        msgs: list[dict],
        *,
        summary_model,
        summary_tokenizer,
    ) -> tuple[bool, str | None, str | None]:
        """
        Use the summarizer model to decide if the user is asking
        to print a file, and if so, which repo_id/path.
        """
        print(32423425)
        if not msgs or summary_model is None or summary_tokenizer is None:
            return False, None, None

        try:
            print(3523346)
            result = classify_print_file_request(
                summary_model,
                summary_tokenizer,
                msgs=msgs,
                max_new_tokens=64,
            )
        except Exception as e:
            print(e)
            print(3425235)
            return False, None, None

        if not isinstance(result, dict):
            return False, None, None

        print("result.get(print_file)", result.get("print_file"))
        print_file = bool(result.get("print_file"))
        print("print_file: ", print_file)
        repo_id = result.get("repo_id")
        path = result.get("path")

        if not print_file:
            return False, None, None

        # Normalize empties
        if repo_id is not None and not repo_id.strip():
            repo_id = None
        if path is not None and not path.strip():
            path = None

        return True, repo_id, path

    def _note_repo_for_sid(self, sid: str, repo_id: str) -> None:
        """
        Record that `repo_id` is associated with this sid (which we're treating as pid/project).
        Used for listing repos per project in the UI.
        """
        sid = (sid or "").strip()
        repo_id = (repo_id or "").strip()
        if not sid or not repo_id:
            return

        sess_meta = self._sess_meta_getter()
        meta = sess_meta.setdefault(sid, {})
        lst = meta.get("repo_ids")
        if not isinstance(lst, list):
            lst = []
        if repo_id not in lst:
            lst.append(repo_id)
        meta["repo_ids"] = lst

    def _count_tokens(self, tokenizer, text: str) -> int:
        if not text:
            return 0
        if tokenizer is None:
            # rough fallback
            return max(1, len(text) // 4)
        try:
            return len(tokenizer.encode(text))
        except Exception:
            return max(1, len(text) // 4)

    def _summarize_chat_hits(
        self,
        sid: str,
        hits: list[dict],
        *,
        summary_model,
        summary_tokenizer,
        existing_summary: str | None = None,
        max_input_chars: int = 4000,
        max_new_tokens: int = 256,
        style: str = "bullets",
    ) -> str:
        """
        Adapt user_rag chat hits into a rolling summary using summarizer.py.

        - sid: session id (not strictly needed here, but handy if you later want logging)
        - hits: user_rag search results for chat (NOT repo/code) docs
        - summary_model: underlying torch model (NOT the HFChatModel wrapper)
        - summary_tokenizer: HF tokenizer
        - existing_summary: optional previous summary to fold in
        """
        # print(2422323523)
        if not hits or summary_model is None or summary_tokenizer is None:
            return existing_summary or ""
        # print(23423534634643)

        # Convert hits → messages[List[{"role","content"}]] for summarizer._format_dialog()
        messages: list[dict] = []
        total_chars = 0

        for h in hits:
            meta = h.get("meta") or h.get("metadata") or {}
            text = (h.get("text") or meta.get("text") or "").strip()
            if not text:
                continue

            role = (meta.get("role") or "").lower()
            if role not in ("user", "assistant", "system"):
                role = "assistant"

            # Enforce a rough char budget for summarizer input
            if total_chars + len(text) > max_input_chars:
                remaining = max_input_chars - total_chars
                if remaining <= 0:
                    break
                text = text[:remaining]

            messages.append({"role": role, "content": text})
            total_chars += len(text)
            if total_chars >= max_input_chars:
                break

        # print("messages: ", messages)
        if not messages:
            return existing_summary or ""

        # Call summarizer.summarize_old_turns with the new-style signature.

        try:
            summary = summarize_old_turns(
                summary_model,
                summary_tokenizer,
                messages,
                existing_summary=existing_summary,
                max_new_tokens=int(max_new_tokens),
                temperature=0.0,
                style=str(style or "bullets"),
            )
            if summary:
                return summary.strip()
        except TypeError as e:
            print(e)
            print(23423423)
            # Fallback for older summarizer versions that accept plain text
            try:
                blob = "\n\n".join(
                    f"{m['role'].upper()}:\n{m['content']}" for m in messages
                )
                summary = summarize_old_turns(
                    summary_model,
                    summary_tokenizer,
                    blob,
                    existing_summary=existing_summary,
                    max_new_tokens=int(max_new_tokens),
                )
                if summary:
                    return summary.strip()
            except Exception as e:
                print(e)
                print(3453443)
                pass
        except Exception as e:
            print(e)
            print(24352352452)
            # Don’t break the request if summarization fails
            pass

        return existing_summary or ""

    def _norm_rel_path(self, p: str) -> str:
        p = (p or "").replace("\\", "/").strip()
        while p.startswith("/"):
            p = p[1:]
        parts = []
        for seg in p.split("/"):
            if not seg or seg == ".":
                continue
            if seg == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(seg)
        return "/".join(parts)

    def _extract_rel_path_from_query(self, text: str) -> str | None:
        if not text:
            return None
        m = re.search(r"([A-Za-z0-9_\-./\\]+\\.[A-Za-z0-9_]{1,6})", text)
        if not m:
            return None
        p = self._norm_rel_path(m.group(1))
        return p if p else None

    def _wants_read_most(self, query: str) -> bool:
        q = (query or "").lower()
        return any(
            s in q
            for s in (
                "read most",
                "most of it",
                "show most",
                "walk me through",
                "entire folder",
                "whole folder",
            )
        )

    def _should_enable_repo_context(self, query: str, ext: dict) -> bool:
        if not ext:
            return False
        sel_repo = (ext.get("selected_repo_id") or "").strip()
        if not sel_repo:
            return False

        sel_file = (ext.get("selected_entry_path") or "").strip()
        sel_pref = (ext.get("selected_path_prefix") or "").strip()
        if sel_file or sel_pref:
            return True

        q = (query or "").lower()
        keywords = (
            "repo",
            "repository",
            "file",
            "folder",
            "directory",
            "path",
            "read",
            "open",
            "print",
            "show",
            "explain",
            "function",
            "class",
            "definition",
            "import",
            "called by",
            "call graph",
        )
        return any(k in q for k in keywords)

    def _iter_cold_docs_for_sid(self, user_rag, sid: str):
        st = user_rag._get_cold_store(sid)
        if hasattr(st, "iter_docs"):
            yield from st.iter_docs()
            return
        # fallback: common in-memory shape
        if hasattr(st, "docs") and isinstance(st.docs, dict):
            for did, rec in st.docs.items():
                meta = rec.get("meta") or rec.get("metadata") or {}
                yield {"id": did, "text": rec.get("text", ""), "meta": meta}

    def _get_repo_analyzer_index(self, user_rag, sid: str, repo_id: str, prefix: str, ttl_sec: int = 60):
        """
        Builds a lightweight relationship index from repo_analyzer cold docs:
        - by_path[path] = {imports:set, calls:set, defs:[{sig,doc,text,kind,fqn}]}
        - symbol_to_paths[last_symbol] = set(paths)
        """
        key = (sid, repo_id, prefix or "")
        now = time.time()
        cached = self._repo_analyzer_cache.get(key)
        if cached and (now - cached["ts"]) < ttl_sec:
            return cached["idx"]

        by_path = {}
        symbol_to_paths = {}

        max_docs = 20000
        n = 0
        for d in self._iter_cold_docs_for_sid(user_rag, sid):
            n += 1
            if n > max_docs:
                break
            meta = d.get("meta") or d.get("metadata") or {}
            if meta.get("repo_id") != repo_id:
                continue
            if not meta.get("repo_analyzer"):
                continue

            path = self._norm_rel_path(meta.get("path") or "")
            if not path:
                continue
            if prefix and not path.startswith(prefix):
                continue

            rec = by_path.setdefault(path, {"imports": set(), "calls": set(), "defs": []})

            for imp in meta.get("imports") or []:
                if isinstance(imp, str) and imp:
                    rec["imports"].add(imp)

            for call in meta.get("calls") or []:
                if isinstance(call, str) and call:
                    rec["calls"].add(call)

            fqn = (meta.get("fqn") or "").strip()
            if fqn:
                last = fqn.split(".")[-1]
                if last:
                    sset = symbol_to_paths.setdefault(last, set())
                    if len(sset) < 50:
                        sset.add(path)

            # Keep compact "definition" snippets (signature/docstring-heavy)
            sig = (meta.get("signature") or "").strip()
            doc = (meta.get("docstring") or "").strip()
            kind = (meta.get("kind") or "").strip()
            txt = (d.get("text") or "").strip()
            if txt or sig or doc:
                defs = rec["defs"]
                if len(defs) < 40:
                    defs.append(
                        {
                            "fqn": fqn,
                            "kind": kind,
                            "signature": sig,
                            "docstring": doc,
                            "text": txt,
                        }
                    )

        idx = {"by_path": by_path, "symbol_to_paths": symbol_to_paths}
        self._repo_analyzer_cache[key] = {"ts": now, "idx": idx}
        return idx

    def _safe_repo_file_excerpt(self, user_rag, sid: str, repo_id: str, rel_path: str, version, max_chars: int) -> str:
        rel_path = self._norm_rel_path(rel_path)
        if not rel_path or os.path.isabs(rel_path) or ".." in rel_path.split("/"):
            return ""
        txt = user_rag.get_repo_file_from_lib_repo_files(
            sid=sid,
            repo_id=repo_id,
            rel_path=rel_path,
            version=version,
            max_chars=0,
        ) or ""
        if max_chars and len(txt) > max_chars:
            return txt[:max_chars]
        return txt

    def _outline_from_defs(self, defs: list, max_items: int = 12) -> str:
        """
        Deterministic "summary" without an LLM: list signatures/fqns.
        """
        out = []
        for d in defs[:max_items]:
            sig = d.get("signature") or ""
            fqn = d.get("fqn") or ""
            kind = d.get("kind") or ""
            line = sig.strip() or fqn.strip()
            if not line:
                continue
            if kind:
                out.append(f"- {kind}: {line}")
            else:
                out.append(f"- {line}")
        return "\n".join(out).strip()

    def _select_repo_snippets_for_hit(
        self,
        sid: str,
        hit: dict,
        *,
        tokenizer,
        per_hit_token_budget: int,
        max_window_lines: int = 20,
    ) -> str:
        print(23423523)
        """
        For a repo hit, either:
        - include full file if under per_hit_token_budget, or
        - include only relevant function chunks (symbol + its calls), under the same budget.
        """
        meta = hit.get("meta") or hit.get("metadata") or {}
        # print("hit: ", hit)
        # print("meta", meta)
        repo_id, path, version, kind, role = self._extract_repo_info_from_hit(hit)
        print("repo_id:", repo_id, " path:", path, version, kind, role)
        print(24234235235)
        if not path:
            return ""
        try:
            calls = meta.get("calls") or []
            fqn = meta.get("fqn") or meta.get("symbol") or ""
            symbol_name = fqn.split(".")[-1] if fqn else ""
        except Exception as e:
            print(e)
            calls = []
            fqn = ""
            symbol_name = ""

        # Load full file
        print(sid, repo_id, path, version)
        try:
            user_rag = self._user_rag_getter()
            full_code = user_rag.get_repo_file_from_lib_repo_files(
                sid=sid,
                repo_id=repo_id,
                rel_path=path,
                version=version,
                max_chars=0,  # 0/None = no char cap; we'll enforce by tokens
            )
        except Exception as e:
            print(e)
            full_code = ""

        if not full_code:
            return ""

        # If full file fits in the per-hit budget, just return it.
        full_tokens = self._count_tokens(tokenizer, full_code)
        print("full_tokens", full_tokens)
        print("len(full_code)", len(full_code))
        if full_tokens <= per_hit_token_budget:
            return full_code

        # Otherwise, fall back to selecting relevant windows in the file.
        lines = full_code.splitlines()
        n = len(lines)

        # Build anchor terms (symbol + calls)
        anchor_terms = set()
        if symbol_name:
            anchor_terms.add(symbol_name)
        for c in calls:
            if isinstance(c, str) and c:
                anchor_terms.add(c.split(".")[-1])

        if not anchor_terms:
            # No anchors; take just the top of file, constrained by token budget
            snippet = "\n".join(lines[: max_window_lines * 2])
            t = self._count_tokens(tokenizer, snippet)
            if t > per_hit_token_budget:
                approx_chars = per_hit_token_budget * 4
                snippet = snippet[:approx_chars]
            return snippet

        # Find line windows around anchors
        windows = []
        for idx, line in enumerate(lines):
            for term in anchor_terms:
                if term and term in line:
                    start = max(0, idx - max_window_lines)
                    end = min(n, idx + max_window_lines)
                    windows.append((start, end))
                    break

        if not windows:
            snippet = "\n".join(lines[: max_window_lines * 2])
            t = self._count_tokens(tokenizer, snippet)
            if t > per_hit_token_budget:
                approx_chars = per_hit_token_budget * 4
                snippet = snippet[:approx_chars]
            return snippet

        # Merge overlapping windows
        windows.sort()
        merged = []
        cur_start, cur_end = windows[0]
        for s, e in windows[1:]:
            if s <= cur_end:
                cur_end = max(cur_end, e)
            else:
                merged.append((cur_start, cur_end))
                cur_start, cur_end = s, e
        merged.append((cur_start, cur_end))

        # Accumulate under token budget
        pieces = []
        used_tokens = 0

        for start, end in merged:
            snippet = "\n".join(lines[start:end])
            if not snippet:
                continue

            t = self._count_tokens(tokenizer, snippet)
            if used_tokens + t > per_hit_token_budget:
                remaining = per_hit_token_budget - used_tokens
                if remaining <= 0:
                    break
                approx_chars = remaining * 4
                snippet = snippet[:approx_chars]
                if not snippet.strip():
                    break
                pieces.append(snippet)
                used_tokens += self._count_tokens(tokenizer, snippet)
                break
            else:
                pieces.append(snippet)
                used_tokens += t

            if used_tokens >= per_hit_token_budget:
                break

        return "\n\n".join(pieces)

    def _merge_urag_hits(self, hit_lists, k_total):
        # ex  hits = _merge_urag_hits([session_hits, project_hits], k_total=k_total)
        merged = []
        seen = set()
        for lst in hit_lists:
            if not lst:
                continue
            for h in lst:
                doc_id = h.get("id") or h.get("doc_id")
                if doc_id and doc_id in seen:
                    continue
                seen.add(doc_id)
                merged.append(h)
        # sort by score desc if present
        merged.sort(key=lambda h: h.get("score", 0.0), reverse=True)
        return merged[:k_total]

    def _clamp_text(self, s: str, max_chars: int) -> str:
        s = s or ""
        return s if len(s) <= max_chars else s[:max_chars]

    def _extend_context_with_userrag_budgeted(self, messages: list[dict], urag_cfg: dict):
        try:
            sid = urag_cfg.get("sid") or ""
            # project_id = urag_cfg.get("project_id") or None
            user_rag = self._user_rag_getter()
            if not sid or not messages or user_rag is None:
                return [], []

            # last user
            last_user = None
            for m in reversed(messages):
                if m.get("role") == "user":
                    last_user = m
                    break
            if not last_user:
                return [], []

            query = (last_user.get("content") or "").strip()
            # print("query:", query)
            if not query:
                return [], []

            selected_repo_id = (urag_cfg.get("selected_repo_id") or "").strip()
            selected_prefix = (urag_cfg.get("selected_path_prefix") or "").replace("\\", "/").strip()
            selected_entry = (urag_cfg.get("selected_entry_path") or "").replace("\\", "/").strip()

            # repo_ctx_on = bool(urag_cfg.get("repo_context_mode"))
            read_most = bool(urag_cfg.get("repo_context_read_most"))

            max_files = int(urag_cfg.get("repo_ctx_max_files", 8))
            per_file_max_chars = int(urag_cfg.get("repo_ctx_per_file_max_chars", 8000))
            max_defs = int(urag_cfg.get("repo_ctx_max_defs", 24))
            outline_items = int(urag_cfg.get("repo_ctx_outline_items", 12))

            repo_context_used = urag_cfg.get("_repo_context_used") or []

            repo_context_mode = bool(urag_cfg.get("repo_context_mode") or False)

            # If a file is selected, automatically enable repo-context mode
            if selected_entry:
                repo_context_mode = True

            tokenizer = urag_cfg.get("summary_tokenizer")
            extra_budget_tokens = int(urag_cfg.get("extra_budget_tokens", 0) or 0)
            if extra_budget_tokens <= 0:
                return [], []

            budget_tokens = int(urag_cfg.get("budget_tokens") or 0)
            max_tokens = max(0, budget_tokens + extra_budget_tokens)
            if max_tokens <= 0:
                return [], []

            k_total = int(urag_cfg.get("top_k", 15) or 15)
            max_chars = int(urag_cfg.get("max_chars", 8000) or 8000)

            # Reserve budget for repo when repo-context is on
            repo_reserve = int(urag_cfg.get("repo_reserve_tokens", int(extra_budget_tokens * (0.65 if repo_context_mode else 0.25))))
            repo_reserve = max(0, min(repo_reserve, extra_budget_tokens))
            chat_reserve = extra_budget_tokens - repo_reserve

            urag_cfg.setdefault("repo_k", 40)  # how many repo hits to consider
            urag_cfg.setdefault("chat_k", 20)  # chat hits to consider
            urag_cfg.setdefault("max_hit_chars", 12000)  # clamp any single hit

            try:
                hot_hits = user_rag.search(sid, query, k=k_total, max_chars=max_chars)
            except Exception as e:
                print(2342342323)
                print(e)
                hot_hits = []
            try:
                cold_hits = user_rag.cold_search(
                    sid,
                    query,
                    k=k_total,
                    max_chars=max_chars,
                    version_mode="",
                )
                # In normal chat-memory mode, use cold chat records too.  Repo
                # cold context is handled by the repo-context branch and should
                # not pollute ordinary conversation memory.
                cold_hits = [
                    h for h in (cold_hits or [])
                    if str(((h.get("metadata") or {}).get("kind") or "")).lower().startswith("chat_")
                ]
            except Exception as e:
                if "object has no attribute 'search'" not in str(e):
                    print("[user_rag] cold chat search failed:", e)
                cold_hits = []
            try:
                cold_store = user_rag._get_cold_store(sid)
                recent_docs = []
                iter_docs = getattr(cold_store, "iter_docs", None)
                if callable(iter_docs):
                    for doc in iter_docs():
                        meta = doc.get("meta") or doc.get("metadata") or {}
                        kind = str(meta.get("kind") or "").lower()
                        if not kind.startswith("chat_"):
                            continue
                        text = str(doc.get("text") or "").strip()
                        if not text:
                            continue
                        recent_docs.append(
                            {
                                "id": doc.get("id"),
                                "score": 0.50,
                                "text": text[:max_chars],
                                "metadata": meta,
                            }
                        )
                # Recent chat turns are important for Budget / Last Assistant
                # context even when semantic search is unavailable or weak.
                if recent_docs:
                    cold_hits.extend(recent_docs[-8:])
            except Exception as e:
                print("[user_rag] recent cold chat fallback failed:", e)

            hits = []
            seen_hit_ids = set()
            for h in list(hot_hits or []) + list(cold_hits or []):
                doc_id = h.get("id") or h.get("doc_id")
                key = doc_id or (str(h.get("text") or "")[:128])
                if key in seen_hit_ids:
                    continue
                seen_hit_ids.add(key)
                hits.append(h)
            hits.sort(key=lambda h: float(h.get("score") or 0.0), reverse=True)
            hits = hits[:k_total]

            if not hits:
                return [], []

            chat_hits = []
            repo_hits = []
            code_hits = []
            used_ids = []

            selected_repo_id = (urag_cfg.get("selected_repo_id") or "").strip() or None

            for h in hits:
                doc_id = h.get("id") or h.get("doc_id")
                meta = h.get("meta") or h.get("metadata") or {}
                kind = (meta.get("kind") or "").lower()

                repo_id, path, _, _, role = self._extract_repo_info_from_hit(h)
                # print("inside budget Repo-id: ", repo_id)
                # print("selected_repo_id: ", selected_repo_id)
                # print("path: ", path)
                # print("selected_prefix: ", selected_prefix)
                # print("h--------", h)

                # If the user picked a repo in the dropdown, only allow repo chunks from that repo
                if (repo_id or path) and selected_repo_id and str(repo_id).strip() != selected_repo_id:
                    continue

                # if path:
                #     if selected_repo_id and str(repo_id).strip() != selected_repo_id:
                #         continue
                #     if selected_prefix and not str(path).startswith(selected_prefix):
                #         continue
                #     print(2342323)
                #     repo_hits.append(h)
                # #elif kind in ("code", "snippet") or role == "assistant" or kind.endswith("chat_assistant_code"):
                # el

                if role == "assistant" and kind.endswith("chat_assistant_code"):
                    code_hits.append(h)
                else:
                    chat_hits.append(h)

                if doc_id:
                    used_ids.append(doc_id)

            blocks = []
            tokens_used = 0
            print(2342352)

            # 3) Assistant-generated code snippets (optional, also budgeted)
            print("tokens_used: ", tokens_used)
            print("extra_budget_tokens: ", extra_budget_tokens)
            print("code_hits:", code_hits)
            if tokens_used < extra_budget_tokens and code_hits:
                print("Assistant generated code_blocks")
                remaining = max(0, extra_budget_tokens - tokens_used)
                per_code_tokens = max(64, remaining // max(1, len(code_hits)))
                code_blocks = []

                for h in code_hits:
                    meta = h.get("meta") or h.get("metadata") or {}
                    text = (h.get("text") or meta.get("text") or "").strip()
                    if not text:
                        continue
                    # trim to per_code_tokens
                    t = self._count_tokens(tokenizer, text)
                    if t > per_code_tokens:
                        approx_chars = per_code_tokens * 4
                        text = text[:approx_chars]
                        t = self._count_tokens(tokenizer, text)

                    if tokens_used + t > extra_budget_tokens:
                        break

                    score = float(h.get("score") or 0.0)
                    code_blocks.append(
                        f"[Code note {len(code_blocks)+1}] (score {score:.3f})\n{text}"
                    )
                    tokens_used += t
                    if tokens_used >= extra_budget_tokens:
                        break

                if code_blocks:
                    blocks.append(
                        "Previously generated code that may be relevant:\n\n"
                        + "\n\n".join(code_blocks)
                    )

            # 1) Chat summary via summarizer.py (budgeted)
            if chat_hits:
                print("chat_hits")
                summary_model = urag_cfg.get("summary_model")
                summary_tokenizer = urag_cfg.get("summary_tokenizer")
                max_summary_tokens = int(urag_cfg.get("summary_max_new_tokens", 256) or 256)

                # we won't let summary exceed half the extra budget
                max_summary_tokens = min(max_summary_tokens, extra_budget_tokens // 2)

                chat_summary = self._summarize_chat_hits(
                    sid,
                    chat_hits,
                    summary_model=summary_model,
                    summary_tokenizer=summary_tokenizer,
                    existing_summary=None,
                    max_input_chars=urag_cfg.get("summary_input_char_cap", 4000),
                    max_new_tokens=max_summary_tokens,
                    style=urag_cfg.get("summary_style", "bullets"),
                )

                # print("chat_summary: ", chat_summary)

                if chat_summary:
                    t = self._count_tokens(tokenizer, chat_summary)
                    if tokens_used + t < extra_budget_tokens:
                        blocks.append("Chat summary may not be neccessarly related the file witin the repo id. Conversation summary:\n" + chat_summary)
                        # blocks.append("You are an image analyzer. If a user attached an image path read it and analyze if for the user. Conversation summary:\n")
                        tokens_used += t
                else:
                    # Memory retrieval should not depend on the optional side
                    # summarizer being loaded.  When summarization is
                    # unavailable or returns empty, inject compact raw chat
                    # snippets so Budget / Last Assistant modes can still
                    # remember prior turns.
                    raw_blocks = []
                    remaining = max(0, extra_budget_tokens - tokens_used)
                    per_hit_tokens = max(48, min(256, remaining // max(1, len(chat_hits))))
                    for h in chat_hits:
                        text = str(h.get("text") or "").strip()
                        if not text:
                            continue
                        score = float(h.get("score") or 0.0)
                        if self._count_tokens(tokenizer, text) > per_hit_tokens:
                            text = text[: max(160, per_hit_tokens * 4)].rstrip()
                        raw_blocks.append(f"[Memory {len(raw_blocks)+1}] score={score:.3f}\n{text}")
                        tokens_used += self._count_tokens(tokenizer, text)
                        if tokens_used >= extra_budget_tokens:
                            break
                    if raw_blocks:
                        blocks.append("Relevant prior conversation memory:\n\n" + "\n\n".join(raw_blocks))

            if not blocks:
                return [], []

            rag_block = (
                "You have external memory (summaries, past code, and repo code) related to the user's question. "
                "Use it to answer, but do not mention scores or internal IDs.\n\n"
                + "\n\n".join(blocks)
            )

            # rag_block = (
            #     "\n\n"
            #     + "\n\n".join(blocks)
            # )

            extra = [{"role": "system", "content": rag_block}]
        except Exception as e:
            print(34242342)
            print(e)
            extra = []
            used_ids = []
        return extra, used_ids
