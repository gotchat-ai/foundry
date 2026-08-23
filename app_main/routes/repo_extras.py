import os
import pathlib
from typing import Any, Callable, Optional

from fastapi import HTTPException


class RepoExtrasRoutes:
    """Miscellaneous model listing and Repo-RAG helper route implementations."""

    TYPE_DEFAULTS = {
        "code": {
            "include_lang": ["py", "js", "ts", "tsx", "jsx", "go", "rs", "java", "kt", "c", "cpp", "h", "hpp", "cs", "rb", "php", "sh", "html", "css", "json", "toml", "yaml", "ini", "md", "rst"],
            "exclude_globs": ["**/.git/**", "**/__pycache__/**", "**/.venv/**", "**/node_modules/**", "**/.idea/**", "**/.vscode/**", "**/dist/**", "**/build/**"],
            "chunk_lines": 200,
        },
        "docs": {"include_lang": ["md", "rst", "txt", "pdf"], "exclude_globs": ["**/.git/**", "**/.idea/**", "**/.vscode/**", "**/node_modules/**"], "chunk_lines": 120},
        "web": {"include_lang": ["html", "css", "js", "ts", "tsx", "jsx", "json", "md"], "exclude_globs": ["**/.git/**", "**/node_modules/**", "**/dist/**", "**/out/**", "**/build/**"], "chunk_lines": 140},
        "notes": {"include_lang": ["md", "txt", "rst"], "exclude_globs": [], "chunk_lines": 100},
        "data": {"include_lang": ["csv", "tsv", "json", "ndjson", "toml", "yaml", "ini", "md", "txt"], "exclude_globs": ["**/.git/**", "**/node_modules/**", "**/*.parquet", "**/*.feather", "**/*.xlsx", "**/*.xls"], "chunk_lines": 160},
    }

    def __init__(
        self,
        *,
        settings_getter: Callable[[], dict[str, Any]],
        safe_id: Callable[[str, str], str],
        repo_rag_getter: Callable[[], Any],
        repo_ingest_module: Any,
        model_getter: Callable[[], Any],
        sessions_getter: Callable[[], dict[str, Any]],
        sess_meta_getter: Callable[[], dict[str, Any]],
        headroom_frac_getter: Callable[[], float],
    ) -> None:
        self._settings_getter = settings_getter
        self._safe_id = safe_id
        self._repo_rag_getter = repo_rag_getter
        self._repo_ingest = repo_ingest_module
        self._model_getter = model_getter
        self._sessions_getter = sessions_getter
        self._sess_meta_getter = sess_meta_getter
        self._headroom_frac_getter = headroom_frac_getter

    @property
    def settings(self) -> dict[str, Any]:
        try:
            return self._settings_getter() or {}
        except Exception:
            return {}

    def list_models(self, depth: int = 3, include_gguf: bool = False) -> dict[str, Any]:
        def _dir_size(p):
            tot = 0
            for r, _, fs in os.walk(p):
                for f in fs:
                    try:
                        tot += os.path.getsize(os.path.join(r, f))
                    except Exception:
                        pass
            return tot

        def _is_hf_root(p):
            return os.path.isfile(os.path.join(p, "config.json"))

        def _scan_flat(root, depth):
            out = []
            root = os.path.abspath(root)
            if not os.path.isdir(root):
                return out
            for cur, dirs, _files in os.walk(root):
                rel = os.path.relpath(cur, root)
                if rel != "." and len(pathlib.Path(rel).parts) > depth:
                    dirs[:] = []
                    continue
                if _is_hf_root(cur):
                    out.append({"kind": "hf-local", "label": os.path.basename(cur), "path": cur, "size": _dir_size(cur)})
            return out

        def _scan_cache(hub_root):
            out = []
            hub_root = os.path.abspath(hub_root)
            if not os.path.isdir(hub_root):
                return out
            try:
                entries = os.listdir(hub_root)
            except Exception:
                entries = []
            for d in entries:
                if not d.startswith("models--"):
                    continue
                model_root = os.path.join(hub_root, d)
                parts = d[len("models--"):].split("--", 1)
                label = "/".join(parts) if len(parts) == 2 else d.replace("models--", "").replace("--", "/")
                refs = os.path.join(model_root, "refs")
                snaps = os.path.join(model_root, "snapshots")
                if not os.path.isdir(snaps):
                    continue
                sha = None
                main = os.path.join(refs, "main")
                try:
                    if os.path.isfile(main):
                        with open(main, "r", encoding="utf-8") as f:
                            sha = f.read().strip()
                    if not sha:
                        cand = [s for s in os.listdir(snaps) if os.path.isdir(os.path.join(snaps, s))]
                        if cand:
                            cand.sort(key=lambda s: os.path.getmtime(os.path.join(snaps, s)), reverse=True)
                            sha = cand[0]
                except Exception:
                    sha = None
                if not sha:
                    continue
                path = os.path.join(snaps, sha)
                if _is_hf_root(path):
                    out.append({"kind": "hf-cache", "label": label, "path": path, "size": _dir_size(path)})
            return out

        settings = self.settings
        roots = list(
            filter(
                None,
                [
                    settings.get("hf_cache_dir") or os.getenv("HUGGINGFACE_HUB_CACHE"),
                    (os.path.join(os.getenv("HF_HOME"), "hub") if os.getenv("HF_HOME") else None),
                    settings.get("models_dir"),
                    "./models",
                ],
            )
        )
        seen = set()
        models = []
        first = None
        for r in roots:
            r = os.path.abspath(r)
            if r in seen:
                continue
            seen.add(r)
            first = first or r
            try:
                names = os.listdir(r)
            except Exception:
                names = []
            if any(n.startswith("models--") for n in names):
                models += _scan_cache(r)
            else:
                models += _scan_flat(r, depth)
        return {"models_dir": first, "models": models}

    def _profile_for_repo(self, root_path: str, repo_type: Optional[str], include_lang, exclude_globs, chunk_lines):
        if include_lang or exclude_globs or chunk_lines:
            return include_lang, exclude_globs, chunk_lines
        key = (repo_type or "").lower().strip() or None
        if key in self.TYPE_DEFAULTS:
            d = self.TYPE_DEFAULTS[key]
            return d["include_lang"], d["exclude_globs"], d["chunk_lines"]
        try:
            ext_count = {}
            for root, dirs, files in os.walk(root_path):
                dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", ".venv", "node_modules", ".idea", ".vscode", "dist", "build", "out"}]
                for f in files:
                    ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
                    if ext:
                        ext_count[ext] = ext_count.get(ext, 0) + 1
            if not ext_count:
                d = self.TYPE_DEFAULTS["notes"]
                return d["include_lang"], d["exclude_globs"], d["chunk_lines"]
            if sum(ext_count.get(x, 0) for x in ["py", "js", "ts", "tsx", "jsx", "go", "rs", "java", "kt", "c", "cpp", "h", "hpp", "cs", "rb", "php"]) >= 5:
                d = self.TYPE_DEFAULTS["code"]
                return d["include_lang"], d["exclude_globs"], d["chunk_lines"]
            if sum(ext_count.get(x, 0) for x in ["html", "css", "js", "ts", "tsx", "jsx"]) >= 5:
                d = self.TYPE_DEFAULTS["web"]
                return d["include_lang"], d["exclude_globs"], d["chunk_lines"]
            if sum(ext_count.get(x, 0) for x in ["md", "rst", "txt", "pdf"]) >= 5:
                d = self.TYPE_DEFAULTS["docs"]
                return d["include_lang"], d["exclude_globs"], d["chunk_lines"]
            if sum(ext_count.get(x, 0) for x in ["csv", "tsv", "json", "ndjson"]) >= 5:
                d = self.TYPE_DEFAULTS["data"]
                return d["include_lang"], d["exclude_globs"], d["chunk_lines"]
            d = self.TYPE_DEFAULTS["notes"]
            return d["include_lang"], d["exclude_globs"], d["chunk_lines"]
        except Exception:
            d = self.TYPE_DEFAULTS["notes"]
            return d["include_lang"], d["exclude_globs"], d["chunk_lines"]

    def repo_ingest_dir(self, req: Any) -> dict[str, Any]:
        req.sid = self._safe_id(req.sid, "session")
        req.repo_id = self._safe_id(req.repo_id, "repo")
        repo_rag = self._repo_rag_getter()
        if repo_rag is None:
            raise HTTPException(500, "RepoRAG not initialized")
        if not req.dir_path or not os.path.isdir(req.dir_path):
            raise HTTPException(400, f"dir_path not found or not a directory: {req.dir_path}")
        prof_inc, prof_exc, prof_chunk = self._profile_for_repo(
            req.dir_path,
            (req.repo_type if req.auto_detect else (req.repo_type or None)),
            req.include_lang,
            req.exclude_globs,
            req.chunk_lines,
        )
        stats = self._repo_ingest.ingest_dir_to_user_rag_cold(
            repo_rag,
            req.sid,
            req.repo_id,
            req.dir_path,
            self._model_getter().tokenizer,
            max_file_bytes=req.max_file_bytes,
            include_lang=prof_inc,
            exclude_globs=prof_exc,
            chunk_lines=prof_chunk,
            version=req.version,
        )
        return {"ok": True, "saved_path": req.dir_path, "stats": stats}

    def sessions_set_hot_repos(self, sid: str, payload: dict[str, Any]) -> dict[str, Any]:
        sessions = self._sessions_getter()
        if sid not in sessions:
            raise HTTPException(404, "session not found")
        repo_ids = payload.get("repo_ids") or []
        hf = float(payload.get("headroom_frac", self._headroom_frac_getter()))
        sess_meta = self._sess_meta_getter()
        m = sess_meta.setdefault(sid, {})
        m["sticky_repo_ids"] = [r for r in repo_ids if r]
        try:
            import repo_rag_hot
            repo_rag = self._repo_rag_getter()
            if repo_rag is None:
                raise RuntimeError("RepoRAG not initialized")
            res = repo_rag_hot.ensure_hot_for_repos_with_budget(repo_rag, sid, m["sticky_repo_ids"], headroom_frac=hf, unload_others=True)
            return {"ok": True, "repo_ids": m["sticky_repo_ids"], "budget": res}
        except Exception as e:
            raise HTTPException(500, f"repo_rag_hot failed: {e}")

