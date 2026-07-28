
import os, json
from typing import Dict

def list_symbols(repo_id: str, data_dir: str, query: str = "", lang: str = "") -> Dict:
    base = os.path.join(data_dir, "analysis", repo_id)
    sym_p = os.path.join(base, "symbols.jsonl")
    items = []
    if os.path.exists(sym_p):
        with open(sym_p, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    j = json.loads(line)
                    items.append(j)
                except Exception:
                    pass
    else:
        try:
            from tools.repo_analyzer import _guess_lang_by_ext
        except Exception:
            def _guess_lang_by_ext(p):
                ext = os.path.splitext(p)[1].lower()
                return {"py":"python","js":"javascript","ts":"typescript","tsx":"typescript",
                        "jsx":"javascript","cs":"csharp","c":"c","h":"c","html":"html",
                        "htm":"html","css":"css"}.get(ext[1:], "text")
        repo_root = os.path.join(data_dir, "repos", repo_id)
        for dirpath, dirnames, filenames in os.walk(repo_root):
            dirnames[:] = [d for d in dirnames if d not in {".git",".hg",".svn","node_modules",".venv","venv","__pycache__"}]
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                L = _guess_lang_by_ext(p)
                items.append({"name": os.path.splitext(fn)[0], "kind": "file", "lang": L,
                              "file": os.path.relpath(p, repo_root), "line_start": 1, "line_end": 1})
    q = (query or "").lower().strip()
    Lf = (lang or "").lower().strip()
    def ok(it):
        if q and q not in (it.get("name","").lower() + " " + it.get("file","").lower()): return False
        if Lf and Lf != str(it.get("lang","")).lower(): return False
        return True
    out = [it for it in items if ok(it)]
    return {"ok": True, "items": out[:2000]}
