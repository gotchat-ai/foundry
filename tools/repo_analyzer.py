
import os, re, json, ast, hashlib, time
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path as _Path

IGNORE_DIRS = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".ruff_cache"}
PY_EXTS = {".py"}

def _hash(s: str) -> str:
    return hashlib.blake2b(s.encode("utf-8"), digest_size=16).hexdigest()

@dataclass
class SymbolChunk:
    repo_id: str
    file: str
    fqn: str
    kind: str  # "module" | "class" | "function"
    start_line: int
    end_line: int
    signature: str
    docstring: str
    text: str  # source code of the symbol
    imports: List[str]
    calls: List[str]
    last_modified: float

SETTINGS_PATH_ENV = "APP_SETTINGS"          # env override for settings file
DEFAULT_SETTINGS_PATH = "settings.json"     # repo-root default

def _to_bool(v: Any) -> bool:
    if isinstance(v, bool): return v
    if v is None: return False
    return str(v).strip().lower() in ("1","true","yes","on","y")

def _to_int(v: Any) -> Optional[int]:
    if v is None or v == "": return None
    try: return int(v)
    except Exception: return None


def load_settings(path: str | None = None) -> Dict[str, Any]:
    #path = path or os.environ.get(SETTINGS_PATH_ENV, DEFAULT_SETTINGS_PATH)
    path = path or _Path(__file__).parent.with_name("settings.json")
    # sensible defaults for ALL create_app kwargs
    s: Dict[str, Any] = {
        "model_id": "distilgpt2",
        "device": "auto",
        "dtype": "auto",
        "chat_template": "default",
        "librag_headroom_frac": 0.20,
        "rag_preload_cold": False,
        "rag_preload_only": None,

        "schemes": True,
        "allow_http_scheme": False,
        "max_context_tokens": None,   # set an int if you want, e.g. 100_000
        "reserve_tokens": 0,

        "enable_summarize": True,
        "enable_rag": True,
        "embed_model": None,

        "enable_user_rag": True,
        "rag_dir": None,
        "rag_autosave": True,
        "user_rag_dir": None,
        "user_rag_autosave": True,
    }

    # file overrides
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # PROMOTE_LIB_RAG_PRELOAD: allow nested lib_rag keys in settings.json
                try:
                    _lib = data.get('lib_rag') or {}
                    if isinstance(_lib, dict):
                        if 'preload_cold' in _lib and 'rag_preload_cold' not in data:
                            data['rag_preload_cold'] = bool(_lib.get('preload_cold'))
                        if 'preload_only' in _lib and 'rag_preload_only' not in data:
                            data['rag_preload_only'] = _lib.get('preload_only')
                        if 'headroom_frac' in _lib and 'librag_headroom_frac' not in data:
                            data['librag_headroom_frac'] = _lib.get('headroom_frac')
                except Exception:
                    pass
                s.update({k: v for k, v in data.items() if v is not None})
        except Exception as e:
            print(f"[settings] Warning: failed to read {path}: {e}")

    # env overrides (optional, short names)
    str_envs = [
        ("librag_headroom_frac", "LIBRAG_HEADROOM_FRAC"),
        ("rag_preload_only", "RAG_PRELOAD_ONLY"),
        ("model_id", "MODEL"),
        ("device", "DEVICE"),
        ("dtype", "DTYPE"),
        ("chat_template", "CHAT_TEMPLATE"),
        ("embed_model", "EMBED_MODEL"),
        ("rag_dir", "RAG_DIR"),
        ("user_rag_dir", "USER_RAG_DIR"),
    ]
    for key, env in str_envs:
        v = os.environ.get(env)
        if v: s[key] = v

    bool_envs = [
        ("rag_preload_cold", "RAG_PRELOAD_COLD"),
        ("schemes", "SCHEMES"),
        ("allow_http_scheme", "ALLOW_HTTP_SCHEME"),
        ("enable_summarize", "ENABLE_SUMMARIZE"),
        ("enable_rag", "ENABLE_RAG"),
        ("enable_user_rag", "ENABLE_USER_RAG"),
        ("rag_autosave", "RAG_AUTOSAVE"),
        ("user_rag_autosave", "USER_RAG_AUTOSAVE"),
    ]
    for key, env in bool_envs:
        if env in os.environ:
            s[key] = _to_bool(os.environ[env])

    mct = _to_int(os.environ.get("MAX_CONTEXT_TOKENS"))
    if mct is not None: s["max_context_tokens"] = mct
    rt = _to_int(os.environ.get("RESERVE_TOKENS"))
    if rt is not None: s["reserve_tokens"] = rt

    return s

try:
    SETTINGS = load_settings()
except Exception as e:
    pass
# ----- END SETTINGS + APP BOOTSTRAP -----


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def _get_module_imports(node: ast.AST) -> List[str]:
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Import):
            for a in n.names:
                out.append(a.name)
        elif isinstance(n, ast.ImportFrom):
            mod = n.module or ""
            for a in n.names:
                out.append(f"{mod}.{a.name}" if mod else a.name)
    return sorted(set(out))

def _get_calls(node: ast.AST) -> List[str]:
    calls = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            fn = n.func
            name = None
            if isinstance(fn, ast.Name):
                name = fn.id
            elif isinstance(fn, ast.Attribute):
                parts = []
                cur = fn
                while isinstance(cur, ast.Attribute):
                    parts.append(cur.attr)
                    cur = cur.value
                if isinstance(cur, ast.Name):
                    parts.append(cur.id)
                parts.reverse()
                name = ".".join(parts)
            if name:
                calls.append(name)
    return sorted(set(calls))

def _signature_for(node: ast.AST) -> str:
    try:
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            args = []
            for a in node.args.args:
                args.append(a.arg)
            if node.args.vararg:
                args.append("*" + node.args.vararg.arg)
            for a in node.args.kwonlyargs:
                args.append(a.arg + "=?")
            if node.args.kwarg:
                args.append("**" + node.args.kwarg.arg)
            return f"({', '.join(args)})"
        elif isinstance(node, ast.ClassDef):
            return "(class)"
    except Exception:
        pass
    return ""

def _fqn(mod: str, cls: Optional[str], name: Optional[str]) -> str:
    if cls and name:
        return f"{mod}.{cls}.{name}"
    if cls and not name:
        return f"{mod}.{cls}"
    if name and not cls:
        return f"{mod}.{name}"
    return mod

def _node_src(text: str, node: ast.AST) -> Tuple[int, int, str]:
    try:
        # Python 3.8+: ast nodes have lineno and end_lineno
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start)
        lines = text.splitlines()
        seg = "\n".join(lines[start-1:end])
        return start, end, seg
    except Exception:
        return 1, len(text.splitlines()), text

def _walk_file(repo_id: str, file_path: str) -> List[SymbolChunk]:
    text = _read_text(file_path)
    try:
        tree = ast.parse(text)
    except Exception:
        return []
    mod_name = os.path.splitext(os.path.basename(file_path))[0]
    imports = _get_module_imports(tree)
    chunks: List[SymbolChunk] = []

    # module-level chunk (optional, to carry module docstring + imports)
    mod_doc = ast.get_docstring(tree) or ""
    chunks.append(SymbolChunk(
        repo_id=repo_id, file=file_path, fqn=_fqn(mod_name, None, None),
        kind="module", start_line=1, end_line=len(text.splitlines()),
        signature="", docstring=mod_doc, text=text, imports=imports, calls=_get_calls(tree),
        last_modified=os.path.getmtime(file_path)
    ))

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            s, e, seg = _node_src(text, node)
            cls_doc = ast.get_docstring(node) or ""
            chunks.append(SymbolChunk(
                repo_id=repo_id, file=file_path, fqn=_fqn(mod_name, node.name, None),
                kind="class", start_line=s, end_line=e, signature="(class)", docstring=cls_doc,
                text=seg, imports=imports, calls=_get_calls(node), last_modified=os.path.getmtime(file_path)
            ))
            for fn in node.body:
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    s2, e2, seg2 = _node_src(text, fn)
                    fn_doc = ast.get_docstring(fn) or ""
                    chunks.append(SymbolChunk(
                        repo_id=repo_id, file=file_path, fqn=_fqn(mod_name, node.name, fn.name),
                        kind="function", start_line=s2, end_line=e2, signature=_signature_for(fn),
                        docstring=fn_doc, text=seg2, imports=imports, calls=_get_calls(fn),
                        last_modified=os.path.getmtime(file_path)
                    ))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            s, e, seg = _node_src(text, node)
            fn_doc = ast.get_docstring(node) or ""
            chunks.append(SymbolChunk(
                repo_id=repo_id, file=file_path, fqn=_fqn(mod_name, None, node.name),
                kind="function", start_line=s, end_line=e, signature=_signature_for(node),
                docstring=fn_doc, text=seg, imports=imports, calls=_get_calls(node),
                last_modified=os.path.getmtime(file_path)
            ))
    return chunks

def scan_repo(repo_id: str, root_dir: str) -> List[SymbolChunk]:
    out: List[SymbolChunk] = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            path = os.path.join(dirpath, fn)
            if ext in PY_EXTS:
                out.extend(_walk_file(repo_id, path))
            elif ext in EXT_JS or ext in EXT_TS:
                if ((SETTINGS or {}).get("analysis", {})).get("enable_treesitter", True):
                    lang = "javascript" if ext in EXT_JS else "typescript"
                    out.extend(_walk_file_ts(repo_id, path, lang))
                else:
                    out.extend(_walk_file_generic(repo_id, path))
            elif ext in EXT_CS:
                if ((SETTINGS or {}).get("analysis", {})).get("enable_treesitter", True):
                    out.extend(_walk_file_ts(repo_id, path, "csharp"))
                else:
                    out.extend(_walk_file_generic(repo_id, path))
            elif ext in EXT_C or ext in EXT_HTML or ext in EXT_CSS:
                out.extend(_walk_file_generic(repo_id, path))
    return out

def persist_symbol_jsonl(chunks: List[SymbolChunk], dst_dir: str) -> str:
    os.makedirs(dst_dir, exist_ok=True)
    p = os.path.join(dst_dir, "notes.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for ch in chunks:
            f.write(json.dumps(asdict(ch), ensure_ascii=False) + "\n")
    return p

def build_map(chunks: List[SymbolChunk]) -> Dict:
    files: Dict[str, Dict] = {}
    for ch in chunks:
        files.setdefault(ch.file, {"symbols": []})
        files[ch.file]["symbols"].append({
            "fqn": ch.fqn, "kind": ch.kind, "start": ch.start_line, "end": ch.end_line,
            "imports": ch.imports, "calls": ch.calls
        })
    return {"files": files}

def persist_map(map_obj: Dict, dst_dir: str) -> str:
    os.makedirs(dst_dir, exist_ok=True)
    p = os.path.join(dst_dir, "map.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(map_obj, f, ensure_ascii=False, indent=2)
    return p

def quick_repo_summary(chunks: List[SymbolChunk]) -> str:
    files = sorted({ch.file for ch in chunks})
    funcs = sum(1 for ch in chunks if ch.kind == "function")
    classes = sum(1 for ch in chunks if ch.kind == "class")
    modules = sum(1 for ch in chunks if ch.kind == "module")
    return f"# Repo Summary\n\nFiles: {len(files)} | Modules: {modules} | Classes: {classes} | Functions: {funcs}\n"

def persist_summary(txt: str, dst_dir: str) -> str:
    os.makedirs(dst_dir, exist_ok=True)
    p = os.path.join(dst_dir, "repo_summary.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(txt)
    return p

# Vector persist hook: call into existing embedding pipeline if available
# def vector_persist(chunks: List[SymbolChunk], dst_dir: str) -> Optional[str]:
#     """Persist vectors if your repo has an embedder. We try common hooks; no-op otherwise."""
#     try:
#         from rag.repo_rag import persist_vectors as rr_persist  # your existing path
#         texts = [ch.text for ch in chunks]
#         metas = [asdict(ch) for ch in chunks]
#         return rr_persist(texts, metas, dst_dir)
#     except Exception:
#         pass
#     try:
#         from rag.common import embed_and_save  # alternative hook
#         texts = [ch.text for ch in chunks]
#         metas = [asdict(ch) for ch in chunks]
#         return embed_and_save(texts, metas, dst_dir)
#     except Exception:
#         return None

def vector_persist(chunks: List[SymbolChunk], dst_dir: str) -> Optional[str]:
    """
    Persist repo symbol docs in a way that plays nicely with the current repo-rag path.

    - If app.repo_rag (UserRagManager) is available, we push docs into it via import_docs.
    - Otherwise we fall back to writing a JSONL file under dst_dir.
    """
    if not chunks:
        return None

    # Build docs: id, text, meta
    docs = []
    for ch in chunks:
        meta = asdict(ch).copy()
        text = meta.pop("text", "") or ""
        if not text:
            continue

        # Reasonable, stable id for this symbol
        doc_id = _hash(f"{ch.repo_id}::{ch.file}::{ch.fqn}::{ch.start_line}-{ch.end_line}")

        docs.append({
            "id": doc_id,
            "text": text,
            "metadata": meta,
        })

    if not docs:
        return None

    # 1) Preferred path: push into repo_rag (UserRagManager) if available
    repo_rag = None
    try:
        # app.py defines `repo_rag = UserRagManager(cold_base_dir=REPO_COLD_DIR)`
        from app import repo_rag as _repo_rag
        repo_rag = _repo_rag
    except Exception:
        repo_rag = None

    if repo_rag is not None:
        # Use a synthetic sid for offline / tool-ingested repos.
        # You can change this to something else; it's just a namespace key.
        try:
            # If all chunks share the same repo_id, use that as sid; otherwise fall back.
            repo_ids = {ch.repo_id for ch in chunks if ch.repo_id}
            sid = repo_ids.pop() if len(repo_ids) == 1 else "repo_analyzer"

            repo_rag.import_docs(sid, docs)
            # We don't really have a "path" to return here; return the sid we used.
            return f"repo_rag:sid={sid}"
        except Exception:
            # non-fatal; fall back to JSONL
            pass

    # 2) Fallback: just write a neutral JSONL file under dst_dir
    try:
        os.makedirs(dst_dir, exist_ok=True)
        out_path = os.path.join(dst_dir, "symbols.jsonl")
        with open(out_path, "w", encoding="utf-8") as f:
            for d in docs:
                json.dump(d, f, ensure_ascii=False)
                f.write("\n")
        return out_path
    except Exception:
        return None

def analyze_repo(repo_id: str, root_dir: str, out_dir: str) -> Dict[str, str]:
    chunks = scan_repo(repo_id, root_dir)
    notes = persist_symbol_jsonl(chunks, out_dir)
    mapp = persist_map(build_map(chunks), out_dir)
    summ = persist_summary(quick_repo_summary(chunks), out_dir)
    vector_persist(chunks, os.path.join(out_dir, "vectors"))
    return {"notes": notes, "map": mapp, "summary": summ}


# ---- Incremental scan based on mtimes ----
def _load_index_cache(out_dir: str) -> dict:
    p = os.path.join(out_dir, "index_cache.json")
    if not os.path.exists(p):
        return {}
    try:
        return json.load(open(p, "r", encoding="utf-8"))
    except Exception:
        return {}

def _save_index_cache(cache: dict, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, "index_cache.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def analyze_repo_incremental(repo_id: str, root_dir: str, out_dir: str) -> Dict[str, str]:
    """
    Only re-index files with modified mtime since last run (stored in index_cache.json).
    Rewrites notes.jsonl with new SymbolChunks for updated files while keeping old ones.
    """
    cache = _load_index_cache(out_dir)
    old_mtimes = cache.get("mtimes", {})
    new_mtimes = {}
    changed_files = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in PY_EXTS:
                path = os.path.join(dirpath, fn)
                mt = os.path.getmtime(path)
                new_mtimes[path] = mt
                if str(mt) != str(old_mtimes.get(path)):
                    changed_files.append(path)

    # load existing notes
    notes_path = os.path.join(out_dir, "notes.jsonl")
    existing = []
    if os.path.exists(notes_path):
        with open(notes_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    existing.append(json.loads(line))
                except Exception:
                    pass

    # drop chunks that belong to changed files
    keep = [row for row in existing if row.get("file") not in set(changed_files)]

    # rescan changed files
    new_chunks = []
    for path in changed_files:
        new_chunks.extend(_walk_file(repo_id, path))

    # rebuild combined
    combined = keep + [asdict(ch) if hasattr(ch, "__dict__") else ch for ch in new_chunks]

    # persist
    os.makedirs(out_dir, exist_ok=True)
    with open(notes_path, "w", encoding="utf-8") as f:
        for row in combined:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # rebuild map and summary from combined
    # reconstruct SymbolChunk-like views
    class _Wrap: pass
    chunks = []
    for row in combined:
        w = _Wrap()
        for k,v in row.items():
            setattr(w, k, v)
        chunks.append(w)

    mapp = persist_map(build_map(chunks), out_dir)
    summ = persist_summary(quick_repo_summary(chunks), out_dir)

    cache = {"mtimes": new_mtimes}
    _save_index_cache(cache, out_dir)

    vector_persist(chunks, os.path.join(out_dir, "vectors"))

    return {"notes": notes_path, "map": mapp, "summary": summ}


def _git_current_commit(root_dir: str) -> str | None:
    try:
        import subprocess
        out = subprocess.check_output(["git","-C", root_dir, "rev-parse", "HEAD"], stderr=subprocess.STDOUT, timeout=5).decode().strip()
        return out
    except Exception:
        return None

def analyze_repo_git_incremental(repo_id: str, root_dir: str, out_dir: str) -> dict:
    cache = _load_index_cache(out_dir)
    last_commit = cache.get("last_commit")
    cur = _git_current_commit(root_dir)
    if not cur:
        return analyze_repo_incremental(repo_id, root_dir, out_dir)
    import subprocess
    if last_commit:
        try:
            out = subprocess.check_output(["git","-C", root_dir, "diff", "--name-only", last_commit, cur], stderr=subprocess.STDOUT, timeout=10).decode().splitlines()
            changed = [os.path.join(root_dir, p) for p in out if p.endswith(".py")]
        except Exception:
            changed = []
    else:
        changed = []
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() in PY_EXTS:
                    changed.append(os.path.join(dirpath, fn))
    notes_path = os.path.join(out_dir, "notes.jsonl")
    existing = []
    if os.path.exists(notes_path):
        with open(notes_path, "r", encoding="utf-8") as f:
            for line in f:
                try: existing.append(json.loads(line))
                except Exception: pass
    keep = [row for row in existing if row.get("file") not in set(changed)]
    new_chunks = []
    for path in changed:
        new_chunks.extend(_walk_file(repo_id, path))
    combined = keep + [asdict(ch) if hasattr(ch, "__dict__") else ch for ch in new_chunks]
    os.makedirs(out_dir, exist_ok=True)
    with open(notes_path, "w", encoding="utf-8") as f:
        for row in combined:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    class _Wrap: pass
    chunks = []
    for row in combined:
        w = _Wrap()
        for k,v in row.items():
            setattr(w, k, v)
        chunks.append(w)
    mapp = persist_map(build_map(chunks), out_dir)
    summ = persist_summary(quick_repo_summary(chunks), out_dir)
    cache["last_commit"] = cur
    _save_index_cache(cache, out_dir)
    vector_persist(chunks, os.path.join(out_dir, "vectors"))
    return {"notes": notes_path, "map": mapp, "summary": summ}


# ---- Multi-language support (file-level for non-Python) ----
EXT_JS = {".js", ".mjs", ".cjs", ".jsx"}
EXT_TS = {".ts", ".tsx"}
EXT_C  = {".c", ".h"}
EXT_CS = {".cs"}
EXT_HTML = {".html", ".htm"}
EXT_CSS  = {".css"}

def _guess_lang_by_ext(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in PY_EXTS: return "python"
    if ext in EXT_JS: return "javascript"
    if ext in EXT_TS: return "typescript"
    if ext in EXT_C:  return "c"
    if ext in EXT_CS: return "csharp"
    if ext in EXT_HTML: return "html"
    if ext in EXT_CSS:  return "css"
    return "text"

def _extract_imports_generic(text: str, lang: str) -> list[str]:
    out = []
    try:
        if lang in ("javascript","typescript"):
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("import "):
                    out.append(s)
                if "require(" in s:
                    out.append(s)
        elif lang == "c":
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("#include"):
                    out.append(s)
        elif lang == "csharp":
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("using "):
                    out.append(s)
        # html/css: no import summary for now
    except Exception:
        pass
    return out[:100]

def _walk_file_generic(repo_id: str, file_path: str) -> list[SymbolChunk]:
    text = _read_text(file_path)
    lang = _guess_lang_by_ext(file_path)
    imports = _extract_imports_generic(text, lang)
    mod_name = os.path.splitext(os.path.basename(file_path))[0]
    return [SymbolChunk(
        repo_id=repo_id, file=file_path, fqn=mod_name, kind="file",
        start_line=1, end_line=len(text.splitlines()), signature=f"({lang})",
        docstring="", text=text, imports=imports, calls=[],
        last_modified=os.path.getmtime(file_path)
    )]


# ---- Optional Tree-sitter symbol extraction for JS/TS/C# ----
def _treesitter_available():
    try:
        import importlib
        importlib.import_module("tree_sitter")
        return True
    except Exception:
        return False

def _ts_get_lang(name: str):
    # Try a bundled language pack first, then per-language packages.
    try:
        from tree_sitter_language_pack import get_language
        mapping = {"javascript":"javascript","typescript":"typescript","csharp":"c_sharp"}
        # tree-sitter-language-pack uses tree-sitter's canonical names.
        # Keep our historical mapping for compatibility.
        requested = mapping.get(name, name)
        try:
            return get_language(requested)
        except Exception:
            # Some installs/language packs use slight name variations.
            if requested == "c_sharp":
                for alt in ("csharp", "c-sharp"):
                    try:
                        return get_language(alt)
                    except Exception:
                        pass
            raise
    except Exception:
        pass
    try:
        if name == "javascript":
            from tree_sitter_javascript import LANGUAGE as L; return L
        if name == "typescript":
            from tree_sitter_typescript import LANGUAGE as L; return L
        if name == "csharp":
            from tree_sitter_c_sharp import LANGUAGE as L; return L
    except Exception:
        return None
    return None

def _ts_parser_for(name: str):
    try:
        from tree_sitter import Parser
        L = _ts_get_lang(name)
        if L is None:
            return None
        p = Parser()
        p.set_language(L)
        return p
    except Exception:
        return None

def _ts_query(name: str, kind: str):
    try:
        from tree_sitter import Query
        L = _ts_get_lang(name)
        if L is None:
            return None
        if name in ("javascript","typescript"):
            if kind == "func":
                q = "(function_declaration name: (identifier) @name)"
            elif kind == "method":
                q = "(method_definition name: (property_identifier) @name)"
            elif kind == "class":
                q = "(class_declaration name: (identifier) @name)"
            elif kind == "interface":
                q = "(interface_declaration name: (type_identifier) @name)"
            elif kind == "namespace":
                q = "(namespace_export name: (identifier) @name)  ; best-effort"
            else:
                return None
        elif name == "csharp":
            if kind == "func":
                q = "(method_declaration name: (identifier) @name)"
            elif kind == "class":
                q = "(class_declaration name: (identifier) @name)"
            elif kind == "interface":
                q = "(interface_declaration name: (identifier) @name)"
            elif kind == "namespace":
                q = "(namespace_declaration name: (identifier) @name)"
            else:
                return None
        else:
            return None
        return Query(L, q)
    except Exception:
        return None
    except Exception:
        return None

def _ts_capture_nodes(tree, src_bytes, name: str):
    res = []
    for kind in ["class","func","method"]:
        Q = _ts_query(name, kind)
        if not Q:
            continue
        try:
            root = tree.root_node
            caps = Q.captures(root)
            for node, capname in caps:
                if capname != "name":
                    continue
                # climb to definition node for lines
                parent = node.parent
                start = parent.start_point if parent is not None else node.start_point
                end = parent.end_point if parent is not None else node.end_point
                start_line = start[0]+1; end_line = end[0]+1
                text = ""
                try:
                    # slice lines
                    lines = src_bytes.decode("utf-8","ignore").splitlines()
                    seg = lines[start_line-1:end_line]
                    text = "\n".join(seg)
                except Exception:
                    pass
                name_text = src_bytes[node.start_byte:node.end_byte].decode("utf-8","ignore")
                k = "function" if kind in ("func","method") else "class"
                res.append({"kind":k, "name":name_text, "start_line":start_line, "end_line":end_line, "text":text})
        except Exception:
            continue
    return res

def _walk_file_ts(repo_id: str, file_path: str, lang_name: str) -> list[SymbolChunk]:
    parser = _ts_parser_for(lang_name)
    if parser is None:
        return _walk_file_generic(repo_id, file_path)
    try:
        src = _read_text(file_path)
        tree = parser.parse(src.encode("utf-8","ignore"))
        items = _ts_capture_nodes(tree, src.encode("utf-8","ignore"), lang_name)
        if not items:
            return _walk_file_generic(repo_id, file_path)
        chunks = []
        from json import dumps
        only_exported = ((SETTINGS or {}).get("analysis", {})).get("treesitter_exported_only", False)
        for it in items[:1000]:
            fqn = it["name"]
            # simple exported-only filter: skip if enabled and snippet does not contain "export"
            if only_exported:
                txt_low = (it.get("text") or "").lstrip()
                if not (txt_low.startswith("export ") or txt_low.startswith("export\n") or "export default" in txt_low):
                    continue
            chunks.append(SymbolChunk(
                repo_id=repo_id, file=file_path, fqn=fqn, kind=it["kind"],
                start_line=it["start_line"], end_line=it["end_line"],
                signature=f"({lang_name})", docstring="", text=it["text"],
                imports=_extract_imports_generic(src, lang_name), calls=[],
                last_modified=os.path.getmtime(file_path)
            ))
        return chunks
    except Exception:
        return _walk_file_generic(repo_id, file_path)
