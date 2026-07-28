from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Set

ROOT = Path(__file__).resolve().parents[1]
ROUTES_PATH = ROOT / "plugins" / "gui_helpers" / "collab_chat" / "routes.py"
AUTOFLOW_PATH = ROOT / "plugins" / "ai_routes" / "autoflow" / "__init__.py"
SMOKE_PATH = ROOT / "tools" / "autoflow_service_chat_smoke.py"

BUILTIN_RE = re.compile(r"__autoflow_builtin_[a-z0-9_]+__")
ALLOWED_AUTOFLOW_ONLY = {"__autoflow_builtin_current_context_answer__", "__autoflow_builtin_web_research__"}
ALLOWED_INLINE_ONLY = {"__autoflow_builtin_web_research__"}
ALLOWED_NO_INLINE_RUNNER = {"__autoflow_builtin_general_answer__"}



def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _builtin_ids(text: str) -> Set[str]:
    return set(BUILTIN_RE.findall(text))


def _section(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        return ""
    end = text.find(end_marker, start)
    if end < 0:
        return text[start:]
    return text[start:end]


def _smoke_builtin_map(text: str) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    parts = text.split("SmokeCase(")
    for block in parts[1:]:
        name_match = re.search(r'name="([^"]+)"', block)
        builtin_match = re.search(r'expect_autoflow_selected="([^"]+)"', block)
        if not name_match or not builtin_match:
            continue
        case_name = str(name_match.group(1) or "").strip()
        builtin = str(builtin_match.group(1) or "").strip()
        if not builtin.startswith("__autoflow_builtin_"):
            continue
        out.setdefault(builtin, []).append(case_name)
    return out


def main() -> int:
    routes = _read(ROUTES_PATH)
    autoflow = _read(AUTOFLOW_PATH)
    smoke = _read(SMOKE_PATH)

    local_selector = _section(routes, '    def _local_builtin_candidate(prompt: str) -> Dict[str, Any]:', '    def _load_skill_runner(skill_id: str):')
    inline_map = _section(routes, '            skill_map = {', '            mapping = skill_map.get(flow_name)')
    autoflow_selector = _section(autoflow, '    def _builtin_direct_candidate(self, user_text: str, profile: Dict[str, Any]) -> Dict[str, Any]:', '    def _preferred_market_data_skill_id(self, workflow_json: Dict[str, Any], request_text: str = "") -> str:')

    local_ids = _builtin_ids(local_selector)
    inline_ids = _builtin_ids(inline_map)
    autoflow_ids = _builtin_ids(autoflow_selector)
    smoke_map = _smoke_builtin_map(smoke)
    smoke_ids = set(smoke_map)

    checks = {
        'local_only_vs_autoflow': sorted(local_ids - autoflow_ids),
        'autoflow_only_vs_local': sorted((autoflow_ids - local_ids) - ALLOWED_AUTOFLOW_ONLY),
        'local_without_inline_runner': sorted((local_ids - inline_ids) - ALLOWED_NO_INLINE_RUNNER),
        'inline_without_local_selector': sorted((inline_ids - local_ids) - ALLOWED_INLINE_ONLY),
        'autoflow_without_smoke_case': sorted((autoflow_ids - smoke_ids) - ALLOWED_NO_INLINE_RUNNER),
    }

    bad = False
    for label, values in checks.items():
        print(f'[{label}]')
        if values:
            bad = True
            for item in values:
                print(item)
        else:
            print('ok')
        print()

    print('[smoke_cases_by_builtin]')
    for builtin in sorted(smoke_map):
        cases = ', '.join(smoke_map[builtin])
        print(f'{builtin}: {cases}')

    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
