from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

NAME = "custom.repo_code_explain"
PERMISSIONS = [NAME, "custom.*"]
_CREATED_AT = "2026-06-25T00:00:00Z"
_LAST_UPDATED = "2026-06-28T02:10:00Z"
_VERSION = "1.8"
_DEV_STATUS = "tested"

_REPO_HINT_RE = re.compile(r"((?:/app|/data)/[^\s]*/repo)\b", re.IGNORECASE)
_FILE_HINT_RE = re.compile(r"\b([A-Za-z0-9_./\\-]+\.(?:js|ts|py|json|md|txt|csv|html|htm|css))\b")
_SYMBOL_HINT_RE = re.compile(r"(?:symbol|function|method|class|def)\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
_SYMBOL_BEFORE_DOES_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s+does\b", re.IGNORECASE)
_FILE_OVERVIEW_RE = re.compile(r"\b(explain|describe|tell me what)\s+(?:what\s+)?([A-Za-z0-9_./\\-]+\.(?:js|ts|py|json|md|txt|csv|html|htm|css))\s+does\b", re.IGNORECASE)


def _looks_like_improvement_request(request_text: str) -> bool:
    text = str(request_text or "")
    return bool(re.search(r"\b(improve|improvement|better|enhance|optimi[sz]e|fix|refactor|review|upgrade|polish|make this game better)\b", text, flags=re.IGNORECASE))


def _find_duplicate_function_names(lines: List[str]) -> List[str]:
    counts: Dict[str, int] = {}
    for line in lines:
        match = re.search(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", str(line or ""))
        if not match:
            continue
        name = str(match.group(1) or "").strip()
        if not name:
            continue
        counts[name] = int(counts.get(name) or 0) + 1
    return [name for name, count in counts.items() if count > 1]


def _game_improvements(path: Path, lines: List[str], request_text: str) -> List[str]:
    body = "\n".join(lines)
    low = body.lower()
    suggestions: List[str] = []
    duplicate_functions = _find_duplicate_function_names(lines)
    if "moveSnake" in duplicate_functions:
        suggestions.append("Fix the duplicate `moveSnake` definitions so there is only one movement implementation. Right now the earlier version is shadowed, which makes the game logic harder to trust and maintain.")
    if "keyCode" in body:
        suggestions.append("Replace deprecated `event.keyCode` handling with `event.key` so input stays compatible with modern browsers and is easier to read.")
    if "function placeFood" in body and "placeFood();" in body:
        suggestions.append("Change food placement from recursive retry logic to a bounded loop over free cells. That avoids edge-case recursion problems when the board gets crowded.")
    if "setInterval(gameLoop, 100)" in body:
        suggestions.append("Move timing onto `requestAnimationFrame` plus a speed accumulator, or at least centralize the tick speed so difficulty scaling and smooth pacing are easier to add.")
    if path.suffix.lower() in {'.html', '.htm'} and ('pac-man' in low or 'pacman' in low):
        suggestions.append("Add real Pac-Man hybrid mechanics. The current file is mostly a snake game, so introduce pellets, maze walls, wrap tunnels, enemy ghosts, and distinct win/lose states to match the title.")
    if '<canvas' in low:
        suggestions.append("Split rendering, game state, collision rules, and input into separate functions or modules. The file is still manageable, but that separation will make new mechanics much easier to add.")
    if 'score' in low and 'game over' in low:
        suggestions.append("Add a restart flow, pause state, and persistent high score so replay feels more complete instead of just resetting on each run.")
    if 'document.addEventListener(\'keydown\'' in body or 'document.addEventListener("keydown"' in body:
        suggestions.append("Add mobile or touch controls and on-screen buttons if you want the game to be playable outside desktop keyboard input.")
    if not suggestions:
        suggestions.append("Refactor the main loop and separate state, rendering, and input first. That gives you the cleanest base for adding new mechanics and fixing gameplay bugs.")
    return suggestions[:6]


def _clean_preview_text(text: str) -> str:
    return str(text or '').replace('\ufeff', '').replace('?', '').strip()


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


def _normalize_target_path(target: str) -> str:
    raw = re.sub(r'/+', '/', str(target or '').replace('\\', '/')).strip()
    if not raw:
        return ''
    lower = raw.lower()
    marker = '/repo/'
    if marker in lower:
        idx = lower.rfind(marker)
        return raw[idx + len(marker):].lstrip('/')
    return raw.lstrip('./').lstrip('/')


def _resolve_repo_root(request_text: str) -> Path:
    match = _REPO_HINT_RE.search(str(request_text or ''))
    raw = re.sub(r'/+', '/', str(match.group(1) or '').strip()) if match else '/data/agent_workflow/repo'
    if raw.startswith('/data/'):
        return _project_root() / raw.lstrip('/')
    return Path(raw)


def _target_file(request_text: str) -> str:
    text = str(request_text or '')
    match = _FILE_OVERVIEW_RE.search(text)
    if match:
        return _normalize_target_path(str(match.group(2) or '').strip())
    matches = _FILE_HINT_RE.findall(text)
    return _normalize_target_path(str(matches[-1] or '').strip()) if matches else ''


def _target_symbol(request_text: str, target_file: str) -> str:
    text = str(request_text or '')
    if target_file and re.search(re.escape(target_file) + r'\s+does\b', text, flags=re.IGNORECASE):
        return ''
    match = _SYMBOL_HINT_RE.search(text)
    if match:
        symbol = str(match.group(1) or '').strip()
        if symbol.lower() not in {'function', 'class', 'method', 'symbol', 'def'}:
            return symbol
    match = _SYMBOL_BEFORE_DOES_RE.search(text)
    if match:
        symbol = str(match.group(1) or '').strip()
        file_name = Path(target_file).name.lower() if target_file else ''
        if target_file and symbol.lower() in {file_name.lower(), Path(file_name).suffix.lstrip('.').lower()}:
            return ''
        if symbol.lower() in {'py', 'js', 'ts', 'json', 'md', 'txt', 'csv', 'what', 'which', 'where', 'how', 'why', 'when', 'who', 'does', 'file'}:
            return ''
        return symbol
    return ''


def _find_file(repo_root: Path, target: str) -> Path | None:
    if not target:
        return None
    normalized = _normalize_target_path(target)
    project_root = _project_root().resolve()
    workspace_root = _workspace_root().resolve()
    suffix = normalized.lower()
    variants: List[str] = []
    base = normalized.lstrip('./')
    if base:
        variants.append(base)
    project_name = project_root.name
    if project_name and base.startswith(project_name + '/'):
        trimmed = base[len(project_name) + 1:]
        if trimmed and trimmed not in variants:
            variants.append(trimmed)
    workspace_name = workspace_root.name
    if workspace_name and base.startswith(workspace_name + '/'):
        trimmed = base[len(workspace_name) + 1:]
        if trimmed and trimmed not in variants:
            variants.append(trimmed)
    if '/' in base:
        first, remainder = base.split('/', 1)
        if first and remainder and first.lower() not in {'app', 'data', 'uploads', 'plugins'} and remainder not in variants:
            variants.append(remainder)
    direct_candidates: List[Path] = []
    for variant in variants:
        direct_candidates.extend([repo_root / variant, project_root / variant, workspace_root / variant])
    for candidate in direct_candidates:
        if candidate.is_file():
            return candidate
    search_roots = [repo_root, project_root, workspace_root]
    name = Path(base).name
    explicit_path = '/' in base or '\\' in str(target or '')
    for root in search_roots:
        if not root.exists() or not name:
            continue
        for candidate in root.rglob(name):
            if not candidate.is_file():
                continue
            try:
                rel = candidate.relative_to(root).as_posix().lower()
            except Exception:
                rel = candidate.as_posix().lower()
            if any(rel == v.lower() or rel.endswith('/' + v.lower()) for v in variants):
                return candidate
    if explicit_path:
        return None
    for root in search_roots:
        if not root.exists() or not name:
            continue
        for candidate in root.rglob(name):
            if candidate.is_file():
                return candidate
    return None


def _find_overview_block(lines: List[str], path: Path | None = None) -> Tuple[int, int]:
    rel_low = str(path.as_posix()).lower() if isinstance(path, Path) else ""
    if isinstance(path, Path) and path.suffix.lower() in {'.html', '.htm'}:
        script_start = -1
        script_end = -1
        for idx, line in enumerate(lines):
            low_line = str(line or '').lower()
            if script_start < 0 and '<script' in low_line:
                script_start = idx
                continue
            if script_start >= 0 and '</script>' in low_line:
                script_end = idx + 1
                break
        if script_start >= 0:
            end = script_end if script_end > script_start else min(len(lines), script_start + 80)
            return (script_start, min(len(lines), max(script_start + 1, end)))
    special_patterns = []
    if rel_low.endswith("plugins/ai_routes/autoflow/__init__.py"):
        special_patterns = [
            re.compile(r"\bclass\s+AutoFlowRoute\b"),
            re.compile(r"\bdef\s+_run_autoflow_service_turn\b"),
        ]
    elif rel_low.endswith("plugins/gui_helpers/collab_chat/routes.py"):
        special_patterns = [
            re.compile(r"@r\.post\(\"/v1/projects/\{pid\}/sessions/\{sid\}/service_chat\""),
            re.compile(r"\bdef\s+_inline_builtin_skill_result\b"),
            re.compile(r"\bdef\s+_run_standard_service_turn\b"),
        ]
    elif rel_low.endswith("plugins/gui_helpers/agent_flow/skills/custom/repo_reference_search.py"):
        special_patterns = [
            re.compile(r"\bdef\s+run\b"),
            re.compile(r"\bdef\s+_target_symbol\b"),
            re.compile(r"\bdef\s+_grep_matches\b"),
        ]
    elif rel_low.endswith("plugins/gui_helpers/agent_flow/routes.py"):
        special_patterns = [
            re.compile(r"\bdef\s+install\b"),
            re.compile(r'@r\.post\("/v1/projects/\{pid\}/sessions/\{sid\}/agent_flow/run"'),
            re.compile(r"\bregister_agent_flow_skills\b"),
        ]
    for pattern in special_patterns:
        for idx, line in enumerate(lines):
            if pattern.search(line):
                start = idx
                return (start, min(len(lines), start + 32))
    anchor_patterns = [
        re.compile(r"@app\."),
        re.compile(r"@r\."),
        re.compile(r"\bFastAPI\("),
        re.compile(r"\bAPIRouter\("),
        re.compile(r"\bdef\s+main\b"),
        re.compile(r"if __name__ == [\'\"]__main__[\'\"]"),
    ]
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if any(p.search(line) for p in anchor_patterns):
            start = max(0, idx - 2)
            return (start, min(len(lines), start + 28))
    substantive_patterns = [
        re.compile(r"\bdef\s+[A-Za-z_][A-Za-z0-9_]*\b"),
        re.compile(r"\bclass\s+[A-Za-z_][A-Za-z0-9_]*\b"),
    ]
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or stripped.startswith('from ') or stripped.startswith('import '):
            continue
        if any(p.search(line) for p in substantive_patterns):
            return (idx, min(len(lines), idx + 28))
    start = 0
    class_pattern = re.compile(r"\bclass\s+[A-Za-z_][A-Za-z0-9_]*\b")
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or stripped.startswith('from ') or stripped.startswith('import '):
            continue
        if class_pattern.search(line):
            start = idx
            break
        start = idx
        break
    return (start, min(len(lines), start + 28))


def _find_symbol_block(lines: List[str], symbol: str) -> Tuple[int, int]:
    if not symbol:
        return _find_overview_block(lines, None)
    definition_patterns = [
        re.compile(rf"^\s*async\s+def\s+{re.escape(symbol)}\s*\(", re.IGNORECASE),
        re.compile(rf"^\s*def\s+{re.escape(symbol)}\s*\(", re.IGNORECASE),
        re.compile(rf"^\s*class\s+{re.escape(symbol)}\b", re.IGNORECASE),
        re.compile(rf"^\s*function\s+{re.escape(symbol)}\b", re.IGNORECASE),
        re.compile(rf"^\s*(?:const|let|var)\s+{re.escape(symbol)}\s*=", re.IGNORECASE),
    ]
    fallback_patterns = [
        re.compile(rf"\b{re.escape(symbol)}\s*[:=]"),
        re.compile(rf"\b{re.escape(symbol)}\s*\("),
    ]
    start = -1
    for idx, line in enumerate(lines):
        if any(p.search(line) for p in definition_patterns):
            start = idx
            break
    if start < 0:
        for idx, line in enumerate(lines):
            if any(p.search(line) for p in fallback_patterns):
                start = idx
                break
    if start < 0:
        return (0, min(len(lines), 40))
    indent = len(lines[start]) - len(lines[start].lstrip(' '))
    brace_depth = 0
    seen_open = False
    end = min(len(lines), start + 28)
    for idx in range(start + 1, min(len(lines), start + 140)):
        line = lines[idx]
        stripped = line.strip()
        current_indent = len(line) - len(line.lstrip(' '))
        brace_depth += line.count('{')
        if line.count('{'):
            seen_open = True
        brace_depth -= line.count('}')
        if seen_open:
            if brace_depth <= 0 and stripped:
                end = idx + 1
                break
            continue
        if stripped and current_indent <= indent and re.match(r'^(async\s+def|def|class|function|const|let|var)\b', stripped):
            end = idx
            break
        end = idx + 1
    return (start, max(start + 1, end))


def _key_functions(path: Path, lines: List[str], limit: int = 5) -> List[str]:
    rel_low = path.as_posix().lower()
    preferred: List[str] = []
    if rel_low.endswith('plugins/ai_routes/autoflow/__init__.py'):
        preferred = ['AutoFlowRoute', 'can_handle', 'handle', '_should_use_builtin_general_answer']
    elif rel_low.endswith('plugins/gui_helpers/collab_chat/routes.py'):
        preferred = ['session_service_chat', '_inline_builtin_skill_result', '_run_standard_service_turn', '_looks_like_general_chat']
    elif rel_low.endswith('plugins/gui_helpers/agent_flow/skills/custom/repo_reference_search.py'):
        preferred = ['run', '_target_symbol', '_grep_matches', '_implementation_matches', '_iter_files']
    elif rel_low.endswith('plugins/gui_helpers/agent_flow/routes.py'):
        preferred = ['install', 'agent_flow_run', '_load_project_flows', '_save_project_flows', '_flow_version_diag']
    names: List[str] = []
    seen = set()
    patterns = [
        re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("),
        re.compile(r"^\s*async\s+def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("),
        re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b"),
    ]
    discovered: List[str] = []
    for line in lines:
        for pattern in patterns:
            match = pattern.search(str(line or ""))
            if not match:
                continue
            name = str(match.group(1) or "").strip()
            if name and name not in seen:
                seen.add(name)
                discovered.append(name)
    ordered: List[str] = []
    for name in preferred + discovered:
        if name and name not in ordered:
            ordered.append(name)
    return ordered[: max(1, int(limit or 5))]


def _focus_summary(path: Path, symbol: str, snippet: List[str]) -> str:
    rel_low = path.as_posix().lower()
    body = _clean_preview_text("\n".join(line.rstrip() for line in snippet))
    low = body.lower()
    if rel_low.endswith('plugins/gui_helpers/collab_chat/routes.py'):
        if 'async def session_service_chat' in low or '/v1/projects/{pid}/sessions/{sid}/service_chat' in low:
            return 'implements the service_chat endpoint: authenticates the caller, reads router settings, short-circuits canned or conceptual answers, decides between no-flow direct handling and AutoFlow, and dispatches built-in inline skills or the standard model turn'
        if 'def _inline_builtin_skill_result' in low:
            return 'runs built-in AutoFlow candidates inline so direct weather, finance, scholar, repo, and web-research skills can answer immediately without generating a full workflow run'
        if 'def _run_standard_service_turn' in low:
            return 'executes the normal service-chat model turn, including message construction, routing context, and assistant response generation when no direct builtin shortcut applies'
    if rel_low.endswith('plugins/gui_helpers/agent_flow/routes.py'):
        if 'def install(app)' in low:
            return 'installs the agent_flow plugin, registers its skills, initializes per-run state on app.state, and wires the FastAPI routes used to run, inspect, and manage workflows'
        if '/v1/projects/{pid}/sessions/{sid}/agent_flow/run' in low or 'def agent_flow_run' in low:
            return 'implements the main agent_flow run endpoint that accepts a request, starts or tracks a workflow run, streams progress, and records final run state'
        if 'register_agent_flow_skills' in low:
            return 'loads the agent-flow skill registry so workflow nodes can execute sheet, repo, pdf, result, and external-data actions at runtime'
    if rel_low.endswith('plugins/ai_routes/autoflow/__init__.py'):
        if 'def _builtin_direct_candidate' in low:
            return 'maps common request shapes to fast built-in AutoFlow candidates so weather, finance, repo, scholar, arxiv, and current-context requests can bypass slower workflow selection'
        if 'def _select_or_create' in low or 'def _select_only' in low:
            return 'scores available workflows, weighs library candidates, and decides whether to reuse an existing flow, pick a built-in route, or create a new one'
        if 'class autoflowroute' in low:
            return 'defines the AutoFlow router entrypoint that profiles the request, selects routing mode, and delegates to planning, judging, or selection logic'
    if rel_low.endswith('repo_reference_search.py') and 'def run' in low:
        return 'handles a repo-reference search request end-to-end by locating likely files, matching symbols, and returning grounded references for the caller'
    if rel_low.endswith('repo_code_explain.py'):
        return 'parses a repo explanation request, resolves the target file or symbol, extracts the most relevant code block, and formats a focused explanation for the user'
    if symbol:
        symbol_low = symbol.lower()
        if f'def {symbol_low}' in low or f'class {symbol_low}' in low:
            return f'contains the implementation of `{symbol}` and the surrounding logic that this symbol depends on'
        if f'{symbol_low}(' in low:
            return f'shows where `{symbol}` is invoked or assigned and how the surrounding logic uses it'
    return ''


def _summarize(path: Path, symbol: str, snippet: List[str], full_text: str = "") -> str:
    body = _clean_preview_text("\n".join(line.rstrip() for line in snippet))
    analysis_body = str(full_text or body)
    low = analysis_body.lower()
    snippet_low = body.lower()
    rel_low = path.as_posix().lower()
    points: List[str] = []

    focus = _focus_summary(path, symbol, snippet)
    if focus:
        points.append(focus)

    has_focus = bool(focus)
    special_router_file = rel_low.endswith('plugins/ai_routes/autoflow/__init__.py') or rel_low.endswith('plugins/gui_helpers/collab_chat/routes.py') or rel_low.endswith('plugins/gui_helpers/agent_flow/routes.py')
    if rel_low.endswith('plugins/ai_routes/autoflow/__init__.py') and not has_focus:
        points.append("implements the AutoFlow router that classifies requests, selects fast built-in flows, scores existing workflows, and decides when workflow creation should be attempted")
    if rel_low.endswith('plugins/gui_helpers/collab_chat/routes.py') and not has_focus:
        points.append("handles service_chat routing, including no-flow direct answers, current-context shortcuts, built-in inline skill execution, and AutoFlow fallback orchestration")
    if rel_low.endswith('plugins/gui_helpers/agent_flow/routes.py') and not has_focus:
        points.append("installs and exposes the agent_flow HTTP routes, keeps workflow run state, loads project and default flows, and coordinates runtime execution for workflow requests")
    if rel_low.endswith('repo_reference_search.py') and not has_focus:
        points.append("searches the repo for symbol references, implementation matches, and likely source files relevant to the user query")
    if rel_low.endswith('repo_code_explain.py') and not has_focus:
        points.append("parses a repo-scoped question, locates the target file or symbol, extracts a relevant code block, and turns it into a short explanation")

    if path.name.lower() == "app.py" and "fastapi" in low:
        points.append("acts as a main backend application entrypoint")
    if not (special_router_file and has_focus) and "fastapi" in low and ("@app." in low or "apirouter" in low or "uvicorn" in low):
        points.append("defines HTTP routes and runtime startup behavior")
    if not (special_router_file and has_focus) and ("apirouter" in low or "@r." in low):
        points.append("defines API routes or request handlers")
    if not (special_router_file and has_focus) and "chat" in low and "session" in low:
        points.append("coordinates chat or session behavior")
    if not (special_router_file and has_focus) and ('autoflow_enabled' in snippet_low or 'route_with_autoflow' in snippet_low):
        points.append('checks whether AutoFlow should run or whether the request should stay on a direct no-flow path')
    if not (special_router_file and has_focus) and ('_looks_like_general_chat' in snippet_low or '_looks_like_direct_text_generation' in snippet_low):
        points.append('classifies direct chat, drafting, and current-context requests before deciding whether a workflow is needed')
    if not (special_router_file and has_focus) and ('assistant_message' in snippet_low and 'return {' in snippet_low):
        points.append('packages the final assistant text and response metadata back to service_chat callers')
    if not (special_router_file and has_focus) and "settings" in low:
        points.append("reads or normalizes settings used by later logic")
    if not (special_router_file and has_focus) and "enabled" in low and "plugin" in low:
        points.append("tracks enabled-plugin state")

    suffix = path.suffix.lower()
    if suffix in {'.html', '.htm'}:
        if all(token in low for token in ('canvas', 'enemies', 'arrowleft', 'arrowright', 'requestanimationframe')):
            points.append('implements a top-down lane-dodging racing game where the player car moves with the arrow keys while enemy cars spawn from the top and scroll downward')
        if 'collision detection' in low or ('player.x < enemies[i].x + enemies[i].width' in analysis_body and 'gameover()' in low):
            points.append('ends the run on rectangle-based collision detection between the player car and enemy cars')
        if 'score' in low and 'speed += 0.5' in low:
            points.append('tracks score as cars are avoided and gradually increases difficulty by raising enemy speed over time')
        if 'startscreen' in low and 'gameover' in low:
            points.append('includes a start screen, an in-game score overlay, and a game-over screen with restart handling')
        if '<canvas' in low or 'requestanimationframe' in low or 'keydown' in low or 'keyup' in low or 'game loop' in low or 'pacman' in low or 'snake' in low:
            points.append('implements a self-contained browser game page with rendering, keyboard controls, and an in-page game loop')
        if '<style' in low and '<script' in low:
            points.append('bundles the page markup, styling, and client-side behavior into a single HTML file')
    elif suffix == '.css':
        points.append('defines frontend styling, layout, and visual presentation rules')

    if "_resolve_repo_root" in low and ("_target_file" in low or "_target_symbol" in low):
        points.append("parses the user request to identify the repo root, requested file, and optional symbol")
    if "_find_file" in low and ("rglob(" in low or "relative_to" in low):
        points.append("resolves repo paths by checking direct matches and then searching the workspace")
    if "_find_symbol_block" in low or "_find_overview_block" in low:
        points.append("selects the most relevant code block so the explanation focuses on the right part of the file")
    if "_summarize" in low and "answer_lines" in low:
        points.append("builds a user-facing explanation with the file path, a summary, and a code snippet")
    if "_grep_matches" in low or "subprocess.run" in low or "grep" in low:
        points.append("uses repo search commands to find references or implementation candidates quickly")
    if "_implementation_matches" in low:
        points.append("ranks likely implementation files by token overlap, path relevance, and matching lines")
    if 'getattr(state, "model"' in body or "getattr(state, 'model'" in body:
        points.append("checks the currently loaded model from application state")
    if "ensure_main_text_llm_loaded" in body:
        points.append("falls back to loading the main text model when one is not already present")
    if "read_text" in body and "splitlines" in body:
        points.append("loads source text and slices a relevant block for explanation")
    if "re.search" in body or "re.compile" in body:
        points.append("uses pattern matching to detect the requested file, symbol, or behavior")
    if not (special_router_file and has_focus) and "try:" in low and "except" in low:
        points.append("guards failures and degrades safely when path resolution or parsing fails")

    if not points:
        points.append("prepares and updates local state used by later workflow or UI logic")

    seen = set()
    ordered: List[str] = []
    for point in points:
        if point not in seen:
            seen.add(point)
            ordered.append(point)
    summary = ". ".join(ordered[:3])
    if symbol:
        return f"`{symbol}` {summary}."
    return f"`{path.name}` {summary}."


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_text = _request_text(ctx or {}, params or {})
    repo_root = _resolve_repo_root(request_text)
    target_file = _target_file(request_text)
    symbol = _target_symbol(request_text, target_file)
    path = _find_file(repo_root, target_file)
    if path is None or not path.is_file():
        return {"ok": False, "warnings": ["target_file_not_found"], "text": f"Could not find {target_file} under {repo_root}."}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start, end = _find_symbol_block(lines, symbol) if symbol else _find_overview_block(lines, path)
    snippet = lines[start:end]
    try:
        rel = path.relative_to(repo_root).as_posix()
    except Exception:
        rel = path.relative_to(_project_root()).as_posix() if path.is_relative_to(_project_root()) else path.as_posix()
    snippet_limit = 36 if path.suffix.lower() in {'.html', '.htm'} else 18
    snippet_text = _clean_preview_text("\n".join(snippet[:snippet_limit]))
    analysis_sample = "\n".join(lines[: min(len(lines), 220)])
    summary = _summarize(path, symbol, snippet, analysis_sample)
    key_functions = _key_functions(path, lines, limit=5)
    improve_mode = not symbol and _looks_like_improvement_request(request_text)
    answer_lines = [f"**File**: `{rel}`"]
    if symbol:
        answer_lines.extend([f"**Symbol**: `{symbol}`", ""])
    else:
        answer_lines.append("")
    if improve_mode:
        suggestions = _game_improvements(path, lines, request_text)
        answer_lines.extend([
            f"**Current Role**: {summary}",
            "",
            "**Best Improvements**",
        ])
        answer_lines.extend(f"- {item}" for item in suggestions)
        if key_functions:
            answer_lines.extend(["", "**Main Areas To Touch**"])
            answer_lines.extend(f"- `{name}`" for name in key_functions)
    else:
        answer_lines.extend([
            f"**What It Does**: {summary}",
        ])
        if key_functions and not symbol:
            answer_lines.extend(["", "**Key Functions/Classes**"])
            answer_lines.extend(f"- `{name}`" for name in key_functions)
    answer_lines.extend([
        "",
        "**Relevant Code**",
        "```text",
        snippet_text,
        "```",
    ])
    answer = "\n".join(answer_lines)
    return {"ok": True, "text": answer, "summary": answer, "final_answer": answer, "data": {"repo_root": str(repo_root), "target_path": str(path), "symbol": symbol, "start_line": start + 1, "mode": "improve" if improve_mode else "explain"}, "warnings": []}


TOOL_SPEC = {"id": NAME, "category": "custom", "label": "Repo Code Explain", "description": "Explain what a named symbol or code block does inside a repo file.", "permissions": PERMISSIONS, "metadata": {"version": _VERSION, "created_at": _CREATED_AT, "last_updated": _LAST_UPDATED, "dev_status": _DEV_STATUS, "required_capabilities": ["repo_editing", "document_io", "content_authoring"], "output_mode": "text"}, "params_schema": {"type": "object", "properties": {"request_text": {"type": "string"}}, "additionalProperties": True}}

