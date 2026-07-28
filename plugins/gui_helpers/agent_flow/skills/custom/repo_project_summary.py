from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

NAME = "custom.repo_project_summary"
PERMISSIONS = [NAME, "custom.*"]
_CREATED_AT = "2026-06-26T00:00:00Z"
_LAST_UPDATED = "2026-06-28T04:20:00Z"
_VERSION = "1.3"
_DEV_STATUS = "tested"

_REPO_HINT_RE = re.compile(r"((?:/app|/data)/[^\s\"']*/repo)\b", re.IGNORECASE)
_TEXT_EXTS = {".md", ".txt", ".py", ".js", ".ts", ".json", ".yml", ".yaml", ".toml"}
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}
_CHANGE_GUIDANCE_STOP = {
    "look", "tell", "what", "which", "files", "file", "need", "change", "update", "modify", "fix",
    "repo", "repository", "codebase", "would", "most", "likely", "for", "the", "and", "to", "in",
    "under", "inside", "behavior", "feature", "service", "should",
}


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


def _resolve_repo_root(request_text: str) -> Path:
    match = _REPO_HINT_RE.search(str(request_text or ""))
    raw = str(match.group(1) or "").strip() if match else "/data/agent_workflow/repo"
    if raw.startswith("/data/"):
        return _project_root() / raw.lstrip("/")
    if raw.startswith("/app/"):
        return _project_root() / raw.replace("/app/", "", 1)
    return Path(raw)


def _safe_text(path: Path, max_chars: int = 8000) -> str:
    try:
        return path.read_text(encoding="utf-8")[:max_chars]
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except Exception:
        return ""


def _top_level_entries(repo_root: Path) -> Tuple[List[str], List[str]]:
    dirs: List[str] = []
    files: List[str] = []
    try:
        rows = sorted(repo_root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except Exception:
        return dirs, files
    for item in rows:
        if item.name in _SKIP_DIRS:
            continue
        if item.is_dir():
            dirs.append(item.name + "/")
        elif item.is_file():
            files.append(item.name)
    return dirs[:12], files[:12]


def _candidate_files(repo_root: Path) -> List[Path]:
    ordered: List[Path] = []
    preferred = [
        "README.md", "README.txt", "readme.md", "readme.txt",
        "app.py", "main.py", "package.json", "pyproject.toml", "requirements.txt",
        "docker-compose.yml", "docker-compose.yaml",
        "agent_flow/manifest.json", "agent_flow/plugin.js",
        "plugins/gui_helpers/agent_flow/manifest.json", "plugins/gui_helpers/agent_flow/plugin.js",
    ]
    for name in preferred:
        candidate = repo_root / Path(name)
        if candidate.is_file() and candidate.suffix.lower() in _TEXT_EXTS:
            ordered.append(candidate)
    try:
        for item in sorted(repo_root.iterdir(), key=lambda p: p.name.lower()):
            if item.is_file() and item.suffix.lower() in _TEXT_EXTS and item not in ordered and item.name not in _SKIP_DIRS:
                ordered.append(item)
            if len(ordered) >= 10:
                break
    except Exception:
        pass
    return ordered[:10]


def _looks_like_change_guidance_request(request_text: str) -> bool:
    low = str(request_text or "").lower()
    return bool(
        any(tok in low for tok in ("what files", "which files", "need to change", "need to update", "need to modify", "where would i change", "where should i change"))
        and any(tok in low for tok in ("autoflow", "service_chat", "routing", "router", "workflow", "plugin", "skill", "route", "behavior"))
    )


def _query_terms(request_text: str) -> List[str]:
    raw = re.findall(r"[A-Za-z_][A-Za-z0-9_/-]{2,}", str(request_text or "").lower())
    out: List[str] = []
    seen = set()
    for tok in raw:
        clean = tok.strip("./-_")
        if not clean or clean in _CHANGE_GUIDANCE_STOP:
            continue
        if clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out[:16]


def _display_change_path(path: Path, repo_root: Path) -> str:
    for root in (repo_root, _project_root()):
        try:
            return path.relative_to(root).as_posix()
        except Exception:
            continue
    return path.as_posix()


def _iter_repo_text_files(repo_root: Path, limit: int = 80) -> List[Path]:
    preferred = [
        repo_root / "plugins" / "gui_helpers" / "collab_chat" / "routes.py",
        repo_root / "plugins" / "ai_routes" / "autoflow" / "__init__.py",
        repo_root / "plugins" / "gui_helpers" / "agent_flow" / "routes.py",
        repo_root / "plugins" / "gui_helpers" / "agent_flow" / "manifest.json",
        repo_root / "plugins" / "gui_helpers" / "agent_flow" / "plugin.js",
    ]
    ordered: List[Path] = []
    seen = set()
    for path in preferred:
        key = path.as_posix().lower()
        if path.is_file() and key not in seen:
            seen.add(key)
            ordered.append(path)
    for path in repo_root.rglob("*"):
        if len(ordered) >= limit:
            break
        if not path.is_file():
            continue
        if path.suffix.lower() not in _TEXT_EXTS:
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        key = path.as_posix().lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(path)
    return ordered


def _score_change_candidate(path: Path, text: str, terms: List[str], repo_root: Path) -> Tuple[int, List[str]]:
    rel = _display_change_path(path, repo_root)
    rel_low = rel.lower()
    text_low = str(text or "").lower()
    score = 0
    reasons: List[str] = []
    high_signal_path_terms = ("autoflow", "service_chat", "collab_chat", "route", "routes", "router", "agent_flow", "skill")
    for term in terms:
        if term in rel_low:
            score += 8
            if len(reasons) < 3:
                reasons.append(f"path matches `{term}`")
        if term in text_low:
            score += 3
            if len(reasons) < 3 and f"content mentions `{term}`" not in reasons:
                reasons.append(f"content mentions `{term}`")
    for marker in high_signal_path_terms:
        if marker in rel_low:
            score += 4
    if rel_low.endswith("plugins/gui_helpers/collab_chat/routes.py"):
        score += 14
        reasons.insert(0, "service chat endpoint and dispatch logic")
    elif rel_low.endswith("plugins/ai_routes/autoflow/__init__.py"):
        score += 14
        reasons.insert(0, "AutoFlow routing and builtin selection logic")
    elif rel_low.endswith("plugins/gui_helpers/agent_flow/routes.py"):
        score += 8
        reasons.insert(0, "agent-flow execution endpoint and runtime wiring")
    elif "/skills/" in rel_low:
        score += 5
        if len(reasons) < 3:
            reasons.append("skill implementation surface")
    if "service_chat" in text_low:
        score += 4
    if "autoflow" in text_low:
        score += 4
    if "route" in text_low or "router" in text_low:
        score += 3
    return score, reasons[:3]


def _change_guidance(repo_root: Path, request_text: str) -> List[Tuple[str, List[str]]]:
    terms = _query_terms(request_text)
    ranked: List[Tuple[int, str, List[str]]] = []
    seen_paths: set[str] = set()
    seen_rels: set[str] = set()
    project_root = _project_root()
    candidate_paths: List[Path] = []
    if project_root.resolve() != repo_root.resolve():
        candidate_paths.extend([
            project_root / "plugins" / "gui_helpers" / "collab_chat" / "routes.py",
            project_root / "plugins" / "ai_routes" / "autoflow" / "__init__.py",
            project_root / "plugins" / "gui_helpers" / "agent_flow" / "routes.py",
            project_root / "plugins" / "gui_helpers" / "agent_flow" / "skills" / "custom" / "repo_project_summary.py",
            project_root / "plugins" / "gui_helpers" / "agent_flow" / "skills" / "custom" / "repo_file_summary.py",
        ])
    candidate_paths.extend(_iter_repo_text_files(repo_root))
    for path in candidate_paths:
        key = path.as_posix().lower()
        if key in seen_paths or not path.is_file():
            continue
        seen_paths.add(key)
        text = _safe_text(path, max_chars=12000)
        score, reasons = _score_change_candidate(path, text, terms, repo_root)
        if score <= 0:
            continue
        rel = _display_change_path(path, repo_root)
        if rel in seen_rels:
            continue
        seen_rels.add(rel)
        ranked.append((score, rel, reasons))
        if len(ranked) >= 6 and any(r[1] == 'plugins/ai_routes/autoflow/__init__.py' for r in ranked) and any(r[1] == 'plugins/gui_helpers/collab_chat/routes.py' for r in ranked):
            break
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [(rel, reasons) for _, rel, reasons in ranked[:6]]


def _trusted_stack_snippets(repo_root: Path) -> List[Tuple[str, str]]:
    ordered: List[Tuple[str, str]] = []
    trusted = [
        "README.md",
        "README.txt",
        "readme.md",
        "readme.txt",
        "app.py",
        "main.py",
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "docker-compose.yml",
        "docker-compose.yaml",
        "agent_flow/manifest.json",
        "agent_flow/plugin.js",
        "plugin.js",
        "manifest.json",
        "plugins/gui_helpers/agent_flow/manifest.json",
        "plugins/gui_helpers/agent_flow/plugin.js",
    ]
    seen: set[str] = set()
    for name in trusted:
        path = repo_root / Path(name)
        if not path.is_file():
            continue
        text = _safe_text(path, max_chars=4000)
        if not text:
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        ordered.append((path.name, text))
    return ordered


def _repo_shape_signals(repo_root: Path, top_dirs: List[str], top_files: List[str]) -> List[str]:
    signals: List[str] = []
    dir_names = [name.rstrip('/') for name in (top_dirs or [])]
    noisy_generated = [name for name in dir_names if re.search(r'(generated|request|test|workflow|plugin|chatjs|snake_game|racing_game|vendor_reconciliation)', name, re.IGNORECASE)]
    if len(noisy_generated) >= 4:
        signals.append('mixed_workspace')
    if (repo_root / 'agent_flow' / 'manifest.json').is_file() or (repo_root / 'agent_flow' / 'plugin.js').is_file():
        signals.append('agent_flow_plugin')
    if (repo_root / 'plugins').is_dir() or (repo_root / 'plugin').is_dir():
        signals.append('plugin_tree')
    if any(name.endswith('.zip') for name in (top_files or [])):
        signals.append('artifact_archive')
    return signals


def _stack_summary(snippets: List[Tuple[str, str]], repo_root: Path, top_dirs: List[str]) -> List[str]:
    trusted_snippets = _trusted_stack_snippets(repo_root)
    joined = "\n".join(text for _, text in trusted_snippets).lower()
    points: List[str] = []
    dir_names = {name.rstrip('/').lower() for name in (top_dirs or [])}
    if (repo_root / 'agent_flow' / 'manifest.json').is_file() or (repo_root / 'agent_flow' / 'plugin.js').is_file():
        points.append('agent-flow plugin or workflow bundle structure')
    if 'plugins' in dir_names or 'plugin' in dir_names:
        points.append('plugin-oriented project layout')
    if re.search(r"\bfastapi\b", joined):
        points.append("Python FastAPI backend")
    if re.search(r"\bflask\b", joined):
        points.append("Flask-style web service")
    if '"react"' in joined or "'react'" in joined or "react-dom" in joined:
        points.append("React frontend")
    if re.search(r"\buvicorn\b", joined):
        points.append("Uvicorn app server")
    if re.search(r"\bdocker\b", joined) or "services:" in joined:
        points.append("containerized deployment/runtime setup")
    if "agent_flow" in joined or re.search(r"\bworkflow\b", joined):
        points.append("workflow/agent orchestration logic")
    if re.search(r"\bmodel_loader\b|\bgguf\b|\bllama\b", joined):
        points.append("local model loading or inference integration")
    return points[:4]


def _purpose_summary(repo_root: Path, snippets: List[Tuple[str, str]], top_dirs: List[str], top_files: List[str]) -> str:
    readme_text = ""
    for name, text in snippets:
        if Path(name).name.lower().startswith("readme"):
            readme_text = text
            break
    if readme_text:
        for line in readme_text.splitlines():
            clean = line.strip().lstrip("#").strip()
            if len(clean.split()) >= 4:
                return clean.rstrip(".") + "."
    signals = _repo_shape_signals(repo_root, top_dirs, top_files)
    joined = "\n".join(text for _, text in snippets).lower()
    if 'mixed_workspace' in signals and 'agent_flow_plugin' in signals:
        return 'This repo appears to be a mixed workflow or plugin workspace: it contains agent-flow or plugin bundle files plus many generated or request-specific project folders rather than one clean application root.'
    if 'agent_flow_plugin' in signals and 'plugin_tree' in signals:
        return 'This repo appears to center on plugin or workflow-bundle code, with agent-flow assets and plugin-oriented project structure.'
    if "agent" in joined and "workflow" in joined and "chat" in joined:
        return "This repo appears to implement an agent or workflow-driven chat/application stack with routing, execution, and supporting runtime utilities."
    if "fastapi" in joined and "model" in joined:
        return "This repo appears to implement a backend application that serves models and higher-level automation or workflow features around them."
    if top_dirs:
        return f"This repo appears to center on the top-level areas {', '.join('`' + d.rstrip('/') + '`' for d in top_dirs[:4])}, with supporting files such as {', '.join('`' + f + '`' for f in top_files[:3])}."
    return "This repo appears to contain application code and supporting configuration for a larger software project."

def _key_components(top_dirs: List[str], top_files: List[str], snippets: List[Tuple[str, str]]) -> List[str]:
    points: List[str] = []
    if top_dirs:
        points.append("Top-level folders: " + ", ".join(f"`{name.rstrip('/')}`" for name in top_dirs[:6]))
    if top_files:
        points.append("Top-level files: " + ", ".join(f"`{name}`" for name in top_files[:6]))
    for name, text in snippets[:4]:
        low = text.lower()
        if name.lower().startswith("readme"):
            points.append(f"`{name}` provides human-oriented project documentation or overview context")
            continue
        if name == "app.py" and "fastapi" in low:
            points.append("`app.py` looks like a main backend entrypoint with route and runtime setup")
            continue
        if name == "package.json":
            points.append("`package.json` indicates a JavaScript/Node-based frontend or tooling layer")
            continue
        if name == "pyproject.toml" or name == "requirements.txt":
            points.append(f"`{name}` describes Python package/runtime dependencies")
            continue
    return points[:6]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_text = _request_text(ctx or {}, params or {})
    repo_root = _resolve_repo_root(request_text)
    if not repo_root.exists() or not repo_root.is_dir():
        answer = f"Repo root does not exist: `{repo_root.as_posix()}`"
        return {"ok": False, "text": answer, "summary": answer, "final_answer": answer, "warnings": ["repo_root_missing"]}
    if _looks_like_change_guidance_request(request_text):
        candidates = _change_guidance(repo_root, request_text)
        lines = [
            f"**Repo Root**: `{repo_root.as_posix()}`",
            "",
            "**Likely Files To Change**",
        ]
        if candidates:
            for rel, reasons in candidates:
                rationale = "; ".join(reason for reason in reasons if reason) or "relevant file for the requested change surface"
                lines.append(f"- `{rel}`: {rationale}")
            lines.extend([
                "",
                "**Why These First**",
                "- Start with the top route file and the AutoFlow selector before changing downstream skills.",
                "- Check skill files only if the routing decision is already correct but the final answer shape or data handling is still wrong.",
            ])
        else:
            lines.append("- No strong file matches were found from the request terms.")
        answer = "\n".join(lines)
        return {
            "ok": True,
            "text": answer,
            "summary": answer,
            "final_answer": answer,
            "data": {
                "repo_root": str(repo_root),
                "change_candidates": [{"path": rel, "reasons": reasons} for rel, reasons in candidates],
            },
            "warnings": [],
        }
    top_dirs, top_files = _top_level_entries(repo_root)
    snippets: List[Tuple[str, str]] = []
    for path in _candidate_files(repo_root):
        text = _safe_text(path)
        if text:
            snippets.append((path.name, text))
    purpose = _purpose_summary(repo_root, snippets, top_dirs, top_files)
    stack = _stack_summary(snippets, repo_root, top_dirs)
    key_components = _key_components(top_dirs, top_files, snippets)
    lines = [
        f"**Repo Root**: `{repo_root.as_posix()}`",
        "",
        f"**Main Purpose**: {purpose}",
    ]
    if stack:
        lines.extend(["", "**Likely Stack**", *(f"- {item}" for item in stack)])
    if key_components:
        lines.extend(["", "**Key Components**", *(f"- {item}" for item in key_components)])
    answer = "\n".join(lines)
    return {
        "ok": True,
        "text": answer,
        "summary": answer,
        "final_answer": answer,
        "data": {
            "repo_root": str(repo_root),
            "top_level_dirs": top_dirs,
            "top_level_files": top_files,
            "stack": stack,
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "custom",
    "label": "Repo Project Summary",
    "description": "Summarize the main purpose, likely stack, and key top-level components of a repo.",
    "permissions": PERMISSIONS,
    "metadata": {
        "version": _VERSION,
        "created_at": _CREATED_AT,
        "last_updated": _LAST_UPDATED,
        "dev_status": _DEV_STATUS,
        "required_capabilities": ["repo_editing", "document_io", "content_authoring"],
        "output_mode": "text",
    },
    "params_schema": {
        "type": "object",
        "properties": {"request_text": {"type": "string"}},
        "additionalProperties": True,
    },
}
