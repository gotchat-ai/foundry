import os
import uuid
from typing import Any, Callable

from fastapi import HTTPException, UploadFile


class UploadRoutes:
    """Implementation for file/media upload endpoints."""

    def __init__(
        self,
        *,
        upload_dir_getter: Callable[[], str],
        workdir_getter: Callable[[], str | None],
    ) -> None:
        self._upload_dir_getter = upload_dir_getter
        self._workdir_getter = workdir_getter

    def resolve_upload_target_dir(self, target_repo_root: str = "") -> tuple[str, str, str]:
        rel = str(target_repo_root or "").strip().replace("\\", "/")
        if not rel:
            return self._upload_dir_getter(), "uploads", ""
        repo_base = "data/agent_workflow/repo"
        if rel != repo_base and not rel.startswith(repo_base + "/"):
            raise HTTPException(status_code=400, detail=f"target_repo_root must be under '{repo_base}'")
        root_dir = self._workdir_getter() or os.path.abspath(".")
        dest_dir = os.path.abspath(os.path.join(str(root_dir), rel.replace("/", os.sep)))
        os.makedirs(dest_dir, exist_ok=True)
        return dest_dir, "repo", rel

    async def save_upload(self, file: UploadFile, target_repo_root: str = "") -> dict[str, Any]:
        ext = os.path.splitext(file.filename or "")[1]
        safe_ext = ext if len(ext) <= 10 else ""
        name = f"{uuid.uuid4().hex}{safe_ext}"
        dest_dir, saved_to, normalized_repo_root = self.resolve_upload_target_dir(target_repo_root)
        path = os.path.join(dest_dir, name)
        with open(path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        size = os.path.getsize(path)
        return {
            "ok": True,
            "name": file.filename,
            "stored_name": name,
            "mime": file.content_type or "",
            "size": size,
            "path": path,
            "local_path": path,
            "download_url": f"/uploads/{name}" if saved_to == "uploads" else "",
            "saved_to": saved_to,
            "target_repo_root": normalized_repo_root,
        }
