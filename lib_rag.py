
import os, re, json, time, math, hashlib, glob
from pathlib import Path
from typing import Any, Dict, List, Optional, Iterable
try:
    import requests
except Exception:
    requests = None
try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

# # --- HOT cache for LibRAG (in-RAM notes per lib) ---
# from typing import Dict as _Dict, List as _List, Optional as _Optional

HOT_LIBS: Dict[str, List[dict]] = {}

def _preload_lib_dir_to_ram(_root_dir: str, lib_id: str) -> int:
    """Load chunks.jsonl for lib_id into HOT_LIBS; return notes count."""
    import os, json
    p = os.path.join(_root_dir, lib_id, "chunks.jsonl")
    notes = []
    if os.path.isfile(p):
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    notes.append(json.loads(line))
                except Exception:
                    continue
    HOT_LIBS[lib_id] = notes
    return len(notes)

def preload_hot(base_dir: str, only: Optional[List[str]] = None) -> dict:
    """
    Preload all libs under base_dir/_lib_rag into RAM (HOT_LIBS).
    If 'only' provided, limit to that subset. Returns stats dict.
    """
    import os
    root = os.path.join(base_dir or ".", "_lib_rag")
    if not os.path.isdir(root):
        return {"loaded": 0, "total": 0}
    candidates = sorted([d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))])
    if only:
        s = set(only)
        candidates = [d for d in candidates if d in s]
    total, loaded = len(candidates), 0
    for lid in candidates:
        try:
            _preload_lib_dir_to_ram(root, lid)
            loaded += 1
        except Exception:
            continue
    return {"loaded": loaded, "total": total}

WORD_RE = re.compile(r"[A-Za-z0-9_\-]{2,}")

def _now() -> int:
    return int(time.time())

def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def _tok(s: str) -> List[str]:
    return [w.lower() for w in WORD_RE.findall(s)]

def _topk(tokens: List[str], k:int=64) -> List[str]:
    from collections import Counter
    c = Counter(tokens)
    return [w for w,_ in c.most_common(k)]

def _split_chunks(text: str, max_chars: int = 1200, overlap: int = 200) -> List[str]:
    text = text.replace("\r\n","\n")
    parts = []
    i = 0
    n = len(text)
    while i < n:
        j = min(n, i + max_chars)
        parts.append(text[i:j])
        i = j - overlap
        if i < 0: i = 0
        if i >= n: break
    return parts


# ---- PDF extraction helpers ----
# def _extract_pdf_text(pdf_path: str) -> str:
#     # Try pdfminer.six
#     try:
#         from pdfminer.high_level import extract_text as _pdfminer_extract
#         return _norm_ws(_pdfminer_extract(pdf_path) or "")
#     except Exception:
#         pass
#     # Try PyPDF/PyPDF2
#     try:
#         import pypdf as _pypdf
#     except Exception:
#         try:
#             import PyPDF2 as _pypdf  # type: ignore
#         except Exception:
#             _pypdf = None
#     if _pypdf is not None:
#         try:
#             reader = _pypdf.PdfReader(pdf_path)
#             parts = []
#             for page in reader.pages:
#                 try:
#                     parts.append(page.extract_text() or "")
#                 except Exception:
#                     continue
#             return _norm_ws("\\n".join(parts))
#         except Exception:
#             pass
#     return ""

# ---- PDF extraction helpers ----
def _extract_pdf_text(pdf_path: str, max_pages: int = 80, min_chars_ok: int = 80) -> str:
    """
    Extract visible text from a PDF quickly and safely.
    Strategy:
      1) Try PyPDF (fast) with per-page extract_text(), capped by max_pages.
      2) Fallback to pdfminer.six with maxpages cap.
    Returns normalized whitespace text, or "" if none.
    """
    # 1) Fast path: PyPDF / PyPDF2
    try:
        try:
            import pypdf as _pypdf
        except Exception:
            try:
                import PyPDF2 as _pypdf  # type: ignore
            except Exception:
                _pypdf = None
        if _pypdf is not None:
            try:
                reader = _pypdf.PdfReader(pdf_path)
                parts = []
                for i, page in enumerate(reader.pages):
                    if i >= max_pages:
                        break
                    try:
                        parts.append(page.extract_text() or "")
                    except Exception:
                        continue
                text = _norm_ws("\\n".join(parts))
                if len(text) >= min_chars_ok:
                    return text
            except Exception:
                pass
    except Exception:
        pass

    # 2) Fallback: pdfminer.six (bounded)
    try:
        from pdfminer.high_level import extract_text as _pdfminer_extract
        text = _pdfminer_extract(pdf_path, maxpages=max_pages) or ""
        return _norm_ws(text)
    except Exception:
        return ""

# ---- Word-association (co-occurrence) index per lib ----
def _assoc_path(base_dir: str, lib_id: str) -> str:
    return os.path.join(base_dir, "_lib_rag", lib_id, "assoc.json")

def _assoc_load(base_dir: str, lib_id: str) -> dict:
    p = _assoc_path(base_dir, lib_id)
    if os.path.isfile(p):
        try:
            return json.loads(open(p,"r",encoding="utf-8").read())
        except Exception:
            return {"n":{}, "co":{}, "chunks":0}
    return {"n":{}, "co":{}, "chunks":0}

def _assoc_save(base_dir: str, lib_id: str, data: dict):
    p = _assoc_path(base_dir, lib_id)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p,"w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _assoc_update_from_tokens(base_dir: str, lib_id: str, tokens: list[str]):
    """Update counts from a single chunk's tokens (topk)."""
    data = _assoc_load(base_dir, lib_id)
    seen = set(tokens)
    for t in seen:
        data["n"][t] = int(data["n"].get(t,0)) + 1
    # co-occurrence (unordered pairs)
    toks = sorted(seen)
    for i in range(len(toks)):
        for j in range(i+1, len(toks)):
            a,b = toks[i], toks[j]
            co = data["co"].get(a); 
            if co is None: co = {}; data["co"][a] = co
            co[b] = int(co.get(b,0)) + 1
    data["chunks"] = int(data.get("chunks",0)) + 1
    _assoc_save(base_dir, lib_id, data)

def _assoc_top_for(base_dir: str, lib_id: str, token: str, k: int = 4) -> list[str]:
    data = _assoc_load(base_dir, lib_id)
    n = data.get("n",{}); co = data.get("co",{}); total = max(1,int(data.get("chunks",1)))
    out = []
    if token in co:
        for other, c in co[token].items():
            # PMI ~ log ( P(x,y) / (P(x)P(y)) )
            px = n.get(token,1) / total
            py = n.get(other,1) / total
            pxy = c / total
            # Positive PMI (PPMI); clamp negatives to 0
            import math
            val = max(0.0, math.log((pxy / (px*py)) + 1e-9))
            out.append((val, other))
    out.sort(reverse=True)
    return [w for _, w in out[:k]]

def _assoc_expand_query(base_dir: str, lib_id: str, q_tokens: list[str], k_each: int = 2) -> list[str]:
    extra = []
    for t in q_tokens:
        extra.extend(_assoc_top_for(base_dir, lib_id, t, k=k_each))
    # keep unique; avoid exploding token set
    uniq = []
    for w in q_tokens + extra:
        if w not in uniq:
            uniq.append(w)
    return uniq[: min(64, len(uniq))]


def _decay_counts_map(d: dict, decay: float, min_count: float) -> dict:
    out = {}
    for k, v in d.items():
        nv = float(v) * decay
        if nv >= min_count:
            out[k] = nv if isinstance(v, float) else int(nv) if nv >= 1 else nv
    return out

# ====== Lib assoc decay/compaction ======
def _assoc_decay(base_dir: str, lib_id: str, decay: float = 0.98, min_count: float = 0.5) -> dict:
    data = _assoc_load(base_dir, lib_id)
    if not data: return {"ok": True, "skipped": True}
    n = data.get("n",{}); co = data.get("co",{}); chunks = float(data.get("chunks",1))
    n2 = _decay_counts_map(n, decay, min_count)
    co2 = {}
    for a, row in co.items():
        row2 = _decay_counts_map(row, decay, min_count)
        if row2: co2[a] = row2
    data["n"] = n2; data["co"] = co2; data["chunks"] = max(1.0, chunks * decay)
    _assoc_save(base_dir, lib_id, data)
    return {"ok": True, "n": len(n2), "co_rows": len(co2)}

class LibRAG:
    """
    Simple cold-store library RAG separate from user-rag.
    Stores per-lib chunks in JSONL under cold dir; retrieval is keyword/Jaccard-ish with recency boost.
    Lower priority than user-rag; can be enabled per chat with lib_ids or auto-detect by tags.
    """
    def __init__(self, base_dir: Optional[str] = None, cold_base_dir: Optional[str] = None):
        self.base_dir = base_dir
        self.cold_base_dir = cold_base_dir
        root = self._root()
        os.makedirs(root, exist_ok=True)

    def _root(self) -> str:
        base = self.cold_base_dir or self.base_dir or "."
        # print("os.path.join(base, _lib_rag): ", os.path.join(base, "_lib_rag"))
        return os.path.join(base, "_lib_rag")

    def _lib_dir(self, lib_id: str) -> str:
        d = os.path.join(self._root(), lib_id)
        os.makedirs(d, exist_ok=True)
        return d

    def _chunks_path(self, lib_id: str) -> str:
        return os.path.join(self._lib_dir(lib_id), "chunks.jsonl")

    def list_libs(self) -> List[str]:
        root = self._root()
        if not os.path.isdir(root): return []
        return sorted([d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))])

    def list_notes(self, lib_id: str) -> List[Dict[str,Any]]:
        # p = self._chunks_path(lib_id)
        # out = []
        # if os.path.isfile(p):
        #     with open(p,"r",encoding="utf-8") as f:
        #         for line in f:
        #             try: out.append(json.loads(line))
        #             except: pass
        # return out
            # Prefer hot in-RAM cache when available
        hot = HOT_LIBS.get(lib_id)
        if hot is not None:
            return list(hot)

        p = self._chunks_path(lib_id)
        out = []
        if os.path.isfile(p):
            with open(p,"r",encoding="utf-8") as f:
                for line in f:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
        return out
            

    def _write_chunk(self, lib_id: str, note: Dict[str,Any]):
        p = self._chunks_path(lib_id)
        with open(p,"a",encoding="utf-8") as f:
            f.write(json.dumps(note, ensure_ascii=False) + "\n")

    def _note(self, lib_id: str, text: str, meta: Dict[str,Any]) -> Dict[str,Any]:
        toks = _tok(text)
        return {
            "note_id": f"lib::{lib_id}::{_now()}::{hashlib.blake2s(text.encode('utf-8')).hexdigest()[:8]}",
            "lib_id": lib_id,
            "chars": len(text),
            "topk": _topk(toks, 64),
            "ts": _now(),
            "meta": meta,
            "text": text
        }

    def ingest_text(self, lib_id: str, text: str, source: Optional[str] = None, tags: Optional[List[str]] = None, max_chars: int = 1200) -> Dict[str,Any]:
        chunks = _split_chunks(text, max_chars=max_chars, overlap=200)
        n = 0
        for ch in chunks:
            note = self._note(lib_id, ch, {"source": source, "tags": tags or []})
            self._write_chunk(lib_id, note)
            try:
                if HOT_LIBS.get(lib_id) is not None:
                    HOT_LIBS[lib_id].append(note)
            except Exception:
                pass
            try:
                _assoc_update_from_tokens(self.cold_base_dir or self.base_dir or ".", lib_id, note.get("topk") or [])
            except Exception:
                pass
            n += 1
        return {"ok": True, "chunks": n}

    def _html_to_text(self, html: str) -> str:
        if BeautifulSoup is not None:
            soup = BeautifulSoup(html, "html.parser")
            # remove scripts/styles
            for bad in soup(["script","style","noscript"]): bad.extract()
            return _norm_ws(soup.get_text("\n"))
        # naive fallback
        return _norm_ws(re.sub(r"<[^>]+>", " ", html))

    def ingest_url(self, lib_id: str, url: str, tags: Optional[List[str]] = None) -> Dict[str,Any]:
        if requests is None:
            return {"ok": False, "error": "requests not installed"}
        try:
            headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
            r = requests.get(url, headers=headers, timeout=20, allow_redirects=True, stream=True)
            r.raise_for_status()
            # cap the amount we read (e.g., 2 MB)
            MAX_BYTES = 2_000_000
            buf = r.raw.read(MAX_BYTES, decode_content=True)
            html = buf.decode(r.encoding or "utf-8", errors="ignore")
            text = self._html_to_text(html)

            # r = requests.get(url, timeout=20)
            # r.raise_for_status()
            # text = self._html_to_text(r.text)
            return self.ingest_text(lib_id, text, source=url, tags=tags)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def ingest_files(self, lib_id: str, root_path: str, include_glob: Optional[List[str]] = None) -> Dict[str,Any]:
        pats = include_glob or ["**/*.md","**/*.txt","**/*.rst","**/*.py","**/*.js","**/*.ts","**/*.tsx","**/*.json"]
        hits = []
        for pat in pats:
            hits.extend(glob.glob(os.path.join(root_path, pat), recursive=True))
        count = 0
        for p in sorted(set(hits)):
            try:
                with open(p,"r",encoding="utf-8",errors="ignore") as f:
                    text = f.read()
                self.ingest_text(lib_id, text, source=os.path.relpath(p, root_path))
                count += 1
            except Exception:
                continue
        return {"ok": True, "files": count}

    def ingest_zip(self, lib_id: str, zip_path: str, extract_dir: Optional[str] = None, include_glob: Optional[List[str]] = None) -> Dict[str,Any]:
        import zipfile, tempfile, shutil
        t = tempfile.mkdtemp(prefix="libzip_")
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(t)
            return self.ingest_files(lib_id, t, include_glob=include_glob)
        finally:
            shutil.rmtree(t, ignore_errors=True)

    # ---- retrieval ----
    def _score(self, q_tokens: List[str], note: Dict[str,Any], recency_boost: float = 0.0) -> float:
        if not note.get("topk"): return 0.0
        s1 = set(q_tokens); s2 = set(note["topk"])
        if not s1 or not s2: return 0.0
        j = len(s1 & s2) / float(len(s1 | s2))
        if recency_boost and note.get("ts"):
            age = max(1.0, (_now() - note["ts"]) / 86400.0)
            j = j * (1.0 + recency_boost/age)
        return j


    def ingest_pdf(self, lib_id: str, pdf_path: str, tags: Optional[List[str]] = None) -> Dict[str,Any]:
        text = _extract_pdf_text(pdf_path)
        if not text:
            return {"ok": False, "error": "unable to extract text (pdfminer/pypdf missing or parse error)"}
        return self.ingest_text(lib_id, text, source=os.path.basename(pdf_path), tags=tags)

    def search_gated(self, query: str, lib_ids: Optional[List[str]] = None, top_k: int = 6, 
                     min_score: float = 0.08, recency_boost: float = 0.15,
                     tags_any: Optional[List[str]] = None, tags_all: Optional[List[str]] = None,
                     assoc_expand: bool = True, assoc_k_each: int = 2) -> List[Dict[str,Any]]:
        q = _tok(query)
        if not q: return []
        libs = lib_ids or self.list_libs()
        # association expansion per-lib (union across libs)
        if assoc_expand and libs:
            q_exp = set(q)
            for lid in libs:
                try:
                    q_exp.update(_assoc_expand_query(self.cold_base_dir or self.base_dir or ".", lid, q, k_each=assoc_k_each))
                except Exception:
                    continue
            q = list(q_exp)
        cand = []
        for lid in libs:
            for note in self.list_notes(lid):
                ntags = set((note.get("meta") or note.get("metadata") or {}).get("tags") or [])
                if tags_all and not set(tags_all).issubset(ntags):
                    continue
                if tags_any and not (ntags & set(tags_any)):
                    continue
                score = self._score(q, note, recency_boost=recency_boost)
                if score >= min_score:
                    cand.append({"score": score, **note})
        cand.sort(key=lambda x: x["score"], reverse=True)
        return cand[:top_k]

    def route_libs_by_tags(self, query: str, preferred_tags: Optional[List[str]] = None, limit: int = 4) -> List[str]:
        q = _tok(query)
        libs = self.list_libs()
        scored = []
        for lid in libs:
            notes = self.list_notes(lid)
            if not notes: 
                continue
            tag_hits = 0
            tok_hits = 0
            for note in notes[:200]:
                ntags = set((note.get("meta") or note.get("metadata") or {}).get("tags") or [])
                if preferred_tags and (ntags & set(preferred_tags)):
                    tag_hits += 1
                if set(note.get("topk") or []) & set(q):
                    tok_hits += 1
            score = tag_hits * 2 + tok_hits
            if score > 0:
                scored.append((score, lid))
        scored.sort(reverse=True)
        return [lid for _, lid in scored[:limit]]

    def search(self, query: str, lib_ids: Optional[List[str]] = None, top_k: int = 6, min_score: float = 0.08, recency_boost: float = 0.15,
                     assoc_expand: bool = True, assoc_k_each: int = 2) -> List[Dict[str,Any]]:
        q = _tok(query)
        if not q: return []
        libs = lib_ids or self.list_libs()
        # association expansion per-lib (union across libs)
        if assoc_expand and libs:
            q_exp = set(q)
            for lid in libs:
                try:
                    q_exp.update(_assoc_expand_query(self.cold_base_dir or self.base_dir or ".", lid, q, k_each=assoc_k_each))
                except Exception:
                    continue
            q = list(q_exp)
        cand = []
        for lid in libs:
            for note in self.list_notes(lid):
                score = self._score(q, note, recency_boost=recency_boost)
                if score >= min_score:
                    cand.append({"score": score, **note})
        cand.sort(key=lambda x: x["score"], reverse=True)
        return cand[:top_k]

