import json
import os
import zipfile
from typing import Any, Callable

from fastapi.responses import FileResponse


class ProjectBuilderRoutes:
    """Project autobuilder route and worker implementations."""

    def __init__(
        self,
        *,
        app_getter: Callable[[], Any],
        data_dir_getter: Callable[[], str],
        settings_getter: Callable[[], dict[str, Any]],
        safe_id: Callable[[str, str], str],
        analysis_executor_getter: Callable[[], Any],
        job_analyze_repo: Callable[..., dict[str, Any]],
        run_tool: Callable[[str, str], dict[str, Any]],
        run_smoke: Callable[[str, str], dict[str, Any]],
        git_init_if_needed: Callable[[str, str], Any],
        git_commit: Callable[[str, str], Any],
        git_tag: Callable[[str, str], Any],
        progress: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._app_getter = app_getter
        self._data_dir_getter = data_dir_getter
        self._settings_getter = settings_getter
        self._safe_id = safe_id
        self._analysis_executor_getter = analysis_executor_getter
        self._job_analyze_repo = job_analyze_repo
        self._run_tool = run_tool
        self._run_smoke = run_smoke
        self._git_init_if_needed = git_init_if_needed
        self._git_commit = git_commit
        self._git_tag = git_tag
        self.progress = progress if progress is not None else {}
        self.active_job_builder: Callable[[str, str, dict[str, Any]], Any] = self._job_build_project

    @property
    def app(self) -> Any:
        return self._app_getter()

    @property
    def data_dir(self) -> str:
        return self._data_dir_getter() or os.path.abspath("./data")

    @property
    def settings(self) -> dict[str, Any]:
        try:
            return self._settings_getter() or {}
        except Exception:
            return {}

    def _set_project_prog(self, project_id: str, stage: str, pct: float, detail: str = "") -> None:
        self.progress[project_id] = {"stage": stage, "pct": float(pct), "detail": detail}

    def _project_paths(self, project_id: str) -> tuple[str, str, str]:
        repo_id = project_id
        repo_root = os.path.join(self.data_dir, "repos", repo_id)
        proj_dir = os.path.join(self.data_dir, "projects", repo_id)
        return repo_id, repo_root, proj_dir

    def _job_build_project(self, project_id: str, requirements: str, options: dict[str, Any]) -> None:
        settings = self.settings
        llm_route = (settings.get("analysis", {}) or {}).get("llm_route", "/v1/chat/completions")
        llm_model = (settings.get("analysis", {}) or {}).get("llm_model", "gpt-local")
        allowed_exts = (settings.get("builder", {}) or {}).get("allowed_exts", [".py", ".md", ".json"])
        max_iters = int(options.get("max_iterations") or (settings.get("builder", {}) or {}).get("max_iterations", 4))
        auto_apply = bool(options.get("auto_apply") if options.get("auto_apply") is not None else (settings.get("builder", {}) or {}).get("auto_apply", True))
        max_files_per_iter = int((settings.get("builder", {}) or {}).get("max_files_per_iter", 40))
        max_file_kb = int((settings.get("builder", {}) or {}).get("max_file_kb", 256))

        repo_id, repo_root, proj_dir = self._project_paths(project_id)
        os.makedirs(repo_root, exist_ok=True)
        os.makedirs(proj_dir, exist_ok=True)
        open(os.path.join(proj_dir, "requirements.txt"), "w", encoding="utf-8").write(requirements)

        from tools.project_builder import llm_plan
        from tools.suggest_llm import suggest
        from tools.acceptance_llm import evaluate
        from tools.llm_patch import propose_patch

        for it in range(1, max_iters + 1):
            self._set_project_prog(project_id, f"planning (iter {it})", min(5 + it, 15), "")
            plan = llm_plan(requirements, allowed_exts, llm_route, llm_model, max_tokens=3500)
            files = plan.get("files", [])[:max_files_per_iter]
            wrote = 0
            for f in files:
                rel = f.get("path", "")
                if not rel:
                    continue
                abs_path = os.path.join(repo_root, rel)
                if not abs_path.startswith(repo_root):
                    continue
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                content = f.get("content", "")
                if len(content.encode("utf-8")) > max_file_kb * 1024:
                    content = content[:max_file_kb * 1024]
                with open(abs_path, "w", encoding="utf-8", errors="ignore") as out:
                    out.write(content)
                wrote += 1
            open(os.path.join(proj_dir, f"iter_{it}_plan.json"), "w", encoding="utf-8").write(json.dumps(files, ensure_ascii=False, indent=2))

            self._set_project_prog(project_id, f"analyzing (iter {it})", 30 + it * 5, "")
            self._job_analyze_repo(repo_id, repo_root, self.data_dir)

            self._set_project_prog(project_id, f"suggesting (iter {it})", 55 + it * 5, "")
            sg = suggest(repo_id, self.data_dir, llm_route=llm_route, model=llm_model, limit=(settings.get("analysis", {}) or {}).get("suggestion_max", 12))
            sugg_path = sg.get("path")
            suggestions = {}
            if sugg_path and os.path.exists(sugg_path):
                suggestions = json.load(open(sugg_path, "r", encoding="utf-8"))
            actions = []
            for s in suggestions.get("suggestions", []):
                actions += s.get("actions", [])
            actions = actions[:12]

            self._set_project_prog(project_id, f"patching (iter {it})", 70 + it * 5, f"{len(actions)} actions")
            applied = 0
            for a in actions:
                if not auto_apply:
                    break
                target = a.get("target_file") or ""
                if not target:
                    continue
                abs_path = target if os.path.isabs(target) else os.path.join(repo_root, target)
                if not os.path.isfile(abs_path):
                    continue
                instruction = a.get("instruction") or ""
                try:
                    pr = propose_patch(repo_id, abs_path, instruction, llm_route, llm_model)
                    diff = pr.get("diff", "")
                    if diff.strip():
                        from fastapi.testclient import TestClient
                        try:
                            client = TestClient(self.app)
                            r1 = client.post("/v1/repo/patch/propose", json={"repo_id": repo_id, "file": target, "instruction": instruction})
                            pid = r1.json().get("patch_id")
                            if pid:
                                r2 = client.post("/v1/repo/patch/apply", json={"repo_id": repo_id, "patch_id": pid})
                                if r2.json().get("ok"):
                                    applied += 1
                        except Exception:
                            pass
                except Exception:
                    continue

            self._set_project_prog(project_id, f"re-analyzing (iter {it})", 80 + it * 2, f"applied {applied}")
            self._job_analyze_repo(repo_id, repo_root, self.data_dir)
            lin = (settings.get("acceptance", {}) or {}).get("linters", {})
            lres = {}
            try:
                if lin.get("ruff_cmd"):
                    lres["ruff"] = self._run_tool(repo_root, lin.get("ruff_cmd"))
                if lin.get("black_cmd"):
                    lres["black"] = self._run_tool(repo_root, lin.get("black_cmd"))
                if lin.get("eslint_cmd"):
                    lres["eslint"] = self._run_tool(repo_root, lin.get("eslint_cmd"))
            except Exception as _e:
                lres["error"] = str(_e)
            open(os.path.join(proj_dir, f"iter_{it}_lint.json"), "w", encoding="utf-8").write(json.dumps(lres, ensure_ascii=False, indent=2))
            if lin.get("enforce", True):
                lint_ok = True
                for _k, v in lres.items():
                    if isinstance(v, dict) and not v.get("ok", True):
                        lint_ok = False
                if not lint_ok:
                    from tools.guidelines import add_rule
                    add_rule(self.data_dir, project_id, "Linter gate failed; produce compliant, formatted code.")
                    continue

            self._set_project_prog(project_id, f"acceptance (iter {it})", 90 + it, "")
            acc = evaluate(repo_id, self.data_dir, requirements, llm_route, llm_model)
            open(os.path.join(proj_dir, f"iter_{it}_acceptance.json"), "w", encoding="utf-8").write(json.dumps(acc, ensure_ascii=False, indent=2))
            if bool(acc.get("pass")):
                break

        try:
            zpath = os.path.join(proj_dir, "final.zip")
            with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _dirs, files in os.walk(repo_root):
                    for fn in files:
                        ap = os.path.join(root, fn)
                        rp = os.path.relpath(ap, repo_root)
                        zf.write(ap, rp)
            self._set_project_prog(project_id, "done", 100.0, zpath)
        except Exception as e:
            self._set_project_prog(project_id, "done_error", 100.0, str(e))

    def project_build(self, payload: dict[str, Any]) -> dict[str, Any]:
        project_id = self._safe_id(payload.get("project_id") or "proj", "proj")
        requirements = payload.get("requirements") or ""
        if not requirements:
            return {"ok": False, "error": "missing_requirements"}
        options = payload.get("options") or {}
        self._set_project_prog(project_id, "queued", 0.0, "")
        fut = self._analysis_executor_getter().submit(self.active_job_builder, project_id, requirements, options)
        return {"ok": True, "job_id": id(fut), "project_id": project_id}

    def project_progress(self, project_id: str) -> dict[str, Any]:
        project_id = self._safe_id(project_id, "proj")
        return self.progress.get(project_id, {"stage": "unknown", "pct": 0.0})

    def project_archive(self, project_id: str) -> Any:
        project_id = self._safe_id(project_id, "proj")
        proj_dir = os.path.join(self.data_dir, "projects", project_id)
        zpath = os.path.join(proj_dir, "final.zip")
        if not os.path.isfile(zpath):
            return {"ok": False, "error": "not_ready"}
        return FileResponse(zpath, media_type="application/zip", filename=f"{project_id}.zip")

    def _job_build_project_enhanced(self, project_id: str, requirements: str, options: dict[str, Any]) -> None:
        settings = self.settings
        llm_route = (settings.get("analysis", {}) or {}).get("llm_route", "/v1/chat/completions")
        llm_model = (settings.get("analysis", {}) or {}).get("llm_model", "gpt-local")
        allowed_exts = (settings.get("builder", {}) or {}).get("allowed_exts", [".py", ".md", ".json"])
        max_iters = int(options.get("max_iterations") or (settings.get("builder", {}) or {}).get("max_iterations", 4))
        auto_apply = bool(options.get("auto_apply") if options.get("auto_apply") is not None else (settings.get("builder", {}) or {}).get("auto_apply", True))
        max_files_per_iter = int((settings.get("builder", {}) or {}).get("max_files_per_iter", 40))
        max_file_kb = int((settings.get("builder", {}) or {}).get("max_file_kb", 256))
        retries = int((settings.get("builder", {}) or {}).get("patch_retry", 2))

        repo_id, repo_root, proj_dir = self._project_paths(project_id)
        os.makedirs(repo_root, exist_ok=True)
        os.makedirs(proj_dir, exist_ok=True)
        try:
            self._git_init_if_needed(repo_root, (settings.get("versioning", {}) or {}).get("branch", "autobuilder"))
        except Exception:
            pass

        from tools.project_builder import llm_plan
        from tools.suggest_llm import suggest
        from tools.acceptance_llm import evaluate
        from tools.llm_patch import propose_patch
        from tools.guidelines import add_rule

        for it in range(1, max_iters + 1):
            self._set_project_prog(project_id, f"planning (iter {it})", min(5 + it, 15), "")
            plan = llm_plan(requirements, allowed_exts, llm_route, llm_model, max_tokens=3500)
            files = plan.get("files", [])[:max_files_per_iter]
            wrote = 0
            for f in files:
                rel = f.get("path", "")
                if not rel:
                    continue
                abs_path = os.path.join(repo_root, rel)
                if not abs_path.startswith(repo_root):
                    continue
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                content = f.get("content", "")
                if len(content.encode("utf-8")) > max_file_kb * 1024:
                    content = content[:max_file_kb * 1024]
                open(abs_path, "w", encoding="utf-8").write(content)
                wrote += 1
            open(os.path.join(proj_dir, f"iter_{it}_plan.json"), "w", encoding="utf-8").write(json.dumps(files, ensure_ascii=False, indent=2))
            try:
                self._git_commit(repo_root, f"plan iter {it}: write {wrote} files")
                self._git_tag(repo_root, f"{(settings.get('versioning', {}) or {}).get('tag_prefix', 'iter-')}{it}-plan")
            except Exception:
                pass

            self._set_project_prog(project_id, f"analyzing (iter {it})", 30 + it * 5, "")
            self._job_analyze_repo(repo_id, repo_root, self.data_dir)

            self._set_project_prog(project_id, f"suggesting (iter {it})", 55 + it * 5, "")
            sg = suggest(repo_id, self.data_dir, llm_route=llm_route, model=llm_model, limit=(settings.get("analysis", {}) or {}).get("suggestion_max", 12))
            suggestions = {}
            pth = (sg or {}).get("path")
            if pth and os.path.exists(pth):
                suggestions = json.load(open(pth, "r", encoding="utf-8"))
            actions = []
            for s in suggestions.get("suggestions", []):
                actions += s.get("actions", [])
            actions = actions[:12]

            self._set_project_prog(project_id, f"patching (iter {it})", 70 + it * 5, f"{len(actions)} actions")
            applied = 0
            from fastapi.testclient import TestClient
            for a in actions:
                if not auto_apply:
                    break
                target = a.get("target_file") or ""
                if not target:
                    continue
                abs_path = target if os.path.isabs(target) else os.path.join(repo_root, target)
                if not os.path.isfile(abs_path):
                    continue
                instruction = a.get("instruction") or ""
                attempt = 0
                while attempt <= retries:
                    attempt += 1
                    pr = propose_patch(repo_id, abs_path, instruction, llm_route, llm_model, data_dir=self.data_dir, project_id=project_id)
                    diff = pr.get("diff", "")
                    if not diff.strip():
                        add_rule(self.data_dir, project_id, "Return non-empty unified diffs with correct file headers.")
                        continue
                    try:
                        client = TestClient(self.app)
                        r1 = client.post("/v1/repo/patch/propose", json={"repo_id": repo_id, "file": target, "instruction": instruction})
                        pid = (r1.json() or {}).get("patch_id")
                        if not pid:
                            add_rule(self.data_dir, project_id, "Patch propose failed to return patch_id.")
                            continue
                        r2 = client.post("/v1/repo/patch/apply", json={"repo_id": repo_id, "patch_id": pid})
                        jr2 = r2.json() or {}
                        ok_apply = jr2.get("ok")
                        if not ok_apply:
                            add_rule(self.data_dir, project_id, f"Patch apply failed for {target}: {jr2}")
                            continue
                        try:
                            self._git_commit(repo_root, f"apply patch: {target}")
                        except Exception:
                            pass
                        applied += 1
                        break
                    except Exception as e:
                        add_rule(self.data_dir, project_id, f"Exception while applying patch: {e}")
                        continue

            try:
                self._git_tag(repo_root, f"{(settings.get('versioning', {}) or {}).get('tag_prefix', 'iter-')}{it}-patched")
            except Exception:
                pass

            self._set_project_prog(project_id, f"re-analyzing (iter {it})", 80 + it * 2, f"applied {applied}")
            self._job_analyze_repo(repo_id, repo_root, self.data_dir)

            smoke = self._run_smoke(repo_root, (settings.get("acceptance", {}) or {}).get("smoke_cmd", ""))
            open(os.path.join(proj_dir, f"iter_{it}_smoke.json"), "w", encoding="utf-8").write(json.dumps(smoke, ensure_ascii=False, indent=2))

            self._set_project_prog(project_id, f"acceptance (iter {it})", 90 + it, "")
            acc = evaluate(repo_id, self.data_dir, requirements, llm_route, llm_model)
            open(os.path.join(proj_dir, f"iter_{it}_acceptance.json"), "w", encoding="utf-8").write(json.dumps(acc, ensure_ascii=False, indent=2))
            if bool(acc.get("pass")):
                try:
                    self._git_commit(repo_root, f"accept iter {it}")
                    self._git_tag(repo_root, f"{(settings.get('versioning', {}) or {}).get('tag_prefix', 'iter-')}{it}-accept")
                except Exception:
                    pass
                break

        zpath = os.path.join(proj_dir, "final.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(repo_root):
                for fn in files:
                    ap = os.path.join(root, fn)
                    rp = os.path.relpath(ap, repo_root)
                    zf.write(ap, rp)

