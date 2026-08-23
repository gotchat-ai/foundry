from __future__ import annotations

import re
import os
import hashlib
from typing import Any, Callable, Dict

import requests


class LibRagFetchService:
    def __init__(self, *, lib_store_getter: Callable[[], Any]) -> None:
        self._lib_store_getter = lib_store_getter

    def _fetch_url_text(self, url: str) -> str:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        ct = (r.headers.get("content-type") or "").lower()
        if "pdf" in ct:
            # write temp and use pdf extractor through lib_store
            import tempfile
            t = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            t.write(r.content); t.flush(); t.close()
            text = ""
            try:
                text = self._lib_store_getter().ingest_pdf("__tmp__", t.name).get("text","")  # not actually stored; just reuse extractor
            except Exception:
                pass
            try: os.remove(t.name)
            except Exception: pass
            if not text: text = r.text
            return text
        # default html/text
        return r.text

    def _background_refresh_loop(
        self,
        *,
        lib_refresh_load: Callable[[], None],
        lib_refresh_save: Callable[[], None],
        lib_refresh_getter: Callable[[], dict[str, Any]],
        lib_thread_stop_getter: Callable[[], bool],
        lib_rag_getter: Callable[[], Any],
        time_module: Any,
    ) -> None:
        lib_refresh_load()
        while not lib_thread_stop_getter():
            try:
                now = int(time_module.time())
                changed = False
                for item in lib_refresh_getter().get("items", []):
                    lib_id = item.get("lib_id"); url = item.get("url"); interval = int(item.get("interval_sec", 86400))
                    last_ts = int(item.get("last_ts", 0))
                    if now - last_ts < interval:
                        continue
                    # fetch
                    try:
                        raw = self._fetch_url_text(url)
                        txt = raw if isinstance(raw, str) else str(raw)
                        h = hashlib.blake2s(txt.encode("utf-8"), digest_size=16).hexdigest()
                        if h != item.get("last_hash"):
                            # store into LibRAG
                            tags = item.get("tags") or []
                            lib_rag_getter().ingest_text(lib_id, txt, source=url, tags=tags)
                            item["last_hash"] = h
                        item["last_ts"] = now
                        changed = True
                    except Exception as e:
                        item["last_ts"] = now  # avoid hot loop; keep hash unchanged
                        changed = True
                if changed: lib_refresh_save()
            except Exception:
                pass
            # sleep a bit
            for _ in range(30):
                if lib_thread_stop_getter(): break
                time_module.sleep(2)


class LibRagContextService:
    def __init__(
        self,
        *,
        normalize_messages: Callable[[Any], list[dict]],
        truncate_chars: Callable[[str, int], str],
        tok: Callable[[str], int],
        pack_snippets_block: Callable[[str, list], list],
        lib_store_getter: Callable[[], Any],
        user_rag_getter: Callable[[], Any],
        settings_getter: Callable[[], dict[str, Any]],
        sess_meta_getter: Callable[[], dict[str, Any]],
        headroom_frac_getter: Callable[[], float],
    ) -> None:
        self._normalize_messages = normalize_messages
        self._truncate_chars = truncate_chars
        self._tok = tok
        self._pack_snippets_block = pack_snippets_block
        self._lib_store_getter = lib_store_getter
        self._user_rag_getter = user_rag_getter
        self._settings_getter = settings_getter
        self._sess_meta_getter = sess_meta_getter
        self._headroom_frac_getter = headroom_frac_getter

    def _extend_context_with_librag(
        self,
        messages,
        lib_ids: list[str] | None,
        top_k: int = 4,
        min_score: float = 0.08,
        assoc_expand: bool = True,
        assoc_k_each: int = 2,
    ):
        """Given the last user message as query, fetch LibRAG notes and prepend a compact context block."""
        messages = self._normalize_messages(messages)
        lib_store = self._lib_store_getter()
        if lib_store is None:
            return [], []
        query = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                query = m.get("content", "")
                break
        if not query:
            return [], []
        hits = lib_store.search(
            query,
            lib_ids=lib_ids,
            top_k=top_k,
            min_score=min_score,
            assoc_expand=assoc_expand,
            assoc_k_each=assoc_k_each,
        )
        notes = []
        ids = []
        for h in hits:
            ids.append(h["note_id"])
            snippet = h["text"]
            if len(snippet) > 800:
                snippet = snippet[:800] + " ..."
            notes.append(f"[LIB {h['lib_id']} | {h['note_id']} | score={h['score']:.2f}] {snippet}")
        if not notes:
            return [], []
        sys = {
            "role": "system",
            "content": "External library context (lower priority than user notes):\n" + "\n".join(notes),
        }
        return [sys], ids

    def _promote_librag_hits_to_hot(self, user_rag, sid: str, hits: list, cfg: dict):
        import time as _t

        try:
            if not hits:
                return {"promoted": 0, "skipped": 0, "reason": "no_hits"}

            pcfg = (cfg or {}).get("promote") or {}
            if not cfg.get("promote_librag_hits", False):
                return {"promoted": 0, "skipped": len(hits), "reason": "disabled"}

            min_score = float(pcfg.get("min_score", 0.18))
            top_k = int(pcfg.get("top_k", 4))
            char_cap = int(pcfg.get("snippet_char_cap", 800))
            tokens_cap = int(pcfg.get("tokens_cap", 1500))

            # Keep higher-scored first
            sel = sorted(
                [h for h in hits if (h.get("score") or 0.0) >= min_score],
                key=lambda h: -(h.get("score") or 0.0),
            )[: max(1, top_k)]

            approx_tokens = 0
            docs, seen = [], set()
            for h in sel:
                meta = h.get("meta") or h.get("metadata") or {}
                lib_id = h.get("lib_id") or meta.get("lib_id") or ""
                path = meta.get("path") or meta.get("source") or ""
                text = (h.get("text") or "")[:char_cap].strip()
                if not text:
                    continue

                did = f"lib|{lib_id}|{path}|{abs(hash(text))}"
                if did in seen:
                    continue

                tk = max(1, len(text) // 4)
                if approx_tokens + tk > max(128, tokens_cap):
                    continue

                docs.append(
                    {
                        "id": did,
                        "text": text,
                        "metadata": {
                            "source": f"lib:{lib_id}",
                            "path": path,
                            "type": "promoted",
                            "score": h.get("score", 0.0),
                            "ts": int(_t.time()),
                        },
                    }
                )
                approx_tokens += tk
                seen.add(did)

            if not docs:
                return {"promoted": 0, "skipped": len(hits), "reason": "budget_zero_or_empty"}

            user_rag.import_docs(sid, docs)
            return {"promoted": len(docs), "skipped": max(0, len(hits) - len(docs)), "approx_tokens": approx_tokens}

        except Exception as e:
            return {"promoted": 0, "skipped": len(hits), "error": str(e)}

    def _extend_context_with_librag_gated(
        self,
        messages,
        lib_cfg: Dict[str, Any],
        sid: None,
        diag: None,
        *,
        promote_librag_hits_to_hot: Callable[[Any, str, list, dict], dict],
    ) -> tuple[list[dict], list[str], list[str]]:
        """
        lib_cfg: {
        "use_lib_rag": bool,
        "lib_ids": [..] | None,
        "auto_enable_by_tags": bool,
        "preferred_tags": [..] | None,
        "top_k": int,
        "min_score": float,
        "tags_any": [..] | None,
        "tags_all": [..] | None
        }
        Returns: (extra_messages, note_ids_used, libs_selected)
        """
        messages = self._normalize_messages(messages)
        if not lib_cfg or not lib_cfg.get("use_lib_rag"):
            return [], [], []
        lib_store = self._lib_store_getter()
        if lib_store is None:
            return [], [], []
        # last user content
        query = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                query = m.get("content", "")
                break
        if not query:
            return [], [], []
        selected_libs = lib_cfg.get("lib_ids")
        if (not selected_libs) and lib_cfg.get("auto_enable_by_tags"):
            selected_libs = lib_store.route_libs_by_tags(query, lib_cfg.get("preferred_tags"))

        # Persist session's last resolved lib selection
        self._sess_meta_getter().setdefault(sid, {})["sticky_lib_ids"] = selected_libs or []

        # Ensure session-selected libs are hot in RAM with headroom; evict others
        try:
            import lib_rag_hot

            _base_dir = getattr(lib_store, "cold_base_dir", None) or getattr(lib_store, "base_dir", ".")
            _desired_libs = selected_libs or []
            _budget = lib_rag_hot.ensure_hot_for_libs_with_budget(
                _base_dir,
                _desired_libs,
                headroom_frac=self._headroom_frac_getter(),
                unload_others=True,
            )
            if _budget.get("blocked"):
                diag["hotlib_blocked"] = {
                    "reason": _budget.get("reason"),
                    "required": _budget.get("required"),
                    "allow": _budget.get("allow"),
                }
        except Exception as _e:
            diag["hotlib_error"] = str(_e)

        hits = lib_store.search_gated(
            query,
            lib_ids=selected_libs,
            top_k=int(lib_cfg.get("top_k", 4)),
            min_score=float(lib_cfg.get("min_score", 0.08)),
            recency_boost=0.15,
            tags_any=lib_cfg.get("tags_any"),
            tags_all=lib_cfg.get("tags_all"),
        )
        # inside _extend_context_with_librag_gated, after you have `hits`
        settings = self._settings_getter()
        try:
            if (
                settings.get("promote_librag_hits", False)
                and hits
                and not diag.get("_promoted_librag_done")  # <— guard
            ):
                prom = promote_librag_hits_to_hot(self._user_rag_getter(), sid, hits, settings)
                diag["promote"] = prom
                diag["_promoted_librag_done"] = True  # <— mark done
        except Exception as _e:
            diag["promote_error"] = str(_e)

        if not hits:
            return [], [], selected_libs or []
        note_ids = [h["note_id"] for h in hits]
        lines = []
        for h in hits:
            snippet = h["text"]
            if len(snippet) > 800:
                snippet = snippet[:800] + " ..."
            tags = (h.get("meta") or h.get("metadata") or {}).get("tags") or []
            lines.append(f"[LIB {h['lib_id']} | {h['note_id']} | score={h['score']:.2f} | tags={','.join(tags)}] {snippet}")
        sys_msg = {"role": "system", "content": "External library context (lower priority than user notes):\n" + "\n".join(lines)}
        return [sys_msg], note_ids, selected_libs or []

    def _extend_context_with_librag_budgeted(
        self,
        messages,
        lib_cfg: dict,
        sid: None,
        diag: None,
        *,
        extend_context_with_librag_gated: Callable[[Any, dict, Any, Any], tuple[list[dict], list[str], list[str]]],
    ) -> tuple[list[dict], list[str]]:
        """Wrap existing gated search but enforce snippet caps + token budget; returns (extra_messages, note_ids_used)."""
        messages = self._normalize_messages(messages)
        extra, note_ids, libs_selected = extend_context_with_librag_gated(messages, lib_cfg, sid, diag)
        if not extra:
            return [], []
        text = extra[0].get("content", "")
        parts = text.split("\n", 1)
        payload = parts[1] if len(parts) > 1 else ""
        items = [s for s in payload.split("\n\n") if s.strip()]
        max_chars = int(lib_cfg.get("snippet_char_cap", 700) or 700)
        budget = int(lib_cfg.get("budget_tokens", 0) or 0)
        used_ids = []
        out_lines = []
        tokens_used = 0
        for i, chunk in enumerate(items, 1):
            if "\n" in chunk:
                head, body = chunk.split("\n", 1)
            else:
                head, body = chunk, ""
            body = self._truncate_chars(body, max_chars)
            line = head + "\n" + body if body else head
            t = self._tok(line) + 6
            if budget and tokens_used + t > budget:
                break
            tokens_used += t
            out_lines.append(line)
            m = re.search(r"note_id=([^\]\s]+)", head)
            if m:
                used_ids.append(m.group(1))
        rebuilt = self._pack_snippets_block("LIB-RAG", out_lines)
        return rebuilt, used_ids
