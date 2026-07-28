from __future__ import annotations

from .schemas import WorkflowContext


def build_context(
    *,
    workflow_id: str,
    pid: str,
    sid: str,
    user_input: str,
    workflow_family: str,
    mode: str,
    constraints: dict | None = None,
    options: dict | None = None,
) -> WorkflowContext:
    return WorkflowContext(
        workflow_id=workflow_id,
        pid=pid,
        sid=sid,
        user_input=user_input,
        workflow_family=workflow_family,
        mode=mode,
        constraints=dict(constraints or {}),
        options=dict(options or {}),
    )

