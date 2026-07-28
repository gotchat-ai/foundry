
import os, ast, re, difflib
from pathlib import Path
try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

from typing import Any, Dict, List, Optional, Tuple
import json

# ---------- Small IO helpers ----------
def _read(p: str) -> str:
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def _write(p: str, s: str):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def _udiff(a: str, b: str, a_name: str, b_name: str) -> str:
    return "".join(difflib.unified_diff(a.splitlines(keepends=True), b.splitlines(keepends=True), fromfile=a_name, tofile=b_name))

# ---------- AST helpers (Python) ----------
def _attach_parents(tree: ast.AST):
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            setattr(child, "_parent", node)

class _SigChanger(ast.NodeTransformer):
    def __init__(self, class_name: Optional[str], func_name: str, param_name: str, default_src: Optional[str], annotation_src: Optional[str], strategy: int = 0):
        self.class_name = class_name
        self.func_name = func_name
        self.param_name = param_name
        self.default_src = default_src
        self.annotation_src = annotation_src
        self.changed = False
        self.strategy = strategy  # 0: end/before *args | 1: after self/cls if present | 2: end

    def _make_arg(self):
        ann = ast.parse(self.annotation_src).body[0].value if self.annotation_src else None
        return ast.arg(arg=self.param_name, annotation=ann)

    def _make_default(self):
        return ast.parse(self.default_src).body[0].value if self.default_src else None

    def _in_target(self, node: ast.FunctionDef) -> bool:
        if node.name != self.func_name:
            return False
        if self.class_name is None:
            # only top-level functions (no class parent)
            parent = getattr(node, "_parent", None)
            while parent is not None and not isinstance(parent, ast.Module):
                parent = getattr(parent, "_parent", None)
            return parent is not None
        # inside specific class
        parent = getattr(node, "_parent", None)
        while parent is not None and not isinstance(parent, ast.ClassDef):
            parent = getattr(parent, "_parent", None)
        return isinstance(parent, ast.ClassDef) and parent.name == self.class_name

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if not self._in_target(node):
            return node
        # already present?
        if any(a.arg == self.param_name for a in node.args.args):
            return node

        new_arg = self._make_arg()
        default_expr = self._make_default()

        args = list(node.args.args)
        # choose insertion index
        insert_idx = len(args)
        # prefer before *args if present
        if self.strategy == 0 and node.args.vararg is not None:
            insert_idx = len(args)  # still end of positional args (before vararg)
        elif self.strategy == 1 and args and args[0].arg in ("self","cls"):
            insert_idx = 1
        elif self.strategy == 2:
            insert_idx = len(args)

        # place arg
        args.insert(insert_idx, new_arg)
        node.args.args = args

        # handle defaults: make our param defaulted by appending to defaults
        if default_expr is not None:
            node.args.defaults = list(node.args.defaults) + [default_expr]

        self.changed = True
        return node

def add_param_to_func(src: str, class_name: Optional[str], func_name: str, param_name: str, default_src: Optional[str], annotation_src: Optional[str]) -> Tuple[str, bool]:
    # try multiple strategies to place param
    for strat in (0,1,2):
        try:
            tree = ast.parse(src)
            _attach_parents(tree)
            changer = _SigChanger(class_name, func_name, param_name, default_src, annotation_src, strategy=strat)
            new_tree = changer.visit(tree)
            if changer.changed:
                return (ast.unparse(new_tree), True)
        except Exception:
            continue
    # fallback regex (simple; may fail on complex defs)
    try:
        pat = r"(def\s+" + re.escape(func_name) + r"\s*\()([^\)]*)(\)\s*:)"
        def _repl(m):
            args = m.group(2).strip()
            if args == "":
                return f"def {func_name}({param_name})" + m.group(3) + ":"
            return f"def {func_name}({args}, {param_name})" + m.group(3) + ":"
        new_src, n = re.subn(pat, _repl, src, count=1, flags=re.S)
        return (new_src, n == 1)
    except Exception:
        return (src, False)

class _CallProp(ast.NodeTransformer):
    def __init__(self, func_name: str, named_arg_src: str):
        self.func_name = func_name
        self.named_arg_src = named_arg_src
        self.changed = False
        self._kw_name = named_arg_src.split("=",1)[0].strip()

    def visit_Call(self, node: ast.Call):
        f = node.func
        is_target = False
        if isinstance(f, ast.Attribute):
            is_target = (f.attr == self.func_name)
        elif isinstance(f, ast.Name):
            is_target = (f.id == self.func_name)
        if is_target:
            for kw in (node.keywords or []):
                if kw.arg == self._kw_name:
                    return node
            try:
                expr = ast.parse(self.named_arg_src).body[0].value
                node.keywords = list(node.keywords or []) + [ast.keyword(arg=self._kw_name, value=expr)]
                self.changed = True
            except Exception:
                return node
        return node

def add_named_kwarg_calls(src: str, func_name: str, named_arg_src: str) -> Tuple[str,bool]:
    try:
        tree = ast.parse(src)
        cp = _CallProp(func_name, named_arg_src)
        new_tree = cp.visit(tree)
        if cp.changed:
            return (ast.unparse(new_tree), True)
    except Exception:
        pass
    # weak regex fallback
    try:
        pat = r"(" + re.escape(func_name) + r"\s*\()([^\)]*)(\))"
        def _repl(m):
            args = m.group(2).strip()
            if args == "" or args == None:
                return f"{func_name}({named_arg_src})" + m.group(3)
            if named_arg_src.split("=")[0] in args:
                return m.group(0)
            return f"{func_name}({args}, {named_arg_src})" + m.group(3)
        new_src, n = re.subn(pat, _repl, src, count=0)
        return (new_src, n > 0)
    except Exception:
        return (src, False)

# ---------- Public API ----------
def apply_python_param_add(root_dir: str, file_glob: str, class_name: Optional[str], func_name: str, param_name: str, default_src: Optional[str], annotation_src: Optional[str]) -> Dict[str, Any]:
    changed = []
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): 
            continue
        old = _read(str(p))
        new, ok = add_param_to_func(old, class_name, func_name, param_name, default_src, annotation_src)
        if ok and new != old:
            _write(str(p), new)
            diff = _udiff(old, new, f"a/{p}", f"b/{p}")
            changed.append({"path": str(p.relative_to(root_dir)), "diff": diff})
    return {"changed": changed}

def propagate_calls(root_dir: str, file_glob: str, func_name: str, named_arg_src: str) -> Dict[str, Any]:
    changed = []
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir():
            continue
        old = _read(str(p))
        new, ok = add_named_kwarg_calls(old, func_name, named_arg_src)
        if ok and new != old:
            _write(str(p), new)
            diff = _udiff(old, new, f"a/{p}", f"b/{p}")
            changed.append({"path": str(p.relative_to(root_dir)), "diff": diff})
    return {"changed": changed}

def verify_signature(root_dir: str, file_glob: str, class_name: Optional[str], func_name: str, expect_param: str) -> Dict[str, Any]:
    hits = 0; files = []
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir():
            continue
        try:
            tree = ast.parse(_read(str(p)))
            # attach parents for class scope check
            for node in ast.walk(tree):
                for child in ast.iter_child_nodes(node):
                    setattr(child, "_parent", node)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == func_name:
                    parent = getattr(node, "_parent", None)
                    while parent is not None and not isinstance(parent, ast.ClassDef):
                        parent = getattr(parent, "_parent", None)
                    if (class_name is None and not isinstance(parent, ast.ClassDef)) or (isinstance(parent, ast.ClassDef) and parent.name == class_name):
                        if any(a.arg == expect_param for a in node.args.args):
                            hits += 1; files.append(str(p.relative_to(root_dir)))
        except Exception:
            continue
    return {"ok": hits > 0, "count": hits, "files": files}

def verify_calls(root_dir: str, file_glob: str, func_name: str, expect_kw: str) -> Dict[str, Any]:
    hits = 0; files = []
    target = expect_kw.split("=",1)[0].strip()
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir():
            continue
        try:
            tree = ast.parse(_read(str(p)))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    f = node.func
                    name = f.attr if isinstance(f, ast.Attribute) else (f.id if hasattr(f,"id") else None)
                    if name == func_name and any((kw.arg == target) for kw in (node.keywords or [])):
                        hits += 1; files.append(str(p.relative_to(root_dir))); break
        except Exception:
            continue
    return {"ok": hits > 0, "count": hits, "files": files}


# ---------- Higher-level edits ----------

def ensure_dir(p: str):
    os.makedirs(os.path.dirname(p), exist_ok=True)

def create_file(root_dir: str, rel_path: str, content: str) -> dict:
    p = os.path.join(root_dir, rel_path)
    ensure_dir(p)
    existed = os.path.exists(p)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return {"path": rel_path, "action": ("overwrite" if existed else "create")}

def _module_insertion_points(tree: ast.AST):
    """Yield likely insertion indices for new defs: end, after imports, after docstring."""
    # We will return None to indicate 'append to end' as default
    return [None]


def create_folder(root_dir: str, rel_path: str) -> dict:
    p = os.path.join(root_dir, rel_path)
    os.makedirs(p, exist_ok=True)
    return {"path": rel_path, "created": True}

def verify_folder_exists(root_dir: str, rel_path: str) -> dict:
    p = os.path.join(root_dir, rel_path)
    ok = os.path.isdir(p)
    return {"ok": ok, "path": rel_path}

def scaffold(root_dir: str, spec: dict) -> dict:
    """
    spec = {
      "folders": ["src", "tests/unit"],
      "files": [{"path":"README.md","content":"..."}, {"path":"src/__init__.py","content":""}]
    }
    """
    logs = {"folders": [], "files": []}
    for d in (spec.get("folders") or []):
        p = os.path.join(root_dir, d)
        os.makedirs(p, exist_ok=True)
        logs["folders"].append({"path": d, "created": True})
    for f in (spec.get("files") or []):
        p = os.path.join(root_dir, f.get("path"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(f.get("content",""))
        logs["files"].append({"path": f.get("path"), "written": True})
    return logs


def upsert_function(root_dir: str, file_glob: str, func_name: str, func_code: str) -> dict:
    changed = []; created = []
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): continue
        src = open(p,"r",encoding="utf-8").read()
        try:
            tree = ast.parse(src)
        except Exception:
            # if parse fails, fallback: append
            new_src = (src.rstrip() + "\n\n" + func_code.strip() + "\n")
            open(p,"w",encoding="utf-8").write(new_src)
            changed.append({"path": str(p.relative_to(root_dir)), "mode":"append_end"})
            continue
        # search for function
        found = False
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                found = True
                break
        if found:
            # replace by text fallback: crude but effective—replace the first def block with same name
            pat = r"(?ms)^def\s+%s\s*\(.*?\)\s*:(?:.*\n)*?(?=^\S|$\Z)" % re.escape(func_name)
            new_src, n = re.subn(pat, func_code.strip()+"\n", src)
            if n == 0:
                # if regex failed, append at end to keep a copy
                new_src = (src.rstrip() + "\n\n" + func_code.strip() + "\n")
            open(p,"w",encoding="utf-8").write(new_src)
            changed.append({"path": str(p.relative_to(root_dir)), "mode":"replace_or_append"})
        else:
            # insert at end
            new_src = (src.rstrip() + "\n\n" + func_code.strip() + "\n")
            open(p,"w",encoding="utf-8").write(new_src)
            changed.append({"path": str(p.relative_to(root_dir)), "mode":"insert_end"})
    return {"changed": changed, "created": created}

def upsert_class(root_dir: str, file_glob: str, class_name: str, class_code: str) -> dict:
    changed = []
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): continue
        src = open(p,"r",encoding="utf-8").read()
        try:
            tree = ast.parse(src)
        except Exception:
            new_src = (src.rstrip() + "\n\n" + class_code.strip() + "\n")
            open(p,"w",encoding="utf-8").write(new_src)
            changed.append({"path": str(p.relative_to(root_dir)), "mode":"append_end"})
            continue
        found = False
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                found = True; break
        if found:
            pat = r"(?ms)^class\s+%s\b.*?(?=^\S|$\Z)" % re.escape(class_name)
            new_src, n = re.subn(pat, class_code.strip()+"\n", src)
            if n == 0:
                new_src = (src.rstrip() + "\n\n" + class_code.strip() + "\n")
            open(p,"w",encoding="utf-8").write(new_src)
            changed.append({"path": str(p.relative_to(root_dir)), "mode":"replace_or_append"})
        else:
            new_src = (src.rstrip() + "\n\n" + class_code.strip() + "\n")
            open(p,"w",encoding="utf-8").write(new_src)
            changed.append({"path": str(p.relative_to(root_dir)), "mode":"insert_end"})
    return {"changed": changed}

def add_imports(root_dir: str, file_glob: str, import_lines: list) -> dict:
    changed = []
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): continue
        src = open(p,"r",encoding="utf-8").read()
        need = [ln for ln in import_lines if ln not in src]
        if not need: 
            continue
        # place after module docstring if present, else at top
        new_src = src
        m = re.match(r'(?s)^\s*(?P<ds>("""|\'\'\').*?\2)\s*', src)
        if m:
            pos = len(m.group(0))
            insert = "".join(ln if ln.endswith("\n") else (ln+"\n") for ln in need)
            new_src = src[:pos] + insert + src[pos:]
        else:
            insert = "".join(ln if ln.endswith("\n") else (ln+"\n") for ln in need)
            new_src = insert + src
        open(p,"w",encoding="utf-8").write(new_src)
        changed.append({"path": str(p.relative_to(root_dir)), "added": need})
    return {"changed": changed}

def replace_region(root_dir: str, file_glob: str, before_pat: str, after_pat: str, replacement: str) -> dict:
    """Replace text between two regex anchors (inclusive of anchors by default)."""
    changed = []
    before = re.compile(before_pat, re.M|re.S)
    after  = re.compile(after_pat, re.M|re.S)
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): continue
        src = open(p,"r",encoding="utf-8").read()
        b = before.search(src)
        if not b: continue
        a = after.search(src, b.end())
        if not a: continue
        new_src = src[:b.start()] + replacement + src[a.end():]
        if new_src != src:
            open(p,"w",encoding="utf-8").write(new_src)
            changed.append({"path": str(p.relative_to(root_dir)), "anchors":[before_pat, after_pat]})
    return {"changed": changed}

def verify_contains(root_dir: str, file_glob: str, contain_regex: str) -> dict:
    r = re.compile(contain_regex, re.M|re.S)
    hits = 0; files = []
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): continue
        s = open(p,"r",encoding="utf-8").read()
        if r.search(s):
            hits += 1; files.append(str(p.relative_to(root_dir)))
    return {"ok": hits>0, "count": hits, "files": files}


def apply_patch_plan(work_dir: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    logs: List[Dict[str, Any]] = []
    verifications: List[Dict[str, Any]] = []
    for op in plan.get("operations", []):
        t = op.get("type")
        if t == "add_param":
            file_glob = op.get("file_glob", "**/*.py")
            cls = op.get("class")
            func = op["function"]
            pname = op["param"]["name"]
            ann = op["param"].get("annotation")
            default = op["param"].get("default")

            res = apply_python_param_add(work_dir, file_glob, cls, func, pname, default, ann)
            logs.append({"op":"add_param","result":res})

            prop = op.get("propagate_calls")
            if prop:
                file_glob2 = prop.get("file_glob", "**/*.py")
                # support "Client.connect" -> pass only "connect" for AST name-matching
                qual = prop.get("qual_name", func)
                func_for_calls = qual.split(".")[-1]
                res2 = propagate_calls(work_dir, file_glob2, func_for_calls, prop["named_arg"])
                logs.append({"op":"propagate_calls","result":res2})

            # verify signature
            ver = verify_signature(work_dir, file_glob, cls, func, pname)
            verifications.append({"verify":"signature", "result": ver})
            if not ver["ok"]:
                # retry once (the AST changer already tries multiple placements)
                res_retry = apply_python_param_add(work_dir, file_glob, cls, func, pname, default, ann)
                v2 = verify_signature(work_dir, file_glob, cls, func, pname)
                logs.append({"op":"add_param_retry","result":res_retry})
                verifications.append({"verify":"signature_after_retry","result": v2})

            # verify calls
            if prop:
                v_calls = verify_calls(work_dir, file_glob2, func_for_calls, prop["named_arg"])
                verifications.append({"verify":"calls", "result": v_calls})
                if not v_calls["ok"]:
                    # second pass
                    res3 = propagate_calls(work_dir, file_glob2, func_for_calls, prop["named_arg"])
                    v3 = verify_calls(work_dir, file_glob2, func_for_calls, prop["named_arg"])
                    logs.append({"op":"propagate_calls_retry","result":res3})
                    verifications.append({"verify":"calls_after_retry","result": v3})

        elif t == "create_folder":
            res = create_folder(work_dir, op["path"])
            logs.append({"op":"create_folder","result":res})
            verifications.append({"verify":"folder_exists","result": verify_folder_exists(work_dir, op["path"])})
        elif t == "scaffold":
            res = scaffold(work_dir, op.get("spec", {}))
            logs.append({"op":"scaffold","result":res})
            # verify first folder if present
            if (op.get("spec",{}).get("folders")):
                verifications.append({"verify":"folder_exists","result": verify_folder_exists(work_dir, op["spec"]["folders"][0])})
        
        elif t == "add_param_js" or t == "add_param_ts":
            res = js_ts_add_param(work_dir, op.get("file_glob","**/*.{js,ts,tsx}"), op["function"], op["param_text"], op.get("class"), op.get("kind"))
            logs.append({"op":t,"result":res})
            if op.get("verify_regex"):
                verifications.append({"verify":"js_ts_contains","result": js_ts_verify_contains(work_dir, op.get("file_glob","**/*.{js,ts,tsx}"), op["verify_regex"])})
        elif t == "propagate_calls_js" or t == "propagate_calls_ts":
            res = js_ts_propagate_calls(work_dir, op.get("file_glob","**/*.{js,ts,tsx}"), op["function"], op["arg_text"])
            logs.append({"op":t,"result":res})
        elif t == "add_imports_js" or t == "add_imports_ts":
            res = js_ts_add_imports(work_dir, op.get("file_glob","**/*.{js,ts,tsx}"), op.get("imports",[]))
            logs.append({"op":t,"result":res})
        elif t == "upsert_function_js" or t == "upsert_function_ts":
            res = js_ts_upsert_function(work_dir, op.get("file_glob","**/*.{js,ts,tsx}"), op["name"], op["code"])
            logs.append({"op":t,"result":res})
        elif t == "upsert_class_js" or t == "upsert_class_ts":
            res = js_ts_upsert_class(work_dir, op.get("file_glob","**/*.{js,ts,tsx}"), op["name"], op["code"])
            logs.append({"op":t,"result":res})
        elif t == "add_using_cs":
            res = cs_add_using(work_dir, op.get("file_glob","**/*.cs"), op.get("usings", []))
            logs.append({"op":"add_using_cs","result":res})
        elif t == "add_param_cs":
            res = cs_add_param(work_dir, op.get("file_glob","**/*.cs"), op.get("class"), op["method"], op["param_text"])
            logs.append({"op":"add_param_cs","result":res})
        elif t == "propagate_calls_cs":
            res = cs_propagate_calls(work_dir, op.get("file_glob","**/*.cs"), op["method"], op["arg_text"])
            logs.append({"op":"propagate_calls_cs","result":res})
        elif t == "upsert_class_cs":
            res = cs_upsert_class(work_dir, op.get("file_glob","**/*.cs"), op["name"], op["code"])
            logs.append({"op":"upsert_class_cs","result":res})
        
        elif t == "html_patch":
            res = html_apply_patch(work_dir, op.get("file_glob","**/*.html"), op.get("ops", []))
            logs.append({"op":"html_patch","result":res})
        elif t == "json_patch":
            res = json_apply_patch(work_dir, op.get("file_glob","**/*.json"), op.get("ops", []))
            logs.append({"op":"json_patch","result":res})
            if op.get("verify_pointer"):
                vp = op["verify_pointer"]
                verifications.append({"verify":"json_pointer","result": json_verify_pointer(work_dir, op.get("file_glob","**/*.json"), vp.get("path"), vp.get("expect"))})

        elif t == "dotnet_build":
            res = dotnet_build(work_dir, op.get("solution_glob"), op.get("project_glob"), op.get("configuration","Debug"), op.get("args"), int(op.get("timeout_sec",600)))
            logs.append({"op":"dotnet_build","result":res})
            verifications.append({"verify":"dotnet_build","result": {"ok": res.get("ok", False)}})
        elif t == "dotnet_test":
            res = dotnet_test(work_dir, op.get("solution_glob"), op.get("project_glob"), op.get("configuration","Debug"), op.get("filter"), op.get("collect"), op.get("args"), int(op.get("timeout_sec",900)))
            logs.append({"op":"dotnet_test","result":res})
            verifications.append({"verify":"dotnet_test","result": {"ok": res.get("ok", False)}})

    return {"logs": logs, "verifications": verifications}


# ================= JS/TS/C#/JSON patch helpers (regex/CST-style) =================

# ---- JS/TS ----
def js_ts_add_param(root_dir: str, file_glob: str, func: str, param_text: str, class_name: str | None = None, kind: str | None = None) -> dict:
    """
    kind: 'function' | 'method' | 'arrow' | None (auto)
    Adds param_text at end of param list if not present.
    """
    changed = []
    fn = re.escape(func)
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): continue
        s = p.read_text(encoding="utf-8")
        orig = s

        def has_param_list(params: str) -> bool:
            # naive contains check by parameter name (before ':' or '=' or ',' or ')')
            name = param_text.split(":")[0].split("=")[0].strip()
            return re.search(rf'(^|[,(\s]){re.escape(name)}(\s*[:=,)\]])', params) is not None

        def insert_into_params(params: str) -> str:
            params_stripped = params.strip()
            if not params_stripped:
                return param_text
            if has_param_list(params):
                return params
            return params + (", " if params_stripped else "") + param_text

        # function decl
        if kind in (None, "function"):
            s = re.sub(rf'(function\s+{fn}\s*\()(?P<p>[^)]*)(\))', lambda m: m.group(1)+insert_into_params(m.group('p'))+")", s, flags=re.M)
        # arrow const
        if kind in (None, "arrow"):
            s = re.sub(rf'(const\s+{fn}\s*=\s*\()(?P<p>[^)]*)(\)\s*=>)', lambda m: m.group(1)+insert_into_params(m.group('p'))+")"+m.group(3), s, flags=re.M)
        # class method
        if kind in (None, "method"):
            if class_name:
                # find class block first (simplified)
                cls_pat = rf'(class\s+{re.escape(class_name)}[^\{{]*\{{)(?P<body>[\s\S]*?)(\n\}})'
                def _cls_repl(mc):
                    body = mc.group('body')
                    body_new = re.sub(rf'(\b{fn}\s*\()(?P<p>[^)]*)(\))', lambda m2: m2.group(1)+insert_into_params(m2.group('p'))+")", body, flags=re.M)
                    if body_new != body:
                        return mc.group(1)+body_new+mc.group(3)
                    return mc.group(0)
                s = re.sub(cls_pat, _cls_repl, s, flags=re.M)

        if s != orig:
            p.write_text(s, encoding="utf-8")
            changed.append({"path": str(p.relative_to(root_dir))})
    return {"changed": changed}

def js_ts_propagate_calls(root_dir: str, file_glob: str, func: str, arg_text: str) -> dict:
    changed = []
    fn = re.escape(func.split(".")[-1])
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): continue
        s = p.read_text(encoding="utf-8"); orig = s

        def append_arg(args: str) -> str:
            if not args.strip(): return arg_text
            if arg_text.split(":")[0].split("=")[0].strip() in args:
                return args
            return args + ", " + arg_text

        # free or method calls
        s = re.sub(rf'(\.{fn}\s*\()(?P<a>[^)]*)(\))', lambda m: m.group(1)+append_arg(m.group('a'))+")", s)
        s = re.sub(rf'({fn}\s*\()(?P<a>[^)]*)(\))', lambda m: m.group(1)+append_arg(m.group('a'))+")", s)

        if s != orig:
            p.write_text(s, encoding="utf-8"); changed.append({"path": str(p.relative_to(root_dir))})
    return {"changed": changed}

def js_ts_add_imports(root_dir: str, file_glob: str, import_lines: list[str]) -> dict:
    changed = []
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): continue
        s = p.read_text(encoding="utf-8")
        need = [ln for ln in import_lines if ln and ln not in s]
        if not need: continue
        insert = "".join([ln if ln.endswith("\n") else (ln+"\n") for ln in need])
        new_s = insert + s
        p.write_text(new_s, encoding="utf-8"); changed.append({"path": str(p.relative_to(root_dir)), "added": need})
    return {"changed": changed}

def js_ts_upsert_function(root_dir: str, file_glob: str, name: str, code: str) -> dict:
    changed = []
    fn = re.escape(name)
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): continue
        s = p.read_text(encoding="utf-8"); orig = s
        # try function decl
        s2, n = re.subn(rf'(?ms)^function\s+{fn}\s*\(.*?\)\s*\{{.*?\}}\s*', code.strip()+"\n", s)
        if n == 0:
            # try const arrow
            s2, n = re.subn(rf'(?ms)^const\s+{fn}\s*=\s*\(.*?\)\s*=>\s*\{{.*?\}}\s*;', code.strip()+"\n", s2)
        if n == 0:
            s2 = s2.rstrip() + "\n\n" + code.strip() + "\n"
        if s2 != orig:
            p.write_text(s2, encoding="utf-8"); changed.append({"path": str(p.relative_to(root_dir))})
    return {"changed": changed}

def js_ts_upsert_class(root_dir: str, file_glob: str, name: str, code: str) -> dict:
    changed = []
    cn = re.escape(name)
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): continue
        s = p.read_text(encoding="utf-8"); orig = s
        s2, n = re.subn(rf'(?ms)^class\s+{cn}\b.*?\n\}}\s*', code.strip()+"\n", s)
        if n == 0:
            s2 = s2.rstrip() + "\n\n" + code.strip() + "\n"
        if s2 != orig:
            p.write_text(s2, encoding="utf-8"); changed.append({"path": str(p.relative_to(root_dir))})
    return {"changed": changed}

def js_ts_verify_contains(root_dir: str, file_glob: str, regex: str) -> dict:
    r = re.compile(regex, re.M|re.S)
    hits = 0; files = []
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): continue
        if r.search(p.read_text(encoding="utf-8")):
            hits += 1; files.append(str(p.relative_to(root_dir)))
    return {"ok": hits>0, "count": hits, "files": files}

# ---- C# ----
def cs_add_using(root_dir: str, file_glob: str, using_lines: list[str]) -> dict:
    changed = []
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): continue
        s = p.read_text(encoding="utf-8"); need = [ln for ln in using_lines if ln not in s]
        if not need: continue
        insert = "".join([ln if ln.endswith("\n") else (ln+"\n") for ln in need])
        new_s = insert + s
        p.write_text(new_s, encoding="utf-8"); changed.append({"path": str(p.relative_to(root_dir)), "added": need})
    return {"changed": changed}

def cs_add_param(root_dir: str, file_glob: str, class_name: str | None, method: str, param_text: str) -> dict:
    changed = []
    mn = re.escape(method)
    pname = re.split(r'[:=\s]', param_text.strip())[-1] if ":" in param_text or "=" in param_text else param_text.strip().split()[-1]
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): continue
        s = p.read_text(encoding="utf-8"); orig = s
        def insert_params(params: str) -> str:
            if re.search(rf'(^|[,(\s]){re.escape(pname)}(\s*[:=,)\]])', params): return params
            if not params.strip(): return param_text
            return params + ", " + param_text
        if class_name:
            cls_pat = rf'(class\s+{re.escape(class_name)}[^\{{]*\{{)(?P<body>[\s\S]*?)(\n\}})'
            def _cls_repl(mc):
                body = mc.group('body')
                body_new = re.sub(rf'(\b{mn}\s*\()(?P<p>[^)]*)(\))', lambda m: m.group(1)+insert_params(m.group('p'))+")", body)
                if body_new != body:
                    return mc.group(1)+body_new+mc.group(3)
                return mc.group(0)
            s = re.sub(cls_pat, _cls_repl, s)
        else:
            s = re.sub(rf'(\b{mn}\s*\()(?P<p>[^)]*)(\))', lambda m: m.group(1)+insert_params(m.group('p'))+")", s)
        if s != orig:
            p.write_text(s, encoding="utf-8"); changed.append({"path": str(p.relative_to(root_dir))})
    return {"changed": changed}

def cs_propagate_calls(root_dir: str, file_glob: str, method: str, arg_text: str) -> dict:
    changed = []
    mn = re.escape(method)
    pname = arg_text.split(":")[0].split("=")[0].strip()
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): continue
        s = p.read_text(encoding="utf-8"); orig = s
        def append_arg(args: str) -> str:
            if not args.strip(): return arg_text
            if re.search(rf'(^|[,(\s]){re.escape(pname)}\s*:', args): return args
            return args + ", " + arg_text
        s = re.sub(rf'(\.{mn}\s*\()(?P<a>[^)]*)(\))', lambda m: m.group(1)+append_arg(m.group('a'))+")", s)
        s = re.sub(rf'({mn}\s*\()(?P<a>[^)]*)(\))', lambda m: m.group(1)+append_arg(m.group('a'))+")", s)
        if s != orig:
            p.write_text(s, encoding="utf-8"); changed.append({"path": str(p.relative_to(root_dir))})
    return {"changed": changed}

def cs_upsert_class(root_dir: str, file_glob: str, name: str, code: str) -> dict:
    changed = []
    cn = re.escape(name)
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): continue
        s = p.read_text(encoding="utf-8"); orig = s
        s2, n = re.subn(rf'(?ms)^class\s+{cn}\b.*?\n\}}\s*', code.strip()+"\n", s)
        if n == 0:
            s2 = s2.rstrip() + "\n\n" + code.strip() + "\n"
        if s2 != orig:
            p.write_text(s2, encoding="utf-8"); changed.append({"path": str(p.relative_to(root_dir))})
    return {"changed": changed}

def cs_verify_contains(root_dir: str, file_glob: str, regex: str) -> dict:
    r = re.compile(regex, re.M|re.S)
    hits = 0; files = []
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): continue
        if r.search(p.read_text(encoding="utf-8")):
            hits += 1; files.append(str(p.relative_to(root_dir)))
    return {"ok": hits>0, "count": hits, "files": files}

# ---- JSON ----
def json_apply_patch(root_dir: str, file_glob: str, ops: list[dict]) -> dict:
    changed = []
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        orig = json.dumps(data, ensure_ascii=False, indent=2)
        def resolve(ptr: str):
            # very small JSON Pointer (RFC 6901) subset
            parts = [seg.replace("~1","/").replace("~0","~") for seg in ptr.strip("/").split("/") if seg!=""]
            parent = None; key = None; cur = data
            for seg in parts:
                parent, key = cur, seg
                if isinstance(cur, list):
                    idx = int(seg)
                    if idx >= len(cur): 
                        while len(cur) <= idx: cur.append(None)
                    cur = cur[idx]
                else:
                    if seg not in cur: cur[seg] = None
                    cur = cur[seg]
            return parent, key
        for op in ops or []:
            t = op.get("op")
            path = op.get("path")
            if not path: continue
            parent, key = resolve(path)
            if t == "add" or t == "replace":
                val = op.get("value")
                if isinstance(parent, list):
                    idx = int(key); 
                    if t == "add" and idx == len(parent): parent.append(val)
                    else: parent[idx] = val
                else:
                    parent[key] = val
            elif t == "remove":
                if isinstance(parent, list):
                    del parent[int(key)]
                else:
                    parent.pop(key, None)
        new = json.dumps(data, ensure_ascii=False, indent=2)
        if new != orig:
            p.write_text(new, encoding="utf-8"); changed.append({"path": str(p.relative_to(root_dir))})
    return {"changed": changed}

def json_verify_pointer(root_dir: str, file_glob: str, path: str, expect_value: Any | None = None) -> dict:
    ok = False; files = []
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        # resolve
        parts = [seg.replace("~1","/").replace("~0","~") for seg in path.strip("/").split("/") if seg!=""]
        cur = data; exists = True
        for seg in parts:
            if isinstance(cur, list):
                idx = int(seg)
                if idx >= len(cur): exists = False; break
                cur = cur[idx]
            else:
                if seg not in cur: exists = False; break
                cur = cur[seg]
        if exists and (expect_value is None or cur == expect_value):
            ok = True; files.append(str(p.relative_to(root_dir)))
    return {"ok": ok, "files": files}


# ================= .NET (C#) build/test hooks =================
import subprocess, shlex, time as _time

def _run_cmd(cmd_list, cwd, timeout_sec=300):
    t0 = _time.time()
    try:
        p = subprocess.run(cmd_list, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_sec, text=True)
        took = _time.time() - t0
        out = (p.stdout or "")[-40000:]  # keep tail
        err = (p.stderr or "")[-40000:]
        return {"rc": p.returncode, "stdout": out, "stderr": err, "took_sec": took}
    except subprocess.TimeoutExpired as e:
        took = _time.time() - t0
        out = (e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or ""))[-40000:]
        err = (e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or ""))[-40000:]
        return {"rc": 124, "stdout": out, "stderr": err, "took_sec": took, "timeout": True}
    except FileNotFoundError:
        return {"rc": 127, "stdout": "", "stderr": "dotnet not found on PATH", "took_sec": 0.0}

def _glob_many(root_dir, patterns):
    import glob
    hits = []
    for pat in patterns:
        hits.extend([p for p in glob.glob(os.path.join(root_dir, pat), recursive=True)])
    return sorted(set(hits))

def dotnet_build(root_dir: str, solution_glob: str | None = None, project_glob: str | None = None, configuration: str = "Debug", args: list[str] | None = None, timeout_sec: int = 600) -> dict:
    sols = _glob_many(root_dir, [solution_glob] if solution_glob else [])
    projs = _glob_many(root_dir, [project_glob] if project_glob else [])
    if not sols and not projs:
        # default search
        sols = _glob_many(root_dir, ["**/*.sln"])
        projs = _glob_many(root_dir, ["**/*.csproj"])

    targets = sols or projs
    results = []
    ok_all = True
    for t in targets:
        cwd = os.path.dirname(t) or root_dir
        cmd = ["dotnet", "build", t, "-c", configuration, "-v", "minimal"]
        if args: cmd.extend(args)
        res = _run_cmd(cmd, cwd=cwd, timeout_sec=timeout_sec)
        ok_all = ok_all and (res.get("rc", 1) == 0)
        results.append({"target": os.path.relpath(t, root_dir), **res})
    return {"ok": ok_all, "results": results}

def dotnet_test(root_dir: str, solution_glob: str | None = None, project_glob: str | None = None, configuration: str = "Debug", filter_expr: str | None = None, collect: list[str] | None = None, args: list[str] | None = None, timeout_sec: int = 900) -> dict:
    sols = _glob_many(root_dir, [solution_glob] if solution_glob else [])
    projs = _glob_many(root_dir, [project_glob] if project_glob else [])
    if not sols and not projs:
        sols = _glob_many(root_dir, ["**/*.sln"])
        projs = _glob_many(root_dir, ["**/*Tests.csproj", "**/*.csproj"])

    targets = sols or projs
    results = []
    ok_all = True
    for t in targets:
        cwd = os.path.dirname(t) or root_dir
        cmd = ["dotnet", "test", t, "-c", configuration, "-v", "minimal", "--nologo"]
        if filter_expr:
            cmd.extend(["--filter", filter_expr])
        if collect:
            for col in collect:
                cmd.extend(["--collect", col])
        if args: cmd.extend(args)
        res = _run_cmd(cmd, cwd=cwd, timeout_sec=timeout_sec)
        ok_all = ok_all and (res.get("rc", 1) == 0)
        results.append({"target": os.path.relpath(t, root_dir), **res})
    return {"ok": ok_all, "results": results}


# ================= HTML patch helpers (BeautifulSoup/CSS) =================
def _html_select(soup, selector: str):
    # Minimal CSS select via bs4; supports tag, #id, .class, attr filters
    try:
        return soup.select(selector)
    except Exception:
        # fallback: try interpreting as id
        if selector.startswith("#"):
            el = soup.find(id=selector[1:])
            return [el] if el else []
        return []

def _html_apply_op(soup, op: dict):
    t = op.get("op")
    selector = op.get("selector")
    if t in ("set_attr","del_attr","set_text","set_html","insert_before","insert_after","append_child","prepend_child","remove","rename_tag","wrap","unwrap"):
        nodes = _html_select(soup, selector) if selector else [soup]
    else:
        nodes = [soup]
    if t == "set_attr":
        name = op["name"]; value = op.get("value","")
        for n in nodes:
            n.attrs[name] = value
    elif t == "del_attr":
        name = op["name"]
        for n in nodes:
            if name in n.attrs: del n.attrs[name]
    elif t == "set_text":
        value = op.get("value","")
        for n in nodes:
            n.string = value
    elif t == "set_html":
        value = op.get("value","")
        for n in nodes:
            n.clear()
            # parse fragment into temp soup and append children
            frag = BeautifulSoup(value, "lxml") if BeautifulSoup else None
            if frag:
                for child in frag.body.contents if frag.body else frag.contents:
                    n.append(child)
            else:
                n.append(value)
    elif t == "insert_before":
        html = op.get("html","")
        for n in nodes:
            frag = BeautifulSoup(html, "lxml") if BeautifulSoup else None
            if frag and (frag.body or frag.contents):
                for child in (frag.body.contents if frag.body else frag.contents):
                    n.insert_before(child)
            else:
                n.insert_before(html)
    elif t == "insert_after":
        html = op.get("html","")
        for n in nodes:
            frag = BeautifulSoup(html, "lxml") if BeautifulSoup else None
            if frag and (frag.body or frag.contents):
                for child in (reversed(frag.body.contents) if frag.body else reversed(frag.contents)):
                    n.insert_after(child)
            else:
                n.insert_after(html)
    elif t == "append_child":
        html = op.get("html","")
        for n in nodes:
            frag = BeautifulSoup(html, "lxml") if BeautifulSoup else None
            if frag and (frag.body or frag.contents):
                for child in (frag.body.contents if frag.body else frag.contents):
                    n.append(child)
            else:
                n.append(html)
    elif t == "prepend_child":
        html = op.get("html","")
        for n in nodes:
            frag = BeautifulSoup(html, "lxml") if BeautifulSoup else None
            if frag and (frag.body or frag.contents):
                for child in (reversed(frag.body.contents) if frag.body else reversed(frag.contents)):
                    n.insert(0, child)
            else:
                n.insert(0, html)
    elif t == "remove":
        for n in nodes:
            n.decompose()
    elif t == "rename_tag":
        new_name = op["name"]
        for n in nodes:
            n.name = new_name
    elif t == "wrap":
        html = op.get("html", "<div></div>")
        for n in nodes:
            wrapper = BeautifulSoup(html, "lxml").find() if BeautifulSoup else None
            if wrapper:
                n.wrap(wrapper)
    elif t == "unwrap":
        for n in nodes:
            n.unwrap()
    else:
        raise ValueError(f"Unsupported html op: {t}")

def html_apply_patch(root_dir: str, file_glob: str, ops: list[dict]) -> dict:
    if BeautifulSoup is None:
        return {"changed": [], "errors": ["beautifulsoup4 is not installed"]}
    changed = []
    errors = []
    for p in Path(root_dir).rglob(file_glob):
        if p.is_dir(): continue
        if not p.suffix.lower() in {".html",".htm"}: 
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except Exception as e:
            errors.append(f"read_fail:{p}:{e}")
            continue
        parser = "lxml" if BeautifulSoup else "html.parser"
        soup = BeautifulSoup(src, parser)
        before = str(soup)
        applied = False
        for op in ops:
            try:
                _html_apply_op(soup, op)
                applied = True
            except Exception as e:
                errors.append(f"op_fail:{p}:{op.get('op')}:{e}")
        after = str(soup)
        if applied and after != before:
            p.write_text(after, encoding="utf-8")
            diff = _udiff(before, after, str(p), str(p))
            changed.append({"file": str(p), "diff": diff})
    return {"changed": changed, "errors": errors}
