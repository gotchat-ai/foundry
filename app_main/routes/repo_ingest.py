import base64
import itertools
import os
import re
import tempfile
import zipfile
from typing import Any, Callable, Iterable, Optional
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import FileResponse


class RepoIngestRoutes:
    """RepoRAG ingestion and query route implementations."""

    DEFAULT_PROF_EXC: list[str] = [
        ".git/**","**/.git/**","**/.hg/**","**/.svn/**",
        "**/__pycache__/**","**/.mypy_cache/**","**/.ruff_cache/**","**/.pytest_cache/**",
        "**/.idea/**","**/.vscode/**",
        "**/node_modules/**","**/dist/**","**/build/**","**/out/**","**/.next/**",
        "**/.venv/**","**/venv/**",".venv/**","venv/**",
        "**/*.min.js","**/*.min.css",
    ]

    DOC_GLOBS: list[str] = ["*.md","*.rst","*.txt","*.json","*.toml","*.ini","*.cfg","*.yaml","*.yml","*.pdf","*.docx","*.pptx"]

    LANGUAGE_GLOB_MAP = {
        "python": ["*.py","*.ipynb"],
        "javascript": ["*.js","*.mjs","*.cjs","*.jsx"],
        "js": ["*.js","*.mjs","*.cjs","*.jsx"],
        "typescript": ["*.ts","*.tsx"],
        "ts": ["*.ts","*.tsx"],
        "html": ["*.html","*.htm"],
        "css": ["*.css","*.scss","*.sass"],
        "c": ["*.c","*.h"],
        "cpp": ["*.cc","*.cpp","*.cxx","*.hpp","*.hh","*.hxx"],
        "c++": ["*.cc","*.cpp","*.cxx","*.hpp","*.hh","*.hxx"],
        "csharp": ["*.cs"],
        "c#": ["*.cs"],
        "go": ["*.go"],
        "rust": ["*.rs"],
        "java": ["*.java"],
        "kotlin": ["*.kt","*.kts"],
        "swift": ["*.swift"],
        "bash": ["*.sh"],
        "shell": ["*.sh"],
        "sql": ["*.sql"],
        "json": ["*.json"],
        "yaml": ["*.yaml","*.yml"],
        "toml": ["*.toml"],
        "markdown": ["*.md","*.rst"],
    }

    def __init__(
        self,
        *,
        user_rag_getter: Callable[[], Any],
        user_rag_enabled_getter: Callable[[], bool],
        settings_getter: Callable[[], dict[str, Any]],
        model_getter: Callable[[], Any],
        repo_ingest_module: Any,
        note_repo_for_sid: Callable[[str, str], None],
        profile_for_repo: Callable[..., Any] | None = None,
    ) -> None:
        self._user_rag_getter = user_rag_getter
        self._user_rag_enabled_getter = user_rag_enabled_getter
        self._settings_getter = settings_getter
        self._model_getter = model_getter
        self._repo_ingest = repo_ingest_module
        self._note_repo_for_sid = note_repo_for_sid
        self._profile_for_repo = profile_for_repo

    def _require_user_rag(self) -> Any:
        user_rag = self._user_rag_getter()
        if not self._user_rag_enabled_getter() or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        return user_rag

    def as_list(self, value: Optional[Iterable]) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.replace("\n", ",").split(",") if part.strip()]
        try:
            return [str(part).strip() for part in value if str(part).strip()]
        except TypeError:
            return [str(value).strip()]

    def expand_langs_to_globs(self, include_lang: list[str]) -> list[str]:
        inc: list[str] = []
        for lang in include_lang or []:
            key = str(lang).lower().strip()
            inc.extend(self.LANGUAGE_GLOB_MAP.get(key, []))
        seen = set()
        out = []
        for glob in inc:
            if glob not in seen:
                out.append(glob)
                seen.add(glob)
        return out

    def resolve_prof_globs_from_req(
        self,
        req: Any,
        settings: dict[str, Any],
        *,
        include_docs_default: bool = True,
    ) -> tuple[list[str], list[str]]:
        profile = getattr(req, "profile", None) or getattr(req, "repo_type", None) or "code"
        profile = str(profile).lower()
        ingest_profiles = (settings.get("ingest", {}) or {}).get("profiles", {})
        prof_settings = ingest_profiles.get(profile, {}) if isinstance(ingest_profiles, dict) else {}

        prof_helper = {}
        if callable(self._profile_for_repo):
            try:
                helper_value = self._profile_for_repo(profile)
                if isinstance(helper_value, dict):
                    prof_helper = helper_value
            except Exception:
                prof_helper = {}

        req_inc = self.expand_langs_to_globs(self.as_list(getattr(req, "include_lang", [])))
        if not req_inc:
            req_inc = self.as_list(prof_settings.get("include")) or self.as_list(prof_helper.get("include"))
        if not req_inc:
            req_inc = list(dict.fromkeys(itertools.chain.from_iterable(self.LANGUAGE_GLOB_MAP.values())))

        include_docs = include_docs_default
        try:
            include_docs = bool((settings.get("ingest", {}) or {}).get("include_docs", include_docs_default))
        except Exception:
            pass
        if include_docs:
            for glob in self.DOC_GLOBS:
                if glob not in req_inc:
                    req_inc.append(glob)

        prof_exc = list(self.DEFAULT_PROF_EXC)
        prof_exc += self.as_list(prof_settings.get("exclude"))
        prof_exc += self.as_list(prof_helper.get("exclude"))
        prof_exc += self.as_list(getattr(req, "exclude_globs", []))
        seen = set()
        prof_exc = [glob for glob in prof_exc if (glob not in seen and not seen.add(glob))]
        return req_inc, prof_exc

    def repo_ingest_zip(self, req: Any, *, safe_id: Callable[[str, str], str]) -> dict[str, Any]:
        settings = self._settings_getter()
        req.sid = safe_id(req.sid, "session")
        req.repo_id = safe_id(req.repo_id, "repo")
        user_rag = self._require_user_rag()
        if not req.sid or not req.repo_id:
            raise HTTPException(400, "sid and repo_id required")
        if req.zip_b64 and not req.zip_path:
            data = base64.b64decode(req.zip_b64)
            try:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{(req.zip_name or 'upload')}.zip")
                tmp.write(data)
                tmp.flush()
                tmp.close()
                path = tmp.name
            except Exception:
                uploads_root = (settings or {}).get("uploads_dir") or os.path.join(os.getcwd(), "uploads")
                os.makedirs(uploads_root, exist_ok=True)
                fname = re.sub(r"[^A-Za-z0-9._-]+", "_", (req.zip_name or "upload"))
                if not fname.endswith(".zip"):
                    fname += ".zip"
                path = os.path.join(uploads_root, f"{uuid4().hex}_" + fname)
                with open(path, "wb") as handle:
                    handle.write(data)
        else:
            path = req.zip_path
        if not path or not os.path.exists(path):
            raise HTTPException(400, "zip_path not found and no zip_b64 provided")
        if callable(self._profile_for_repo):
            prof_inc, prof_exc, _prof_chunk = self._profile_for_repo(
                path,
                (req.repo_type if getattr(req, "auto_detect", False) else (getattr(req, "repo_type", None) or None)),
                req.include_lang,
                req.exclude_globs,
                req.chunk_lines,
            )
        else:
            prof_inc, prof_exc = self.resolve_prof_globs_from_req(req, settings)
        stats = self._repo_ingest.ingest_zip_to_user_rag_cold(
            user_rag,
            req.sid,
            req.repo_id,
            path,
            self._model_getter().tokenizer,
            max_file_bytes=int(req.max_file_bytes),
            include_lang=prof_inc,
            exclude_globs=prof_exc,
            chunk_lines=int(req.chunk_lines),
            version=req.version,
        )
        self._note_repo_for_sid(req.sid, req.repo_id)
        return {"ok": True, "repo_id": req.repo_id, "sid": req.sid, "stats": stats}

    def repo_ingest_path(self, req: Any, *, safe_id: Callable[[str, str], str]) -> dict[str, Any]:
        req.sid = safe_id(req.sid, "session")
        req.repo_id = safe_id(req.repo_id, "repo")
        prof_inc, prof_exc = self.resolve_prof_globs_from_req(req, self._settings_getter())
        user_rag = self._require_user_rag()
        stats = self._repo_ingest.ingest_dir_to_user_rag_cold(
            user_rag,
            req.sid,
            req.repo_id,
            req.root_dir,
            self._model_getter().tokenizer,
            max_file_bytes=int(req.max_file_bytes),
            include_lang=prof_inc,
            exclude_globs=prof_exc,
            chunk_lines=int(req.chunk_lines),
            version=req.version,
        )
        return {"repo_id": req.repo_id, "sid": req.sid, "stats": stats}

    def repo_ingest_async_job(self, job_id: str, req: Any, *, jobs: dict[str, Any]) -> None:
        jobs[job_id] = {"status": "running", "kind": req.kind, "result": None, "error": None}
        print(333333)

        try:
            from repo_ingest import ingest_zip_to_user_rag_cold, ingest_dir_to_user_rag_cold, analyze_repo_dir
            sid = req.sid or "default"
            repo_id = req.repo_id or "repo"
            # project_id = req.project_id or repo_id
            kind = req.kind
            include_glob = req.include_glob or [
                "**/*.py","**/*.md","**/*.txt","**/*.json","**/*.toml",
                "**/*.rst","**/*.yaml","**/*.yml","**/*.js","**/*.ts","**/*.tsx"
            ]
            include_lang =  [
                "python"
            ]
            try:
                tok = getattr(self._model_getter(), "tokenizer", None)
            except Exception as e:
                tok = None

            print(2342223)
            tags = req.tags or []
            user_rag = self._user_rag_getter()
            if kind == "zip":
                zp = req.zip_path
                if not zp:
                    raise ValueError("zip_path required")
                ingest_zip_to_user_rag_cold(user_rag, sid, repo_id, zp,
                                                include_glob=include_glob, tags=tags,
                                                chunk_lines=int(req.chunk_lines), version=req.version, tokenizer=tok)
                self._note_repo_for_sid(sid, repo_id)
                # ingest_zip_to_user_rag_cold(user_rag, sid, repo_id, zp,
                #                                 include_glob=include_glob, tags=tags,
                #                                 chunk_lines=int(req.chunk_lines), version=req.version, tokenizer=tok, project_id=project_id)



            # elif kind == "path":
            #     rp = req.root_path
            #     if not rp:
            #         raise ValueError("root_path required")
            #     ingest_dir_to_user_rag_cold(user_rag, sid, repo_id, rp,
            #                                     include_glob=include_glob, tags=tags,
            #                                     chunk_lines=int(req.chunk_lines), version=req.version, tokenizer=tok)
            #     self._note_repo_for_sid(sid, repo_id)

            elif kind == "path":
                rp = req.root_path
                if not rp:
                    raise ValueError("root_path required")

                if getattr(req, "delta", False) and (req.changed_paths or req.deleted_paths):
                    from repo_ingest import ingest_dir_delta_to_user_rag_cold
                    res = ingest_dir_delta_to_user_rag_cold(
                        user_rag,
                        sid,
                        repo_id,
                        rp,
                        tok,
                        changed_paths=req.changed_paths or [],
                        deleted_paths=req.deleted_paths or [],
                        include_lang=include_lang,
                        exclude_globs=None,
                        chunk_lines=int(req.chunk_lines or 200),
                        max_file_bytes=200_000,
                        version=req.version,
                        base_version=req.base_version,
                        keep_versions=int(req.keep_versions or 3),
                    )
                else:
                    res = ingest_dir_to_user_rag_cold(
                        user_rag,
                        sid,
                        repo_id,
                        rp,
                        tokenizer=tok,
                        include_glob=include_glob,
                        tags=tags,
                        chunk_lines=int(req.chunk_lines),
                        version=req.version,
                    )

                self._note_repo_for_sid(sid, repo_id)


            else:
                raise ValueError("invalid kind; expected 'zip' or 'path'")

            jobs[job_id]["status"] = "done"
        except Exception as e:
            print(e)
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(e)

    def repo_stats(self, sid: str, repo_id: str) -> dict[str, Any]:
        user_rag = self._require_user_rag()
        hot = user_rag.count_by_repo(sid, repo_id, cold=False)
        cold = user_rag.count_by_repo(sid, repo_id, cold=True)
        return {"repo_id": repo_id, "hot": hot, "cold": cold}

    def repo_search(
        self,
        sid: str,
        repo_id: str,
        q: str,
        k: int = 8,
        scope: str = "cold",
        min_score: float = 0.0,
        lang: Optional[str] = None,
        path_contains: Optional[str] = None,
    ) -> dict[str, Any]:
        user_rag = self._require_user_rag()
        k = int(k)
        scope = str(scope).lower()
        out = []
        if scope in ("hot", "both"):
            res_hot = user_rag._get_store(sid).search(q, top_k=k)
            res_hot = [item for item in res_hot if (item.get("metadata") or {}).get("repo_id") == repo_id]
            out.extend(res_hot[:k])
        if scope in ("cold", "both"):
            out.extend(
                user_rag.cold_search(
                    sid,
                    q,
                    k=k,
                    min_score=min_score,
                    repo_id=repo_id,
                    lang=lang,
                    path_contains=path_contains,
                )
            )
        out = sorted(out, key=lambda item: item.get("score", 0.0), reverse=True)[:k]
        return {"data": out}

    def repo_map(self, sid: str, repo_id: str, path_contains: Optional[str] = None) -> dict[str, Any]:
        user_rag = self._require_user_rag()
        hot = user_rag._get_store(sid)
        items = []
        for doc_id in getattr(hot, "ids", []):
            doc = hot.docs[doc_id]
            meta = doc.get("meta") or doc.get("metadata") or {}
            if meta.get("type") == "repo_map" and meta.get("repo_id") == repo_id:
                if path_contains and path_contains not in (meta.get("path") or ""):
                    continue
                items.append({"id": doc_id, "path": meta.get("path"), "lang": meta.get("lang"), "text": doc.get("text")})
        return {"repo_id": repo_id, "maps": items}

    def repo_zip(
        self,
        sid: str,
        repo_id: str,
        version: str,
        path_prefix: Optional[str] = None,
        glob_pattern: Optional[str] = None,
    ) -> Any:
        user_rag = self._require_user_rag()
        version_dir = user_rag.repo_version_dir(sid, repo_id, version)
        if not version_dir or not os.path.isdir(version_dir):
            raise HTTPException(404, "version snapshot not found")
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{repo_id}_{version}.zip")
        tmp_path = tmp.name
        tmp.close()
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for rel, path in user_rag.iter_version_files(
                sid,
                repo_id,
                version,
                path_prefix=path_prefix,
                glob_pattern=glob_pattern,
            ):
                zip_file.write(path, arcname=rel)
        return FileResponse(tmp_path, filename=f"{repo_id}_{version}.zip", media_type="application/zip")
