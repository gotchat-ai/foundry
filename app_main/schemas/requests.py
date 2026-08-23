from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel


class ModelLoadRequest(BaseModel):
    model_id: str
    device: str | None = "auto"
    dtype: str | None = "auto"
    quant: str | None = "none"
    trust_remote_code: bool | None = False
    gpu_vram_percent: int | None = None
    gguf_n_gpu_layers: int | None = None


class ModelDownloadRequest(BaseModel):
    model_id: str
    revision: str | None = None
    allow_patterns: list[str] | None = None
    ignore_patterns: list[str] | None = None


class GGUFInfoRequest(BaseModel):
    model_id: str


class GGUFInfoResponse(BaseModel):
    n_layers: int
    file_size_bytes: int
    warning: str | None = None


class ModelUnloadRequest(BaseModel):
    """
    Request to unload models from memory/VRAM.

    target:
        "main"     -> unload only the main model
        "thinking" -> unload only the thinking model
        "all"      -> unload both (default)
    """
    target: str = "all"


class PatchPlan(BaseModel):
    operations: list


class PatchApplyRequest(BaseModel):
    sid: str
    repo_id: str
    parent_version: Optional[str] = None
    new_version: str
    plan: PatchPlan


class ChatCodeEditRequest(BaseModel):
    sid: str
    repo_id: str
    parent_version: str
    new_version: str
    plan: dict | None = None
    request: str | None = None
    include_glob: str | None = "**/*.py"


class LibIngestURL(BaseModel):
    lib_id: str
    url: str
    tags: List[str] | None = None


class LibIngestText(BaseModel):
    lib_id: str
    text: str
    source: str | None = None
    tags: List[str] | None = None


class LibIngestZip(BaseModel):
    lib_id: str
    zip_path: str
    include_glob: List[str] | None = None


class LibIngestPath(BaseModel):
    lib_id: str
    root_path: str
    include_glob: List[str] | None = None


class RepoIngestAsyncRequest(BaseModel):
    sid: Optional[str] = None
    repo_id: str
    kind: Literal["zip", "path"]
    zip_path: Optional[str] = None
    root_path: Optional[str] = None
    include_glob: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    chunk_lines: Optional[int] = 200
    version: Optional[str] = None
    delta: bool = False
    changed_paths: Optional[List[str]] = None
    deleted_paths: Optional[List[str]] = None
    base_version: Optional[str] = None
    keep_versions: Optional[int] = 3


class LibIngestPDF(BaseModel):
    lib_id: str
    pdf_path: str
    tags: List[str] | None = None


class RagIngestAsyncRequest(BaseModel):
    lib_id: str = "default"
    kind: Literal["url", "pdf", "text", "zip", "path"]
    url: str | None = None
    pdf_path: str | None = None
    text: str | None = None
    source: str | None = None
    zip_path: str | None = None
    files: Optional[List[str]] = None
    root_path: str | None = None
    include_glob: list[str] | None = None
    tags: list[str] | None = None


class LibScheduleAdd(BaseModel):
    lib_id: str
    url: str
    interval_sec: int = 86400
    tags: List[str] | None = None


class LibScheduleRemove(BaseModel):
    lib_id: str
    url: str


class AssocCompactConfig(BaseModel):
    interval_sec: Optional[int] = None
    decay: float | None = None
    min_count: float | None = None
    enabled: bool | None = None


class AssocCompactRun(BaseModel):
    scope: str | None = None
    sid: str | None = None
    user_id: str | None = None
    lib_id: str | None = None
    decay: float | None = None
    min_count: float | None = None


class RepoIngestDirRequest(BaseModel):
    sid: str
    repo_id: str
    dir_path: str
    include_lang: Optional[List[str]] = None
    exclude_globs: Optional[List[str]] = None
    chunk_lines: Optional[int] = None
    max_file_bytes: Optional[int] = None
    version: Optional[str] = None
    repo_type: Optional[str] = None
    auto_detect: bool = True


class RepoIngestZipRequest(BaseModel):
    sid: str
    repo_id: str
    zip_path: Optional[str] = None
    zip_b64: Optional[str] = None
    zip_name: Optional[str] = None
    max_file_bytes: int = 200_000
    include_lang: Optional[list] = None
    exclude_globs: Optional[list] = None
    chunk_lines: int = 200
    version: Optional[str] = None


class RepoIngestPathRequest(BaseModel):
    sid: str
    repo_id: str
    root_dir: str
    max_file_bytes: int = 200_000
    include_lang: Optional[list] = None
    exclude_globs: Optional[list] = None
    chunk_lines: int = 200
    version: Optional[str] = None


class LibIngestPDFAsync(BaseModel):
    lib_id: str
    pdf_path: str
    tags: List[str] | None = None
