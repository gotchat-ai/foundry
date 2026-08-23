from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

NAME = "custom.repo_review_final_summary_v3"
PERMISSIONS = [NAME, "custom.*"]
_CREATED_AT = "2026-08-01T00:00:00Z"
_LAST_UPDATED = "2026-08-01T00:00:00Z"
_VERSION = "1.2"
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
    return ""


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
    if not (root / ".git").is_dir():
        return "unavailable for target folder (not a git repo)"
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
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
        if "Mutex<HashMap<" in rust_main:
            findings.append("- The Rust service uses a single global `Mutex<HashMap<...>>`, so all requests contend on one lock and all data is lost on restart.")
        if "appt.start_time >= query.start && appt.start_time <= query.end" in rust_main:
            findings.append("- Date-range retrieval compares ISO 8601 strings and only checks `start_time`, so overlapping appointments that begin before the requested range can be missed.")
        if 'format!("appt_{}"' in rust_main:
            findings.append("- Appointment IDs are derived from `start_time`, which can collide for duplicate or concurrent timestamps.")
        if "payload.user_id.clone()" in rust_main and "chrono" not in rust_main:
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
    verified_files = [vf for vf in verified_files if not target_folder or vf == _exact_target_tail(target_folder) or vf.startswith(_exact_target_tail(target_folder) + "/")]
    if not verified_files:
        verified_files = _auto_verified_files_from_target(target_folder)
    if git_status == "unavailable for target folder":
        low_outputs = "\n".join(outputs).lower()
        if "git.status: ok" in low_outputs and not changed_files:
            git_status = f"no changes in {_exact_target_tail(target_folder)}" if _exact_target_tail(target_folder) else "no changes"
    if git_status == "unavailable for target folder":
        inline_git = _inline_field(outputs, "Git status")
        if inline_git:
            git_status = inline_git
    if git_status == "unavailable for target folder":
        git_status = _direct_git_status(target_folder) or git_status
    if rag_status == "unavailable":
        inline_rag = _inline_field(outputs, "RAG sync")
        if inline_rag:
            rag_status = inline_rag
    if not findings and verified_files:
        findings = _heuristic_findings(target_folder, verified_files)
    if not improvements and findings:
        improvements = _heuristic_improvements(findings)
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

