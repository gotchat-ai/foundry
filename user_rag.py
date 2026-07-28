import fnmatch
import shutil
import json, threading
import os
from typing import Any, Dict, List, Optional
from typing import List, Dict, Any, Optional, Tuple, Iterable
from dataclasses import dataclass, field
import time
import re
from rag_store import RagStore
from pathlib import Path
import uuid

_CODE_FENCE_RE = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)
CHAT_KIND_USER = "chat_user"
CHAT_KIND_ASSISTANT = "chat_assistant"
CHAT_KIND_CODE = "chat_assistant_code"
CHAT_KIND_SUMMARY = "chat_summary"


def _chunk_text(text: str, chunk_chars: int = 600, overlap: int = 120) -> List[str]:
    text = text.strip()
    if len(text) <= chunk_chars:
        return [text]
    out = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_chars)
        out.append(text[start:end])
        if end == len(text):
            break
        start = max(0, end - overlap)
    return out

@dataclass
class URagDoc:
    id: str
    chunk_index: int
    text: str
    meta: Dict[str, Any] = field(default_factory=dict)

class UserRagManager:
    """
    Maintains a per-session RagStore containing only **user**-authored content,
    with optional topics and summary checkpoints.
    """
    def __init__(self, embed_model: str = "sentence-transformers/all-MiniLM-L6-v2", base_dir: Optional[str] = None, cold_base_dir: Optional[str] = None, autosave: bool = True):
        self.embed_model = embed_model
        self._stores: Dict[str, RagStore] = {}
        self.autosave = autosave
        self._topics: Dict[str, Dict[str, int]] = {}  # sid -> topic -> count
        self._checkpoints: Dict[str, List[Dict[str, Any]]] = {}  # sid -> list of summaries

        # user store (per session)
        self.base_dir = Path(base_dir or ".rag/user").expanduser()
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # cold/global store (a.k.a. LibRAG root)
        self.cold_base_dir = Path(cold_base_dir or ".rag/lib").expanduser()
        self.cold_base_dir.mkdir(parents=True, exist_ok=True)

        # ---- backward-compat aliases (in case other code uses old names)
        self.user_rag_dir = self.base_dir
        self.rag_dir = self.cold_base_dir         # some code may still call this
        self.cold_dir = self.cold_base_dir        # if earlier you used `cold_dir`

        # caches + lock
        self._cold_cache: Dict[str, Any] = {}
        self._lock = getattr(self, "_lock", threading.RLock())

    def _store_path(self, sid: str) -> Optional[str]:
        if not self.base_dir:
            return None
        d = os.path.join(self.base_dir, sid)
        os.makedirs(d, exist_ok=True)
        return d

    def _get_store(self, sid: str) -> RagStore:
        if sid not in self._stores:
            self._stores[sid] = RagStore(self.embed_model, persist_dir=self._store_path(sid), autosave=self.autosave)
        return self._stores[sid]

    def clear(self, sid: str):
        if sid in self._stores:
            self._stores[sid].clear()
        self._topics.pop(sid, None)
        self._checkpoints.pop(sid, None)
        d = self._store_path(sid)
        if d and os.path.isdir(d):
            try:
                for fn in ("docs.json","ids.json","matrix.npy"):
                    fp = os.path.join(d, fn)
                    if os.path.exists(fp):
                        os.remove(fp)
            except Exception:
                pass

    def add_user_messages(self, sid: str, messages: List[Dict[str, str]], topic_hint: Optional[str] = None,
                          chunk_chars: int = 600, overlap: int = 120,
                          checkpoint_id: Optional[str] = None, extra_meta: Optional[Dict[str, Any]] = None) -> List[str]:
        store = self._get_store(sid)
        docs = []
        ids = []
        ts = int(time.time())
        for m in messages:
            if (m.get("role") or "").lower() != "user":
                continue
            text = m.get("content","").strip()
            if not text:
                continue
            # chunk it
            chunks = _chunk_text(text, chunk_chars=chunk_chars, overlap=overlap)
            meta = {
                "sid": sid,
                "ts": ts,
                "topic": topic_hint or "",
                "source": "user",
                "orig_len": len(text),
            }
            if checkpoint_id:
                meta["checkpoint_id"] = checkpoint_id
            if extra_meta:
                meta.update(dict(extra_meta))
            for i, ch in enumerate(chunks):
                did = None
                docs.append({"id": did, "text": ch, "metadata": {**meta, "chunk_index": i}})
        if docs:
            ids = store.add_batch(docs)
        return ids

    def add_summary_checkpoint(self, sid: str, summary: str, covered_turns: int, label: Optional[str] = None) -> str:
        arr = self._checkpoints.setdefault(sid, [])
        cid = __import__('uuid').uuid4().hex[:12]
        arr.append({"id": cid, "ts": int(time.time()), "summary": summary, "covered_turns": int(covered_turns), "label": label or ""})
        return cid

    def search(self, sid: str, query: str, k: int = 4, max_chars: int = 1200, topics: Optional[List[str]] = None, min_score: Optional[float] = None) -> List[Dict[str, Any]]:
        store = self._get_store(sid)
        res = store.search(query, top_k=max(k, 4))  # oversample for filtering
        # optional filter by topic metadata
        if topics:
            tset = set([t for t in topics if t])
            res = [r for r in res if (r.get('metadata') or {}).get('topic') in tset]
        if min_score is not None:
            res = [r for r in res if float(r.get('score', 0.0)) >= float(min_score)]
        res = res[:k]
        out = []
        for r in res:
            txt = r["text"]
            if len(txt) > max_chars:
                txt = txt[:max_chars] + "..."
            out.append({"id": r["id"], "score": r["score"], "text": txt, "metadata": r["metadata"]})
        return out

    def list_topics(self, sid: str) -> List[Dict[str, Any]]:
        topics = self._topics.get(sid, {})
        return [{"topic": t, "count": c} for t, c in sorted(topics.items(), key=lambda x: -x[1])]

    def add_topics(self, sid: str, topics: List[str]):
        if not topics:
            return
        tmap = self._topics.setdefault(sid, {})
        for t in topics:
            if not t:
                continue
            tmap[t] = tmap.get(t, 0) + 1

    def export_docs(self, sid: str) -> Dict[str, Any]:
        st = self._get_store(sid)
        docs = []
        for did in st.ids:
            d = st.docs[did]
            docs.append({"id": did, "text": d["text"], "metadata": d["meta"]})
        return {"sid": sid, "docs": docs, "topics": self.list_topics(sid), "checkpoints": self._checkpoints.get(sid, [])}

    def import_docs(self, sid: str, docs: List[Dict[str, Any]]):
        st = self._get_store(sid)
        # simple add (re-embed)
        st.add_batch(docs)

    def stats(self, sid: str) -> Dict[str, Any]:
        st = self._get_store(sid)
        return {"sid": sid, "doc_count": len(st.ids)}

    def _label_to_topics(self, label: str) -> list:
        if not label:
            return []
        return [t.strip().lower() for t in str(label).split(",") if t.strip()]

    def latest_checkpoint_for_topics(self, sid: str, topics: List[str]) -> Optional[str]:
        """Return the most recent checkpoint id whose label overlaps with topics."""
        if not topics:
            return None
        arr = self._checkpoints.get(sid, [])
        tset = set([t.lower() for t in topics])
        for cp in sorted(arr, key=lambda x: x.get("ts", 0), reverse=True):
            lbl = cp.get("label", "")
            lbl_tags = set(self._label_to_topics(lbl))
            if lbl_tags & tset:
                return cp.get("id")
        return None

    def count_by_topics(self, sid: str, topics: List[str]) -> int:
        st = self._get_store(sid)
        if not topics or not st.ids:
            return 0
        tset = set([t for t in topics if t])
        c = 0
        for did in st.ids:
            d = st.docs[did]
            if (d.get("meta") or d.get("metadata") or {}).get("topic") in tset:
                c += 1
        return c

    # -------- Repo-aware add helpers --------
    def _mk_id(self, *parts: str) -> str:
        base = "::".join([p for p in parts if p])
        return base

    def add_repo_chunk_to_cold(self, sid: str, repo_id: str, path: str, text: str, lang: str,
                               symbol: Optional[str] = None, kind: Optional[str] = None,
                               version: Optional[str] = None, topics: Optional[List[str]] = None, ts: Optional[int] = None) -> str:
        st = self._get_cold_store(sid)
        print("st: ", st)
        did = self._mk_id(repo_id, path, symbol or "", str(abs(hash(text))))
        meta = {"repo_id": repo_id, "path": path, "lang": lang, "symbol": symbol, "kind": kind, "version": version, "topic": (topics or []), "ts": ts}
        st.add(did, text, meta)
        return did

    def add_repo_map_to_hot(self, sid: str, repo_id: str, path: str, map_text: str, lang: str, topics: Optional[List[str]] = None, ts: Optional[int] = None) -> str:
        st = self._get_store(sid)
        did = self._mk_id("map", repo_id, path, str(abs(hash(map_text))))
        meta = {"repo_id": repo_id, "path": path, "lang": lang, "type": "repo_map", "topic": (topics or []), "ts": ts}
        st.add(did, map_text, meta)
        return did

    def count_by_repo(self, sid: str, repo_id: str, cold: bool = False) -> Dict[str, int]:
        st = self._get_cold_store(sid) if cold else self._get_store(sid)
        docs = getattr(st, "docs", {})
        n = 0; toks = 0
        for did, d in docs.items():
            if (d.get("meta") or d.get("metadata") or {}).get("repo_id") == repo_id:
                n += 1
                toks += len((d.get("text") or ""))
        return {"docs": n, "approx_chars": toks}

    def cold_search(self, sid: str, query: str, k: int = 8, max_chars: int = 1200, topics: Optional[List[str]] = None, min_score: Optional[float] = None, repo_id: Optional[str] = None, lang: Optional[str] = None, path_contains: Optional[str] = None, version: Optional[str] = None, version_mode: str = "latest" ) -> List[Dict[str, Any]]:
        #version_mode: str = "latest",   # 'latest' | 'exact' | 'lte'
        st = self._get_cold_store(sid)
        res = st.search(query, top_k=max(k, 8))
        if topics:
            tset = set([t for t in topics if t])
            res = [r for r in res if (r.get('metadata') or {}).get('topic') in tset or any(((m:= (r.get('metadata') or {})).get('topic') or [])) and (set(m.get('topic')).intersection(tset))]
        if repo_id:
            res = [r for r in res if (r.get('metadata') or {}).get('repo_id') == repo_id]
        if lang:
            res = [r for r in res if (r.get('metadata') or {}).get('lang') == lang]
        if path_contains:
            res = [r for r in res if path_contains in ((r.get('metadata') or {}).get('path') or '')]
        # version filtering
        if version or version_mode == 'latest':
            allowed = self.resolve_versions(sid, repo_id or (None), version, version_mode)
            if allowed:
                res = [r for r in res if (r.get('metadata') or {}).get('version') in set(allowed)]
        if min_score is not None:
            res = [r for r in res if float(r.get('score', 0.0)) >= float(min_score)]
        #res = res[:k]
        out = []
        #for r in res:
        for r in sorted(res, key=lambda x: x.get("score", 0.0), reverse=True)[:k]:
            txt = r["text"]
            if len(txt) > max_chars:
                txt = txt[:max_chars] + "..."
            out.append({"id": r["id"], "score": r["score"], "text": txt, "metadata": r["metadata"]})
        return out
    
    def export_cold_docs_for_repo(self, sid: str, repo_id: str, version: str = None, version_mode: str = "latest", limit: int = None):
        """
        Export cold-store docs for a repo (optionally filtered to a version or version_mode).
        Returns a list of {"text": str, "metadata": dict}.
        """
        try:
            st = self._get_cold_store(sid)
        except Exception:
            return []
        docs = []
        allowed = None
        try:
            if version is not None or version_mode:
                allowed = set(self.resolve_versions(sid, repo_id, version, version_mode or "latest"))
        except Exception:
            allowed = None
        for did in getattr(st, "ids", []):
            d = getattr(st, "docs", {}).get(did) or {}
            meta = d.get("meta") or d.get("metadata") or {}
            if meta.get("repo_id") != repo_id:
                continue
            if allowed is not None and meta.get("version") not in allowed:
                continue
            docs.append({"text": d.get("text") or "", "metadata": meta})
            if isinstance(limit, int) and limit > 0 and len(docs) >= limit:
                break
        return docs

    # --- LibRAG: ingest text into cold store with vectors persisted ---
    def ingest_text_lib(self, lib_id: str, text: str, source: str = "", tags: list | None = None) -> dict:
        """
        Chunk arbitrary text and add to the LibRAG cold store.
        - Persists docs + vectors to disk (matrix.npy, ids.json, docs.json).
        - Uses a dedicated global lib store slot ("__lib__") so no session id required.
        """
        if not text or not isinstance(text, str):
            return {"ok": False, "added": 0, "reason": "empty_text"}
        # init a dedicated lib store
        sid = "__lib__"
        store = self._stores.get(sid)
        if store is None:
            # cold_base_dir can be repurposed for libs when lib_rag manager is constructed with LIB_COLD_DIR
            base = getattr(self, "cold_base_dir", None) or getattr(self, "base_dir", ".rag/lib")
            store = RagStore(self.embed_model, persist_dir=str(base), autosave=True)
            self._stores[sid] = store

        chunks = _chunk_text(text, chunk_chars=800, overlap=160)
        docs = []
        for i, ch in enumerate(chunks):
            meta = {"lib_id": lib_id, "source": source or "", "chunk_index": i}
            if tags: meta["tags"] = list(tags)
            docs.append({"id": None, "text": ch, "metadata": meta})
        ids = store.add_batch(docs) if docs else []
        # autosave=True will persist matrix.npy, ids.json, docs.json, embed_meta.json
        return {"ok": True, "added": len(ids), "ids": ids}

    # -------- Repo version metadata (per-session, per-repo) --------
    def _repo_meta_base(self) -> Optional[str]:
        base = self.base_dir or self.cold_base_dir
        if not base:
            return None
        p = os.path.join(base, "_repo_meta")
        os.makedirs(p, exist_ok=True)
        return p

    def _repo_meta_path(self, sid: str, repo_id: str) -> Optional[str]:
        base = self._repo_meta_base()
        if not base:
            return None
        d = os.path.join(base, sid)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"{repo_id}.json")

    def _load_repo_meta(self, sid: str, repo_id: str) -> Dict[str, Any]:
        p = self._repo_meta_path(sid, repo_id)
        print("p", p)
        if not p or not os.path.exists(p):
            return {"repo_id": repo_id, "versions": [], "latest_seq": 0}
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            # print(4329923)
            print(e)
            return {"repo_id": repo_id, "versions": [], "latest_seq": 0}

    def _save_repo_meta(self, sid: str, repo_id: str, meta: Dict[str, Any]):
        p = self._repo_meta_path(sid, repo_id)
        if not p:
            return
        with open(p, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def _register_version(self, sid: str, repo_id: str, version: str, parent: Optional[str], ts: Optional[int] = None) -> Dict[str, Any]:
        meta = self._load_repo_meta(sid, repo_id)
        seq = int(meta.get("latest_seq", 0)) + 1
        vrec = {"id": version, "seq": seq, "parent": parent, "ts": int(ts or 0), "files": {}}
        meta.setdefault("versions", []).append(vrec)
        meta["latest_seq"] = seq
        self._save_repo_meta(sid, repo_id, meta)
        return vrec

    def _get_repo_versions(self, sid: str, repo_id: str) -> List[Dict[str, Any]]:
        return self._load_repo_meta(sid, repo_id).get("versions", [])

    def _get_version_record(self, sid: str, repo_id: str, version: Optional[str]) -> Optional[Dict[str, Any]]:
        if version is None:
            return None
        for v in self._get_repo_versions(sid, repo_id):
            if v.get("id") == version:
                return v
        return None

    def _get_latest_version_record(self, sid: str, repo_id: str) -> Optional[Dict[str, Any]]:
        vs = self._get_repo_versions(sid, repo_id)
        if not vs:
            return None
        return max(vs, key=lambda x: int(x.get("seq", 0)))

    def resolve_versions(self, sid: str, repo_id: str, version: Optional[str], mode: str = "latest") -> List[str]:
        """
        mode: 'exact' | 'lte' | 'latest'
        - exact: [version]
        - lte: all versions with seq <= seq(version)
        - latest: [latest_version]
        """
        vs = self._get_repo_versions(sid, repo_id)
        if not vs:
            return []
        by_id = {v["id"]: v for v in vs}
        if mode == "latest" or not version:
            v = self._get_latest_version_record(sid, repo_id)
            return [v["id"]] if v else []
        if mode == "exact":
            return [version] if version in by_id else []
        if mode == "lte":
            if version not in by_id:
                return []
            tgt = by_id[version]["seq"]
            return [v["id"] for v in vs if int(v.get("seq",0)) <= int(tgt)]
        return []

    def repo_diff(self, sid: str, repo_id: str, from_version: Optional[str], to_version: Optional[str]) -> Dict[str, Any]:
        meta = self._load_repo_meta(sid, repo_id)
        vs = meta.get("versions", [])
        by_id = {v["id"]: v for v in vs}
        a = by_id.get(from_version) if from_version else None
        b = by_id.get(to_version) if to_version else self._get_latest_version_record(sid, repo_id)
        if not b:
            return {"repo_id": repo_id, "error": "target version not found"}
        added = []; modified = []; deleted = []; unchanged = []
        a_files = (a or {}).get("files", {})
        b_files = (b or {}).get("files", {})
        all_paths = set(a_files.keys()) | set(b_files.keys())
        for pth in sorted(all_paths):
            A = a_files.get(pth, {}); B = b_files.get(pth, {})
            ahashes = set([c.get("hash") for c in A.get("chunks", [])])
            bhashes = set([c.get("hash") for c in B.get("chunks", [])])
            if not A and B:
                added.append({"path": pth, "added": len(bhashes)})
            elif A and not B:
                deleted.append({"path": pth, "deleted": len(ahashes)})
            else:
                new = list(bhashes - ahashes)
                gone = list(ahashes - bhashes)
                same = list(bhashes & ahashes)
                if new or gone:
                    modified.append({"path": pth, "added": len(new), "removed": len(gone)})
                else:
                    unchanged.append({"path": pth, "chunks": len(same)})
        return {
            "repo_id": repo_id,
            "from": (a or {}).get("id"),
            "to": b.get("id"),
            "counts": {
                "added_files": len([x for x in added if x.get("added")>0]),
                "deleted_files": len([x for x in deleted if x.get("deleted")>0]),
                "modified_files": len([x for x in modified if (x.get('added',0)>0 or x.get('removed',0)>0)]),
                "unchanged_files": len(unchanged)
            },
            "added": added, "deleted": deleted, "modified": modified, "unchanged": unchanged
        }

    # -------- Repo file snapshots (per version) --------
    def _repo_files_root(self, sid: str, repo_id: str) -> Optional[str]:
        base = self.cold_base_dir or self.base_dir
        if not base:
            return None
        root = os.path.join(base, "_repo_files", sid, repo_id)
        os.makedirs(root, exist_ok=True)
        return root

    def repo_version_dir(self, sid: str, repo_id: str, version: str) -> Optional[str]:
        root = self._repo_files_root(sid, repo_id)
        if not root:
            return None
        d = os.path.join(root, version)
        os.makedirs(d, exist_ok=True)
        return d

    def copy_version_dir(self, sid: str, repo_id: str, from_version: str, to_version: str):
        src = self.repo_version_dir(sid, repo_id, from_version)
        dst = self.repo_version_dir(sid, repo_id, to_version)
        if not src or not os.path.isdir(src) or not dst:
            return
        # copy tree without overwriting existing files (new/modified files will overwrite later)
        for root, dirs, files in os.walk(src):
            rel = os.path.relpath(root, src)
            tdir = os.path.join(dst, rel) if rel != "." else dst
            os.makedirs(tdir, exist_ok=True)
            for f in files:
                sp = os.path.join(root, f); dp = os.path.join(tdir, f)
                if not os.path.exists(dp):
                    shutil.copy2(sp, dp)

    def write_version_file(self, sid: str, repo_id: str, version: str, rel_path: str, text: str):
        vdir = self.repo_version_dir(sid, repo_id, version)
        if not vdir:
            return
        # ensure parent dirs
        import os
        p = os.path.join(vdir, rel_path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)

    def iter_version_files(self, sid: str, repo_id: str, version: str, path_prefix: Optional[str] = None, glob_pattern: Optional[str] = None):
        vdir = self.repo_version_dir(sid, repo_id, version)
        if not vdir or not os.path.isdir(vdir):
            return
        plen = len(vdir.rstrip(os.sep)) + 1
        for root, dirs, files in os.walk(vdir):
            for f in files:
                p = os.path.join(root, f)
                rel = p[plen:]
                if path_prefix and not rel.startswith(path_prefix):
                    continue
                if glob_pattern and not fnmatch.fnmatch(rel, glob_pattern):
                    continue
                yield rel, p

    def cold_stats(self, sid: str) -> dict:
        """Return token stats for hot vs cold stores."""
        try:
            hot = self._get_store(sid)
        except Exception:
            return {"ok": False, "error": "no hot store"}
        cold = _ColdIface(self, sid).store()
        hot_tokens = 0
        cold_tokens = 0
        try:
            for did, d in (hot.docs or {}).items():
                hot_tokens += _estimate_tokens(d.get("text",""))
        except Exception:
            pass
        try:
            for did, d in (cold.docs or {}).items():
                cold_tokens += _estimate_tokens(d.get("text",""))
        except Exception:
            pass
        total = hot_tokens + cold_tokens
        ratio = (cold_tokens / total) if total > 0 else 0.0
        return {"ok": True, "hot_tokens": int(hot_tokens), "cold_tokens": int(cold_tokens), "total_tokens": int(total), "cold_ratio": float(ratio)}

    def enforce_cold_rotation(self, sid: str, target_pct: float = 0.35, min_rotate_pct: float = 0.05) -> dict:
        """
        Move least-hot (oldest) docs from hot store to session cold store until:
        - cold_ratio >= target_pct, OR
        - rotated_pct >= min_rotate_pct (of total tokens)
        Returns summary with before/after ratios and moved ids.
        """
        try:
            hot = self._get_store(sid)
        except Exception as e:
            return {"ok": False, "error": "no hot store", "detail": str(e)}
        cold = _ColdIface(self, sid).store()
        # compute current stats
        before = self.cold_stats(sid)
        if not before.get("ok", False):
            return before
        total = max(1, int(before.get("total_tokens", 0)))
        if total == 1 and (before["hot_tokens"] + before["cold_tokens"]) == 0:
            return {"ok": True, "skipped": True, "reason": "no docs"}
        cold_ratio = float(before.get("cold_ratio", 0.0))
        target_pct = float(target_pct or 0.0)
        min_rotate_pct = float(min_rotate_pct or 0.0)
        if target_pct <= 0 and min_rotate_pct <= 0:
            return {"ok": True, "skipped": True, "reason": "no target set"}
        rotated = []
        rotated_tokens = 0

        if cold_ratio < target_pct or min_rotate_pct > 0:
            # Build hot candidate list sorted by 'ts' (oldest first), fallback to short length
            cand = []
            try:
                for did, d in (hot.docs or {}).items():
                    meta = (d.get("meta") or d.get("metadata") or {})
                    ts = int(meta.get("ts", 0))
                    txt = d.get("text","") or ""
                    tok = _estimate_tokens(txt)
                    cand.append((ts, tok, did, txt, meta))
            except Exception:
                pass
            cand.sort(key=lambda x: (x[0], x[1]))  # oldest & smaller first

            # How many tokens to rotate this turn?
            need_pct = max(target_pct - cold_ratio, 0.0)
            need_pct = max(need_pct, min_rotate_pct)
            need_tokens = int(need_pct * total)

            for (ts, tok, did, txt, meta) in cand:
                if need_tokens <= 0:
                    break
                # move doc: add to cold, delete from hot
                try:
                    cold.add(did, txt, metadata=meta)
                    hot.delete(did)
                    rotated.append(did)
                    rotated_tokens += tok
                    need_tokens -= tok
                except Exception:
                    continue

        after = self.cold_stats(sid)
        return {
            "ok": True,
            "rotated_count": len(rotated),
            "rotated_tokens": int(rotated_tokens),
            "before": before,
            "after": after
        }

    def _safe_id(self, sid: Optional[str]) -> str:
        s = (sid or "default").strip()
        # simple sanitize for folder names
        return "".join(ch if ch.isalnum() or ch in ("-","_",".") else "_" for ch in s) or "default"

    def _cold_path_for_sid(self, sid: Optional[str]) -> str:
        return os.path.join(self.cold_base_dir, self._safe_id(sid))

    def _get_cold_store(self, sid: Optional[str] = None):
        """
        Return a cold (persistent) doc store for the given session/user id.
        Creates it lazily and caches the instance. Thread-safe.
        """
        key = self._safe_id(sid)
        with self._lock:
            st = self._cold_cache.get(key)
            if st is not None:
                return st

            base = self._cold_path_for_sid(sid)
            os.makedirs(base, exist_ok=True)

            # Prefer an existing project store if available
            st = None
            for mod_name, cls_name, ctor in (
                # (module, class, arg pattern)
                ("rag.stores.sqlite_store", "SQLiteDocStore", dict(path=os.path.join(base, "store.sqlite3"))),
                ("rag.stores.jsonl_store",  "JsonlDocStore",  dict(path=os.path.join(base, "docs.jsonl"))),
                ("stores.sqlite_store",     "SQLiteDocStore", dict(path=os.path.join(base, "store.sqlite3"))),
                ("stores.jsonl_store",      "JsonlDocStore",  dict(path=os.path.join(base, "docs.jsonl"))),
            ):
                try:
                    mod = __import__(mod_name, fromlist=[cls_name])
                    cls = getattr(mod, cls_name)
                    st = cls(**ctor) if ctor else cls(base_dir=base)
                    break
                except Exception as e:
                    # print(2323244)
                    print(e)
                    continue

            if st is None:
                # Minimal JSONL fallback so callers don’t crash
                st = _FallbackJsonlStore(base_dir=base)

            self._cold_cache[key] = st
            return st

    # public alias if other modules prefer it
    def get_cold_store(self, sid: Optional[str] = None):
        return self._get_cold_store(sid)
    

    def update_chat_summary(
        self,
        sid: str,
        summary_text: str,
        meta: dict | None = None,
    ) -> None:
        """
        Store/update a rolling summary doc for this session in hot+cold.
        """
        if not sid or not summary_text:
            return

        meta = dict(meta or {})
        meta.setdefault("kind", CHAT_KIND_SUMMARY)
        meta.setdefault("role", "system")

        # simplest approach: just add a new summary doc; old ones can be compacted later
        hot = self._get_store(sid)
        hot.add(None, summary_text, meta)

        cold = self._get_cold_store(sid)
        did = f"chat:summary:{uuid.uuid4().hex}"
        cold.add(did, summary_text, meta)
    
    # def get_repo_file_context(
    #     self,
    #     sid: str,
    #     repo_id: str,
    #     path: str,
    #     max_chars: int = 4000,
    # ) -> str:
    #     """
    #     Collect code/text for a given (repo_id, path) from the cold store
    #     for session `sid`, up to `max_chars` characters.

    #     This assumes cold docs are stored as JSON lines with at least:
    #         {"id": ..., "text": "...", "meta": {"repo_id": ..., "path": ...}, ...}
    #     """
    #     st = self._get_cold_store(sid)

    #     # Try a high-level iterator first, if the store has one
    #     docs = []

    #     if hasattr(st, "iter_docs"):
    #         try:
    #             for doc in st.iter_docs():
    #                 meta = (doc.get("meta") or {})
    #                 if meta.get("repo_id") == repo_id and meta.get("path") == path:
    #                     docs.append(doc)
    #         except Exception:
    #             docs = []

    #     # Fallback: open the JSONL file directly (used by _FallbackJsonlStore)
    #     if not docs and hasattr(st, "_path"):
    #         cold_path = getattr(st, "_path", None)
    #         if cold_path and os.path.exists(cold_path):
    #             try:
    #                 with open(cold_path, "r", encoding="utf-8") as f:
    #                     for line in f:
    #                         line = line.strip()
    #                         if not line:
    #                             continue
    #                         try:
    #                             doc = json.loads(line)
    #                         except Exception:
    #                             continue
    #                         meta = (doc.get("meta") or {})
    #                         if meta.get("repo_id") == repo_id and meta.get("path") == path:
    #                             docs.append(doc)
    #             except Exception:
    #                 pass

    #     if not docs:
    #         return ""

    #     # Sort by line/offset if present
    #     def _sort_key(d):
    #         meta = d.get("meta") or {}
    #         # prefer explicit line numbers if you stored them
    #         return (
    #             int(meta.get("start_line", 0)),
    #             int(meta.get("end_line", 0)),
    #         )

    #     docs.sort(key=_sort_key)

    #     pieces = []
    #     total = 0
    #     for d in docs:
    #         t = (d.get("text") or "").rstrip()
    #         if not t:
    #             continue
    #         if total + len(t) > max_chars:
    #             remaining = max_chars - total
    #             if remaining <= 0:
    #                 break
    #             t = t[:remaining]
    #         pieces.append(t)
    #         total += len(t)
    #         if total >= max_chars:
    #             break

    #     return "\n\n".join(pieces)

    def get_repo_file_from_lib_repo_files(
        self,
        sid: str,
        repo_id: str,
        rel_path: str,
        version: str | None = None,
        max_chars: int = 4000,
    ) -> str:
        """
        Load the contents of a repo file extracted under:
            <base_dir>/_repo_files/<sid>/<repo_id>/<version>/<rel_path>

        If version is None, we pick the latest "v*-style" subdirectory.
        """

        # thisBasedir = Path(base_dir or ".rag/lib").expanduser()
        # Root of extracted repo files
        root = os.path.join(self.cold_base_dir, "_repo_files", sid, repo_id)

        if not os.path.isdir(root):
            return ""

        # Choose version directory
        if version:
            ver_dir = os.path.join(root, version)
            if not os.path.isdir(ver_dir):
                return ""
        else:
            # Pick latest "v...." directory if version not given
            try:
                entries = [
                    d for d in os.listdir(root)
                    if os.path.isdir(os.path.join(root, d))
                ]
            except OSError:
                entries = []

            if not entries:
                return ""

            # crude “latest” heuristic: sort by name; your version names are v<timestamp>
            ver_dir = os.path.join(root, sorted(entries)[-1])

        full_path = os.path.join(ver_dir, rel_path)
        if not os.path.isfile(full_path):
            return ""

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                if max_chars == 0:
                    data = f.read()
                else:
                    data = f.read(max_chars + 1)
        except Exception as e:
            return ""

        if len(data) > max_chars and max_chars > 0:
            data = data[:max_chars]

        return data

    def add_assistant_message(self, sid: str, repo_id: str,  content: str):
            """
            Split an assistant message into plain text + code blocks,
            store each piece into chat hot/cold.
            """
            if not content:
                return

            idx = 0
            for m in _CODE_FENCE_RE.finditer(content):
                start, end = m.span()
                lang = (m.group(1) or "").strip()
                code = (m.group(2) or "").rstrip("\n")

                # non-code before this block
                before = content[idx:start].strip()
                if before:
                    self.add_chat_doc(
                        sid,
                        before,
                        role="assistant",
                        meta={"repo_id": repo_id, "kind": CHAT_KIND_ASSISTANT},
                    )

                if code:
                    self.add_chat_doc(
                        sid,
                        code,
                        role="assistant",
                        meta={"repo_id": repo_id, "kind": CHAT_KIND_CODE, "lang": lang},
                    )

                idx = end

            tail = content[idx:].strip()
            if tail:
                self.add_chat_doc(
                    sid,
                    tail,
                    role="assistant",
                    meta={"repo_id": repo_id, "kind": CHAT_KIND_ASSISTANT},
                )

    def add_chat_doc(self, sid: str, text: str, role: str, meta: dict | None = None):
            """
            Store one chat fragment (user or assistant) into hot+cold.

            role: "user" or "assistant" (or any string you want)
            """
            if not text:
                return

            meta = dict(meta or {})
            meta.setdefault("kind", CHAT_KIND_USER if role == "user" else CHAT_KIND_ASSISTANT)
            meta.setdefault("role", role)
            meta.setdefault("ts", time.time())

            # Use the normal hot store
            st = self._get_store(sid)
            # Allow store to pick id
            st.add(None, text, meta)

            # Also mirror into cold JSONL as a long-term record
            cold = self._get_cold_store(sid)
            did = f"chat:{role}:{uuid.uuid4().hex}"
            cold.add(did, text, meta)

    def list_repo_ids(self, sid: str) -> list[str]:
        base = self._repo_meta_base()
        if not base:
            return []
        d = os.path.join(base, sid)
        if not os.path.isdir(d):
            return []
        out = []
        for name in os.listdir(d):
            if name.endswith(".json"):
                out.append(name[:-5])
        out.sort()
        return out

class _ColdIface:
    def __init__(self, mgr: "UserRagManager", sid: str):
        self.mgr = mgr
        from rag_store import RagStore as _RagStore  # relative import safe at runtime
        # session-specific cold dir under cold_base_dir
        import os
        self.dir = os.path.join(str(mgr.cold_base_dir), "_user_cold", sid.replace("/", "_"))
        try:
            os.makedirs(self.dir, exist_ok=True)
        except Exception:
            pass
        # lazy store: we'll instantiate when first used
        self._store = None
        self.embed_model = mgr.embed_model

    def store(self):
        if self._store is None:
            from rag_store import RagStore
            self._store = RagStore(self.embed_model, persist_dir=self.dir, autosave=True)
        return self._store

    
    
class _FallbackJsonlStore:
    """
    Minimal persistent doc store:
      - add_batch(docs)
      - iter_docs()
      - count()
      - flush()
    Optional helpers .add_preembedded(...) no-op to keep API tolerant.
    """
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
        self._path = os.path.join(self.base_dir, "docs.jsonl")
        # ensure file exists
        open(self._path, "a", encoding="utf-8").close()
        self._lock = threading.RLock()

    def add_batch(self, docs: Iterable[Dict[str, Any]]):
        with self._lock, open(self._path, "a", encoding="utf-8") as f:
            for d in docs or []:
                try:
                    json.dump(d, f, ensure_ascii=False)
                    f.write("\n")
                except Exception:
                    continue

    # compat shim: many callers use add(...) for single doc
    # def add(self, doc: Dict[str, Any]):
    #     self.add_batch([doc])
    # compat shim: accept either add(doc) or RagStore-style add(id, text, metadata=...)
    def add(self, *args, **kwargs):
        # Case 1: add({"id": ..., "text": ..., "meta": ...})
        if len(args) == 1 and isinstance(args[0], dict) and not kwargs:
            doc = args[0]
        else:
            # Case 2: RagStore-style add(doc_id, text, meta?) or add(doc_id, text, metadata=...)
            if not args:
                raise TypeError("add() missing required arguments")

            doc_id = args[0]
            text = args[1] if len(args) > 1 else ""
            meta = None

            # positional meta
            if len(args) > 2 and isinstance(args[2], dict):
                meta = args[2]

            # keyword metadata=...
            if "metadata" in kwargs and isinstance(kwargs["metadata"], dict):
                meta = kwargs["metadata"]

            doc = {
                "id": doc_id,
                "text": text,
                "meta": meta or {},
            }

        self.add_batch([doc])

    def iter_docs(self) -> Iterable[Dict[str, Any]]:
        with self._lock:
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            yield json.loads(line)
                        except Exception:
                            continue
            except FileNotFoundError:
                return

    def count(self) -> int:
        return sum(1 for _ in self.iter_docs())

    def flush(self):
        # JSONL is append-only; nothing to do
        return True

    # tolerant no-ops for vector-related APIs some call sites may probe
    def add_preembedded(self, *args, **kwargs): return False
    def load_vectors(self, *args, **kwargs): return False
    def save_vectors(self, *args, **kwargs): return False


# ===== Word-association (co-occurrence) index for User-RAG =====
def _u_assoc_path(base_dir: str, sid: str) -> str:
    # one assoc per session id
    return os.path.join(base_dir or ".", "_user_rag", sid.replace("/", "_"), "assoc.json")

def _u_assoc_load(base_dir: str, sid: str) -> dict:
    p = _u_assoc_path(base_dir, sid)
    if os.path.isfile(p):
        try:
            return json.loads(open(p,"r",encoding="utf-8").read())
        except Exception:
            return {"n":{}, "co":{}, "chunks":0}
    return {"n":{}, "co":{}, "chunks":0}

def _u_assoc_save(base_dir: str, sid: str, data: dict):
    p = _u_assoc_path(base_dir, sid)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p,"w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _u_assoc_update_from_tokens(base_dir: str, sid: str, tokens: list[str]):
    data = _u_assoc_load(base_dir, sid)
    seen = set(tokens)
    for t in seen:
        data["n"][t] = int(data["n"].get(t,0)) + 1
    toks = sorted(seen)
    for i in range(len(toks)):
        for j in range(i+1, len(toks)):
            a,b = toks[i], toks[j]
            co = data["co"].get(a)
            if co is None: co = {}; data["co"][a] = co
            co[b] = int(co.get(b,0)) + 1
    data["chunks"] = int(data.get("chunks",0)) + 1
    _u_assoc_save(base_dir, sid, data)

def _u_assoc_top_for(base_dir: str, sid: str, token: str, k:int=3) -> list[str]:
    data = _u_assoc_load(base_dir, sid)
    n = data.get("n",{}); co = data.get("co",{}); total = max(1,int(data.get("chunks",1)))
    out = []
    if token in co:
        for other, c in co[token].items():
            import math
            px = n.get(token,1) / total
            py = n.get(other,1) / total
            pxy = c / total
            val = max(0.0, math.log((pxy / (px*py)) + 1e-9))  # PPMI
            out.append((val, other))
    out.sort(reverse=True)
    return [w for _, w in out[:k]]

def _u_assoc_expand_query(base_dir: str, sid: str, q_tokens: list[str], k_each:int=2) -> list[str]:
    extra = []
    for t in q_tokens:
        extra.extend(_u_assoc_top_for(base_dir, sid, t, k=k_each))
    uniq = []
    for w in q_tokens + extra:
        if w not in uniq:
            uniq.append(w)
    return uniq[: min(64, len(uniq))]


# ===== User-level assoc (persist across sessions) =====
def _u_user_assoc_path(base_dir: str, user_id: str) -> str:
    return os.path.join(base_dir or ".", "_user_rag", "_users", user_id.replace("/", "_"), "assoc.json")

def _u_user_assoc_load(base_dir: str, user_id: str) -> dict:
    p = _u_user_assoc_path(base_dir, user_id)
    if os.path.isfile(p):
        try:
            return json.loads(open(p,"r",encoding="utf-8").read())
        except Exception:
            return {"n":{}, "co":{}, "chunks":0}
    return {"n":{}, "co":{}, "chunks":0}

def _u_user_assoc_save(base_dir: str, user_id: str, data: dict):
    p = _u_user_assoc_path(base_dir, user_id)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p,"w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _u_user_assoc_update_from_tokens(base_dir: str, user_id: str, tokens: list[str]):
    data = _u_user_assoc_load(base_dir, user_id)
    seen = set(tokens)
    for t in seen:
        data["n"][t] = int(data["n"].get(t,0)) + 1
    toks = sorted(seen)
    for i in range(len(toks)):
        for j in range(i+1, len(toks)):
            a,b = toks[i], toks[j]
            co = data["co"].get(a)
            if co is None: co = {}; data["co"][a] = co
            co[b] = int(co.get(b,0)) + 1
    data["chunks"] = int(data.get("chunks",0)) + 1
    _u_user_assoc_save(base_dir, user_id, data)

def _u_user_assoc_top_for(base_dir: str, user_id: str, token: str, k:int=3) -> list[str]:
    data = _u_user_assoc_load(base_dir, user_id)
    n = data.get("n",{}); co = data.get("co",{}); total = max(1,int(data.get("chunks",1)))
    out = []
    if token in co:
        for other, c in co[token].items():
            import math
            px = n.get(token,1) / total
            py = n.get(other,1) / total
            pxy = c / total
            val = max(0.0, math.log((pxy / (px*py)) + 1e-9))  # PPMI
            out.append((val, other))
    out.sort(reverse=True)
    return [w for _, w in out[:k]]

def _u_user_assoc_expand_query(base_dir: str, user_id: str, q_tokens: list[str], k_each:int=2) -> list[str]:
    extra = []
    for t in q_tokens:
        extra.extend(_u_user_assoc_top_for(base_dir, user_id, t, k=k_each))
    uniq = []
    for w in q_tokens + extra:
        if w not in uniq:
            uniq.append(w)
    return uniq[: min(64, len(uniq))]


# ====== Assoc decay/compaction ======
def _decay_counts_map(d: dict, decay: float, min_count: float) -> dict:
    out = {}
    for k, v in d.items():
        nv = float(v) * decay
        if nv >= min_count:
            out[k] = nv if isinstance(v, float) else int(nv) if nv >= 1 else nv
    return out

def _u_assoc_decay(base_dir: str, sid: str, decay: float = 0.98, min_count: float = 0.5) -> dict:
    data = _u_assoc_load(base_dir, sid)
    if not data: return {"ok": True, "skipped": True}
    n = data.get("n",{}); co = data.get("co",{}); chunks = float(data.get("chunks",1))
    n2 = _decay_counts_map(n, decay, min_count)
    co2 = {}
    for a, row in co.items():
        row2 = _decay_counts_map(row, decay, min_count)
        if row2: co2[a] = row2
    data["n"] = n2; data["co"] = co2; data["chunks"] = max(1.0, chunks * decay)
    _u_assoc_save(base_dir, sid, data)
    return {"ok": True, "n": len(n2), "co_rows": len(co2)}

def _u_user_assoc_decay(base_dir: str, user_id: str, decay: float = 0.98, min_count: float = 0.5) -> dict:
    data = _u_user_assoc_load(base_dir, user_id)
    if not data: return {"ok": True, "skipped": True}
    n = data.get("n",{}); co = data.get("co",{}); chunks = float(data.get("chunks",1))
    n2 = _decay_counts_map(n, decay, min_count)
    co2 = {}
    for a, row in co.items():
        row2 = _decay_counts_map(row, decay, min_count)
        if row2: co2[a] = row2
    data["n"] = n2; data["co"] = co2; data["chunks"] = max(1.0, chunks * decay)
    _u_user_assoc_save(base_dir, user_id, data)
    return {"ok": True, "n": len(n2), "co_rows": len(co2)}


# ===== Cold-rotation utilities =====
def _estimate_tokens(text: str) -> int:
    try:
        return len((text or "").split())
    except Exception:
        return 0
    
_STOPWORDS = {
    "the","a","an","and","or","but","if","then","else","for","to","of","in","on","at","by","with","is","are",
    "was","were","be","been","it","its","this","that","these","those","as","from","into","about","over","under",
    "you","your","yours","me","my","we","our","they","them","their","he","she","his","her","i"
}

_token_re = re.compile(r"[A-Za-z0-9_]+", re.U)

def _tokenize(text: str) -> List[str]:
    toks = [t.lower() for t in _token_re.findall(text or "")]
    return [t for t in toks if len(t) > 1 and t not in _STOPWORDS]

def _safe_id(sid: Optional[str]) -> str:
    s = (sid or "default").strip()
    # simple sanitize for folder names
    return "".join(ch if ch.isalnum() or ch in ("-","_",".") else "_" for ch in s) or "default"

# ---------- Public API: update from user text ----------

def assoc_update_from_text_user(
    base_dir: str,
    sid: Optional[str],
    text: str,
    *,
    weight: float = 1.0,
    window: int = 5,
    halflife_days: float = 30.0,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Update the user-association graph from raw user text.

    - Tokenizes text, filters stopwords
    - Increments term counts and symmetric co-occurrence within a sliding window
    - Applies exponential decay before update
    - Persists to <base>/assoc/<sid>.json

    Returns a small summary for logging.
    """
    if not text or not text.strip():
        return {"updated": False, "reason": "empty_text"}

    now = now or time.time()
    data = _u_assoc_load(base_dir,sid)

    # decay first so recent text dominates
    _u_assoc_decay(base_dir,sid=sid, now=now, halflife_days=halflife_days)

    toks = _tokenize(text)
    n = len(toks)
    if n == 0:
        return {"updated": False, "reason": "no_tokens_after_filter"}

    terms = data["terms"]
    pairs = 0

    def _ensure(term: str) -> Dict[str, Any]:
        rec = terms.get(term)
        if rec is None:
            rec = {"count": 0.0, "last": now, "co": {}}
            terms[term] = rec
        return rec

    # term frequency
    for t in toks:
        r = _ensure(t)
        r["count"] = float(r.get("count", 0.0)) + float(weight)
        r["last"] = now

    # symmetric co-occurrence within window
    w = max(1, int(window))
    for i, ti in enumerate(toks):
        ri = _ensure(ti)
        start = i + 1
        end = min(n, i + 1 + w)
        for j in range(start, end):
            tj = toks[j]
            if tj == ti:
                continue
            rj = _ensure(tj)

            # i -> j
            co_i = ri["co"]; co_i[tj] = float(co_i.get(tj, 0.0)) + float(weight)
            # j -> i
            co_j = rj["co"]; co_j[ti] = float(co_j.get(ti, 0.0)) + float(weight)
            pairs += 1

    # persist
    _u_assoc_save(base_dir, sid, data)

    return {
        "updated": True,
        "tokens": n,
        "pairs": pairs,
        "vocab": len(terms),
        "sid": _safe_id(sid),
        "ts": now,
    }