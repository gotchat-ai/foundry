import json
import os
import shutil
import zipfile
from typing import Any, Callable


class QARoutes:
    """QA, roadmap, and revision route implementations."""

    def __init__(
        self,
        *,
        data_dir_getter: Callable[[], str],
        settings_getter: Callable[[], dict[str, Any]],
        safe_id: Callable[[str, str], str],
        analysis_executor_getter: Callable[[], Any],
        job_build_project: Callable[[str, str, dict[str, Any]], Any],
        safe_extract_zip: Callable[[zipfile.ZipFile, str], None],
    ) -> None:
        self._data_dir_getter = data_dir_getter
        self._settings_getter = settings_getter
        self._safe_id = safe_id
        self._analysis_executor_getter = analysis_executor_getter
        self._job_build_project = job_build_project
        self._safe_extract_zip = safe_extract_zip

    @property
    def data_dir(self) -> str:
        return self._data_dir_getter() or os.path.abspath("./data")

    @property
    def settings(self) -> dict[str, Any]:
        try:
            return self._settings_getter() or {}
        except Exception:
            return {}

    def qa_submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tools.qa_store import append
        repo_id = self._safe_id(payload.get("repo_id") or "repo", "repo")
        return append(self.data_dir, repo_id, payload)

    def qa_list(self, repo_id: str, status: str = "", q: str = "", qtype: str = "") -> dict[str, Any]:
        from tools.qa_store import list
        return list(self.data_dir, repo_id, status=status, q=q, qtype=qtype)

    def qa_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tools.qa_store import update_status
        return update_status(self.data_dir, payload.get("repo_id"), payload.get("qa_id"), payload.get("status"))

    def qa_triage_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tools.qa_triage import run_triage
        repo_id = self._safe_id(payload.get("repo_id") or "repo", "repo")
        llm_route = (self.settings.get("analysis", {}) or {}).get("llm_route", "/v1/chat/completions")
        llm_model = (self.settings.get("analysis", {}) or {}).get("llm_model", "gpt-local")
        return run_triage(repo_id, self.data_dir, llm_route, llm_model)

    def qa_roadmap_build(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tools.qa_roadmap import build_roadmap
        repo_id = self._safe_id(payload.get("repo_id") or "repo", "repo")
        base = payload.get("rev_base") or "HEAD"
        return build_roadmap(repo_id, self.data_dir, base)

    def qa_roadmap_get(self, repo_id: str) -> dict[str, Any]:
        path = os.path.join(self.data_dir, "projects", repo_id, "roadmap.json")
        if not os.path.isfile(path):
            return {"ok": False, "error": "roadmap_missing"}
        return json.load(open(path, "r", encoding="utf-8"))

    def qa_build_revisions(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tools.qa_roadmap import revision_requirements, build_roadmap
        repo_id = self._safe_id(payload.get("repo_id") or "repo", "repo")
        options = payload.get("options") or {}
        rr = revision_requirements(repo_id, self.data_dir)
        if not rr.get("ok"):
            build_roadmap(repo_id, self.data_dir, payload.get("rev_base") or "HEAD")
            rr = revision_requirements(repo_id, self.data_dir)
            if not rr.get("ok"):
                return rr
        reqs = rr.get("requirements") or {}
        jobs = []
        executor = self._analysis_executor_getter()
        for name, req in reqs.items():
            fut = executor.submit(self._job_build_project, f"{repo_id}_{name}", req, options)
            jobs.append({"rev": name, "job_id": id(fut)})
        return {"ok": True, "jobs": jobs, "revisions": list(reqs.keys())}

    def qa_adopt_revision(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Adopt a built revision by copying its final.zip into repos/<repo_id> and marking linked QA as done.
        payload: {repo_id, rev} where rev is 'Rev-A' or 'Rev-B'
        """
        repo_id = self._safe_id(payload.get("repo_id") or "repo", "repo")
        rev = payload.get("rev") or "Rev-A"
        base_proj = f"{repo_id}_{rev}"
        proj_zip = os.path.join(self.data_dir, "projects", base_proj, "final.zip")
        if not os.path.isfile(proj_zip):
            return {"ok": False, "error": "final_zip_missing", "path": proj_zip}
        repo_root = os.path.join(self.data_dir, "repos", repo_id)
        os.makedirs(repo_root, exist_ok=True)
        with zipfile.ZipFile(proj_zip, "r") as zf:
            self._safe_extract_zip(zf, repo_root)
        pdir = os.path.join(self.data_dir, "projects", repo_id)
        rm = os.path.join(pdir, "roadmap.json")
        if os.path.isfile(rm):
            r = json.load(open(rm, "r", encoding="utf-8"))
            mapping = r.get("task_to_qa", {})
            scopes = {rev_item.get("name"): set(rev_item.get("scope", [])) for rev_item in r.get("revisions", [])}
            scope = scopes.get(rev, set())
            done_qas = [mapping.get(t) for t in scope if mapping.get(t)]
            try:
                from tools import qa_store as _qs
                for qid in done_qas:
                    _qs.update_status(self.data_dir, repo_id, qid, "done")
            except Exception:
                pass
        rev_dir = os.path.join(self.data_dir, "projects", repo_id, "revs", rev)
        os.makedirs(rev_dir, exist_ok=True)
        shutil.copy2(proj_zip, os.path.join(rev_dir, "final.zip"))
        return {"ok": True, "adopted": rev, "repo_id": repo_id}

