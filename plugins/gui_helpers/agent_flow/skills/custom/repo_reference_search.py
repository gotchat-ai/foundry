from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple

NAME = "custom.repo_reference_search"
PERMISSIONS = [NAME, "custom.*"]
_CREATED_AT = "2026-06-25T00:00:00Z"
_LAST_UPDATED = "2026-06-25T18:55:00Z"
_VERSION = "1.1"
_DEV_STATUS = "tested"

_REPO_HINT_RE = re.compile(r"((?:/app|/data)/[^\s]*/repo)\b", re.IGNORECASE)
_FILE_HINT_RE = re.compile(r"\b([A-Za-z0-9_./-]+\.(?:js|ts|py|json|md|txt|csv))\b")
_SYMBOL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")
_STOP = {"look","at","the","repo","in","and","tell","me","where","is","used","which","files","file","contains","reference","references","referenced","what","does","implemented","implementation","defined","located","live","reside","find","summarize","summary","most","relevant"}
_SKIP_DIRS = {".git", ".rag", "node_modules", "__pycache__", "obj", "bin", "dist", "build", "chatjs_flow_tests", "rag_git_flow_tests", "generated"}
_MAX_BYTES = 512 * 1024


def _looks_like_literal_only_match(snippet: str, symbol: str) -> bool:
    line = str(snippet or '').strip()
    sym = str(symbol or '').strip()
    if not line or not sym:
        return False
    quoted = [f'"{sym}"', f"'{sym}'", f'`{sym}`']
    if any(token in line for token in quoted):
        code_signals = ('def ', 'class ', 'function ', 'const ', 'let ', 'var ', 'getattr(', 'setattr(', sym + '(', sym + ' =', sym + ':')
        if not any(signal in line for signal in code_signals):
            return True
    return False


def _preferred_roots(repo_root: Path) -> List[Path]:
    out: List[Path] = []
    seen = set()
    for base in _search_roots(repo_root):
        roots = [
            base / "agent_flow",
            base / "chatjs",
            base / "plugin",
            base / "plugins",
        ]
        for root in roots:
            key = root.as_posix().lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(root)
    return out


def _grep_matches(repo_root: Path, query: str, limit: int = 8) -> List[Tuple[str, str]]:
    if not query or not shutil.which("grep"):
        return []
    roots = [str(root) for root in _preferred_roots(repo_root) if root.exists()]
    if not roots:
        roots = [str(root) for root in _search_roots(repo_root) if root.exists()]
    cmd = [
        "grep", "-R", "-n", "-m", "1",
        "--include=*.js", "--include=*.ts", "--include=*.py", "--include=*.json", "--include=*.md", "--include=*.txt", "--include=*.csv",
        "--exclude-dir=chatjs_flow_tests", "--exclude-dir=rag_git_flow_tests", "--exclude-dir=generated",
        "--exclude-dir=node_modules", "--exclude-dir=dist", "--exclude-dir=build", "--exclude-dir=.git", "--exclude-dir=__pycache__",
        query,
        *roots,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
    except Exception:
        return []
    output = str(proc.stdout or "")
    if not output.strip():
        return []
    primary: List[Tuple[str, str]] = []
    secondary: List[Tuple[str, str]] = []
    seen = set()
    for line in output.splitlines():
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        raw_path, _lineno, snippet = parts
        rel = _display_rel(Path(raw_path), repo_root)
        if rel in seen:
            continue
        seen.add(rel)
        item = (rel, snippet.strip()[:220])
        if _looks_like_literal_only_match(item[1], query):
            secondary.append(item)
        else:
            primary.append(item)
        if len(primary) >= limit:
            break
    matches = (primary + secondary)[:limit]
    return matches


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
    raw = str(target or '').replace('\\', '/').strip()
    if not raw:
        return ''
    lower = raw.lower()
    marker = '/repo/'
    if marker in lower:
        idx = lower.rfind(marker)
        return raw[idx + len(marker):].lstrip('/')
    return raw.lstrip('./').lstrip('/')


def _search_roots(repo_root: Path) -> List[Path]:
    roots = [repo_root, _project_root()]
    out: List[Path] = []
    seen = set()
    for root in roots:
        key = root.as_posix().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(root)
    return out


def _resolve_repo_root(request_text: str) -> Path:
    match = _REPO_HINT_RE.search(str(request_text or ""))
    raw = str(match.group(1) or "").strip() if match else "/data/agent_workflow/repo"
    if raw.startswith('/data/'):
        return _project_root() / raw.lstrip('/')
    return Path(raw)


def _target_file(request_text: str) -> str:
    matches = _FILE_HINT_RE.findall(str(request_text or ""))
    return _normalize_target_path(str(matches[-1] or "").strip()) if matches else ""


def _find_file(repo_root: Path, target: str) -> Path | None:
    if not target:
        return None
    normalized = _normalize_target_path(target)
    project_root = _project_root().resolve()
    workspace_root = _workspace_root().resolve()
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


def _target_symbol(request_text: str, target_file: str) -> str:
    text = str(request_text or "")
    patterns = (
        r"where\s+([A-Za-z_][A-Za-z0-9_]*)\s+is\s+used",
        r"where\s+is\s+([A-Za-z_][A-Za-z0-9_]*)\s+referenced",
        r"find\s+where\s+([A-Za-z_][A-Za-z0-9_]*)\s+is\s+referenced",
        r"find\s+where\s+([A-Za-z_][A-Za-z0-9_]*)\s+is\s+used",
        r"find\s+where\s+([A-Za-z_][A-Za-z0-9_]*)\s+appears",
        r"find\s+where\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        r"references?\s+to\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"uses\s+of\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"which\s+file\s+contains\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"contains\s+([A-Za-z_][A-Za-z0-9_]*)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return str(match.group(1) or "").strip()
    candidates = []
    for tok in _SYMBOL_RE.findall(text):
        low = tok.lower()
        if low in _STOP:
            continue
        if target_file and tok in target_file:
            continue
        if tok.lower().endswith(('.js','.ts','.py','.json','.md','.txt','.csv')):
            continue
        candidates.append(tok)
    return candidates[0] if candidates else ""


def _implementation_phrase(request_text: str) -> str:
    text = str(request_text or "")
    patterns = (
        r"where\s+is\s+(?:the\s+)?(.+?)\s+implemented\b",
        r"where\s+is\s+(?:the\s+)?(.+?)\s+defined\b",
        r"where\s+is\s+(?:the\s+)?(.+?)\s+located\b",
        r"where\s+does\s+(?:the\s+)?(.+?)\s+(?:live|reside)\b",
        r"which\s+(?:file|module)\s+implements\s+(?:the\s+)?(.+?)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        phrase = str(match.group(1) or "").strip()
        phrase = re.sub(r"\s+in\s+/(?:app|data)/.*$", "", phrase, flags=re.IGNORECASE).strip()
        phrase = phrase.strip("`\"'").strip()
        phrase = re.sub(r"[?.!,;:]+$", "", phrase).strip()
        phrase = re.sub(r"\s+", " ", phrase)
        if phrase:
            return phrase
    return ""


def _token_variants(token: str) -> List[str]:
    low = str(token or "").strip().lower()
    if not low:
        return []
    out = [low]
    if low == 'router':
        out.extend(['route', 'routes'])
    elif low == 'route':
        out.extend(['router', 'routes'])
    elif low.endswith('ies') and len(low) > 4:
        out.append(low[:-3] + 'y')
    elif low.endswith('s') and len(low) > 3:
        out.append(low[:-1])
    elif len(low) > 3:
        out.append(low + 's')
    seen = set()
    ordered: List[str] = []
    for item in out:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _phrase_tokens(text: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for tok in _SYMBOL_RE.findall(str(text or "")):
        low = tok.lower()
        if low in _STOP or len(low) <= 1:
            continue
        if low not in seen:
            seen.add(low)
            out.append(low)
    return out


def _implementation_matches(repo_root: Path, phrase: str, limit: int = 6) -> List[Tuple[str, str]]:
    tokens = _phrase_tokens(phrase)
    if not tokens:
        return []
    scored: List[Tuple[float, str, str]] = []
    for path in _iter_preferred_files(repo_root):
        rel = _display_rel(path, repo_root)
        rel_low = rel.lower()
        if (
            rel_low.endswith('/result.json')
            or rel_low.startswith('tmp_')
            or '/autoflow_mixed_tests/' in ('/' + rel_low)
            or '/autoflow_sequential_tests/' in ('/' + rel_low)
            or '/data/workflow_training/examples/' in ('/' + rel_low)
        ):
            continue
        text = _read_text(path)
        text_low = text.lower()
        score = 0.0
        token_hits = 0
        path_hits = 0
        snippet = ""
        line_bonus = 0.0
        best_line_score = -1.0
        for token in tokens:
            variants = _token_variants(token)
            if any(var in rel_low for var in variants):
                path_hits += 1
                score += 4.0
            if any(var in text_low for var in variants):
                token_hits += 1
                score += 1.5
        if token_hits == 0 and path_hits == 0:
            continue
        for line in text.splitlines():
            ll = line.lower()
            hit_count = 0
            for token in tokens:
                if any(var in ll for var in _token_variants(token)):
                    hit_count += 1
            if hit_count <= 0:
                continue
            current_line_score = float(hit_count)
            if re.search(r"\b(class|def|function|const|let|var|apirouter|baseroute|route_id)\b", ll):
                current_line_score += 1.5
            if current_line_score > best_line_score:
                best_line_score = current_line_score
                snippet = line.strip()[:220]
            if hit_count == len(tokens):
                line_bonus = max(line_bonus, 4.0)
            elif hit_count >= 2:
                line_bonus = max(line_bonus, 2.5)
            elif hit_count == 1:
                line_bonus = max(line_bonus, 1.0)
        score += line_bonus
        if token_hits == len(tokens):
            score += 2.0
        if path_hits == len(tokens):
            score += 3.0
        if path.suffix.lower() in {'.py', '.js', '.ts'}:
            score += 0.5
        if '/plugins/' in ('/' + rel_low):
            score += 0.5
        scored.append((score, rel, snippet))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(rel, snippet) for _score, rel, snippet in scored[:limit]]


def _iter_files(repo_root: Path):
    seen: set[str] = set()

    def _yield_from(root: Path):
        if not root.exists():
            return
        for path in root.rglob('*'):
            if not path.is_file():
                continue
            if any(part in _SKIP_DIRS or part.startswith('.rag') for part in path.parts):
                continue
            if path.suffix.lower() not in {'.js','.ts','.py','.json','.md','.txt','.csv'}:
                continue
            try:
                if path.stat().st_size > _MAX_BYTES:
                    continue
            except Exception:
                continue
            norm = path.as_posix()
            if norm in seen:
                continue
            seen.add(norm)
            yield path

    for root in _preferred_roots(repo_root):
        for path in _yield_from(root):
            yield path
    for root in _search_roots(repo_root):
        for path in _yield_from(root):
            yield path


def _iter_preferred_files(repo_root: Path):
    seen: set[str] = set()
    for root in _preferred_roots(repo_root):
        if not root.exists():
            continue
        for path in root.rglob('*'):
            if not path.is_file():
                continue
            if any(part in _SKIP_DIRS or part.startswith('.rag') for part in path.parts):
                continue
            if path.suffix.lower() not in {'.js','.ts','.py','.json','.md','.txt','.csv'}:
                continue
            try:
                if path.stat().st_size > _MAX_BYTES:
                    continue
            except Exception:
                continue
            norm = path.as_posix()
            if norm in seen:
                continue
            seen.add(norm)
            yield path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        return path.read_text(encoding='utf-8', errors='replace')


def _file_symbol_matches(path: Path, symbol: str, limit: int = 8) -> List[Tuple[int, str]]:
    if not isinstance(path, Path) or not path.is_file() or not str(symbol or '').strip():
        return []
    text = _read_text(path)
    pattern = re.compile(rf"\b{re.escape(str(symbol or '').strip())}\b")
    matches: List[Tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if pattern.search(line):
            matches.append((lineno, line.strip()[:220]))
            if len(matches) >= max(1, int(limit or 8)):
                break
    return matches


def _display_rel(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except Exception:
        try:
            return path.relative_to(_project_root()).as_posix()
        except Exception:
            return path.as_posix()


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_text = _request_text(ctx or {}, params or {})
    repo_root = _resolve_repo_root(request_text)
    target_file = _target_file(request_text)
    target_symbol = _target_symbol(request_text, target_file)
    file_scope_path = _find_file(repo_root, target_file) if target_file else None
    implementation_phrase = _implementation_phrase(request_text)
    if implementation_phrase:
        matches = _implementation_matches(repo_root, implementation_phrase, limit=6)
        body = [f"**Concept**: `{implementation_phrase}`", "", "**Most Likely Implementation Files**"]
        if matches:
            for rel, snippet in matches:
                body.append(f"- `{rel}`")
                if snippet:
                    body.append(f"  Snippet: `{snippet}`")
        else:
            body.append("- No likely implementation files found.")
        answer = "\n".join(body)
        return {
            "ok": True,
            "text": answer,
            "summary": answer,
            "final_answer": answer,
            "data": {"repo_root": str(repo_root), "concept": implementation_phrase, "matches": [m[0] for m in matches]},
            "warnings": [],
        }
    if target_symbol and file_scope_path and file_scope_path.is_file():
        rel = _display_rel(file_scope_path, repo_root)
        local_matches = _file_symbol_matches(file_scope_path, target_symbol, limit=8)
        body = [f"**File**: `{rel}`", f"**Symbol**: `{target_symbol}`", "", f"**References inside `{Path(rel).name}`**"]
        if local_matches:
            for lineno, snippet in local_matches:
                body.append(f"- line {lineno}: `{snippet}`")
        else:
            body.append("- No matches found in the target file.")
        answer = "\n".join(body)
        return {
            "ok": True,
            "text": answer,
            "summary": answer,
            "final_answer": answer,
            "data": {"repo_root": str(repo_root), "file": rel, "symbol": target_symbol, "matches": [ln for ln, _ in local_matches]},
            "warnings": [],
        }
    want_contains = 'contains' in request_text.lower() and bool(target_symbol)
    if want_contains:
        matches = []
        for path in _iter_files(repo_root):
            text = _read_text(path)
            if target_symbol in text:
                matches.append(_display_rel(path, repo_root))
                if len(matches) >= 8:
                    break
        body = [f"**Symbol**: `{target_symbol}`", "", "**Files That Contain It**"]
        if matches:
            body.extend(f"- `{m}`" for m in matches)
        else:
            body.append("- No matches found.")
        answer = "\n".join(body)
        return {"ok": True, "text": answer, "summary": answer, "final_answer": answer, "data": {"repo_root": str(repo_root), "symbol": target_symbol, "matches": matches}, "warnings": []}
    query = target_symbol or target_file
    fallback_query = Path(target_file).name if (target_file and not target_symbol) else query
    matches: List[Tuple[str, str]] = []
    grep_query = query or fallback_query
    if grep_query:
        matches = _grep_matches(repo_root, grep_query, limit=8)
    if not matches:
        primary: List[Tuple[str, str]] = []
        secondary: List[Tuple[str, str]] = []
        for path in _iter_files(repo_root):
            rel = _display_rel(path, repo_root)
            if target_file and rel == target_file:
                continue
            text = _read_text(path)
            matched_query = ""
            if query and query in text:
                matched_query = query
            elif fallback_query and fallback_query != query and fallback_query in text:
                matched_query = fallback_query
            if matched_query:
                snippet = ""
                for line in text.splitlines():
                    if matched_query in line:
                        snippet = line.strip()[:220]
                        break
                item = (rel, snippet)
                if _looks_like_literal_only_match(snippet, matched_query):
                    secondary.append(item)
                else:
                    primary.append(item)
                if len(primary) >= 8:
                    break
        matches = (primary + secondary)[:8]
    heading = f"Uses of `{target_symbol}`" if target_symbol else (f"References to `{target_file}`" if target_file else "Matches")
    body = [f"**Query**: `{query}`", "", f"**{heading}**"]
    if matches:
        for rel, snippet in matches:
            body.append(f"- `{rel}`")
            if snippet:
                body.append(f"  Snippet: `{snippet}`")
    else:
        body.append("- No matches found.")
    answer = "\n".join(body)
    return {"ok": True, "text": answer, "summary": answer, "final_answer": answer, "data": {"repo_root": str(repo_root), "query": query, "matches": [m[0] for m in matches]}, "warnings": []}


TOOL_SPEC = {"id": NAME, "category": "custom", "label": "Repo Reference Search", "description": "Search a repo for symbol uses or file references and return matching files.", "permissions": PERMISSIONS, "metadata": {"version": _VERSION, "created_at": _CREATED_AT, "last_updated": _LAST_UPDATED, "dev_status": _DEV_STATUS, "required_capabilities": ["repo_editing", "document_io", "content_authoring"], "output_mode": "text"}, "params_schema": {"type": "object", "properties": {"request_text": {"type": "string"}}, "additionalProperties": True}}
