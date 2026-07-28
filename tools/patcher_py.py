
import os, json
try:
    import libcst as cst
    CST_OK = True
except Exception:
    CST_OK = False

def propose_python_patch(file_path: str, instruction: str) -> dict:
    """
    Simple strategy: we do not modify here; we just load file contents for LLM and expect a unified diff back.
    The apply step will verify parse via LibCST.
    """
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        src = f.read()
    return {"ok": True, "language":"python", "file": file_path, "src": src}

def apply_unified_diff_python(file_path: str, diff_text: str) -> dict:
    if not CST_OK:
        return {"ok": False, "error": "libcst_not_installed"}
    # naive patch via difflib: we trust diff; afterwards, validate parse
    import io, difflib
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        old = f.read().splitlines(keepends=True)
    # parse diff (expects unified diff)
    patched = list(difflib.restore(list(difflib.Differ().compare(old, old)), 1))  # start with identity
    # We'll apply unified diff using patch module if available; else manual (best effort)
    try:
        import patch as patchmod  # optional 'python-patch' package
        ps = patchmod.fromstring(diff_text)
        if not ps.apply(root=os.path.dirname(file_path)):
            return {"ok": False, "error": "patch_apply_failed"}
        new_src = open(file_path,"r",encoding="utf-8",errors="ignore").read()
    except Exception:
        # Fallback: crude replace by hunks is complex; bail with error
        return {"ok": False, "error": "patch_module_missing"}
    # validate parse
    try:
        cst.parse_module(new_src)
    except Exception as e:
        return {"ok": False, "error": f"parse_error_after_patch: {e}"}
    return {"ok": True, "file": file_path}
