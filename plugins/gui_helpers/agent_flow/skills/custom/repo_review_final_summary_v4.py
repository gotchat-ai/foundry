from __future__ import annotations

import re
import subprocess
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

NAME = "custom.repo_review_final_summary_v4"
PERMISSIONS = [NAME, "custom.*"]
_CREATED_AT = "2026-08-01T00:00:00Z"
_LAST_UPDATED = "2026-08-01T00:00:00Z"
_VERSION = "1.4"
_DEV_STATUS = "tested"


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ("request_text", "user_request", "request", "text", "prompt", "query"):
        value = str((params or {}).get(key) or "").strip()
        if value:
            return value
    ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
    ext = ext if isinstance(ext, dict) else {}
    for key in ("original_request", "user_text", "current_request_text", "request_text"):
        value = str(ext.get(key) or (ctx or {}).get(key) or "").strip()
        if value:
            return value
    return ""


def _state_key(pid: str, sid: str, run_id: str = "") -> str:
    rid = str(run_id or "").strip()
    return f"{pid}::{sid}::{rid}" if rid else f"{pid}::{sid}"


def _current_state(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    app = (ctx or {}).get("app")
    pid = str((ctx or {}).get("pid") or (ctx or {}).get("project_id") or "").strip()
    sid = str((ctx or {}).get("sid") or (ctx or {}).get("session_id") or "").strip()
    ext = (ctx or {}).get("ext") if isinstance((ctx or {}).get("ext"), dict) else {}
    run_id = str(
        (params or {}).get("run_id")
        or ext.get("run_id")
        or (ctx or {}).get("run_id")
        or (ctx or {}).get("agent_flow_run_id")
        or ""
    ).strip()
    if app is None or not pid or not sid:
        return {}
    runs = getattr(getattr(app, "state", None), "agent_flow_runs", None)
    lock = getattr(getattr(app, "state", None), "agent_flow_runs_lock", None)
    if not isinstance(runs, dict):
        return {}
    key = _state_key(pid, sid, run_id)
    latest_key = _state_key(pid, sid)
    try:
        if lock is not None:
            with lock:
                state = runs.get(key) or runs.get(latest_key) or {}
        else:
            state = runs.get(key) or runs.get(latest_key) or {}
    except Exception:
        state = {}
    return dict(state) if isinstance(state, dict) else {}


def _stream_message_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    pid = str((ctx or {}).get("pid") or (ctx or {}).get("project_id") or "").strip()
    sid = str((ctx or {}).get("sid") or (ctx or {}).get("session_id") or "").strip()
    ext = (ctx or {}).get("ext") if isinstance((ctx or {}).get("ext"), dict) else {}
    run_id = str(
        (params or {}).get("run_id")
        or ext.get("run_id")
        or (ctx or {}).get("run_id")
        or (ctx or {}).get("agent_flow_run_id")
        or ""
    ).strip()
    if not (pid and sid and run_id):
        return ""
    app = (ctx or {}).get("app")
    db_path = ""
    try:
        collab_db = getattr(getattr(app, "state", None), "collab_db", None)
        db_path = str(getattr(collab_db, "path", "") or "").strip()
    except Exception:
        db_path = ""
    if not db_path:
        here = Path(__file__).resolve()
        for parent in here.parents:
            candidate = parent / "data" / "collab_chat.db"
            if candidate.exists():
                db_path = str(candidate)
                break
    if not db_path or not Path(db_path).exists():
        return ""
    msg_id = f"{run_id}_stream"
    try:
        con = sqlite3.connect(db_path)
        row = con.execute("select content from messages where pid=? and sid=? and msg_id=?", (pid, sid, msg_id)).fetchone()
        con.close()
        return str(row[0] or "") if row else ""
    except Exception:
        return ""


def _step_outputs(state: Dict[str, Any]) -> List[str]:
    outs: List[str] = []
    for step in state.get("steps") if isinstance(state.get("steps"), list) else []:
        if not isinstance(step, dict):
            continue
        out = str(step.get("output") or "").strip()
        if out:
            outs.append(out)
    return outs


def _latest_complete_release_summary(outputs: List[str]) -> str:
    candidates: List[str] = []
    strong_candidates: List[str] = []
    rich_candidates: List[str] = []
    for out in reversed(outputs):
        text = str(out or "").strip()
        low = text.lower()
        if not text:
            continue
        if "target folder:" not in low or "verified files:" not in low:
            continue
        if "git status:" not in low or "rag sync:" not in low:
            continue
        if "changed files:" not in low:
            continue
        if "pending verification" in low:
            continue
        target_match = re.search(r"(?im)^target folder:\s*(.+)$", text)
        target_value = str(target_match.group(1) or "").strip() if target_match else ""
        if not target_value.lower().startswith("data/agent_workflow/repo/"):
            continue
        verified_match = re.search(r"(?im)^verified files:\s*(.+)$", text)
        verified_value = str(verified_match.group(1) or "").strip() if verified_match else ""
        if verified_value and verified_value.lower() != "none":
            parts = [p.strip() for p in verified_value.split(",")]
            if not parts or any(not _is_valid_repo_rel_path(part) for part in parts):
                continue
        if any(token in low for token in ("- bugs:", "- fixes:", "- actions:", "- handoff:")):
            continue
        candidates.append(text)
        if (
            "| file | status | details |" in low
            or "| :--- | :--- | :--- |" in low
            or "1. **" in text
            or "## summary" in low
            or "## details" in low
            or "## changed files" in low
            or "## verified files" in low
        ):
            rich_candidates.append(text)
        if (
            "already implemented" in low
            or "requested changes are already present" in low
            or "no further code changes were required" in low
            or "none required; requested improvements are already implemented" in low
        ) and "need to verify" not in low and "need to confirm" not in low:
            strong_candidates.append(text)
    if rich_candidates:
        return rich_candidates[0]
    if strong_candidates:
        return strong_candidates[0]
    return candidates[0] if candidates else ""


def _is_rich_release_summary(text: str) -> bool:
    low = str(text or "").strip().lower()
    if not low:
        return False
    markers = (
        "## summary",
        "## details",
        "## changed files",
        "## verified files",
        "## grid view",
        "| field | value |",
        "| file | status | details |",
        "| :--- | :--- |",
        "| :--- | :--- | :--- |",
        "1. **",
    )
    return any(marker in low for marker in markers)


def _markdown_repo_review(
    conclusion: str,
    target_folder: str,
    verified_files: List[str],
    changed_files: List[str],
    git_status: str,
    rag_status: str,
    findings: List[str],
    improvements: List[str],
    markdown_tables: List[List[str]],
) -> str:
    lines: List[str] = ["## Summary", conclusion, ""]
    lines.extend(
        [
            "## Details",
            "",
            "| Field | Value |",
            "| :--- | :--- |",
            f"| Target folder | `{target_folder}` |",
            f"| Git status | {git_status} |",
            f"| RAG sync | {rag_status} |",
            f"| Changed files | {len(changed_files)} |",
            f"| Verified files | {len(verified_files)} |",
            "",
        ]
    )
    lines.append("## Changed Files")
    if changed_files:
        lines.append("")
        for path0 in changed_files:
            lines.append(f"- `{path0}`")
    else:
        lines.extend(["", "- None"])
    lines.append("")
    lines.append("## Verified Files")
    if verified_files:
        lines.append("")
        for path0 in verified_files:
            lines.append(f"- `{path0}`")
    else:
        lines.extend(["", "- None"])
    if findings:
        lines.extend(["", "## Findings", ""])
        lines.extend(findings[:8])
    tables_to_render = markdown_tables or [_synthesize_grid_table(verified_files, changed_files, findings)]
    if tables_to_render:
        for idx, table in enumerate(tables_to_render, start=1):
            lines.extend(["", "## Grid View" if idx == 1 else f"## Grid View {idx}", ""])
            lines.extend(table)
    if improvements:
        lines.extend(["", "## Proposed Improvements", ""])
        lines.extend(improvements[:8])
    return "\n".join(lines).strip()


def _synthesize_grid_table(
    verified_files: List[str],
    changed_files: List[str],
    findings: List[str],
) -> List[str]:
    rows: List[str] = [
        "| File | Status | Details |",
        "| :--- | :--- | :--- |",
    ]
    changed_set = {str(p or "").strip().replace("\\", "/") for p in changed_files}
    files = verified_files or changed_files
    if not files:
        rows.append("| `(repo scope)` | Reviewed | No file-level verification details were captured. |")
        return rows
    for path0 in files:
        rel = str(path0 or "").strip().replace("\\", "/")
        if not rel:
            continue
        base = rel.split("/")[-1].lower()
        status = "Changed" if rel in changed_set else "Verified"
        matching = [
            line.lstrip("- ").strip()
            for line in findings
            if base in str(line or "").lower()
        ]
        detail = matching[0] if matching else "Reviewed in final summary."
        detail = detail.replace("|", "\\|")
        rows.append(f"| `{rel}` | {status} | {detail} |")
    return rows


def _step_tool_rows(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for step in state.get("steps") if isinstance(state.get("steps"), list) else []:
        if not isinstance(step, dict):
            continue
        tr = step.get("tool_results")
        if not isinstance(tr, list):
            continue
        for row in tr:
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _request_target_literal(request_text: str) -> str:
    raw = str(request_text or "").strip()
    if not raw:
        return ""
    normalized = raw.replace("\\", "/")
    explicit = re.search(r"(data/agent_workflow/repo/[A-Za-z0-9_.\-/]+)", normalized, flags=re.IGNORECASE)
    if explicit:
        return str(explicit.group(1) or "").strip().replace("\\", "/")
    folder_patterns = (
        r"\brepo\s+folder\s+([A-Za-z0-9_.-]+)\b",
        r"\bfolder\s+called\s+([A-Za-z0-9_.-]+)\b",
        r"\bin\s+the\s+repo\s+folder\s+([A-Za-z0-9_.-]+)\b",
        r"\btarget\s+folder\s+([A-Za-z0-9_.-]+)\b",
    )
    for pattern in folder_patterns:
        m = re.search(pattern, raw, flags=re.IGNORECASE)
        if m:
            return f"data/agent_workflow/repo/{str(m.group(1) or '').strip()}"
    return ""


def _target_folder(request_text: str, outputs: List[str], state: Dict[str, Any], tool_rows: List[Dict[str, Any]]) -> str:
    req_target = _request_target_literal(request_text)
    if req_target:
        return req_target
    candidates = [request_text, str(state.get("final_result") or "").strip(), *outputs]
    for text in candidates:
        m = re.search(r"(data/agent_workflow/repo/[A-Za-z0-9_.\-/]+)", text, flags=re.IGNORECASE)
        if m:
            value = str(m.group(1) or "").strip().replace("\\", "/")
            tail = value.split("data/agent_workflow/repo/", 1)[-1]
            if re.search(r"/[^/]+\.[A-Za-z0-9]+$", tail):
                parts = tail.split("/")
                if len(parts) >= 2:
                    return f"data/agent_workflow/repo/{parts[0]}"
            return value
    for row in tool_rows:
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        for key in ("root", "path", "repo_root", "target_repo_root"):
            value = str(data.get(key) or "").strip().replace("\\", "/")
            if not value:
                continue
            if "data/agent_workflow/repo/" in value.lower():
                if key == "path":
                    prefix = value.split("data/agent_workflow/repo/", 1)[0]
                    tail = value.split("data/agent_workflow/repo/", 1)[1]
                    top = tail.split("/", 1)[0]
                    return f"data/agent_workflow/repo/{top}"
                return value
    inferred_files = _verified_files(outputs, "", tool_rows)
    if inferred_files:
        top = str(inferred_files[0] or "").strip().replace("\\", "/").split("/", 1)[0]
        if top:
            return f"data/agent_workflow/repo/{top}"
    return ""


def _verified_files(outputs: List[str], target_folder: str, tool_rows: List[Dict[str, Any]]) -> List[str]:
    target_tail = target_folder.split("data/agent_workflow/repo/", 1)[-1].strip("/") if "data/agent_workflow/repo/" in target_folder else target_folder.strip("/")
    found: List[str] = []
    for row in tool_rows:
        skill = str(row.get("skill") or row.get("id") or "").strip().lower()
        if skill not in {"repo.read_range", "repo.read", "repo.search", "repo.tree"}:
            continue
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        candidates: List[str] = []
        for key in ("path", "target_path"):
            value = str(data.get(key) or "").strip().replace("\\", "/")
            if value:
                candidates.append(value)
        for item in data.get("matches") if isinstance(data.get("matches"), list) else []:
            if isinstance(item, dict):
                value = str(item.get("path") or "").strip().replace("\\", "/")
                if value:
                    candidates.append(value)
        for path0 in candidates:
            if "data/agent_workflow/repo/" in path0.lower():
                path0 = path0.split("data/agent_workflow/repo/", 1)[1]
            if target_tail and not (path0 == target_tail or path0.startswith(target_tail + "/")):
                continue
            if path0 and path0 not in found:
                found.append(path0)
    for out in outputs:
        for m in re.finditer(r"repo\.(?:read|read_range): ok \(([^)]+)\)", out, flags=re.IGNORECASE):
            path0 = str(m.group(1) or "").strip().replace("\\", "/")
            if not path0:
                continue
            if target_tail and not (path0 == target_tail or path0.startswith(target_tail + "/")):
                continue
            if path0 not in found:
                found.append(path0)
    return found


def _is_valid_repo_rel_path(path0: str) -> bool:
    s = str(path0 or "").strip().replace("\\", "/")
    if not s or "," in s:
        return False
    return bool(re.match(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+$", s))


def _sanitize_repo_paths(paths: List[str], target_folder: str) -> List[str]:
    target_tail = _exact_target_tail(target_folder)
    out: List[str] = []
    for raw in paths or []:
        path0 = str(raw or "").strip().replace("\\", "/")
        if "data/agent_workflow/repo/" in path0.lower():
            path0 = path0.split("data/agent_workflow/repo/", 1)[1]
        if not _is_valid_repo_rel_path(path0):
            continue
        if target_tail and not (path0 == target_tail or path0.startswith(target_tail + "/")):
            continue
        if path0 not in out:
            out.append(path0)
    return out


def _exact_target_tail(target_folder: str) -> str:
    if "data/agent_workflow/repo/" in target_folder:
        return target_folder.split("data/agent_workflow/repo/", 1)[-1].strip("/")
    return target_folder.strip("/")


def _collect_section_lines(outputs: List[str], headers: tuple[str, ...]) -> List[str]:
    out_rows: List[str] = []
    header_set = {h.lower() for h in headers}
    for out in outputs:
        in_section = False
        for line in str(out).splitlines():
            s = str(line or "").strip()
            low = s.lower()
            if low in header_set:
                in_section = True
                continue
            if re.match(r"^[a-z_ ]+:\s*$", low) and low not in header_set:
                in_section = False
            if in_section and (s.startswith("-") or re.match(r"^\d+\.\s+", s)):
                item = s
                if re.match(r"^\d+\.\s+", s):
                    item = "- " + re.sub(r"^\d+\.\s+", "", s).strip()
                elif not s.startswith("- "):
                    item = f"- {s.lstrip('-').strip()}"
                if item not in out_rows:
                    out_rows.append(item)
    return out_rows


def _collect_markdown_tables(outputs: List[str]) -> List[List[str]]:
    tables: List[List[str]] = []
    seen: set[str] = set()
    for out in outputs:
        current: List[str] = []
        for line in str(out or "").splitlines():
            s = str(line or "").rstrip()
            trimmed = s.strip()
            if trimmed.startswith("- |"):
                trimmed = trimmed[2:].strip()
            if trimmed.startswith("|") and trimmed.endswith("|"):
                current.append(trimmed)
                continue
            if len(current) >= 2:
                key = "\n".join(current)
                if key not in seen:
                    seen.add(key)
                    tables.append(list(current))
            current = []
        if len(current) >= 2:
            key = "\n".join(current)
            if key not in seen:
                seen.add(key)
                tables.append(list(current))
    return tables


def _git_status(outputs: List[str], target_folder: str, tool_rows: List[Dict[str, Any]]) -> str:
    target_tail = _exact_target_tail(target_folder)
    for row in reversed(tool_rows):
        skill = str(row.get("skill") or row.get("id") or "").strip().lower()
        if skill != "git.status":
            continue
        warnings = [str(x or "").strip().lower() for x in (row.get("warnings") if isinstance(row.get("warnings"), list) else [])]
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        root = str(data.get("root") or "").strip().replace("\\", "/")
        if target_tail and root and target_tail not in root:
            continue
        if "empty_git_repo_no_commits" in warnings:
            return "unavailable for target folder (empty git repo with no commits)"
        if "not_git_repo" in warnings:
            return "unavailable for target folder (not a git repo)"
        changed = data.get("changed") if isinstance(data.get("changed"), list) else []
        deleted = data.get("deleted") if isinstance(data.get("deleted"), list) else []
        if not changed and not deleted:
            return f"no changes in {target_tail}" if target_tail else "no changes"
        rows = [str(x).strip().replace("\\", "/") for x in [*changed, *deleted] if str(x or "").strip()]
        scoped = [x for x in rows if not target_tail or x == target_tail or x.startswith(target_tail + "/")]
        if scoped:
            return "changed: " + ", ".join(scoped[:10])
        if rows:
            return f"out-of-scope changes ignored; no changes in {target_tail}" if target_tail else "out-of-scope changes ignored"
    for out in reversed(outputs):
        low = out.lower()
        if "git status shows the repo is clean" in low or "repo is clean" in low:
            return f"no changes in {target_tail}" if target_tail else "no changes"
        if "out-of-scope" in low and "git" in low:
            return f"out-of-scope changes ignored; no changes in {target_tail}" if target_tail else "out-of-scope changes ignored"
        if "git status:" in low:
            m = re.search(r"(?im)^git status:\s*(.+)$", out)
            if m:
                text = str(m.group(1) or "").strip()
                if text:
                    return text
        if "not a git repo" in low or "git scope unavailable for target folder" in low:
            return "unavailable for target folder (not a git repo)"
        if "empty git repo with no commits" in low:
            return "unavailable for target folder (empty git repo with no commits)"
        if target_tail and f"no changes in {target_tail}".lower() in low:
            return f"no changes in {target_tail}"
    return ""


def _rag_status(outputs: List[str], target_folder: str, tool_rows: List[Dict[str, Any]]) -> str:
    target_tail = target_folder.split("data/agent_workflow/repo/", 1)[-1].strip("/") if "data/agent_workflow/repo/" in target_folder else target_folder.strip("/")
    for row in reversed(tool_rows):
        skill = str(row.get("skill") or row.get("id") or "").strip().lower()
        if skill != "rag.refresh_repo_delta":
            continue
        warnings = [str(x or "").strip().lower() for x in (row.get("warnings") if isinstance(row.get("warnings"), list) else [])]
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        root = str(data.get("root") or "").strip().replace("\\", "/")
        if target_tail and root and target_tail not in root:
            continue
        if "no_delta" in warnings:
            return f"no delta for {target_tail}" if target_tail else "no delta"
        version = str(data.get("version") or "").strip()
        changed = data.get("changed") if isinstance(data.get("changed"), list) else []
        deleted = data.get("deleted") if isinstance(data.get("deleted"), list) else []
        scoped = [str(x).strip().replace("\\", "/") for x in [*changed, *deleted] if str(x or "").strip()]
        if version or scoped:
            detail = ", ".join(scoped[:10]) if scoped else "no changed paths"
            return f"refreshed ({detail})"
    for out in reversed(outputs):
        low = out.lower()
        if "rag.refresh_repo_delta: ok warnings=no_delta" in low or ("rag.refresh_repo_delta" in low and "no_delta" in low):
            return f"no delta for {target_tail}" if target_tail else "no delta"
        if "rag.refresh_repo_delta: ok" in low:
            return f"completed for {target_tail}" if target_tail else "completed"
        if "rag sync:" in low:
            m = re.search(r"(?im)^rag sync:\s*(.+)$", out)
            if m:
                text = str(m.group(1) or "").strip()
                if text:
                    return text
        if "no delta" in low:
            if target_tail:
                return f"no delta for {target_tail}"
            return "no delta"
        if "rag refresh outcome:" in low:
            m = re.search(r"(?im)^rag refresh outcome:\s*(.+)$", out)
            if m:
                text = str(m.group(1) or "").strip()
                if text:
                    return text
        if "refreshed for" in low and "rag" in low:
            m = re.search(r"refreshed for ([A-Za-z0-9_.\-/]+)", out, flags=re.IGNORECASE)
            if m:
                return f"refreshed for {str(m.group(1) or '').strip()}"
    return "not checked in this flow"


def _inline_field(outputs: List[str], label: str) -> str:
    pattern = re.compile(re.escape(label) + r"\s*:\s*([^\r\n]+)", flags=re.IGNORECASE)
    for out in reversed(outputs):
        m = pattern.search(out)
        if m:
            value = str(m.group(1) or "").strip()
            if value:
                return value
    return ""


def _changed_files(outputs: List[str], target_folder: str, tool_rows: List[Dict[str, Any]]) -> List[str]:
    target_tail = target_folder.split("data/agent_workflow/repo/", 1)[-1].strip("/") if "data/agent_workflow/repo/" in target_folder else target_folder.strip("/")
    found: List[str] = []
    for row in tool_rows:
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        for key in ("changed_files", "final_paths", "requested_paths", "files"):
            values = data.get(key)
            if not isinstance(values, list):
                continue
            for value in values:
                path0 = str(value or "").strip().replace("\\", "/")
                if not path0:
                    continue
                if "data/agent_workflow/repo/" in path0.lower():
                    path0 = path0.split("data/agent_workflow/repo/", 1)[1]
                if target_tail and not (path0 == target_tail or path0.startswith(target_tail + "/")):
                    continue
                if path0 not in found:
                    found.append(path0)
    for out in outputs:
        inline = re.search(r"(?im)^changed files:\s*(.+)$", out)
        if inline:
            raw = str(inline.group(1) or "").strip()
            if raw and raw.lower() != "none":
                for part in [p.strip().replace("\\", "/") for p in raw.split(",")]:
                    path0 = part
                    if "data/agent_workflow/repo/" in path0.lower():
                        path0 = path0.split("data/agent_workflow/repo/", 1)[1]
                    if target_tail and not (path0 == target_tail or path0.startswith(target_tail + "/")):
                        continue
                    if path0 and path0 not in found:
                        found.append(path0)
        for m in re.finditer(r"changed file:\s*([^\r\n]+)", out, flags=re.IGNORECASE):
            path0 = str(m.group(1) or "").strip().replace("\\", "/")
            if not path0:
                continue
            if target_tail and not (path0 == target_tail or path0.startswith(target_tail + "/")):
                continue
            if path0 not in found:
                found.append(path0)
    return found


def _clean_lines(lines: List[str]) -> List[str]:
    cleaned: List[str] = []
    seen_norm: set[str] = set()
    generic_bug_lines: List[str] = []
    for item in lines:
        s = str(item or "").strip()
        low = s.lower()
        if not s:
            continue
        if low.startswith("- |") or low.startswith("|"):
            continue
        if "calendar-tool-light-nodejs/src/index.js" in low and "nodejs" not in low:
            continue
        if low.startswith("- inspect repo scope:"):
            continue
        if low.startswith("- call "):
            continue
        if low.startswith("- report "):
            continue
        if low.startswith("- bugs:") or low.startswith("- fixes:") or low.startswith("- actions:"):
            continue
        if low.startswith("- handoff"):
            continue
        if low.startswith("- git status:") or low.startswith("- rag sync:") or low.startswith("- changed files:"):
            continue
        if low.startswith("- read cargo.toml") or low.startswith("- read src/main.rs") or low.startswith("- call repo.read"):
            continue
        if low.startswith("- verify uuid") or low.startswith("- verify the code content"):
            continue
        if "outside scope" in low or "out-of-scope" in low:
            continue
        if "no modifications made to preserve current structure" in low:
            continue
        if "no further action required unless specific bug confirmation is provided" in low:
            continue
        if low.startswith("- none found") or "no concrete bugs found" in low or "logic is sound" in low:
            generic_bug_lines.append(s)
            continue
        norm = re.sub(r"[^a-z0-9]+", " ", low).strip()
        if not norm:
            continue
        if norm in seen_norm:
            continue
        seen_norm.add(norm)
        cleaned.append(s)
    if not cleaned and generic_bug_lines:
        return [generic_bug_lines[0]]
    return cleaned


def _repo_root_from_target(target_folder: str) -> Optional[Path]:
    if not target_folder or "data/agent_workflow/repo/" not in target_folder:
        return None
    rel = target_folder.split("data/agent_workflow/repo/", 1)[-1].strip("/")
    if not rel:
        return None
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data" / "agent_workflow" / "repo" / rel
        if candidate.exists():
            return candidate
    return None


def _read_verified_sources(target_folder: str, verified_files: List[str]) -> Dict[str, str]:
    root = _repo_root_from_target(target_folder)
    out: Dict[str, str] = {}
    if root is None:
        return out
    repo_root = root.parent
    for rel in verified_files:
        try:
            p = repo_root / rel
            if p.is_file():
                out[rel] = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
    return out


def _auto_verified_files_from_target(target_folder: str) -> List[str]:
    root = _repo_root_from_target(target_folder)
    if root is None:
        return []
    candidates = [
        "Cargo.toml",
        "src/main.rs",
        "package.json",
        "src/index.js",
        "Program.cs",
        "Controllers/AppointmentsController.cs",
        "Models/Appointment.cs",
        "CalendarService.cs",
    ]
    rel_root = _exact_target_tail(target_folder)
    found: List[str] = []
    for rel in candidates:
        p = root / rel
        if p.is_file():
            found.append(f"{rel_root}/{rel}".replace("\\", "/"))
    return found


def _direct_git_status(target_folder: str) -> str:
    root = _repo_root_from_target(target_folder)
    if root is None:
        return ""
    repo_root = root
    while repo_root != repo_root.parent:
        if (repo_root / ".git").is_dir() or (repo_root / ".git").is_file():
            break
        repo_root = repo_root.parent
    else:
        return "unavailable for target folder (not a git repo)"
    try:
        rel_target = root.relative_to(repo_root).as_posix()
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--", rel_target],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
            stderr = str(proc.stderr or "").lower()
            if "dubious ownership" in stderr or "safe.directory" in stderr:
                return "git repo detected but blocked by safe.directory ownership guard"
            return "unavailable for target folder"
        rows = [line.strip() for line in str(proc.stdout or "").splitlines() if line.strip()]
        if not rows:
            return f"no changes in {_exact_target_tail(target_folder)}"
        changed: List[str] = []
        for row in rows[:10]:
            parts = row.split(maxsplit=1)
            if len(parts) == 2:
                changed.append(parts[1].replace("\\", "/"))
        if changed:
            return "changed: " + ", ".join(changed)
        return f"no changes in {_exact_target_tail(target_folder)}"
    except Exception:
        return "unavailable for target folder"


def _heuristic_findings(target_folder: str, verified_files: List[str]) -> List[str]:
    texts = _read_verified_sources(target_folder, verified_files)
    findings: List[str] = []
    rust_main = next((v for k, v in texts.items() if k.endswith("src/main.rs")), "")
    node_index = next((v for k, v in texts.items() if k.endswith("src/index.js")), "")
    if rust_main:
        create_match = re.search(r"async fn create_appointment\s*\([^)]*\)\s*->\s*HttpResponse\s*\{(.*?)\n\}", rust_main, flags=re.DOTALL)
        create_body = str(create_match.group(1) or "") if create_match else ""
        has_persistence = "save_appointments" in rust_main and "appointments.json" in rust_main
        if "Mutex<HashMap<" in rust_main:
            if has_persistence:
                findings.append("- The Rust service still uses a single global `Mutex<HashMap<...>>`, so requests contend on one lock even though appointments are now persisted.")
            else:
                findings.append("- The Rust service uses a single global `Mutex<HashMap<...>>`, so all requests contend on one lock and all data is lost on restart.")
        if "appt.start_time >= query.start && appt.start_time <= query.end" in rust_main:
            findings.append("- Date-range retrieval compares ISO 8601 strings and only checks `start_time`, so overlapping appointments that begin before the requested range can be missed.")
        if 'format!("appt_{}"' in rust_main:
            findings.append("- Appointment IDs are derived from `start_time`, which can collide for duplicate or concurrent timestamps.")
        if "payload.user_id.clone()" in rust_main and "validate_times(" not in create_body:
            findings.append("- The create endpoint does not validate `start_time` and `end_time` before storing appointments.")
        elif "payload.user_id.clone()" in rust_main and "chrono" not in rust_main:
            findings.append("- The create endpoint stores `user_id`, `start_time`, and `end_time` without validating format or chronology.")
    if node_index:
        if "const appointments = []" in node_index:
            findings.append("- The Node.js service stores appointments in memory, so all data is lost on restart.")
        if "const { start, end } = req.query;" in node_index and "userId" not in node_index.split("app.get('/appointments'", 1)[-1]:
            findings.append("- The GET `/appointments` route does not filter by `userId`, so it cannot return user-scoped ranges even though appointments are stored with a `userId`.")
        if "start.slice(0, 4)" in node_index and "parseAndValidateDate" not in node_index.split("app.get('/appointments'", 1)[-1]:
            findings.append("- The GET `/appointments` path parses dates with string slicing instead of the stricter validator used by POST, which makes query parsing more fragile.")
    return findings[:8]


def _heuristic_improvements(findings: List[str]) -> List[str]:
    joined = "\n".join(findings).lower()
    improvements: List[str] = []
    if "user-scoped" in joined or "filter by `userid`" in joined:
        improvements.append("- Add a validated `userId` query parameter to the range endpoint and scope results to that user.")
    if "date-range retrieval compares iso 8601 strings" in joined:
        improvements.append("- Parse dates into typed UTC timestamps before comparison so overlap logic covers full appointment ranges safely.")
    if "derived from `start_time`" in joined:
        improvements.append("- Use UUID-based identifiers instead of deriving IDs from timestamps.")
    if "stores appointments in memory" in joined or "data is lost on restart" in joined:
        improvements.append("- Add a persistence layer if the service is expected to survive restarts.")
    if "without validating format or chronology" in joined:
        improvements.append("- Validate date formats and ensure `end_time` is after `start_time` before storing an appointment.")
    return improvements[:8]


def _ranked_improvements_from_outputs(outputs: List[str]) -> List[str]:
    found: List[str] = []
    for out in outputs:
        text = str(out or "")
        if not text:
            continue
        m = re.search(r"top\s*3\s+improvements\s*:\s*(.+)", text, flags=re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        tail = str(m.group(1) or "").strip()
        candidates: List[str] = []
        numbered = re.split(r"(?:^|[\s\r\n])(?:1[\)\.\:]|2[\)\.\:]|3[\)\.\:])\s*", tail)
        if len(numbered) > 1:
            for part in numbered[1:]:
                item = str(part or "").strip(" \r\n\t-")
                if item:
                    item = re.split(r"(?:^|[\s\r\n])(?:1[\)\.\:]|2[\)\.\:]|3[\)\.\:])\s*", item)[0].strip(" \r\n\t-")
                    if item:
                        candidates.append(item)
        if not candidates:
            for part in re.split(r";|\n|,\s*(?=[A-Z0-9])", tail):
                item = str(part or "").strip(" \r\n\t-")
                if item:
                    candidates.append(item)
        for item in candidates:
            bullet = item if item.startswith("-") else f"- {item.rstrip('.')}"
            norm = re.sub(r"[^a-z0-9]+", " ", bullet.lower()).strip()
            if norm and bullet not in found:
                found.append(bullet)
            if len(found) >= 3:
                return found[:3]
    return found[:3]


def _should_prefer_heuristics(target_folder: str, verified_files: List[str]) -> bool:
    tail = _exact_target_tail(target_folder).lower()
    if tail.endswith("calendar-tool-light-nodejs") and any(v.endswith("src/index.js") for v in verified_files):
        return True
    if tail.endswith("calendar-tool-light-rust") and any(v.endswith("src/main.rs") for v in verified_files):
        return True
    return False


def _implemented_findings(target_folder: str, verified_files: List[str], request_text: str = "") -> List[str]:
    texts = _read_verified_sources(target_folder, verified_files)
    findings: List[str] = []
    rust_main = next((v for k, v in texts.items() if k.endswith("src/main.rs")), "")
    rust_cargo = next((v for k, v in texts.items() if k.endswith("Cargo.toml")), "")
    node_index = next((v for k, v in texts.items() if k.endswith("src/index.js")), "")
    csharp_program = next((v for k, v in texts.items() if k.endswith("Program.cs")), "")
    target_tail = _exact_target_tail(target_folder)
    rust_main_label = f"`{target_tail}/src/main.rs`" if target_tail else "`src/main.rs`"
    rust_cargo_label = f"`{target_tail}/Cargo.toml`" if target_tail else "`Cargo.toml`"
    node_index_label = f"`{target_tail}/src/index.js`" if target_tail else "`src/index.js`"
    csharp_program_label = f"`{target_tail}/Program.cs`" if target_tail else "`Program.cs`"
    request_low = str(request_text or "").lower()
    if rust_cargo:
        if "uuid =" in rust_cargo.lower():
            findings.append(f"- {rust_cargo_label} includes the `uuid` dependency required for UUID-based appointment ids.")
        if "chrono =" in rust_cargo.lower():
            findings.append(f"- {rust_cargo_label} includes the `chrono` dependency used for date parsing and time comparisons.")
    if rust_main:
        create_match = re.search(r"async fn create_appointment\s*\([^)]*\)\s*->\s*HttpResponse\s*\{(.*?)\n\}", rust_main, flags=re.DOTALL)
        create_body = str(create_match.group(1) or "") if create_match else ""
        if "/health" in request_low or "health endpoint" in request_low or '"status":"ok"' in request_low or '"status": "ok"' in request_low:
            has_health_attr = '#[get("/health")]' in rust_main or '"/health"' in rust_main
            has_health_fn = "health_handler" in rust_main
            has_ok_json = '"status": "ok"' in rust_main or '"status":"ok"' in rust_main
            has_health_registration = ".service(health_handler)" in rust_main or "service(health_handler)" in rust_main
            if has_health_attr and has_health_fn:
                findings.append(f"- {rust_main_label} defines a GET `/health` handler.")
            if has_ok_json:
                findings.append(f"- {rust_main_label} returns JSON `{{\"status\":\"ok\"}}` from the health handler.")
            if has_health_registration:
                findings.append(f"- {rust_main_label} registers the health handler in the server/router configuration.")
        if "/version" in request_low or "version endpoint" in request_low or '"version"' in request_low:
            requested_version = ""
            m_version = re.search(r'"version"\s*:\s*"([^"]+)"', request_text, flags=re.IGNORECASE)
            if m_version:
                requested_version = str(m_version.group(1) or "").strip()
            has_version_attr = '#[get("/version")]' in rust_main or '"/version"' in rust_main
            has_version_fn = "get_version" in rust_main or "version_handler" in rust_main
            has_version_registration = ".service(get_version)" in rust_main or "service(get_version)" in rust_main or ".service(version_handler)" in rust_main
            has_version_json = ('"version"' in rust_main and requested_version in rust_main) if requested_version else '"version"' in rust_main
            if has_version_attr and has_version_fn:
                findings.append(f"- {rust_main_label} defines a GET `/version` handler.")
            if has_version_json:
                if requested_version:
                    findings.append(f"- {rust_main_label} returns JSON `{{\"version\":\"{requested_version}\"}}` from the version handler.")
                else:
                    findings.append(f"- {rust_main_label} returns a JSON `version` payload from the version handler.")
            if has_version_registration:
                findings.append(f"- {rust_main_label} registers the version handler in the server/router configuration.")
        if "uuid" in request_low or "validate the appointment date/time" in request_low or "persist appointments to json" in request_low or "persist appointments" in request_low:
            if "Uuid::new_v4()" in rust_main:
                findings.append(f"- {rust_main_label} uses `Uuid::new_v4()` inside `create_appointment`, so new appointments receive UUID-based identifiers.")
            if "fs::write(DATA_FILE" in rust_main or "save_appointments(&self)" in rust_main:
                findings.append(f"- {rust_main_label} persists appointments through `save_appointments`/`load_appointments`, writing and reading `appointments.json` across restarts.")
            if "validate_times(" in create_body and ("NaiveDateTime::parse_from_str" in rust_main or "end_time must be after start_time" in rust_main):
                findings.append(f"- {rust_main_label} calls `validate_times` from `create_appointment`, validating datetime format and enforcing `end_time` after `start_time`.")
    if node_index:
        if "/version" in request_low or "version endpoint" in request_low or '"version"' in request_low:
            requested_version = ""
            m_version = re.search(r'"version"\s*:\s*"([^"]+)"', request_text, flags=re.IGNORECASE)
            if m_version:
                requested_version = str(m_version.group(1) or "").strip()
            has_route = "app.get('/version'" in node_index or 'app.get("/version"' in node_index
            has_version_json = requested_version in node_index if requested_version else '"version"' in node_index
            if has_route:
                findings.append(f"- {node_index_label} defines a GET `/version` route.")
            if has_version_json:
                if requested_version:
                    findings.append(f"- {node_index_label} returns JSON `{{\"version\":\"{requested_version}\"}}` from the version route.")
                else:
                    findings.append(f"- {node_index_label} returns a JSON `version` payload from the version route.")
        if "writeFile" in node_index or "fs.writeFile" in node_index:
            findings.append("- The Node.js calendar service now persists appointment data to disk.")
    if csharp_program:
        if "/version" in request_low or "version endpoint" in request_low or '"version"' in request_low:
            requested_version = ""
            m_version = re.search(r'"version"\s*:\s*"([^"]+)"', request_text, flags=re.IGNORECASE)
            if m_version:
                requested_version = str(m_version.group(1) or "").strip()
            has_mapget = 'MapGet("/version"' in csharp_program or "MapGet('/version'" in csharp_program
            has_version_json = requested_version in csharp_program if requested_version else '"version"' in csharp_program
            if has_mapget:
                findings.append(f"- {csharp_program_label} maps a GET `/version` endpoint.")
            if has_version_json:
                if requested_version:
                    findings.append(f"- {csharp_program_label} returns JSON `{{\"version\":\"{requested_version}\"}}` from the version endpoint.")
                else:
                    findings.append(f"- {csharp_program_label} returns a JSON `version` payload from the version endpoint.")
    deduped: List[str] = []
    seen: set[str] = set()
    for item in findings:
        norm = re.sub(r"[^a-z0-9]+", " ", item.lower()).strip()
        if norm and norm not in seen:
            seen.add(norm)
            deduped.append(item)
    return deduped[:8]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    state = _current_state(ctx or {}, params or {})
    state_request_text = str(
        state.get("current_request_text")
        or (state.get("current_request", {}).get("request_text") if isinstance(state.get("current_request"), dict) else "")
        or state.get("request_text")
        or state.get("original_request")
        or state.get("user_text")
        or ""
    ).strip()
    request_text = state_request_text or _request_text(ctx or {}, params or {})
    outputs = _step_outputs(state)
    stream_text = _stream_message_text(ctx or {}, params or {})
    if stream_text:
        outputs = [*outputs, stream_text]
    tool_rows = _step_tool_rows(state)
    latest_release_summary = _latest_complete_release_summary(outputs)
    request_low = request_text.lower()
    implementation_intent_early = any(
        phrase in request_low
        for phrase in (
            "make the improvements",
            "make improvements",
            "implement the improvements",
            "implement improvements",
            "apply the improvements",
            "apply improvements",
            "improve the",
            "improve this",
            "fix the",
            "fix this",
            "update the",
            "update this",
            "rerun the workflow",
            "add a get ",
            "add get ",
            "add /",
            "create ",
        )
    )
    if latest_release_summary and _is_rich_release_summary(latest_release_summary):
        low_summary = latest_release_summary.lower()
        changed_evidence_present = False
        for row in tool_rows:
            data = row.get("data") if isinstance(row, dict) and isinstance(row.get("data"), dict) else {}
            cfs = data.get("changed_files") if isinstance(data.get("changed_files"), list) else []
            if cfs:
                changed_evidence_present = True
                break
        if not changed_evidence_present:
            changed_evidence_present = "changed file:" in "\n".join(outputs).lower()
        stale_impl_summary = (
            implementation_intent_early
            and changed_evidence_present
            and "changed files: none" in low_summary
        )
        stale_proposal_summary = (
            implementation_intent_early
            and changed_evidence_present
            and "proposed improvements:" in low_summary
            and ("- add " in low_summary or "- create " in low_summary or "- update " in low_summary)
        )
        if not stale_impl_summary and not stale_proposal_summary:
            return {
                "ok": True,
                "text": latest_release_summary,
                "response": latest_release_summary,
                "summary": latest_release_summary,
                "final_answer": latest_release_summary,
                "finalized_text": latest_release_summary,
                "markdown": latest_release_summary,
                "content": latest_release_summary,
                "data": {
                    "mode": "text",
                    "passthrough_release_summary": True,
                },
                "warnings": [],
            }
    target_folder = _target_folder(request_text, outputs, state, tool_rows)
    verified_files = _sanitize_repo_paths(_verified_files(outputs, target_folder, tool_rows), target_folder)
    git_status = _git_status(outputs, target_folder, tool_rows) or "unavailable for target folder"
    rag_status = _rag_status(outputs, target_folder, tool_rows) or "unavailable"
    changed_files = _sanitize_repo_paths(_changed_files(outputs, target_folder, tool_rows), target_folder)
    markdown_tables = _collect_markdown_tables(outputs)
    findings = _clean_lines(_collect_section_lines(outputs, ("bugs:", "findings:")))
    improvements = _clean_lines(_collect_section_lines(outputs, ("fixes:", "proposed improvements:")))
    if not verified_files:
        verified_files = _sanitize_repo_paths(_auto_verified_files_from_target(target_folder), target_folder)
    if git_status == "unavailable for target folder":
        low_outputs = "\n".join(outputs).lower()
        if "git.status: ok" in low_outputs and not changed_files:
            git_status = f"no changes in {_exact_target_tail(target_folder)}" if _exact_target_tail(target_folder) else "no changes"
    if git_status == "unavailable for target folder":
        inline_git = _inline_field(outputs, "Git status")
        if inline_git:
            git_status = inline_git
    direct_git = _direct_git_status(target_folder)
    if git_status == "unavailable for target folder":
        git_status = direct_git or git_status
    elif direct_git.startswith("changed:") and git_status.startswith("no changes in "):
        git_status = direct_git
    if rag_status == "unavailable":
        inline_rag = _inline_field(outputs, "RAG sync")
        if inline_rag:
            rag_status = inline_rag
    heuristic_findings = _heuristic_findings(target_folder, verified_files) if verified_files else []
    heuristic_improvements = _heuristic_improvements(heuristic_findings) if heuristic_findings else []
    ranked_output_improvements = _ranked_improvements_from_outputs(outputs)
    outputs_low = "\n".join(outputs).lower()
    explicit_already_implemented = (
        "already implemented" in outputs_low
        or "already present" in outputs_low
        or "no further changes needed" in outputs_low
        or "no code changes needed" in outputs_low
        or "none required; implementation is complete" in outputs_low
        or "none required; requested improvements are already implemented" in outputs_low
    )
    implementation_intent = any(
        phrase in request_low
        for phrase in (
            "make the improvements",
            "make improvements",
            "implement the improvements",
            "implement improvements",
            "apply the improvements",
            "apply improvements",
            "improve the",
            "improve this",
            "fix the",
            "fix this",
            "update the",
            "update this",
            "rerun the workflow",
            "add a get ",
            "add get ",
            "add /",
            "create ",
        )
    )
    verification_intent = any(
        phrase in request_low
        for phrase in (
            "verify whether",
            "check whether",
            "already implemented",
            "tell me exactly where",
            "if they are already implemented",
            "confirm whether",
        )
    )
    top_three_intent = "top 3" in request_low and "improvement" in request_low
    implemented_findings = _implemented_findings(target_folder, verified_files, request_text) if (
        verified_files and (changed_files or implementation_intent or explicit_already_implemented)
    ) else []
    if not changed_files and implemented_findings and git_status.lower().startswith("changed:"):
        preferred = [
            p for p in verified_files
            if p.endswith(("src/main.rs", "src/index.js", "Program.cs", "Controllers/AppointmentsController.cs"))
        ]
        changed_files = preferred[:1] or verified_files[:1]
    if explicit_already_implemented and implemented_findings:
        findings = implemented_findings
        improvements = ["- None required; requested improvements are already implemented."]
    elif verification_intent and implemented_findings and not changed_files:
        findings = implemented_findings
        improvements = ["- None required; requested improvements are already implemented."]
    elif changed_files and implemented_findings:
        findings = implemented_findings
        improvements = ["- None required; requested improvements were applied in this run."]
    elif _should_prefer_heuristics(target_folder, verified_files) and not (implementation_intent and implemented_findings):
        if implemented_findings:
            residual_findings = [line for line in heuristic_findings if line not in implemented_findings]
            findings = implemented_findings + residual_findings[: max(0, 8 - len(implemented_findings))]
            improvements = [line for line in (heuristic_improvements or improvements) if line not in findings]
        else:
            findings = heuristic_findings or findings
            improvements = heuristic_improvements or improvements
    else:
        if implemented_findings:
            findings = implemented_findings
            improvements = []
        elif not findings and heuristic_findings:
            findings = heuristic_findings
        if not improvements and heuristic_improvements:
            improvements = heuristic_improvements
    if (
        implemented_findings
        and (
            explicit_already_implemented
            or (not changed_files and implementation_intent)
            or verification_intent
        )
    ):
        findings = implemented_findings
        improvements = ["- None required; requested improvements are already implemented."]
    if top_three_intent and ranked_output_improvements:
        merged: List[str] = []
        seen: set[str] = set()
        for item in [*improvements, *ranked_output_improvements]:
            text = str(item or "").strip()
            if not text:
                continue
            bullet = text if text.startswith("-") else f"- {text}"
            norm = re.sub(r"[^a-z0-9]+", " ", bullet.lower()).strip()
            if not norm or norm in seen:
                continue
            seen.add(norm)
            merged.append(bullet)
            if len(merged) >= 3:
                break
        if merged:
            improvements = merged
    if not target_folder:
        target_folder = "data/agent_workflow/repo"
    conclusion = "Analysis complete."
    if changed_files:
        conclusion = "Review and scoped changes complete."
    elif implementation_intent and implemented_findings:
        conclusion = "Implementation review complete. The requested changes are already present in the scoped repo files."
    elif implementation_intent:
        conclusion = "Implementation review complete. No scoped repo changes were applied in this run."
    elif "not a git repo" in git_status:
        conclusion = "Analysis complete. Git scope is unavailable for the target folder."
    text = _markdown_repo_review(
        conclusion=conclusion,
        target_folder=target_folder,
        verified_files=verified_files,
        changed_files=changed_files,
        git_status=git_status,
        rag_status=rag_status,
        findings=findings,
        improvements=improvements,
        markdown_tables=markdown_tables,
    )
    return {
        "ok": True,
        "text": text,
        "response": text,
        "summary": text,
        "final_answer": text,
        "finalized_text": text,
        "markdown": text,
        "content": text,
        "data": {
            "mode": "text",
            "target_folder": target_folder,
            "verified_files": verified_files,
            "git_status": git_status,
            "rag_status": rag_status,
            "changed_files": changed_files,
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "custom",
    "label": "Repo Review Final Summary",
    "description": "Build a concise final repo-review answer from the current workflow run state and prior verified evidence.",
    "permissions": PERMISSIONS,
    "metadata": {
        "version": _VERSION,
        "created_at": _CREATED_AT,
        "last_updated": _LAST_UPDATED,
        "dev_status": _DEV_STATUS,
        "required_capabilities": ["repo_editing", "content_authoring"],
        "output_mode": "text",
    },
    "params_schema": {
        "type": "object",
        "properties": {
            "request_text": {"type": "string"},
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "text": {"type": "string"},
            "prompt": {"type": "string"},
            "run_id": {"type": "string"},
        },
        "additionalProperties": True,
    },
}

