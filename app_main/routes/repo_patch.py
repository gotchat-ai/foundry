import json
import os
from typing import Any, Callable


class RepoPatchRoutes:
    """Repo patch proposal and application route implementations."""

    def __init__(
        self,
        *,
        data_dir_getter: Callable[[], str],
        settings_getter: Callable[[], dict[str, Any]],
        safe_id: Callable[[str, str], str],
        safe_join: Callable[[str, str], str],
    ) -> None:
        self._data_dir_getter = data_dir_getter
        self._settings_getter = settings_getter
        self._safe_id = safe_id
        self._safe_join = safe_join

    @property
    def data_dir(self) -> str:
        return self._data_dir_getter() or os.path.abspath("./data")

    @property
    def settings(self) -> dict[str, Any]:
        try:
            return self._settings_getter() or {}
        except Exception:
            return {}

    def repo_patch_propose(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self.settings
        repo_id = self._safe_id(payload.get("repo_id") or "repo", "repo")
        file = payload.get("file")
        instruction = payload.get("instruction") or ""
        if not file:
            return {"ok": False, "error": "missing_file"}
        repo_root = os.path.join(self.data_dir, "repos", repo_id)
        try:
            abs_path = self._safe_join(repo_root, file)
        except Exception as e:
            return {"ok": False, "error": f"invalid_file: {e}"}
        if not os.path.isfile(abs_path):
            return {"ok": False, "error": "file_not_found"}
        llm_route = (settings.get("analysis", {}) or {}).get("llm_route", "/v1/chat/completions")
        llm_model = (settings.get("analysis", {}) or {}).get("llm_model", "gpt-local")
        try:
            from tools.llm_patch import propose_patch
            res = propose_patch(repo_id, abs_path, instruction, llm_route, llm_model)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        out_dir = os.path.join(self.data_dir, "analysis", repo_id, "patches")
        os.makedirs(out_dir, exist_ok=True)
        pid = str(len(os.listdir(out_dir)) + 1).zfill(4)
        pfile = os.path.join(out_dir, f"{pid}.diff")
        with open(pfile, "w", encoding="utf-8") as f:
            f.write(res.get("diff", ""))
        meta = {"patch_id": pid, "file": file, "instruction": instruction, "status": "proposed"}
        with open(os.path.join(out_dir, f"{pid}.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return {"ok": True, "patch_id": pid, "path": pfile}

    def repo_patch_apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        repo_id = self._safe_id(payload.get("repo_id") or "repo", "repo")
        patch_id = payload.get("patch_id")
        if not patch_id:
            return {"ok": False, "error": "missing_patch_id"}
        repo_root = os.path.join(self.data_dir, "repos", repo_id)
        pdir = os.path.join(self.data_dir, "analysis", repo_id, "patches")
        pfile = os.path.join(pdir, f"{patch_id}.diff")
        if not os.path.isfile(pfile):
            return {"ok": False, "error": "patch_not_found"}
        diff = open(pfile, "r", encoding="utf-8", errors="ignore").read()
        target = None
        for ln in diff.splitlines():
            if ln.startswith("+++ "):
                target = ln[4:].strip()
                if target.startswith("b/"):
                    target = target[2:]
                if target.startswith("a/"):
                    target = target[2:]
                break
        if not target:
            return {"ok": False, "error": "no_target_in_diff"}
        try:
            abs_path = self._safe_join(repo_root, target)
        except Exception as e:
            return {"ok": False, "error": f"invalid_target: {e}"}
        ext = os.path.splitext(abs_path)[1].lower()
        os.makedirs(os.path.join(pdir, "backups"), exist_ok=True)
        bak = os.path.join(pdir, "backups", f"{patch_id}.bak")
        try:
            src_before = open(abs_path, "r", encoding="utf-8", errors="ignore").read()
        except Exception as e:
            return {"ok": False, "error": f"read_error: {e}"}
        open(bak, "w", encoding="utf-8").write(src_before)
        ok = False
        err = None
        try:
            if ext == ".py":
                from tools.patcher_py import apply_unified_diff_python
                res = apply_unified_diff_python(abs_path, diff)
                ok = bool(res.get("ok"))
                err = res.get("error")
            else:
                try:
                    import patch as patchmod
                    ps = patchmod.fromstring(diff)
                    ok = ps.apply(root=repo_root)
                except Exception as e:
                    err = f"patch_apply_failed: {e}"
                if ok:
                    try:
                        from tools.repo_analyzer import _treesitter_available, _ts_parser_for, _guess_lang_by_ext
                        lang = _guess_lang_by_ext(abs_path)
                        if _treesitter_available() and lang in ("javascript", "typescript", "csharp"):
                            parser = _ts_parser_for(lang)
                            if parser is None:
                                ok = True
                            else:
                                src_after = open(abs_path, "r", encoding="utf-8", errors="ignore").read()
                                parser.parse(src_after.encode("utf-8", "ignore"))
                    except Exception as e:
                        err = f"syntax_check_failed: {e}"
                        ok = False
        except Exception as e:
            err = str(e)
            ok = False
        if not ok:
            open(abs_path, "w", encoding="utf-8").write(src_before)
            return {"ok": False, "error": err or "apply_failed"}
        clog = os.path.join(pdir, f"{patch_id}_changelog.txt")
        with open(clog, "w", encoding="utf-8") as f:
            f.write("FILE: " + abs_path + "\n")
            f.write("BEGIN ORIGINAL\n")
            f.write(src_before)
            f.write("\nEND ORIGINAL\n")
            try:
                src_after = open(abs_path, "r", encoding="utf-8", errors="ignore").read()
            except Exception:
                src_after = ""
            f.write("BEGIN NEW\n")
            f.write(src_after)
            f.write("\nEND NEW\n")
        return {"ok": True, "patch_id": patch_id, "file": abs_path, "changelog": clog}

