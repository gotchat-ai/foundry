from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


WORKFLOW_FAMILIES = Literal["feature", "bugfix", "review", "qa_release", "learning_feedback"]
WORKFLOW_MODES = Literal["plan_only", "suggest_patch", "apply_patch", "review_only", "qa_only", "release_only"]
APPROVAL_ACTIONS = Literal["approve", "reject", "revise", "cancel"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowRunRequest(BaseModel):
    pid: str
    sid: str
    intent: str = "auto"
    input: str
    mode: WORKFLOW_MODES = "plan_only"
    workflow_family: Optional[WORKFLOW_FAMILIES] = None
    targets: Dict[str, Any] = Field(default_factory=dict)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    options: Dict[str, Any] = Field(default_factory=dict)


class WorkflowResult(BaseModel):
    workflow_id: str
    ok: bool
    workflow_family: str
    mode: str
    summary: str
    outputs: List[Any] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    trace_id: Optional[str] = None


class ApprovalRequest(BaseModel):
    workflow_id: str
    node_id: str
    action: APPROVAL_ACTIONS
    notes: Optional[str] = None


class FeedbackCaptureRequest(BaseModel):
    workflow_id: Optional[str] = None
    pid: str
    sid: str
    pattern: str
    correction_type: str
    notes: str = ""
    preferred_files: List[str] = Field(default_factory=list)
    avoid: List[str] = Field(default_factory=list)
    workflow_family: Optional[str] = None


class WorkflowStatus(BaseModel):
    workflow_id: str
    state: str
    current_stage: Optional[str] = None
    current_node: Optional[str] = None
    started_at: datetime
    updated_at: datetime
    progress: float = 0.0


class WorkflowTraceEntry(BaseModel):
    timestamp: datetime = Field(default_factory=utc_now)
    stage: str
    node_id: Optional[str] = None
    event_type: str
    message: str
    data: Dict[str, Any] = Field(default_factory=dict)


class WorkflowContext(BaseModel):
    workflow_id: str
    pid: str
    sid: str
    user_input: str
    workflow_family: str
    mode: str
    constraints: Dict[str, Any] = Field(default_factory=dict)
    options: Dict[str, Any] = Field(default_factory=dict)
    graph_state: Dict[str, Any] = Field(default_factory=dict)
    memory_state: Dict[str, Any] = Field(default_factory=dict)
    trace: List[WorkflowTraceEntry] = Field(default_factory=list)
    approvals: Dict[str, Any] = Field(default_factory=dict)
    outputs: List[Any] = Field(default_factory=list)
