from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from plugins.gui_helpers.agent_workflow.repo_file_preview import read_repo_file_preview

NAME = "custom.repo_file_summary"
PERMISSIONS = [NAME, "custom.*"]
_CREATED_AT = "2026-06-25T00:00:00Z"
_LAST_UPDATED = "2026-06-28T04:40:00Z"
_VERSION = "1.3"
_DEV_STATUS = "tested"

_REPO_HINT_RE = re.compile(r"((?:/app|/data)/[^\s\"']*/repo)\b", re.IGNORECASE)
_FILE_HINT_RE = re.compile(r"\b([A-Za-z0-9._/\\-]+\.(?:json|md|txt|csv|tsv|js|ts|py|yml|yaml|html|htm|css|xlsx|xlsm|xls))\b", re.IGNORECASE)
_ABS_PATH_RE = re.compile(r"""([A-Za-z]:[\/][^\s"']+\.(?:json|md|txt|csv|tsv|js|ts|py|yml|yaml|xlsx|xlsm|xls)|/(?:app|data|uploads)/[^\s"']+\.(?:json|md|txt|csv|tsv|js|ts|py|yml|yaml|xlsx|xlsm|xls))""", re.IGNORECASE)


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ("request_text", "user_request", "request", "text", "prompt", "query"):
        value = str((params or {}).get(key) or "").strip()
        if value:
            return value
    for key in ("original_request", "user_text"):
        value = str((ctx or {}).get(key) or "").strip()
        if value:
            return value
    return ""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _workspace_root() -> Path:
    return _project_root().parent


def _uploads_dir(ctx: Dict[str, Any]) -> Path:
    app = (ctx or {}).get("app")
    uploads = None
    try:
        uploads = getattr(getattr(app, "state", None), "uploads_dir", None)
    except Exception:
        uploads = None
    if uploads:
        return Path(str(uploads))
    return _project_root() / "data" / "uploads"


def _resolve_repo_root(ctx: Dict[str, Any], request_text: str) -> Path:
    match = _REPO_HINT_RE.search(str(request_text or ""))
    raw = str(match.group(1) or "").strip() if match else "/data/agent_workflow/repo"
    return _map_path_token(ctx, raw)


def _map_path_token(ctx: Dict[str, Any], raw: str) -> Path:
    token = str(raw or "").strip().strip("`\"'")
    token = token.replace('\\', '/')
    project_root = _project_root()
    workspace_root = _workspace_root()
    if token.startswith('/uploads/'):
        return _uploads_dir(ctx) / Path(token).name
    if token.startswith('/data/'):
        return project_root / token.lstrip('/')
    if token.startswith('/app/'):
        return project_root / token.replace('/app/', '', 1)
    lower = token.lower()
    project_anchor = f"/{project_root.name.lower()}/"
    if re.match(r'^[a-z]:/', lower) and project_anchor in lower:
        suffix = token[token.lower().index(project_anchor) + len(project_anchor):]
        return project_root / suffix.replace('\\', '/')
    projects_match = re.search(r'/projects/[^/]+/(.+)$', lower)
    if re.match(r'^[a-z]:/', lower) and projects_match:
        suffix = token[len(token) - len(projects_match.group(1)): ]
        return project_root / suffix.replace('\\', '/')
    workspace_anchor = f"/{workspace_root.name.lower()}/"
    if re.match(r'^[a-z]:/', lower) and workspace_anchor in lower:
        suffix = token[token.lower().index(workspace_anchor) + len(workspace_anchor):]
        return workspace_root / suffix.replace('\\', '/')
    return Path(token)


def _target_hint(request_text: str) -> str:
    match = _ABS_PATH_RE.search(str(request_text or ""))
    if match:
        return str(match.group(1) or "").strip()
    matches = _FILE_HINT_RE.findall(str(request_text or ""))
    return str(matches[-1] or "").strip() if matches else ""


def _find_target(ctx: Dict[str, Any], repo_root: Path, hint: str) -> Path | None:
    if not hint:
        return None
    candidate = _map_path_token(ctx, hint)
    project_root = _project_root().resolve()
    workspace_root = _workspace_root().resolve()
    hint_text = str(hint or '').replace('\\', '/')
    normalized_variants = []
    base_hint = hint_text.lstrip('./')
    for value in (base_hint,):
        if value and value not in normalized_variants:
            normalized_variants.append(value)
    project_name = project_root.name
    if project_name and base_hint.startswith(project_name + '/'):
        trimmed = base_hint[len(project_name) + 1:]
        if trimmed and trimmed not in normalized_variants:
            normalized_variants.append(trimmed)
    workspace_name = workspace_root.name
    if workspace_name and base_hint.startswith(workspace_name + '/'):
        trimmed = base_hint[len(workspace_name) + 1:]
        if trimmed and trimmed not in normalized_variants:
            normalized_variants.append(trimmed)
    if '/' in base_hint:
        first, remainder = base_hint.split('/', 1)
        if first and remainder and first.lower() not in {'app', 'data', 'uploads', 'plugins'} and remainder not in normalized_variants:
            normalized_variants.append(remainder)
    if hint_text.startswith('/data/agent_workflow/repo/') and not candidate.is_file():
        suffix = hint_text.split('/data/agent_workflow/repo/', 1)[1]
        fallback = (project_root / suffix).resolve()
        if fallback.is_file():
            return fallback
    try:
        resolved_candidate = candidate.resolve()
    except Exception:
        resolved_candidate = candidate
    hint_text = str(hint or '')
    is_explicit_path = (':' in hint_text[:3]) or hint_text.startswith('/app/') or hint_text.startswith('/data/') or hint_text.startswith('/uploads/') or ('/' in hint_text) or ('\\' in hint_text)
    for root in (project_root, workspace_root):
        try:
            resolved_candidate.relative_to(root)
            if resolved_candidate.is_file():
                return resolved_candidate
        except Exception:
            pass
    if candidate.is_file():
        return candidate
    normalized_hint = str(hint or '').replace('\\', '/').lstrip('./')
    candidate_hints = normalized_variants if normalized_variants else [normalized_hint]
    if repo_root.exists():
        for candidate_hint in candidate_hints:
            if not candidate_hint or candidate_hint.startswith(('/', 'app/', 'data/', 'uploads/')):
                continue
            direct_repo = repo_root / candidate_hint
            if direct_repo.is_file():
                return direct_repo
            direct_project = project_root / candidate_hint
            if direct_project.is_file():
                return direct_project
            direct_workspace = workspace_root / candidate_hint
            if direct_workspace.is_file():
                return direct_workspace
    if is_explicit_path:
        return None
    file_name = Path(str(hint).replace('\\', '/')).name
    if repo_root.exists():
        direct = repo_root / file_name
        if direct.is_file():
            return direct
        for path in repo_root.rglob(file_name):
            if path.is_file():
                return path
    for root in (project_root, workspace_root):
        try:
            for path in root.rglob(file_name):
                if path.is_file():
                    return path
        except Exception:
            continue
    return None


def _safe_text(path: Path, max_chars: int = 12000) -> str:
    suffix = path.suffix.lower()
    if suffix in {'.xlsx', '.xlsm'}:
        preview = read_repo_file_preview(str(path), max_chars=max_chars)
        return str(preview.get('text') or '')
    try:
        return path.read_text(encoding='utf-8')[:max_chars]
    except UnicodeDecodeError:
        return path.read_text(encoding='utf-8', errors='replace')[:max_chars]


def _json_shape_summary(payload: Any) -> str:
    if isinstance(payload, dict):
        keys = list(payload.keys())
        preview = ', '.join(str(key) for key in keys[:8]) if keys else 'no keys'
        return f"JSON object with {len(keys)} top-level keys: {preview}"
    if isinstance(payload, list):
        first_type = type(payload[0]).__name__ if payload else 'empty'
        return f"JSON array with {len(payload)} items; first item type: {first_type}"
    return f"JSON scalar value of type {type(payload).__name__}"


def _tabular_shape_summary(path: Path, text_preview: str) -> str:
    suffix = path.suffix.lower()
    delimiter = '\t' if suffix == '.tsv' else ','
    lines = [line for line in str(text_preview or '').splitlines() if line.strip()]
    if not lines:
        return ''
    header = [part.strip() for part in lines[0].split(delimiter)]
    if len(header) < 2:
        return ''
    data_rows = max(0, len(lines) - 1)
    preview = ', '.join(col for col in header[:8] if col) or 'no named columns'
    kind = 'TSV table' if suffix == '.tsv' else 'CSV table'
    return f"{kind} with approximately {data_rows} data row(s) and {len(header)} column(s): {preview}"


def _csv_header_fields(text_preview: str) -> List[str]:
    first_line = str(text_preview or '').splitlines()[0].strip() if str(text_preview or '').strip() else ''
    if not first_line or ',' not in first_line:
        return []
    return [part.strip().lower() for part in first_line.split(',') if part.strip()]


def _workbook_header_fields(text_preview: str) -> List[str]:
    for line in str(text_preview or '').splitlines():
        line = str(line or '').strip()
        if not line.startswith('Columns: '):
            continue
        return [part.strip().lower() for part in line.split('Columns: ', 1)[-1].split('|') if part.strip()]
    return []


def _infer_use(path: Path, payload: Any, text_preview: str) -> str:
    low_name = path.name.lower()
    low_text = text_preview.lower()
    suffix = path.suffix.lower()
    csv_fields = set(_csv_header_fields(text_preview))
    workbook_fields = set(_workbook_header_fields(text_preview))
    if low_name == 'manifest.json' and isinstance(payload, dict):
        keys = {str(k).strip().lower() for k in payload.keys()}
        if {'id', 'name', 'kind', 'description', 'entry'} <= keys:
            return 'This appears to be a plugin or workflow manifest that declares the bundle identity, display metadata, type, description, and entry file used to load that component.'
    if low_name == 'plugin.js' and ('plugin_id' in low_text or 'kind:' in low_text or 'description:' in low_text):
        return 'This appears to be a frontend plugin entry file that declares plugin metadata and wires the UI-side behavior, events, or rendering logic for that plugin bundle.'
    if isinstance(payload, dict):
        keys = {str(k).strip().lower() for k in payload.keys()}
        if {'request', 'run_id', 'status', 'tail'} & keys and ('workflow' in low_text or 'role:' in low_text):
            return 'This looks like a workflow execution artifact or test-run record that captures an original request, run status, change flags, and a detailed multi-step execution trace.'
        if {'messages', 'session_id', 'project_id'} & keys:
            return 'This appears to be a chat or session transcript artifact used to store messages and conversation state.'
        if {'charts'} <= keys or ({'charts', 'series'} & keys and {'xvalues', 'x_values'} & keys):
            return 'This appears to be a structured chart payload used to render one or more charts.'
        if {'product', 'version', 'highlights', 'customer_benefits', 'next_steps'} <= keys or 'release_notes' in low_name:
            return 'This appears to be a structured release-notes or product-update artifact with customer-facing highlights, benefits, and follow-up steps.'
        if {'faq', 'questions', 'answers'} <= keys:
            return 'This appears to be a structured FAQ artifact that stores question-and-answer content for end users.'
    if suffix in {'.csv', '.tsv'}:
        if {'ticket_id', 'priority', 'issue', 'customer'} <= csv_fields:
            return 'This appears to be a support-ticket dataset used for triage, prioritization, and customer-response planning.'
        if {'topic', 'question', 'answer'} & csv_fields or 'faq' in low_name:
            return 'This appears to be an FAQ-topic dataset used to turn support or onboarding topics into user-facing FAQ content.'
        if {'department', 'january', 'february'} <= csv_fields:
            return 'This appears to be a monthly comparison spreadsheet used to review department-level budget or operating changes over time.'
        if {'vendor', 'security', 'support', 'cost'} <= csv_fields:
            return 'This appears to be a vendor-comparison matrix used to compare shortlist candidates across operational tradeoffs.'
        if {'ticket_id', 'priority'} & csv_fields:
            return 'This appears to be a tabular operational dataset used for sorting, triage, or reporting.'
    if suffix in {'.xlsx', '.xlsm', '.xls'}:
        if {'order no', 'order date', 'customer name', 'ship date', 'retail price (usd)', 'order quantity', 'tax (usd)', 'total (usd)'} <= workbook_fields:
            return 'This appears to be a sample supermarket sales workbook that tracks orders, dates, customers, shipping dates, prices, quantities, tax, and order totals.'
        if {'ticket id', 'priority', 'issue', 'customer'} <= workbook_fields:
            return 'This appears to be a support-ticket workbook used for triage, prioritization, and customer-response planning.'
        if {'department', 'january', 'february'} <= workbook_fields:
            return 'This appears to be a monthly comparison workbook used to review department-level budget or operating changes over time.'
        if {'vendor', 'security', 'support', 'cost'} <= workbook_fields:
            return 'This appears to be a vendor-comparison workbook used to compare shortlist candidates across operational tradeoffs.'
        if workbook_fields:
            return 'This appears to be a spreadsheet workbook that stores structured tabular business data for reporting or analysis.'
    if low_name in {'readme.md', 'readme.txt'}:
        return 'This appears to be a human-oriented project overview or usage guide.'
    if low_name in {'settings.json', 'config.json'} or low_name.endswith('.config.json') or low_name.endswith('.settings.json'):
        return 'This appears to be a configuration file that defines shared runtime, model, or application settings.'
    if suffix == '.py':
        rel_parts = {part.lower() for part in path.parts}
        if low_name == 'app.py' and 'fastapi' in low_text:
            return 'This appears to be the main backend application entrypoint that defines the FastAPI server, middleware, model-serving routes, and service startup behavior.'
        if low_name == 'repo_file_summary.py':
            return 'This appears to be a helper skill that summarizes what a requested file is likely used for, what kind of data it contains, and where it sits in the repo or workspace.'
        if low_name == 'repo_code_explain.py':
            return 'This appears to be a helper skill that explains what a requested repo file or code symbol does and extracts a relevant code block for the answer.'
        if low_name == 'repo_reference_search.py':
            return 'This appears to be a helper skill that searches the repo for references, implementation locations, or files containing a requested symbol or concept.'
        if low_name == 'repo_path_inspect.py':
            return 'This appears to be a helper skill that lists directory contents, checks whether files exist, and reports path-level repo structure details.'
        if {'plugins', 'ai_routes', 'autoflow'} <= rel_parts and low_name == '__init__.py':
            return 'This appears to be the AutoFlow router implementation that classifies user requests, selects direct built-in workflows or existing flows, and decides when to use live research, repo analysis, market-data handling, or workflow creation.'
        if 'route_id' in low_text and 'autoflow' in low_text and ('selected_flow' in low_text or 'builtin_direct' in low_text):
            return 'This appears to be AutoFlow routing code that scores request intent, picks built-in capability paths, and returns the chosen flow or direct-answer strategy.'
        if 'fastapi' in low_text and ('app = fastapi' in low_text or 'app=fastapi' in low_text or '@app.' in low_text):
            return 'This appears to be a Python application entrypoint or main backend module that wires HTTP routes, middleware, and service startup behavior.'
        if 'apirouter' in low_text or '@r.' in low_text:
            return 'This appears to be a route or controller module that defines HTTP endpoints and request handling logic.'
        if 'model' in low_text and ('load' in low_text or 'loader' in low_text or 'gguf' in low_text):
            return 'This appears to be source code that manages model loading, runtime configuration, or inference behavior.'
        return 'This appears to be a Python source file that implements application logic for the project.'
    if suffix in {'.js', '.ts', '.html', '.htm', '.css'}:
        if suffix in {'.html', '.htm'}:
            if '<canvas' in low_text or 'requestanimationframe' in low_text or 'addEventListener'.lower() in low_text or '<script' in low_text:
                return 'This appears to be a browser-based interactive HTML page that renders UI, game, or app behavior with embedded client-side logic.'
            return 'This appears to be an HTML page used to render a browser UI or static content.'
        if suffix == '.css':
            return 'This appears to be a stylesheet that controls visual presentation and layout in the frontend.'
        if 'react' in low_text or 'useeffect' in low_text or 'export default' in low_text:
            return 'This appears to be frontend source code that implements client-side UI behavior.'
        return 'This appears to be JavaScript or TypeScript source code used by the application.'
    if suffix in {'.yml', '.yaml'}:
        return 'This appears to be a YAML configuration or orchestration file.'
    if suffix in {'.md', '.txt'}:
        return 'This appears to be a human-readable notes, documentation, or plain-text artifact file.'
    if 'request' in low_name and 'chatjs' in low_name:
        return 'This appears to be a saved request-specific workflow or repo-maintenance run artifact related to chat.js work.'
    return 'This appears to be a saved repo or workspace artifact used as structured input, documentation, or execution output.'


def _path_context(target_path: Path, repo_root: Path) -> str:
    try:
        rel = target_path.relative_to(repo_root).as_posix()
        if '/' not in rel:
            return 'Located at the repo root, so it is likely shared project-level code, configuration, or documentation.'
        parent = Path(rel).parent.as_posix()
        return f'Located under `{parent}`, which suggests it is scoped to that area of the repo.'
    except Exception:
        try:
            rel = target_path.relative_to(_project_root()).as_posix()
            if '/' not in rel:
                return 'Located at the project root, so it is likely shared project-level code, configuration, or documentation.'
            parent = Path(rel).parent.as_posix()
            return f'Located under `{parent}`, which suggests it is scoped to that area of the project.'
        except Exception:
            return 'Located in the accessible workspace.'


def _wants_requested_summary(request_text: str) -> bool:
    low = str(request_text or "").lower()
    return any(tok in low for tok in ("summary", "summarize", "summarise", "overview", "customer-ready", "customer ready", "compact"))


def _requested_summary_text(request_text: str, target_path: Path, payload: Any, text_preview: str) -> str:
    if isinstance(payload, dict):
        keys = {str(k).strip().lower() for k in payload.keys()}
        if {'product', 'version', 'highlights', 'next_steps'} <= keys or 'release_notes' in target_path.name.lower():
            product = str(payload.get('product') or 'The product').strip()
            version = str(payload.get('version') or '').strip()
            release_date = str(payload.get('release_date') or '').strip()
            highlights = payload.get('highlights') if isinstance(payload.get('highlights'), list) else []
            next_steps = payload.get('next_steps') if isinstance(payload.get('next_steps'), list) else []
            highlight_text = '; '.join(str(x).strip() for x in highlights[:3] if str(x).strip())
            next_text = '; '.join(str(x).strip() for x in next_steps[:2] if str(x).strip())
            lead = f"{product} {version}".strip() if version else product
            parts = [f"{lead} delivers {highlight_text or 'a new set of customer-facing improvements'}"]
            if release_date:
                parts[0] += f" in the {release_date} release"
            if next_text:
                parts.append(f"Next steps: {next_text}")
            return '. '.join(part.rstrip('. ') for part in parts if part).strip() + '.'
        preview_keys = ', '.join(str(k) for k in list(payload.keys())[:4])
        if preview_keys:
            return f"This file is a structured JSON artifact centered on {preview_keys}."
    if target_path.suffix.lower() in {'.csv', '.tsv'}:
        lines = [line for line in str(text_preview or '').splitlines() if line.strip()]
        if len(lines) >= 2:
            return f"This file is a tabular dataset with columns like {lines[0].strip()}."
    first_line = str(text_preview or '').strip().splitlines()[0][:220] if str(text_preview or '').strip() else ''
    if first_line:
        return f"This file starts with: {first_line}"
    return ''


def _display_path(target_path: Path, repo_root: Path) -> str:
    for root in (repo_root, _project_root(), _workspace_root()):
        try:
            return target_path.relative_to(root).as_posix()
        except Exception:
            continue
    return target_path.as_posix()


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_text = _request_text(ctx or {}, params or {})
    repo_root = _resolve_repo_root(ctx or {}, request_text)
    target_hint = _target_hint(request_text)
    if not target_hint:
        return {'ok': False, 'warnings': ['target_file_name_not_found'], 'text': 'Could not determine the target file path or file name from the request.'}
    target_path = _find_target(ctx or {}, repo_root, target_hint)
    if target_path is None or not target_path.is_file():
        return {
            'ok': False,
            'warnings': ['target_file_not_found'],
            'text': f'Could not find {target_hint} in the accessible workspace or repo context.',
            'data': {'repo_root': str(repo_root), 'target_file': target_hint},
        }
    text_preview = _safe_text(target_path)
    payload = None
    shape_summary = ''
    if target_path.suffix.lower() == '.json':
        try:
            payload = json.loads(text_preview)
            shape_summary = _json_shape_summary(payload)
        except Exception:
            payload = None
    if not shape_summary and target_path.suffix.lower() in {'.csv', '.tsv'}:
        shape_summary = _tabular_shape_summary(target_path, text_preview)
    if not shape_summary and target_path.suffix.lower() in {'.xlsx', '.xlsm', '.xls'}:
        sheet_line = next((line.strip() for line in text_preview.splitlines() if line.startswith('Sheets: ')), '')
        columns_line = next((line.strip() for line in text_preview.splitlines() if line.startswith('Columns: ')), '')
        parts = ['Spreadsheet workbook']
        if sheet_line:
            parts.append(sheet_line)
        if columns_line:
            parts.append(columns_line)
        shape_summary = '; '.join(parts)
    if not shape_summary:
        lines = text_preview.count('\n') + 1 if text_preview else 0
        shape_summary = f'Text-like file with approximately {lines} line(s)'
    likely_use = _infer_use(target_path, payload, text_preview)
    requested_summary = _requested_summary_text(request_text, target_path, payload, text_preview) if _wants_requested_summary(request_text) else ''
    references = _path_context(target_path, repo_root)
    preview_line = text_preview.replace('\ufeff', '').replace('?', '').strip().splitlines()[0][:220] if text_preview.strip() else ''
    rel = _display_path(target_path, repo_root)
    answer = (
        f"**File**: `{rel}`\n\n"
        + (f"**Requested Summary**: {requested_summary}\n\n" if requested_summary else '')
        + f"**Likely Use**: {likely_use}\n\n"
        + f"**Data It Contains**: {shape_summary}.\n"
        + (f"First line preview: `{preview_line}`.\n" if preview_line else '')
        + f"\n**Project Context**: {references}"
    )
    return {
        'ok': True,
        'text': answer,
        'summary': answer,
        'final_answer': answer,
        'data': {
            'repo_root': str(repo_root),
            'target_path': str(target_path),
            'shape_summary': shape_summary,
            'likely_use': likely_use,
        },
        'warnings': [],
    }


TOOL_SPEC = {
    'id': NAME,
    'category': 'custom',
    'label': 'Repo File Summary',
    'description': 'Find a file inside a target repo path or local workspace path, summarize what it contains, and infer its likely purpose, including spreadsheet workbooks.',
    'permissions': PERMISSIONS,
    'metadata': {
        'version': _VERSION,
        'created_at': _CREATED_AT,
        'last_updated': _LAST_UPDATED,
        'dev_status': _DEV_STATUS,
        'required_capabilities': ['repo_editing', 'document_io', 'content_authoring'],
        'output_mode': 'text',
    },
    'params_schema': {
        'type': 'object',
        'properties': {
            'request_text': {'type': 'string'},
            'user_request': {'type': 'string'},
            'request': {'type': 'string'},
            'text': {'type': 'string'},
            'query': {'type': 'string'},
        },
        'additionalProperties': True,
    },
}
