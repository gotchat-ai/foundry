import concurrent.futures
import json
import os
import shutil
import subprocess
import zipfile
from typing import Any, Callable

from fastapi import UploadFile


class RepoAnalysisRoutes:
    """Repository analysis, notes, snippets, and patch route implementations."""

    def __init__(
        self,
        *,
        data_dir_getter: Callable[[], str],
        settings_getter: Callable[[], dict[str, Any]],
        safe_id: Callable[[str, str], str],
        safe_join: Callable[[str, str], str],
        safe_extract_zip: Callable[[zipfile.ZipFile, str], None],
        executor: concurrent.futures.Executor | None = None,
        progress: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._data_dir_getter = data_dir_getter
        self._settings_getter = settings_getter
        self._safe_id = safe_id
        self._safe_join = safe_join
        self._safe_extract_zip = safe_extract_zip
        self.executor = executor or concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self.progress = progress if progress is not None else {}

    @property
    def data_dir(self) -> str:
        data_dir = self._data_dir_getter()
        return data_dir or os.path.abspath("./data")

    @property
    def settings(self) -> dict[str, Any]:
        try:
            return self._settings_getter() or {}
        except Exception:
            return {}

    def _set_prog(self, repo_id: str, stage: str, pct: float) -> None:
        self.progress[repo_id] = {"stage": stage, "pct": float(max(0.0, min(100.0, pct)))}

    def _load_settings(self) -> dict[str, Any]:
        settings = self.settings
        if settings:
            return settings
        try:
            p = os.path.abspath("settings.json")
            return json.load(open(p, "r", encoding="utf-8"))
        except Exception:
            return {}

    def _git_log(self, repo_root: str, max_n: int = 50) -> list[str]:
        try:
            out = subprocess.check_output(
                ["git", "-C", repo_root, "log", f"-{max_n}", "--pretty=%h %s"],
                stderr=subprocess.STDOUT,
            )
            return out.decode("utf-8", "ignore").splitlines()
        except Exception:
            return []

    def _job_analyze_repo(self, repo_id: str, repo_root: str, data_dir: str | None = None) -> dict[str, Any]:
        from tools.repo_analyzer import analyze_repo, analyze_repo_incremental
        from tools.static_checks import run_checks, run_generic_checks
        from tools.lint_integration import run_ruff, run_mypy, run_bandit
        from tools.notes_llm import enrich_notes

        data_dir = data_dir or self.data_dir
        out_dir = os.path.join(data_dir, "analysis", repo_id)
        os.makedirs(out_dir, exist_ok=True)

        self._set_prog(repo_id, "scan+index", 5.0)
        settings = self._load_settings()
        do_inc = bool(((settings or {}).get("analysis", {})).get("incremental", True))
        res = analyze_repo_incremental(repo_id, repo_root, out_dir) if do_inc else analyze_repo(repo_id, repo_root, out_dir)
        self._set_prog(repo_id, "static-checks", 35.0)
        issues = os.path.join(out_dir, "issues.jsonl")
        run_checks(repo_id, repo_root, issues)
        try:
            run_generic_checks(repo_root, issues)
        except Exception:
            pass
        analysis_settings = (settings or {}).get("analysis", {})
        try:
            if analysis_settings.get("enable_ruff", True):
                run_ruff(repo_root, issues)
        except Exception:
            pass
        try:
            if analysis_settings.get("enable_mypy", True):
                run_mypy(repo_root, issues)
        except Exception:
            pass
        try:
            if analysis_settings.get("enable_bandit", True):
                run_bandit(repo_root, issues)
        except Exception:
            pass
        self._set_prog(repo_id, "llm-notes", 60.0)
        try:
            enrich_notes(settings, os.path.join(out_dir, "notes.jsonl"), os.path.join(out_dir, "notes_enriched.jsonl"))
        except Exception:
            pass
        self._set_prog(repo_id, "rollups", 80.0)

        self._set_prog(repo_id, "done", 100.0)
        return {"ok": True, "paths": res, "out_dir": out_dir}

    def repo_analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Start a multi-stage analysis for a repo.
        payload: { "repo_id": "...", "repo_root": "/abs/path/..." }
        If repo_root is omitted, tries DATA_DIR/repos/<repo_id>
        """
        repo_id = self._safe_id(payload.get("repo_id") or "repo", "repo")
        repo_root = payload.get("repo_root")
        data_dir = self.data_dir
        if not repo_root:
            guess = os.path.join(data_dir, "repos", repo_id)
            if os.path.isdir(guess):
                repo_root = guess
        if not repo_root or not os.path.isdir(repo_root):
            return {"ok": False, "error": "repo_root_not_found", "hint": repo_root}

        self._set_prog(repo_id, "queued", 0.0)
        fut = self.executor.submit(self._job_analyze_repo, repo_id, repo_root, data_dir)
        return {"ok": True, "job_id": id(fut), "repo_id": repo_id}

    def repo_analysis_progress(self, repo_id: str) -> dict[str, Any]:
        repo_id = self._safe_id(repo_id, "repo")
        return self.progress.get(repo_id, {"stage": "unknown", "pct": 0.0})

    def repo_analysis_fetch(self, repo_id: str, kind: str = "summary", offset: int = 0, limit: int = 100) -> dict[str, Any]:
        repo_id = self._safe_id(repo_id, "repo")
        base = os.path.join(self.data_dir, "analysis", repo_id)
        if not os.path.isdir(base):
            return {"ok": False, "error": "not_found"}
        if kind == "summary":
            p = os.path.join(base, "repo_summary.md")
            return {"ok": True, "kind": "summary", "text": open(p, "r", encoding="utf-8", errors="ignore").read()}
        if kind == "map":
            p = os.path.join(base, "map.json")
            return {"ok": True, "kind": "map", "map": json.load(open(p, "r", encoding="utf-8"))}
        if kind == "issues":
            p = os.path.join(base, "issues.jsonl")
            rows = self._read_jsonl_window(p, offset, limit)
            return {"ok": True, "kind": "issues", "items": rows, "offset": offset, "limit": limit}
        if kind == "notes":
            p = os.path.join(base, "notes.jsonl")
            rows = self._read_jsonl_window(p, offset, limit)
            return {"ok": True, "kind": "notes", "items": rows, "offset": offset, "limit": limit}
        return {"ok": False, "error": "bad_kind"}

    def _read_jsonl_window(self, path: str, offset: int, limit: int) -> list[Any]:
        rows = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i < offset:
                        continue
                    if len(rows) >= limit:
                        break
                    rows.append(json.loads(line))
        return rows

    def _hotload_repo_notes_for_session(self, session_id: str, repo_id: str) -> None:
        """
        Best-effort: load vector slices from analysis/<repo_id>/vectors into hot store if available,
        and/or bias retrieval with notes_enriched.jsonl.
        """
        settings = self._load_settings()
        analysis_settings = (settings or {}).get("analysis", {})
        if not analysis_settings.get("hot_load_repo_notes", True):
            return
        base = os.path.join(self.data_dir, "analysis", repo_id)
        vec_dir = os.path.join(base, "vectors")
        try:
            from repo_rag_hot import ensure_hot_vectors_for_session
            ensure_hot_vectors_for_session(session_id, vec_dir, budget_ratio=0.33)
        except Exception:
            pass
        try:
            path = os.path.join(base, "notes_enriched.jsonl")
            if not os.path.exists(path):
                path = os.path.join(base, "notes.jsonl")
            from repo_rag_hot import register_notes_for_session
            texts = []
            with open(path, "r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i > 5000:
                        break
                    try:
                        j = json.loads(line)
                        if "analysis" in j and isinstance(j["analysis"], dict):
                            s = j["analysis"].get("summary") or ""
                            if s:
                                texts.append(s)
                        elif "docstring" in j:
                            if j["docstring"]:
                                texts.append(j["docstring"])
                    except Exception:
                        pass
            if texts:
                register_notes_for_session(session_id, texts)
        except Exception:
            pass

    async def repo_analyze_zip_upload(self, repo_id: str, file: UploadFile) -> dict[str, Any]:
        repo_id = self._safe_id(repo_id, "repo")
        data_dir = self.data_dir
        os.makedirs(os.path.join(data_dir, "uploads"), exist_ok=True)
        os.makedirs(os.path.join(data_dir, "repos"), exist_ok=True)
        temp_path = os.path.join(data_dir, "uploads", f"{repo_id}.zip")
        with open(temp_path, "wb") as out:
            chunk = await file.read()
            out.write(chunk)
        repo_root = os.path.join(data_dir, "repos", repo_id)
        if os.path.isdir(repo_root):
            shutil.rmtree(repo_root)
        os.makedirs(repo_root, exist_ok=True)
        with zipfile.ZipFile(temp_path, "r") as z:
            self._safe_extract_zip(z, repo_root)
        self._set_prog(repo_id, "queued", 0.0)
        fut = self.executor.submit(self._job_analyze_repo, repo_id, repo_root, data_dir)
        return {"ok": True, "job_id": id(fut), "repo_id": repo_id, "repo_root": repo_root}

    def repo_analyze_zip(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Given {repo_id, zip_path}, unpack and analyze on server.
        """
        data_dir = self.data_dir
        repo_id = self._safe_id(payload.get("repo_id") or "repo", "repo")
        zip_path = payload.get("zip_path")
        if not zip_path or not os.path.isfile(zip_path):
            return {"ok": False, "error": "zip_not_found"}
        repo_root = os.path.join(data_dir, "repos", repo_id)
        if os.path.isdir(repo_root):
            shutil.rmtree(repo_root)
        os.makedirs(repo_root, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as z:
            self._safe_extract_zip(z, repo_root)
        self._set_prog(repo_id, "queued", 0.0)
        fut = self.executor.submit(self._job_analyze_repo, repo_id, repo_root, data_dir)
        return {"ok": True, "job_id": id(fut), "repo_id": repo_id, "repo_root": repo_root}

    def repo_analysis_snippet(self, repo_id: str, file: str, line: int = 1, radius: int = 10) -> dict[str, Any]:
        """
        Return a slice of the file around `line` with +/- `radius` lines.
        """
        repo_id = self._safe_id(repo_id, "repo")
        repo_root = os.path.join(self.data_dir, "repos", repo_id)
        try:
            path = self._safe_join(repo_root, file)
        except Exception as e:
            return {"ok": False, "error": f"invalid_path: {e}", "path": file}
        if not os.path.isfile(path):
            return {"ok": False, "error": "file_not_found", "path": path}
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.read().splitlines()
            n = len(lines)
            line = max(1, min(int(line), n))
            start = max(1, line - int(radius))
            end = min(n, line + int(radius))
            segment = "\n".join(lines[start - 1:end])
            return {"ok": True, "file": file, "start": start, "end": end, "line": line, "text": segment}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def repo_analysis_suggest(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self.settings
        repo_id = self._safe_id(payload.get("repo_id") or "repo", "repo")
        limit = int(payload.get("limit", (settings.get("analysis", {}) or {}).get("suggestion_max", 12)))
        llm_route = (settings.get("analysis", {}) or {}).get("llm_route", "/v1/chat/completions")
        llm_model = (settings.get("analysis", {}) or {}).get("llm_model", "gpt-local")
        try:
            from tools.suggest_llm import suggest
            res = suggest(repo_id, self.data_dir, llm_route=llm_route, model=llm_model, limit=limit)
            return res | {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def repo_analysis_add_notes(self, payload: dict[str, Any]) -> dict[str, Any]:
        repo_id = self._safe_id(payload.get("repo_id") or "repo", "repo")
        items = payload.get("items") or []
        base = os.path.join(self.data_dir, "analysis", repo_id)
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, "notes_enriched.jsonl")
        count = 0
        with open(path, "a", encoding="utf-8") as f:
            for it in items:
                try:
                    it["authored_by"] = "assistant"
                    f.write(json.dumps(it, ensure_ascii=False) + "\n")
                    count += 1
                except Exception:
                    continue
        return {"ok": True, "added": count}

