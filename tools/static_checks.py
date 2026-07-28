
import os, re, json, ast
from typing import List, Dict

def _read(path: str) -> str:
    return open(path, "r", encoding="utf-8", errors="ignore").read()

def _iter_py(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git",".hg",".svn","__pycache__",".venv","venv",".mypy_cache",".ruff_cache"}]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)

def _mutable_default_args(node: ast.AST) -> List[int]:
    lines = []
    for n in ast.walk(node):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defaults = (n.args.defaults or []) + (n.args.kw_defaults or [])
            for d in defaults:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                    lines.append(n.lineno)
    return lines

def _broad_except_pass(node: ast.AST) -> List[int]:
    lines = []
    for n in ast.walk(node):
        if isinstance(n, ast.Try):
            for h in n.handlers:
                if h.type is None or (isinstance(h.type, ast.Name) and h.type.id in {"Exception","BaseException"}):
                    # check for pass or empty body
                    body = h.body or []
                    if all(isinstance(x, ast.Pass) for x in body) or len(body) == 0:
                        lines.append(h.lineno or n.lineno)
    return lines

def _inconsistent_returns(node: ast.AST) -> List[int]:
    # Very coarse: functions that have both "return value" and "bare return"/no return
    lines = []
    for n in ast.walk(node):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            has_value = False; has_bare = False
            for sub in ast.walk(n):
                if isinstance(sub, ast.Return):
                    if sub.value is None:
                        has_bare = True
                    else:
                        has_value = True
            if has_value and has_bare:
                lines.append(n.lineno)
    return lines

def run_checks(repo_id: str, root_dir: str, out_path: str) -> str:
    issues: List[Dict] = []
    for path in _iter_py(root_dir):
        try:
            src = _read(path)
            tree = ast.parse(src)
        except Exception as e:
            issues.append({"tool":"parser","file":path,"line":1,"severity":"high","code":"syntax-error","message":str(e)})
            continue
        for ln in _mutable_default_args(tree):
            issues.append({"tool":"static","file":path,"line":ln,"severity":"med","code":"mutable-default","message":"Function has mutable default parameter"})
        for ln in _broad_except_pass(tree):
            issues.append({"tool":"static","file":path,"line":ln,"severity":"med","code":"broad-except-pass","message":"Broad except that passes"})
        for ln in _inconsistent_returns(tree):
            issues.append({"tool":"static","file":path,"line":ln,"severity":"med","code":"inconsistent-returns","message":"Function mixes return with/without value"})
    with open(out_path, "w", encoding="utf-8") as f:
        for it in issues:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    return out_path


GENERIC_JS = {".js",".mjs",".cjs",".jsx",".ts",".tsx"}
GENERIC_C  = {".c",".h"}
GENERIC_HTML = {".html",".htm"}

def _iter_generic(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git",".hg",".svn","__pycache__",".venv","venv",".mypy_cache",".ruff_cache"}]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in GENERIC_JS or ext in GENERIC_C or ext in GENERIC_HTML:
                yield os.path.join(dirpath, fn), ext

def _scan_js(text: str, path: str) -> list[dict]:
    items=[]; lines=text.splitlines()
    for i,l in enumerate(lines, start=1):
        if "eval(" in l:
            items.append({"tool":"static","file":path,"line":i,"severity":"high","code":"js-eval","message":"Use of eval() is dangerous"})
        if "document.write(" in l:
            items.append({"tool":"static","file":path,"line":i,"severity":"med","code":"js-document-write","message":"document.write() can be unsafe"})
        if "innerHTML" in l and "=" in l:
            items.append({"tool":"static","file":path,"line":i,"severity":"med","code":"js-innerHTML-assign","message":"Direct innerHTML assignment may be XSS-prone"})
    return items

def _scan_c(text: str, path: str) -> list[dict]:
    items=[]; lines=text.splitlines()
    for i,l in enumerate(lines, start=1):
        if "gets(" in l:
            items.append({"tool":"static","file":path,"line":i,"severity":"high","code":"c-gets","message":"gets() is unsafe; use fgets()"})
        if "strcpy(" in l and "strncpy" not in l:
            items.append({"tool":"static","file":path,"line":i,"severity":"med","code":"c-strcpy","message":"strcpy() may overflow; use strncpy()/strlcpy()"})
        if "system(" in l:
            items.append({"tool":"static","file":path,"line":i,"severity":"med","code":"c-system","message":"system() use: ensure inputs are sanitized"})
    return items

def _scan_html(text: str, path: str) -> list[dict]:
    items=[]; lines=text.splitlines()
    for i,l in enumerate(lines, start=1):
        if "onload=" in l or "onclick=" in l:
            items.append({"tool":"static","file":path,"line":i,"severity":"low","code":"html-inline-handler","message":"Inline event handler found; prefer addEventListener"})
    return items

def run_generic_checks(root_dir: str, out_path: str) -> str:
    items=[]
    for path, ext in _iter_generic(root_dir):
        try:
            text = _read(path)
        except Exception as e:
            items.append({"tool":"static","file":path,"line":1,"severity":"high","code":"read-error","message":str(e)})
            continue
        if ext in GENERIC_JS:
            items.extend(_scan_js(text, path))
        elif ext in GENERIC_C:
            items.extend(_scan_c(text, path))
        elif ext in GENERIC_HTML:
            items.extend(_scan_html(text, path))
    if items:
        with open(out_path, "a", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
    return out_path
