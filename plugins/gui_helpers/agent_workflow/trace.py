from __future__ import annotations

from typing import Any, Dict, List

from .schemas import WorkflowTraceEntry


class TraceStore:
    def __init__(self) -> None:
        self._by_workflow: Dict[str, List[Dict[str, Any]]] = {}

    async def append(self, workflow_id: str, entry: WorkflowTraceEntry) -> None:
        key = str(workflow_id)
        if key not in self._by_workflow:
            self._by_workflow[key] = []
        self._by_workflow[key].append(entry.model_dump())

    async def get_trace(self, workflow_id: str) -> List[Dict[str, Any]]:
        return list(self._by_workflow.get(str(workflow_id)) or [])

