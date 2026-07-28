from __future__ import annotations

import inspect
from typing import Any, Dict


class WorkflowRegistry:
    def __init__(self) -> None:
        self._workflows: Dict[str, Dict[str, Any]] = {}

    def register_workflow(self, name: str, definition: Dict[str, Any]) -> None:
        self._workflows[str(name)] = dict(definition or {})

    def get_workflow(self, name: str) -> Dict[str, Any] | None:
        row = self._workflows.get(str(name))
        return dict(row) if isinstance(row, dict) else None

    def list_workflows(self) -> Dict[str, Dict[str, Any]]:
        return {k: dict(v) for k, v in self._workflows.items()}


class WorkflowToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register_tool(self, name: str, handler: Any, permissions: Any = None) -> None:
        self._tools[str(name)] = {
            "handler": handler,
            "permissions": permissions,
        }

    def list_tools(self) -> Dict[str, Dict[str, Any]]:
        return {k: {"permissions": v.get("permissions")} for k, v in self._tools.items()}

    def call_tool(self, name: str, ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        rec = self._tools.get(str(name))
        if not rec:
            return {"ok": False, "data": {}, "warnings": [f"tool_not_found:{name}"]}
        handler = rec.get("handler")
        if not callable(handler):
            return {"ok": False, "data": {}, "warnings": [f"tool_not_callable:{name}"]}
        out = handler(ctx, params or {})
        if inspect.isawaitable(out):
            raise RuntimeError(f"Async tool handler not supported in sync path: {name}")
        if isinstance(out, dict) and "ok" in out:
            row = dict(out)
            row.setdefault("warnings", [])
            data = row.get("data")
            if not isinstance(data, dict):
                data = {}
            # Preserve top-level payload keys emitted by skills (e.g. records/value/columns)
            # by mirroring them under data, so downstream workflow nodes can read tool values.
            for k, v in row.items():
                if k in {"ok", "data", "warnings", "error"}:
                    continue
                if k not in data:
                    data[k] = v
            row["data"] = data
            return row
        return {"ok": True, "data": out if isinstance(out, dict) else {"result": out}, "warnings": []}
