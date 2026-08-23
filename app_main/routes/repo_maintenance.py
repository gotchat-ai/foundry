import datetime
import os
import subprocess
from typing import Any, Callable


class RepoMaintenanceRoutes:
    """Repo git maintenance, symbols, versions, and targeted analysis helpers."""

    def __init__(
        self,
        *,
        data_dir_getter: Callable[[], str],
        settings_getter: Callable[[], dict[str, Any]],
        safe_id: Callable[[str, str], str],
        git_log: Callable[[str, int], list[str]],
        job_analyze_repo: Callable[..., dict[str, Any]],
    ) -> None:
        self._data_dir_getter = data_dir_getter
        self._settings_getter = settings_getter
        self._safe_id = safe_id
        self._git_log = git_log
        self._job_analyze_repo = job_analyze_repo

    @property
    def data_dir(self) -> str:
        return self._data_dir_getter() or os.path.abspath("./data")

    @property
    def settings(self) -> dict[str, Any]:
        try:
            return self._settings_getter() or {}
        except Exception:
            return {}

    def _run_tool(self, repo_root: str, cmd: str) -> dict[str, Any]:
        try:
            proc = subprocess.run(cmd, cwd=repo_root, shell=True, capture_output=True, text=True, timeout=900)
            return {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": proc.stdout[-12000:],
                "stderr": proc.stderr[-12000:],
                "cmd": cmd,
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "cmd": cmd}

    def _git_is_dirty(self, repo_root: str) -> bool:
        try:
            out = subprocess.check_output(["git", "status", "--porcelain"], cwd=repo_root).decode("utf-8", "ignore")
            return bool(out.strip())
        except Exception:
            return False

    def _git_head_hash(self, repo_root: str) -> str:
        try:
            return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root).decode("utf-8", "ignore").strip()
        except Exception:
            return ""

    def _git_backup_tag(self, repo_root: str, prefix: str = "backup") -> str:
        try:
            ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            tag = f"{prefix}-{ts}"
            subprocess.run(["git", "tag", tag], cwd=repo_root, check=False)
            return tag
        except Exception:
            return ""

    def _git_checkout_ref(self, repo_root: str, ref: str, branch: str = None) -> dict[str, Any]:
        try:
            if branch:
                subprocess.run(["git", "checkout", "-B", branch, ref], cwd=repo_root, check=False)
            else:
                subprocess.run(["git", "checkout", ref], cwd=repo_root, check=False)
            head = self._git_head_hash(repo_root)
            return {"ok": True, "head": head}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _git_init_if_needed(self, repo_root: str, branch: str = "autobuilder") -> None:
        try:
            if not os.path.isdir(os.path.join(repo_root, ".git")):
                subprocess.run(["git", "init"], cwd=repo_root, check=False)
            subprocess.run(["git", "checkout", "-B", branch], cwd=repo_root, check=False)
        except Exception:
            pass

    def _git_commit(self, repo_root: str, message: str) -> None:
        try:
            subprocess.run(["git", "add", "-A"], cwd=repo_root, check=False)
            subprocess.run(["git", "commit", "-m", message], cwd=repo_root, check=False)
        except Exception:
            pass

    def _git_tag(self, repo_root: str, tag: str) -> None:
        try:
            subprocess.run(["git", "tag", "-f", tag], cwd=repo_root, check=False)
        except Exception:
            pass

    def _run_smoke(self, repo_root: str, smoke_cmd: str) -> dict[str, Any]:
        if not smoke_cmd:
            return {"ok": True, "skipped": True}
        try:
            proc = subprocess.run(smoke_cmd, cwd=repo_root, shell=True, capture_output=True, text=True, timeout=600)
            return {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": proc.stdout[-8000:],
                "stderr": proc.stderr[-8000:],
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def repo_rollback(self, payload: dict[str, Any]) -> dict[str, Any]:
        repo_id = self._safe_id(payload.get("repo_id") or "repo", "repo")
        ref = payload.get("ref") or ""
        branch = payload.get("branch")
        backup = bool(payload.get("backup", True))
        commit_dirty = bool(payload.get("commit_dirty", False))

        repo_root = os.path.join(self.data_dir, "repos", repo_id)
        if not os.path.isdir(repo_root):
            return {"ok": False, "error": "repo_not_found"}

        try:
            if not os.path.isdir(os.path.join(repo_root, ".git")):
                self._git_init_if_needed(repo_root, (self.settings.get("versioning", {}) or {}).get("branch", "autobuilder"))
            dirty = self._git_is_dirty(repo_root)
            if dirty and commit_dirty:
                self._git_commit(repo_root, "rollback: auto-save dirty tree")
            if backup and dirty:
                self._git_backup_tag(repo_root)
            res = self._git_checkout_ref(repo_root, ref, branch=branch)
            versions = []
            try:
                versions = self._git_log(repo_root, 50)
            except Exception:
                pass
            res["versions"] = versions
            return res
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def repo_analysis_symbols(self, repo_id: str, q: str = "", lang: str = "") -> dict[str, Any]:
        try:
            from tools.symbols import list_symbols
            return list_symbols(repo_id, self.data_dir, query=q, lang=lang)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def repo_versions(self, repo_id: str, limit: int = 50) -> dict[str, Any]:
        repo_id = self._safe_id(repo_id, "repo")
        repo_root = os.path.join(self.data_dir, "repos", repo_id)
        if not os.path.isdir(repo_root):
            return {"ok": False, "error": "repo_not_found"}
        try:
            out = subprocess.check_output(
                ["git", "--no-pager", "log", f"-{limit}", "--pretty=format:%H%x09%ad%x09%s", "--date=iso"],
                cwd=repo_root,
            ).decode("utf-8", "ignore")
            items = []
            for ln in out.splitlines():
                parts = ln.split("\t")
                if len(parts) >= 3:
                    items.append({"hash": parts[0], "date": parts[1], "message": "\t".join(parts[2:])})
            return {"ok": True, "items": items}
        except Exception:
            return {"ok": True, "items": []}

    def repo_analyze_path(self, payload: dict[str, Any]) -> dict[str, Any]:
        repo_id = self._safe_id(payload.get("repo_id") or "repo", "repo")
        path = payload.get("path") or ""
        try:
            root = os.path.join(self.data_dir, "repos", repo_id)
            include_root = os.path.abspath(os.path.join(root, path)) if path else root
            if not include_root.startswith(root):
                return {"ok": False, "error": "invalid_path"}
            try:
                self._job_analyze_repo(repo_id, root, self.data_dir, include_root=include_root)
            except TypeError:
                self._job_analyze_repo(repo_id, root, self.data_dir)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

