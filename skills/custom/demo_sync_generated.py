from __future__ import annotations

from typing import Any, Dict


NAME = 'custom.demo_sync_generated'
PERMISSIONS = ['custom.demo_sync_generated', 'custom.*']


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ok": False,
        "data": {"params": dict(params or {})},
        "warnings": ["todo_skill_not_implemented"],
    }


TOOL_SPEC = {'id': 'custom.demo_sync_generated', 'category': 'custom', 'label': 'custom.demo_sync_generated', 'description': 'Implement a bounded authored sync test note.', 'permissions': ['custom.demo_sync_generated', 'custom.*'], 'metadata': {'version': '1.0', 'created_at': '2026-06-16T21:38:20.404145+00:00', 'last_updated': '2026-06-16T21:38:20.404145+00:00', 'dev_status': 'untested'}, 'params_schema': {}}
