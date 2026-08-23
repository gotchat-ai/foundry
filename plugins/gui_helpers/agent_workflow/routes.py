from __future__ import annotations

import json
import secrets
import threading
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pathlib import Path

from plugins.gui_helpers._framework.services import get_plugin_service
from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled
from .executor import WorkflowExecutor
from .registry import WorkflowToolRegistry
from .repo_file_preview import read_repo_file_preview
from .reviewers import build_default_profile_registry, load_profiles_from_dir, ProfileRegistry
from .schemas import (
    ApprovalRequest,
    FeedbackCaptureRequest,
    WorkflowResult,
    WorkflowRunRequest,
    WorkflowStatus,
    WorkflowTraceEntry,
)
from .tools import register_default_tools


GUI_PLUGIN_ID = "agent_workflow"


_PRESET_DIR = Path(__file__).resolve().parent / "presets" / "agent_flow_imports"


def _framework_data_dir(app: Any) -> str:
    cand = getattr(app.state, "data_dir", None) or getattr(app.state, "workdir", None) or None
    if isinstance(cand, str) and cand.strip():
        path = os.path.abspath(str(cand))
        if os.path.basename(path).lower() == "data":
            return path
        return os.path.join(path, "data")
    return os.path.abspath("./data")


def _require_user(app: Any, request: Request) -> Any:
    collab = get_plugin_service(app, "collab_chat")
    fn = collab.get("require_user") if isinstance(collab, dict) else None
    if not callable(fn):
        raise HTTPException(status_code=503, detail="collab_chat service unavailable")
    return fn(request)


def _require_session_access(app: Any, user: Any, pid: str, sid: str) -> Any:
    collab = get_plugin_service(app, "collab_chat")
    fn = collab.get("require_session_access") if isinstance(collab, dict) else None
    if not callable(fn):
        raise HTTPException(status_code=503, detail="collab_chat service unavailable")
    return fn(user, pid, sid)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _repo_context_service(app: Any) -> Any:
    return get_plugin_service(app, "repo_context")


def _canonical_agent_flow_project_flows(app: Any, pid: str = "project2") -> Dict[str, Any]:
    try:
        from plugins.gui_helpers.agent_flow.skills.workflow import _workflow_store  # type: ignore
        flows = _workflow_store.load_project_flows({"app": app, "pid": pid}, pid)
        return dict(flows or {}) if isinstance(flows, dict) else {}
    except Exception:
        return {}


def _load_import_preset_file(name: str) -> Dict[str, Any]:
    p = _PRESET_DIR / f"{str(name or '').strip()}.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return dict(data or {}) if isinstance(data, dict) else {}
    except Exception:
        return {}


def _select_import_flows_payload(app: Any, flow_names: List[str], *, default_flow: str, preset_name: str = "") -> Dict[str, Any]:
    wanted = [str(x or "").strip() for x in (flow_names or []) if str(x or "").strip()]
    canonical = _canonical_agent_flow_project_flows(app, "project2")
    if wanted and all(isinstance(canonical.get(name), dict) for name in wanted):
        flows = {name: canonical[name] for name in wanted}
        active = default_flow if default_flow in flows else wanted[0]
        return {
            "flows": flows,
            "default_flow": active,
            "active_flow": active,
            "mode": "execute",
        }
    preset = _load_import_preset_file(preset_name) if preset_name else {}
    return dict(preset or {})


def _scan_stat_index_for_app(app: Any, root: str, *, ignore_dirs: Any, ignore_exts: Any) -> Dict[str, Any]:
    svc = _repo_context_service(app)
    fn = svc.get("scan_stat_index") if isinstance(svc, dict) else None
    if not callable(fn):
        raise HTTPException(status_code=503, detail="repo_context service unavailable")
    return fn(root, ignore_dirs=ignore_dirs, ignore_exts=ignore_exts)


def _stat_delta_for_app(app: Any, prev_index: Dict[str, Any], cur_index: Dict[str, Any]) -> Any:
    svc = _repo_context_service(app)
    fn = svc.get("stat_delta") if isinstance(svc, dict) else None
    if not callable(fn):
        raise HTTPException(status_code=503, detail="repo_context service unavailable")
    return fn(prev_index, cur_index)


def _sse(event: str, data: Dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


def _aw_repo_delta_key(sid: str, repo_id: str, abs_dir: str) -> str:
    return f"{str(sid or '').strip()}::{str(repo_id or '').strip()}::{os.path.abspath(abs_dir or '').lower()}"


def _aw_detect_moves(prev_index: Dict[str, Any], cur_index: Dict[str, Any], changed: List[str], deleted: List[str]) -> List[Dict[str, str]]:
    by_fp_prev: Dict[Any, List[str]] = {}
    by_fp_cur: Dict[Any, List[str]] = {}
    for rel in deleted or []:
        fp = prev_index.get(rel)
        if fp is None:
            continue
        by_fp_prev.setdefault(fp, []).append(rel)
    for rel in changed or []:
        fp = cur_index.get(rel)
        if fp is None:
            continue
        by_fp_cur.setdefault(fp, []).append(rel)
    out: List[Dict[str, str]] = []
    for fp, olds in by_fp_prev.items():
        news = by_fp_cur.get(fp) or []
        if not news:
            continue
        limit = min(len(olds), len(news))
        for idx in range(limit):
            old_path = str(olds[idx] or "").strip()
            new_path = str(news[idx] or "").strip()
            if old_path and new_path and old_path != new_path:
                out.append({"from": old_path, "to": new_path})
    out.sort(key=lambda row: (row.get("from", ""), row.get("to", "")))
    return out


def install(app) -> None:
    if not hasattr(app.state, "agent_workflow_runs"):
        app.state.agent_workflow_runs = {}
    if not hasattr(app.state, "agent_workflow_traces"):
        app.state.agent_workflow_traces = {}
    if not hasattr(app.state, "agent_workflow_runs_lock"):
        app.state.agent_workflow_runs_lock = threading.Lock()
    if not hasattr(app.state, "agent_workflow_approvals"):
        app.state.agent_workflow_approvals = {}
    if not hasattr(app.state, "agent_workflow_requests"):
        app.state.agent_workflow_requests = {}
    if not hasattr(app.state, "agent_workflow_repo_delta_state"):
        app.state.agent_workflow_repo_delta_state = {}
    if not hasattr(app.state, "agent_workflow_tools"):
        reg = WorkflowToolRegistry()
        register_default_tools(app, reg)
        app.state.agent_workflow_tools = reg
    if not hasattr(app.state, "agent_workflow_profiles"):
        preg = build_default_profile_registry()
        prof_dir = os.path.join(_framework_data_dir(app), "projects", "agent_workflow", "profiles")
        load_info = load_profiles_from_dir(preg, prof_dir)
        app.state.agent_workflow_profiles = preg
        app.state.agent_workflow_profile_json = {"dir": prof_dir, **load_info}

    r = APIRouter()
    profile_registry: ProfileRegistry = app.state.agent_workflow_profiles

    def _tool_registry() -> WorkflowToolRegistry:
        reg = getattr(app.state, "agent_workflow_tools", None)
        required_tools = {"repo.read_range", "repo.search"}
        existing = set()
        if reg is not None and hasattr(reg, "list_tools"):
            try:
                rows = reg.list_tools()
                if isinstance(rows, dict):
                    existing = {str(k or "").strip() for k in rows.keys() if str(k or "").strip()}
            except Exception:
                existing = set()
        if reg is None or not required_tools.issubset(existing):
            reg = WorkflowToolRegistry()
            register_default_tools(app, reg)
            app.state.agent_workflow_tools = reg
        return reg

    def _set_status(status: WorkflowStatus) -> None:
        with app.state.agent_workflow_runs_lock:
            app.state.agent_workflow_runs[status.workflow_id] = status.model_dump()

    def _get_status(workflow_id: str) -> Dict[str, Any] | None:
        with app.state.agent_workflow_runs_lock:
            row = app.state.agent_workflow_runs.get(workflow_id)
            return dict(row) if isinstance(row, dict) else None

    def _set_approval(workflow_id: str, data: Dict[str, Any]) -> None:
        with app.state.agent_workflow_runs_lock:
            app.state.agent_workflow_approvals[workflow_id] = dict(data or {})

    def _get_approval(workflow_id: str) -> Dict[str, Any] | None:
        with app.state.agent_workflow_runs_lock:
            row = app.state.agent_workflow_approvals.get(workflow_id)
            return dict(row) if isinstance(row, dict) else None

    def _set_request(workflow_id: str, req: WorkflowRunRequest) -> None:
        with app.state.agent_workflow_runs_lock:
            app.state.agent_workflow_requests[workflow_id] = req.model_dump()

    def _get_request(workflow_id: str) -> Dict[str, Any] | None:
        with app.state.agent_workflow_runs_lock:
            row = app.state.agent_workflow_requests.get(workflow_id)
            return dict(row) if isinstance(row, dict) else None

    def _get_repo_delta_state(key: str) -> Dict[str, Any] | None:
        with app.state.agent_workflow_runs_lock:
            row = app.state.agent_workflow_repo_delta_state.get(key)
            return dict(row) if isinstance(row, dict) else None

    def _set_repo_delta_state(key: str, data: Dict[str, Any]) -> None:
        with app.state.agent_workflow_runs_lock:
            app.state.agent_workflow_repo_delta_state[key] = dict(data or {})

    def _append_trace(workflow_id: str, entry: WorkflowTraceEntry) -> None:
        with app.state.agent_workflow_runs_lock:
            if workflow_id not in app.state.agent_workflow_traces:
                app.state.agent_workflow_traces[workflow_id] = []
            app.state.agent_workflow_traces[workflow_id].append(entry.model_dump())

    def _resolve_family(req: WorkflowRunRequest) -> str:
        if req.workflow_family:
            return str(req.workflow_family)
        return "feature"

    def _workflow_data_dir() -> str:
        p = os.path.join(_framework_data_dir(app), "agent_workflow")
        os.makedirs(p, exist_ok=True)
        return p

    def _profiles_dir() -> str:
        p = os.path.join(_workflow_data_dir(), "profiles")
        os.makedirs(p, exist_ok=True)
        return p

    def _agents_path() -> str:
        return os.path.join(_workflow_data_dir(), "agents.json")

    def _repo_base_rel() -> str:
        return "data/agent_workflow/repo"

    def _tokenizer_from_model(model) -> Any | None:
        if model is None:
            return None
        tok = getattr(model, "tokenizer", None)
        if tok is not None:
            return tok
        llama = getattr(model, "llama", None)
        if llama is not None and hasattr(llama, "tokenize"):
            class LlamaTokenizerAdapter:
                def __init__(self, llama_obj):
                    self._llama = llama_obj

                def encode(self, text: str):
                    data = str(text or "").encode("utf-8")
                    return self._llama.tokenize(data, add_bos=True)

            return LlamaTokenizerAdapter(llama)
        tokenize = getattr(model, "tokenize", None)
        if callable(tokenize):
            class TokenizeAdapter:
                def __init__(self, fn):
                    self._fn = fn

                def encode(self, text: str):
                    return self._fn(str(text or ""))

            return TokenizeAdapter(tokenize)
        class FallbackTokenizer:
            def encode(self, text: str):
                s = str(text or "")
                # Conservative token proxy when model tokenizer is unavailable (e.g. llama.cpp server mode).
                parts = [p for p in s.replace("\r", " ").replace("\n", " ").split(" ") if p]
                return list(range(len(parts)))

        return FallbackTokenizer()
        return None

    def _sanitize_repo_root(raw: Any) -> str:
        s = str(raw or "").strip().replace("\\", "/")
        if not s:
            return _repo_base_rel()
        if s == _repo_base_rel() or s.startswith(_repo_base_rel() + "/"):
            return s
        raise HTTPException(status_code=400, detail=f"target_repo_root must be under '{_repo_base_rel()}'")

    # @r.post("/v1/agent_workflow/run", response_model=WorkflowResult)
    # def run_workflow(req: WorkflowRunRequest, request: Request):
    #     require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
    #     u = _require_user(app, request)
    #     _require_session_access(app, u, req.pid, req.sid)

    #     opts = dict(req.options or {})
    #     opts["target_repo_root"] = _sanitize_repo_root(opts.get("target_repo_root"))
    #     req = req.model_copy(update={"options": opts})

    #     workflow_id = f"wf_{secrets.token_hex(8)}"
    #     now = _utc_now()
    #     _set_request(workflow_id, req)
    #     _set_status(
    #         WorkflowStatus(
    #             workflow_id=workflow_id,
    #             state="running",
    #             current_stage="classify",
    #             current_node=None,
    #             started_at=now,
    #             updated_at=now,
    #             progress=0.0,
    #         )
    #     )
    #     _append_trace(
    #         workflow_id,
    #         WorkflowTraceEntry(
    #             stage="classify",
    #             event_type="workflow_start",
    #             message="Workflow run accepted.",
    #             data={"pid": req.pid, "sid": req.sid, "mode": req.mode},
    #         ),
    #     )
    #     executor = WorkflowExecutor(
    #         set_status=_set_status,
    #         append_trace=_append_trace,
    #         tool_call=tool_registry.call_tool,
    #         profile_registry=profile_registry,
    #     )
    #     try:
    #         result = executor.run(workflow_id=workflow_id, req=req)
    #         latest = _get_status(workflow_id) or {}
    #         if str(latest.get("state") or "") == "paused":
    #             _set_approval(
    #                 workflow_id,
    #                 {
    #                     "state": "pending",
    #                     "node_id": "approval_1",
    #                     "requested_at": _utc_now().isoformat(),
    #                 },
    #             )
    #         return result
    #     except Exception as exc:
    #         now2 = _utc_now()
    #         _set_status(
    #             WorkflowStatus(
    #                 workflow_id=workflow_id,
    #                 state="failed",
    #                 current_stage="lifecycle",
    #                 current_node=None,
    #                 started_at=now,
    #                 updated_at=now2,
    #                 progress=1.0,
    #             )
    #         )
    #         _append_trace(
    #             workflow_id,
    #             WorkflowTraceEntry(
    #                 stage="lifecycle",
    #                 event_type="workflow_error",
    #                 message=f"Workflow run failed: {exc}",
    #                 data={},
    #             ),
    #         )
    #         raise HTTPException(status_code=500, detail=f"workflow execution failed: {exc}")

    # @r.post("/v1/agent_workflow/stream")
    # def stream_workflow(req: WorkflowRunRequest, request: Request):
    #     require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
    #     u = _require_user(app, request)
    #     _require_session_access(app, u, req.pid, req.sid)

    #     opts = dict(req.options or {})
    #     opts["target_repo_root"] = _sanitize_repo_root(opts.get("target_repo_root"))
    #     req = req.model_copy(update={"options": opts})

    #     workflow_id = f"wf_{secrets.token_hex(8)}"
    #     _set_request(workflow_id, req)
    #     executor = WorkflowExecutor(
    #         set_status=_set_status,
    #         append_trace=_append_trace,
    #         tool_call=tool_registry.call_tool,
    #         profile_registry=profile_registry,
    #     )

    #     def _gen():
    #         try:
    #             for event, payload in executor.run_stream(workflow_id=workflow_id, req=req):
    #                 if event == "approval_required":
    #                     _set_approval(
    #                         workflow_id,
    #                         {
    #                             "state": "pending",
    #                             "node_id": str(payload.get("node_id") or "approval_1"),
    #                             "requested_at": _utc_now().isoformat(),
    #                         },
    #                     )
    #                 yield _sse(event, payload)
    #         except Exception as exc:
    #             now = _utc_now()
    #             existing = _get_status(workflow_id)
    #             if existing:
    #                 _set_status(
    #                     WorkflowStatus.model_validate(
    #                         {**existing, "state": "failed", "updated_at": now, "current_stage": existing.get("current_stage")}
    #                     )
    #                 )
    #             _append_trace(
    #                 workflow_id,
    #                 WorkflowTraceEntry(
    #                     stage="lifecycle",
    #                     event_type="workflow_error",
    #                     message=f"Workflow stream failed: {exc}",
    #                     data={},
    #                 ),
    #             )
    #             yield _sse("workflow_error", {"workflow_id": workflow_id, "message": str(exc)})

    #     return StreamingResponse(_gen(), media_type="text/event-stream")

    # @r.post("/v1/agent_workflow/approval")
    # def workflow_approval(req: ApprovalRequest, request: Request):
    #     require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
    #     _require_user(app, request)

    #     status = _get_status(req.workflow_id)
    #     if not status:
    #         raise HTTPException(status_code=404, detail="workflow_id not found")
    #     current = str(status.get("state") or "")
    #     if current != "paused":
    #         raise HTTPException(status_code=409, detail="workflow is not awaiting approval")

    #     pending = _get_approval(req.workflow_id) or {}
    #     node_id = str(pending.get("node_id") or "approval_1")
    #     if req.node_id != node_id:
    #         raise HTTPException(status_code=400, detail="node_id does not match pending approval")

    #     _append_trace(
    #         req.workflow_id,
    #         WorkflowTraceEntry(
    #             stage="approval",
    #             node_id=req.node_id,
    #             event_type="approval_received",
    #             message=f"Approval action recorded: {req.action}",
    #             data={"notes": req.notes or ""},
    #         ),
    #     )
    #     now = _utc_now()
    #     if req.action == "approve":
    #         _set_approval(req.workflow_id, {"state": "approved", "node_id": node_id, "resolved_at": now.isoformat()})
    #         request_data = _get_request(req.workflow_id)
    #         if not request_data:
    #             raise HTTPException(status_code=500, detail="original workflow request not found")
    #         resume_req = WorkflowRunRequest.model_validate(request_data)
    #         _append_trace(
    #             req.workflow_id,
    #             WorkflowTraceEntry(
    #                 stage="approval",
    #                 node_id=node_id,
    #                 event_type="approval_resume",
    #                 message="Resuming workflow after approval.",
    #                 data={},
    #             ),
    #         )
    #         executor = WorkflowExecutor(
    #             set_status=_set_status,
    #             append_trace=_append_trace,
    #             tool_call=tool_registry.call_tool,
    #             profile_registry=profile_registry,
    #         )
    #         result = executor.resume_after_approval(workflow_id=req.workflow_id, req=resume_req)
    #         if not result.ok:
    #             raise HTTPException(status_code=500, detail="workflow resume failed after approval")
    #         return {
    #             "ok": True,
    #             "workflow_id": req.workflow_id,
    #             "action": req.action,
    #             "node_id": node_id,
    #             "resumed": True,
    #         }
    #     elif req.action == "revise":
    #         _set_approval(req.workflow_id, {"state": "revision_requested", "node_id": node_id, "resolved_at": now.isoformat()})
    #         _set_status(
    #             WorkflowStatus.model_validate(
    #                 {
    #                     **status,
    #                     "state": "paused",
    #                     "current_stage": "approval",
    #                     "current_node": node_id,
    #                     "updated_at": now,
    #                 }
    #             )
    #         )
    #     elif req.action in ("reject", "cancel"):
    #         _set_approval(req.workflow_id, {"state": "rejected", "node_id": node_id, "resolved_at": now.isoformat()})
    #         _set_status(
    #             WorkflowStatus.model_validate(
    #                 {
    #                     **status,
    #                     "state": "cancelled",
    #                     "current_stage": "approval",
    #                     "current_node": node_id,
    #                     "updated_at": now,
    #                 }
    #             )
    #         )
    #     return {"ok": True, "workflow_id": req.workflow_id, "action": req.action, "node_id": node_id}

    # @r.get("/v1/agent_workflow/status/{workflow_id}", response_model=WorkflowStatus)
    # def workflow_status(workflow_id: str, request: Request):
    #     require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
    #     _require_user(app, request)

    #     status = _get_status(workflow_id)
    #     if not status:
    #         raise HTTPException(status_code=404, detail="workflow_id not found")
    #     return WorkflowStatus.model_validate(status)

    # @r.post("/v1/agent_workflow/cancel/{workflow_id}")
    # def cancel_workflow(workflow_id: str, request: Request):
    #     require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
    #     _require_user(app, request)

    #     status = _get_status(workflow_id)
    #     if not status:
    #         raise HTTPException(status_code=404, detail="workflow_id not found")

    #     now = _utc_now()
    #     updated = WorkflowStatus.model_validate({**status, "state": "cancelled", "updated_at": now})
    #     _set_status(updated)
    #     _append_trace(
    #         workflow_id,
    #         WorkflowTraceEntry(
    #             stage="lifecycle",
    #             event_type="workflow_cancelled",
    #             message="Workflow marked as cancelled.",
    #             data={},
    #         ),
    #     )
    #     return {"ok": True, "workflow_id": workflow_id, "state": "cancelled"}

    # @r.get("/v1/agent_workflow/trace/{workflow_id}")
    # def workflow_trace(workflow_id: str, request: Request):
    #     require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
    #     _require_user(app, request)
    #     with app.state.agent_workflow_runs_lock:
    #         rows: List[Dict[str, Any]] = list(app.state.agent_workflow_traces.get(workflow_id) or [])
    #         approval = dict(app.state.agent_workflow_approvals.get(workflow_id) or {})
    #     return {"ok": True, "workflow_id": workflow_id, "trace": rows, "approval": approval}

    @r.post("/v1/agent_workflow/agent_flow_nodes")
    def workflow_agent_flow_nodes(payload: Dict[str, Any], request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        p = str((payload or {}).get("pid") or "").strip()
        s = str((payload or {}).get("sid") or "").strip()
        if not p or not s:
            raise HTTPException(status_code=400, detail="pid and sid required")
        _require_session_access(app, u, p, s)

        team = str((payload or {}).get("team") or "feature").strip() or "feature"
        flow_name = str((payload or {}).get("flow_name") or f"workflow_{team}").strip() or f"workflow_{team}"
        canonical = _canonical_agent_flow_project_flows(app, "project2")
        canonical_flow = canonical.get(flow_name) if isinstance(canonical.get(flow_name), dict) else None
        if canonical_flow:
            return {
                "ok": True,
                "team": team,
                "profile_ids": [],
                "warnings": ["canonical_flow_imported_from_project2"],
                "flow_name": flow_name,
                "flow": canonical_flow,
                "agent_flow_import": {
                    "flows": {flow_name: canonical_flow},
                    "default_flow": flow_name,
                    "active_flow": flow_name,
                    "mode": "execute",
                    "max_steps": 24,
                },
            }
        profile_ids = profile_registry.resolve_team(team, explicit=team)
        if not profile_ids:
            profile_ids = profile_registry.resolve_team("feature", explicit="feature")
        warnings: List[str] = []

        # Enforce core execution roles so imported team flows can actually deliver code + validation.
        required_roles = ["coder", "qa"]
        available_profiles = profile_registry.list_profiles() or {}
        for rr in required_roles:
            if rr not in profile_ids and rr in available_profiles:
                profile_ids.append(rr)
                warnings.append(f"required_role_added:{rr}")

        nodes: Dict[str, Any] = {}
        order: List[str] = []
        role_skill_map: Dict[str, List[str]] = {
            "product": ["auth.project_context", "repo.context", "repo.read", "learning.get_hints"],
            "gui_designer": ["repo.context", "repo.read", "rag.search", "learning.get_hints"],
            "architect": ["repo.tree", "repo.context", "repo.read", "rag.search"],
            "coder": ["repo.tree", "repo.read", "rag.search", "code.generate_patch_candidates", "code.apply_patch"],
            "staff_engineer": ["repo.tree", "repo.read", "rag.search", "code.generate_patch_candidates", "code.apply_patch", "tests.run_project"],
            "qa": ["repo.read", "tests.run_project", "tests.smoke", "debug.fix_from_errors"],
            "docs": ["repo.context", "repo.read", "learning.get_hints"],
            "security": ["repo.tree", "repo.read", "rag.search"],
            "release": ["repo.read", "tests.run_project", "learning.list"],
        }
        for i, pid2 in enumerate(profile_ids):
            nid = f"n{i+1}"
            order.append(nid)
            prof = (profile_registry.list_profiles() or {}).get(pid2, {})
            label = str(prof.get("label") or pid2)
            role_prompt = str(prof.get("prompt") or "").strip()
            skills = list(role_skill_map.get(pid2, ["repo.context"]))
            skill_text = ", ".join(skills)
            role_behavior = {
                "product": "Clarify user outcomes, acceptance criteria, and scope boundaries.",
                "gui_designer": "Design and validate UI/UX flows, component behavior, and frontend polish constraints.",
                "architect": "Define plugin boundaries, interfaces, and safe change plan.",
                "coder": "Implement minimal code changes and generate targeted patches.",
                "staff_engineer": "Refine implementation, validate risk, and stabilize execution plan.",
                "qa": "Run and interpret tests, isolate failures, and propose concrete fixes.",
                "docs": "Ensure docs/changelog coverage and release-facing clarity.",
                "security": "Identify unsafe operations and enforce guardrails.",
                "release": "Check readiness and summarize shippable status.",
            }.get(pid2, "Perform your assigned workflow role.")
            if role_prompt:
                role_prompt = role_prompt.strip() + "\n\n"
            role_prompt += (
                f"You are the {label} ({pid2}). {role_behavior}\n"
                "You may invoke action skills by returning STRICT JSON with tool calls.\n"
                f"Allowed action skills: {skill_text}\n"
                "When invoking skills, return this shape exactly:\n"
                "{\"summary\":\"...\",\"actions\":[\"...\"],\"tool_calls\":[{\"skill\":\"<allowed-skill>\",\"params\":{}}],\"handoff\":\"...\"}\n"
                "If no skill is needed, return plain text with sections: summary, actions, handoff."
            )
            x = 80 + (i % 3) * 290
            y = 80 + (i // 3) * 170
            nodes[nid] = {
                "label": label,
                "plugin_id": "agent_workflow_member",
                "agent_kind": pid2,
                "system_prompt": role_prompt,
                "x": x,
                "y": y,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [{"target": f"n{i+2}"}] if i + 1 < len(profile_ids) else [],
                "plugin_settings": {
                    "member_role": pid2,
                    "handoff_format": "concise_structured",
                    "member_token_stream": True,
                    "action_skills": skills,
                },
            }
        flow = {"start": order[0] if order else "", "nodes": nodes}
        return {
            "ok": True,
            "team": team,
            "profile_ids": profile_ids,
            "warnings": warnings,
            "flow_name": flow_name,
            "flow": flow,
            "agent_flow_import": {
                "flows": {flow_name: flow},
                "default_flow": flow_name,
                "active_flow": flow_name,
                "mode": "execute",
                "max_steps": max(8, len(order) + 2),
            },
        }

    @r.get("/v1/agent_workflow/agent_flow_import_preset")
    def workflow_agent_flow_import_preset(request: Request, preset: str = ""):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_user(app, request)
        key = str(preset or "").strip().lower()
        if key == "dev_pipeline":
            payload = _select_import_flows_payload(
                app,
                [
                    "workflow_dev_pipeline",
                    "workflow_team_discovery",
                    "workflow_team_build",
                    "workflow_team_quality",
                    "workflow_team_release",
                ],
                default_flow="workflow_dev_pipeline",
                preset_name="dev_pipeline",
            )
        elif key == "repo_improvement":
            payload = _select_import_flows_payload(
                app,
                [
                    "workflow_repo_improvement",
                    "workflow_repo_improvement_interactive",
                    "workflow_repo_improvement_rag_git",
                    "workflow_repo_improvement_system_debugger",
                ],
                default_flow="workflow_repo_improvement",
                preset_name="repo_improvement",
            )
        else:
            raise HTTPException(status_code=400, detail="unknown preset")
        if not isinstance(payload.get("flows"), dict) or not payload.get("flows"):
            raise HTTPException(status_code=404, detail="preset not available")
        return {"ok": True, "preset": key, "agent_flow_import": payload}

    @r.get("/v1/agent_workflow/tools")
    def workflow_tools(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_user(app, request)
        return {"ok": True, "tools": _tool_registry().list_tools()}

    @r.get("/v1/agent_workflow/repo_tree")
    def workflow_repo_tree(request: Request, pid: str, sid: str, max_files: int = 1200):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        base = _repo_base_rel()
        root = getattr(app.state, "workdir", None) or os.path.abspath(".")
        abs_base = os.path.abspath(os.path.join(str(root), base.replace("/", os.sep)))
        os.makedirs(abs_base, exist_ok=True)
        out = _tool_registry().call_tool(
            "repo.tree",
            {"pid": pid, "sid": sid},
            {"max_files": max(50, min(5000, int(max_files))), "base_prefix": base},
        )
        if not out.get("ok"):
            raise HTTPException(status_code=400, detail={"warnings": out.get("warnings") or ["repo_tree_failed"]})
        data = dict(out.get("data") or {})
        files = [str(x).replace("\\", "/") for x in (data.get("files") or []) if str(x).strip()]
        scoped = [f for f in files if f == base or f.startswith(base + "/")]
        data["files"] = scoped
        data["scoped_base"] = base
        return {"ok": True, "data": data, "warnings": out.get("warnings") or []}

    @r.post("/v1/agent_workflow/repo_prepare")
    def workflow_repo_prepare(request: Request, payload: Dict[str, Any] | None = None, pid: str | None = None, sid: str | None = None, target_repo_root: str | None = None):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        p = str((payload or {}).get("pid") or pid or "").strip()
        s = str((payload or {}).get("sid") or sid or "").strip()
        tr = str((payload or {}).get("target_repo_root") or target_repo_root or "").strip() or None
        if not p or not s:
            raise HTTPException(status_code=400, detail="pid and sid required")
        u = _require_user(app, request)
        _require_session_access(app, u, p, s)
        rel = _sanitize_repo_root(tr)
        root = getattr(app.state, "workdir", None) or os.path.abspath(".")
        abs_dir = os.path.abspath(os.path.join(str(root), rel.replace("/", os.sep)))
        os.makedirs(abs_dir, exist_ok=True)
        return {"ok": True, "target_repo_root": rel, "abs_dir": abs_dir}

    @r.post("/v1/agent_workflow/repo_ingest")
    def workflow_repo_ingest(request: Request, payload: Dict[str, Any] | None = None):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        p = str((payload or {}).get("pid") or "").strip()
        s = str((payload or {}).get("sid") or "").strip()
        tr = str((payload or {}).get("target_repo_root") or "").strip()
        if not p or not s:
            raise HTTPException(status_code=400, detail="pid and sid required")
        u = _require_user(app, request)
        _require_session_access(app, u, p, s)
        rel = _sanitize_repo_root(tr)
        root = getattr(app.state, "workdir", None) or os.path.abspath(".")
        abs_dir = os.path.abspath(os.path.join(str(root), rel.replace("/", os.sep)))
        repo_id = str((payload or {}).get("repo_id") or "current").strip() or "current"
        os.makedirs(abs_dir, exist_ok=True)
        if not os.path.isdir(abs_dir):
            raise HTTPException(status_code=400, detail=f"target repo dir not found: {abs_dir}")

        user_rag = getattr(app.state, "user_rag", None)
        if user_rag is None:
            raise HTTPException(status_code=400, detail="USER-RAG disabled")
        model_fn = getattr(app.state, "model", None)
        model = model_fn() if callable(model_fn) else model_fn
        tokenizer = _tokenizer_from_model(model)
        if tokenizer is None:
            class FallbackTokenizer:
                def encode(self, text: str):
                    s = str(text or "")
                    parts = [p for p in s.replace("\r", " ").replace("\n", " ").split(" ") if p]
                    return list(range(len(parts)))
            tokenizer = FallbackTokenizer()

        try:
            import repo_ingest
            max_file_bytes = int((payload or {}).get("max_file_bytes") or 220000)
            include_lang = (payload or {}).get("include_lang")
            exclude_globs = (payload or {}).get("exclude_globs")
            chunk_lines = int((payload or {}).get("chunk_lines") or 220)
            requested_version = (payload or {}).get("version")
            force_full = bool((payload or {}).get("force_full"))
            scan_cache_ttl_ms = int((payload or {}).get("scan_cache_ttl_ms") or 60000)
            now_ms = int(time.time() * 1000)
            delta_key = _aw_repo_delta_key(s, repo_id, abs_dir)
            prev_state = _get_repo_delta_state(delta_key) or {}
            prev_version = str(prev_state.get("version") or "").strip() or None
            prev_scan_ts = int(prev_state.get("scan_ts") or 0)
            prev_mode = str(prev_state.get("last_mode") or "").strip()
            if (
                not force_full
                and prev_version
                and prev_mode in {"no_delta", "cached_no_delta"}
                and prev_scan_ts > 0
                and scan_cache_ttl_ms > 0
                and (now_ms - prev_scan_ts) < scan_cache_ttl_ms
            ):
                return {
                    "ok": True,
                    "target_repo_root": rel,
                    "abs_dir": abs_dir,
                    "mode": "cached_no_delta",
                    "changed": [],
                    "deleted": [],
                    "moved": [],
                    "stats": {"ok": True, "repo_id": repo_id, "version": prev_version, "stats": {"changed_files": 0, "deleted_files": 0, "new_chunks": 0, "reused_chunks": 0, "skipped_files": 0}},
                }

            cur_index = _scan_stat_index_for_app(
                app,
                abs_dir,
                ignore_dirs={".git", ".hg", ".svn", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv", "dist", "build", ".mypy_cache"},
                ignore_exts={".pyc", ".pyo", ".pyd", ".o", ".obj", ".so", ".dll", ".dylib", ".zip", ".tar", ".gz", ".7z"},
            )
            prev_index = prev_state.get("index") if isinstance(prev_state.get("index"), dict) else None

            latest = None
            try:
                latest = user_rag._get_latest_version_record(s, repo_id) or None
            except Exception:
                latest = None
            if latest and not prev_version:
                prev_version = str(latest.get("id") or "").strip() or None

            mode = "full"
            moved: List[Dict[str, str]] = []
            changed: List[str] = []
            deleted: List[str] = []

            if not force_full and prev_index is not None and prev_version:
                batch = _stat_delta_for_app(app, prev_index, cur_index)
                changed = list(batch.changed or [])
                deleted = list(batch.deleted or [])
                moved = _aw_detect_moves(prev_index, cur_index, changed, deleted)
                if not changed and not deleted:
                    _set_repo_delta_state(
                        delta_key,
                        {
                            "root_dir": abs_dir,
                            "target_repo_root": rel,
                            "repo_id": repo_id,
                            "version": prev_version,
                            "index": cur_index,
                            "last_mode": "no_delta",
                            "scan_ts": int(time.time() * 1000),
                        },
                    )
                    return {
                        "ok": True,
                        "target_repo_root": rel,
                        "abs_dir": abs_dir,
                        "mode": "no_delta",
                        "changed": [],
                        "deleted": [],
                        "moved": [],
                        "stats": {"ok": True, "repo_id": repo_id, "version": prev_version, "stats": {"changed_files": 0, "deleted_files": 0, "new_chunks": 0, "reused_chunks": 0, "skipped_files": 0}},
                    }
                mode = "delta"
                stats = repo_ingest.ingest_dir_delta_to_user_rag_cold(
                    user_rag,
                    s,
                    repo_id,
                    abs_dir,
                    tokenizer,
                    changed_paths=changed,
                    deleted_paths=deleted,
                    include_lang=include_lang,
                    exclude_globs=exclude_globs,
                    chunk_lines=chunk_lines,
                    max_file_bytes=max_file_bytes,
                    version=requested_version,
                    base_version=prev_version,
                )
            else:
                stats = repo_ingest.ingest_dir_to_user_rag_cold(
                    user_rag,
                    s,
                    repo_id,
                    abs_dir,
                    tokenizer,
                    max_file_bytes=max_file_bytes,
                    include_lang=include_lang,
                    exclude_globs=exclude_globs,
                    chunk_lines=chunk_lines,
                    version=requested_version,
                )
                mode = "full"
                changed = sorted(cur_index.keys())
                deleted = []
                moved = []

            next_version = ""
            if isinstance(stats, dict):
                next_version = str(stats.get("version") or "").strip()
                if not next_version:
                    next_version = str(((stats.get("stats") or {}) if isinstance(stats.get("stats"), dict) else {}).get("version") or "").strip()
            if not next_version:
                next_version = prev_version or ""

            _set_repo_delta_state(
                delta_key,
                {
                    "root_dir": abs_dir,
                    "target_repo_root": rel,
                    "repo_id": repo_id,
                    "version": next_version,
                    "index": cur_index,
                    "last_mode": mode,
                    "scan_ts": int(time.time() * 1000),
                },
            )
            return {
                "ok": True,
                "target_repo_root": rel,
                "abs_dir": abs_dir,
                "mode": mode,
                "changed": changed,
                "deleted": deleted,
                "moved": moved,
                "stats": stats,
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"repo_ingest_failed:{exc}")

    @r.post("/v1/agent_workflow/rag_query")
    def workflow_rag_query(request: Request, payload: Dict[str, Any] | None = None):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        p = str((payload or {}).get("pid") or "").strip()
        s = str((payload or {}).get("sid") or "").strip()
        q = str((payload or {}).get("query") or "").strip()
        tr = str((payload or {}).get("target_repo_root") or "").strip()
        k = int((payload or {}).get("k") or 6)
        max_chars = int((payload or {}).get("max_chars") or 1200)
        if not p or not s:
            raise HTTPException(status_code=400, detail="pid and sid required")
        if not q:
            return {"ok": True, "hits": [], "scoped_prefix": _sanitize_repo_root(tr)}
        u = _require_user(app, request)
        _require_session_access(app, u, p, s)
        prefix = _sanitize_repo_root(tr)
        user_rag = getattr(app.state, "user_rag", None)
        if user_rag is None:
            raise HTTPException(status_code=400, detail="USER-RAG disabled")
        try:
            raw_hits = user_rag.search(s, q, k=max(1, min(40, k)), max_chars=max(800, min(12000, max_chars))) or []
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"rag_query_failed:{exc}")
        out = []
        prefix_rel = prefix
        prefix_tail = prefix_rel.split("/", 1)[-1] if "/" in prefix_rel else prefix_rel

        def _path_in_scope(path: str) -> bool:
            p = str(path or "").replace("\\", "/")
            if not p:
                return False
            if p == prefix_rel or p.startswith(prefix_rel + "/"):
                return True
            # Some repo_ingest metadata stores path relative to repo root.
            if p.startswith(prefix_tail + "/"):
                return True
            if "/" not in p and prefix_rel:
                return True
            return False

        for h in raw_hits:
            if not isinstance(h, dict):
                continue
            meta = h.get("meta") or h.get("metadata") or {}
            repo_id = str(meta.get("repo_id") or "")
            path = str(meta.get("path") or "").replace("\\", "/")
            if repo_id != "current":
                continue
            if not _path_in_scope(path):
                continue
            txt = str(h.get("text") or "")
            out.append(
                {
                    "path": path,
                    "score": float(h.get("score") or 0.0),
                    "text": txt[: max(200, min(3000, max_chars))],
                }
            )
            if len(out) >= max(1, min(12, k)):
                break

        # Fallback: if semantic hits are empty, try direct file lookup from query file name.
        if not out:
            m = re.search(r"([A-Za-z0-9_./\\-]+\.(?:py|js|ts|tsx|jsx|json|md|html|css))", q)
            requested = str(m.group(1) if m else "").replace("\\", "/").strip()
            tree = _tool_registry().call_tool("repo.tree", {"pid": p, "sid": s}, {"max_files": 4000, "base_prefix": prefix_rel})
            files = [str(x).replace("\\", "/") for x in (((tree.get("data") or {}).get("files") or []) if isinstance(tree, dict) else [])]
            rel_candidates = []
            if requested:
                req_name = requested.split("/")[-1].lower()
                for f in files:
                    fl = f.lower()
                    if fl.endswith(requested.lower()) or fl.endswith("/" + req_name):
                        rel = f[len(prefix_rel) + 1 :] if f.startswith(prefix_rel + "/") else f
                        rel_candidates.append((f, rel))
                rel_candidates = rel_candidates[: max(1, min(6, k))]
            for full_path, rel_path in rel_candidates:
                txt = ""
                try:
                    txt = user_rag.get_repo_file_from_lib_repo_files(
                        sid=s,
                        repo_id="current",
                        rel_path=rel_path,
                        version=None,
                        max_chars=max(800, min(4000, max_chars)),
                    ) or ""
                except Exception:
                    txt = ""
                if txt:
                    out.append({"path": full_path, "score": 0.0, "text": txt[: max(200, min(3000, max_chars))]})
                    if len(out) >= max(1, min(6, k)):
                        break
        return {"ok": True, "hits": out, "scoped_prefix": prefix}

    @r.post("/v1/agent_workflow/repo_read")
    def workflow_repo_read(request: Request, payload: Dict[str, Any] | None = None):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        p = str((payload or {}).get("pid") or "").strip()
        s = str((payload or {}).get("sid") or "").strip()
        tr = str((payload or {}).get("target_repo_root") or "").strip()
        target = str((payload or {}).get("target") or "").strip().replace("\\", "/")
        max_chars = int((payload or {}).get("max_chars") or 2500)
        if not p or not s:
            raise HTTPException(status_code=400, detail="pid and sid required")
        if not target:
            raise HTTPException(status_code=400, detail="target required")
        u = _require_user(app, request)
        _require_session_access(app, u, p, s)
        prefix = _sanitize_repo_root(tr)
        root = getattr(app.state, "workdir", None) or os.path.abspath(".")
        abs_root = os.path.abspath(os.path.join(str(root), prefix.replace("/", os.sep)))
        if not os.path.isdir(abs_root):
            raise HTTPException(status_code=400, detail=f"target repo root not found: {prefix}")

        # Resolve direct relative path first.
        cand = os.path.abspath(os.path.join(abs_root, target.replace("/", os.sep)))
        chosen = ""
        if cand.startswith(abs_root) and os.path.isfile(cand):
            chosen = cand
        else:
            # Fallback by filename match inside scoped root.
            base_name = target.split("/")[-1].lower()
            for b, _dirs, files in os.walk(abs_root):
                for fn in files:
                    if fn.lower() == base_name:
                        path = os.path.abspath(os.path.join(b, fn))
                        if path.startswith(abs_root):
                            chosen = path
                            break
                if chosen:
                    break
        if not chosen:
            return {"ok": True, "found": False, "target": target}

        try:
            preview = read_repo_file_preview(chosen, max_chars=max_chars)
            txt = str(preview.get("text") or "")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"repo_read_failed:{exc}")
        rel = os.path.relpath(chosen, str(root)).replace("\\", "/")
        return {"ok": True, "found": True, "path": rel, "text": txt}

    @r.get("/v1/agent_workflow/profiles")
    def workflow_profiles(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_user(app, request)
        load_meta = getattr(app.state, "agent_workflow_profile_json", {})
        return {
            "ok": True,
            "profiles": profile_registry.list_profiles(),
            "teams": profile_registry.list_teams(),
            "profile_json": load_meta if isinstance(load_meta, dict) else {},
        }

    @r.post("/v1/agent_workflow/profiles/reload")
    def workflow_profiles_reload(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_user(app, request)
        root = getattr(app.state, "workdir", None) or os.path.abspath(".")
        prof_dir = os.path.join(str(root), "data", "projects", "agent_workflow", "profiles")
        preg = build_default_profile_registry()
        load_info = load_profiles_from_dir(preg, prof_dir)
        app.state.agent_workflow_profiles = preg
        app.state.agent_workflow_profile_json = {"dir": prof_dir, **load_info}
        return {
            "ok": bool(load_info.get("ok", True)),
            "profiles": preg.list_profiles(),
            "teams": preg.list_teams(),
            "profile_json": app.state.agent_workflow_profile_json,
        }

    @r.get("/v1/agent_workflow/profiles/files")
    def workflow_profile_files(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_user(app, request)
        pdir = _profiles_dir()
        items = []
        for fn in sorted(os.listdir(pdir)):
            if not fn.lower().endswith(".json"):
                continue
            path = os.path.join(pdir, fn)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                data = {}
            items.append({"file_name": fn, "content": data})
        return {"ok": True, "files": items, "dir": pdir}

    @r.post("/v1/agent_workflow/profiles/upsert")
    def workflow_profile_upsert(payload: Dict[str, Any], request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_user(app, request)
        file_name = str((payload or {}).get("file_name") or "custom_profiles.json").strip()
        if not file_name.endswith(".json"):
            file_name += ".json"
        if "/" in file_name or "\\" in file_name:
            raise HTTPException(status_code=400, detail="invalid file_name")
        path = os.path.join(_profiles_dir(), file_name)
        cur = {}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    cur = json.load(fh) or {}
            except Exception:
                cur = {}
        if not isinstance(cur, dict):
            cur = {}
        cur.setdefault("profiles", {})
        cur.setdefault("teams", {})
        prof_id = str((payload or {}).get("profile_id") or "").strip()
        prof_cfg = (payload or {}).get("profile")
        if prof_id and isinstance(prof_cfg, dict):
            cur["profiles"][prof_id] = prof_cfg
        team_name = str((payload or {}).get("team_name") or "").strip()
        team_members = (payload or {}).get("team_members")
        if team_name and isinstance(team_members, list):
            cur["teams"][team_name] = [str(x) for x in team_members if str(x).strip()]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cur, fh, ensure_ascii=True, indent=2)
        # reload registry after update
        root = getattr(app.state, "workdir", None) or os.path.abspath(".")
        prof_dir = os.path.join(str(root), "data", "projects", "agent_workflow", "profiles")
        preg = build_default_profile_registry()
        load_info = load_profiles_from_dir(preg, prof_dir)
        app.state.agent_workflow_profiles = preg
        app.state.agent_workflow_profile_json = {"dir": prof_dir, **load_info}
        return {"ok": True, "file_name": file_name, "profiles": preg.list_profiles(), "teams": preg.list_teams()}

    @r.get("/v1/agent_workflow/agents/config")
    def workflow_agents_get(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_user(app, request)
        path = _agents_path()
        if not os.path.isfile(path):
            return {"ok": True, "teams": {}}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh) or {}
        except Exception:
            data = {}
        teams = data.get("teams") if isinstance(data, dict) else {}
        if not isinstance(teams, dict):
            teams = {}
        return {"ok": True, "teams": teams}

    @r.post("/v1/agent_workflow/agents/config")
    def workflow_agents_set(payload: Dict[str, Any], request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_user(app, request)
        team_name = str((payload or {}).get("team_name") or "").strip()
        workers = (payload or {}).get("workers")
        if not team_name:
            raise HTTPException(status_code=400, detail="team_name required")
        if not isinstance(workers, list):
            raise HTTPException(status_code=400, detail="workers must be list")
        norm = []
        for w in workers:
            if not isinstance(w, dict):
                continue
            pid = str(w.get("profile_id") or "").strip()
            wid = str(w.get("worker_id") or "").strip()
            resp = str(w.get("responsibility") or "").strip()
            if not pid:
                continue
            norm.append(
                {
                    "worker_id": wid or f"{pid}_worker",
                    "profile_id": pid,
                    "responsibility": resp,
                }
            )
        path = _agents_path()
        cur = {"teams": {}}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    cur = json.load(fh) or {"teams": {}}
            except Exception:
                cur = {"teams": {}}
        if not isinstance(cur, dict):
            cur = {"teams": {}}
        if not isinstance(cur.get("teams"), dict):
            cur["teams"] = {}
        cur["teams"][team_name] = norm
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cur, fh, ensure_ascii=True, indent=2)
        return {"ok": True, "teams": cur["teams"], "team_name": team_name}

    @r.post("/v1/agent_workflow/feedback")
    def workflow_feedback(req: FeedbackCaptureRequest, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, req.pid, req.sid)
        out = _tool_registry().call_tool(
            "learning.capture_feedback",
            {"pid": req.pid, "sid": req.sid},
            req.model_dump(),
        )
        if not out.get("ok"):
            raise HTTPException(status_code=400, detail={"warnings": out.get("warnings") or ["feedback_capture_failed"]})
        if req.workflow_id:
            _append_trace(
                req.workflow_id,
                WorkflowTraceEntry(
                    stage="learn",
                    event_type="feedback_captured",
                    message="Feedback captured via API.",
                    data={"feedback_id": ((out.get("data") or {}).get("feedback_id") or "")},
                ),
            )
        return {"ok": True, "feedback": out.get("data") or {}}

    @r.get("/v1/agent_workflow/learning")
    def workflow_learning(request: Request, limit: int = 40):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_user(app, request)
        out = _tool_registry().call_tool("learning.list", {}, {"limit": limit})
        return {"ok": True, "learning": (out.get("data") or {}).get("items") or []}

    app.include_router(r)
    print("[gui_helpers] agent_workflow routes installed")
