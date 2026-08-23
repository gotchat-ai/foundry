from __future__ import annotations

from app_main.schemas import requests as request_schemas


class ModelLoadRequest(request_schemas.ModelLoadRequest):
    pass


class ModelDownloadRequest(request_schemas.ModelDownloadRequest):
    pass


class GGUFInfoRequest(request_schemas.GGUFInfoRequest):
    pass


class GGUFInfoResponse(request_schemas.GGUFInfoResponse):
    pass


class ModelUnloadRequest(request_schemas.ModelUnloadRequest):
    pass


class PatchPlan(request_schemas.PatchPlan):
    pass


class PatchApplyRequest(request_schemas.PatchApplyRequest):
    pass


class ChatCodeEditRequest(request_schemas.ChatCodeEditRequest):
    pass


class LibIngestURL(request_schemas.LibIngestURL):
    pass


class LibIngestText(request_schemas.LibIngestText):
    pass


class LibIngestZip(request_schemas.LibIngestZip):
    pass


class LibIngestPath(request_schemas.LibIngestPath):
    pass


class RepoIngestAsyncRequest(request_schemas.RepoIngestAsyncRequest):
    pass


class LibIngestPDF(request_schemas.LibIngestPDF):
    pass


class RagIngestAsyncRequest(request_schemas.RagIngestAsyncRequest):
    pass


class LibScheduleAdd(request_schemas.LibScheduleAdd):
    pass


class LibScheduleRemove(request_schemas.LibScheduleRemove):
    pass


class AssocCompactConfig(request_schemas.AssocCompactConfig):
    pass


class AssocCompactRun(request_schemas.AssocCompactRun):
    pass


class RepoIngestDirRequest(request_schemas.RepoIngestDirRequest):
    pass


class RepoIngestZipRequest(request_schemas.RepoIngestZipRequest):
    pass


class RepoIngestPathRequest(request_schemas.RepoIngestPathRequest):
    pass


class LibIngestPDFAsync(request_schemas.LibIngestPDFAsync):
    pass
