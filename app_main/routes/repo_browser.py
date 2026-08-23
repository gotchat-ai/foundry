import datetime
from typing import Any, Callable

from fastapi import HTTPException


class RepoBrowserRoutes:
    """Repo browsing endpoints backed by User-RAG repo metadata."""

    def __init__(
        self,
        *,
        user_rag_getter: Callable[[], Any],
        user_rag_enabled_getter: Callable[[], bool],
        sess_meta_getter: Callable[[], dict[str, Any]],
    ) -> None:
        self._user_rag_getter = user_rag_getter
        self._user_rag_enabled_getter = user_rag_enabled_getter
        self._sess_meta_getter = sess_meta_getter

    def repo_files(self, sid: str, repo_id: str, *, fmt: Callable[[Any], str | None] | None = None) -> dict[str, Any]:
        user_rag = self._user_rag_getter()
        if user_rag is None:
            raise HTTPException(500, "user_rag not configured")

        try:
            meta = user_rag._load_repo_meta(sid, repo_id)
            print("meta", meta)
        except Exception as exc:
            raise HTTPException(404, f"repo meta not found for sid={sid} repo_id={repo_id}: {exc!r}") from exc

        def default_fmt(ts: Any) -> str | None:
            if not ts:
                return None
            try:
                return datetime.datetime.utcfromtimestamp(float(ts)).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                return None

        fmt_fn = fmt or default_fmt
        files_map: dict[str, dict[str, Any]] = {}
        for version in meta.get("versions", []):
            print(23523523)
            for file_path, file_info in (version.get("files") or {}).items():
                created_ts = file_info.get("ctime") or file_info.get("created_ts") or meta.get("ts")
                modified_ts = file_info.get("mtime") or file_info.get("modified_ts") or meta.get("ts")
                files_map[file_path] = {
                    "path": file_path,
                    "created": fmt_fn(created_ts),
                    "modified": fmt_fn(modified_ts),
                }

        files = sorted(files_map.values(), key=lambda item: item["path"])
        return {"files": files}

    def repo_list(self, sid: str) -> dict[str, Any]:
        user_rag = self._user_rag_getter()
        if self._user_rag_enabled_getter() and user_rag is not None:
            return {"repo_ids": user_rag.list_repo_ids(sid)}

        meta = self._sess_meta_getter().get(sid) or {}
        repo_ids = meta.get("repo_ids") or []
        seen = set()
        out: list[str] = []
        for repo_id in repo_ids:
            if not isinstance(repo_id, str):
                continue
            normalized = repo_id.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            out.append(normalized)

        out.sort()
        print("repo/list out: ", out)
        return {"repo_ids": out}
