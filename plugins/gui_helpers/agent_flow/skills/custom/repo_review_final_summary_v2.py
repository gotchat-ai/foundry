from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

NAME = "custom.repo_review_final_summary_v2"
PERMISSIONS = [NAME, "custom.*"]
_CREATED_AT = "2026-08-01T00:00:00Z"
_LAST_UPDATED = "2026-08-01T00:00:00Z"
_VERSION = "1.1"
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


def _step_outputs(state: Dict[str, Any]) -> List[str]:
    outs: List[str] = []
    for step in state.get("steps") if isinstance(state.get("steps"), list) else []:
        if not isinstance(step, dict):
            continue
        out = str(step.get("output") or "").strip()
        if out:
            outs.append(out)
    return outs


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
            if in_section and s.startswith("-"):
                item = s if s.startswith("- ") else f"- {s.lstrip('-').strip()}"
                if item not in out_rows:
                    out_rows.append(item)
    return out_rows


def _git_status(outputs: List[str], target_folder: str, tool_rows: List[Dict[str, Any]]) -> str:
    target_tail = target_folder.split("data/agent_workflow/repo/", 1)[-1].strip("/") if "data/agent_workflow/repo/" in target_folder else target_folder.strip("/")
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
    for out in reversed(outputs):
        low = out.lower()
        if "git status shows the repo is clean" in low or "repo is clean" in low:
            return f"no changes in {target_tail}" if target_tail else "no changes"
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
        if "calendar-tool-light-nodejs/src/index.js" in low and "nodejs" not in low:
            continue
        if low.startswith("- inspect repo scope:"):
            continue
        if low.startswith("- call "):
            continue
        if low.startswith("- report "):
            continue
        if low.startswith("- handoff"):
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
    tool_rows = _step_tool_rows(state)
    target_folder = _target_folder(request_text, outputs, state, tool_rows)
    verified_files = _verified_files(outputs, target_folder, tool_rows)
    git_status = _git_status(outputs, target_folder, tool_rows) or "unavailable for target folder"
    rag_status = _rag_status(outputs, target_folder, tool_rows) or "unavailable"
    changed_files = _changed_files(outputs, target_folder, tool_rows)
    findings = _clean_lines(_collect_section_lines(outputs, ("bugs:", "findings:")))
    improvements = _clean_lines(_collect_section_lines(outputs, ("fixes:", "proposed improvements:")))
    if not target_folder:
        target_folder = "data/agent_workflow/repo"
    conclusion = "Analysis complete."
    if changed_files:
        conclusion = "Review and scoped changes complete."
    elif "not a git repo" in git_status:
        conclusion = "Analysis complete. Git scope is unavailable for the target folder."
    lines = [conclusion, "", f"Target folder: {target_folder}"]
    lines.append("Verified files: " + (", ".join(verified_files) if verified_files else "none"))
    lines.append(f"Git status: {git_status}")
    lines.append(f"RAG sync: {rag_status}")
    lines.append("Changed files: " + (", ".join(changed_files) if changed_files else "none"))
    if findings:
        lines.append("Findings:")
        lines.extend(findings[:8])
    if improvements:
        lines.append("Proposed improvements:")
        lines.extend(improvements[:8])
    text = "\n".join(lines).strip()
    return {
        "ok": True,
        "text": text,
        "summary": text,
        "final_answer": text,
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

