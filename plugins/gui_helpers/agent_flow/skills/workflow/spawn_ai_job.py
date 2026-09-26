from __future__ import annotations

import json
import secrets
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List


NAME = "workflow.spawn_ai_job"
PERMISSIONS = ["workflow.spawn_ai_job", "workflow.*", "ai_jobs.*", "ai_router.*"]


def _dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _safe_int(value: Any, default: int, *, minimum: int = 0, maximum: int = 64) -> int:
    try:
        ivalue = int(value)
    except Exception:
        ivalue = int(default)
    return max(minimum, min(maximum, ivalue))


def _template(value: Any, params: Dict[str, Any], ctx: Dict[str, Any]) -> Any:
    if not isinstance(value, str):
        return value
    ext = _dict(ctx.get("ext"))
    run_id = str(
        params.get("run_id")
        or params.get("agent_flow_run_id")
        or params.get("workflow_run_id")
        or ext.get("run_id")
        or ext.get("agent_flow_run_id")
        or ""
    ).strip()
    pid = str(params.get("pid") or ctx.get("pid") or "").strip()
    sid = str(params.get("sid") or ctx.get("sid") or "").strip()
    request_text = str(ctx.get("user_text") or ctx.get("original_request") or params.get("request_text") or params.get("text") or "").strip()
    return (
        value.replace("{run_id}", run_id)
        .replace("{pid}", pid)
        .replace("{sid}", sid)
        .replace("{request_text}", request_text)
        .replace("{original_request}", request_text)
    )


def _skill_setting(app: Any, key: str, default: Any) -> Any:
    try:
        from plugins.gui_helpers.skills_settings import resolve_skill_setting

        return resolve_skill_setting(app, NAME, key, default)
    except Exception:
        return default


def _base_url(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    settings = _dict((ctx or {}).get("settings"))
    ext = _dict((ctx or {}).get("ext"))
    return str(
        (params or {}).get("base_url")
        or ext.get("base_url")
        or settings.get("download_base_url")
        or settings.get("server_url")
        or settings.get("__request_base_url")
        or "http://127.0.0.1:8000"
    ).rstrip("/")


def _http_json(base: str, token: str, method: str, path: str, payload: Any = None, *, enabled_plugins: str = "agent_flow", timeout: int = 120) -> Dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Gui-Enabled-Plugins": enabled_plugins,
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        raise RuntimeError(f"{method} {path} -> HTTP {getattr(exc, 'code', 'error')}: {body[:500]}") from exc


def _consume_sse(base: str, token: str, path: str, payload: Dict[str, Any], *, enabled_plugins: str, timeout: int = 0) -> Dict[str, Any]:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "X-Gui-Enabled-Plugins": enabled_plugins,
        },
        method="POST",
    )
    chunks: List[str] = []
    routers: List[Dict[str, Any]] = []
    done: Dict[str, Any] = {}
    with urllib.request.urlopen(req, timeout=max(1, int(timeout or 0)) if timeout else None) as resp:
        event = "message"
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                event = "message"
                continue
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip() or "message"
                continue
            if not line.startswith("data:"):
                continue
            text = line.split(":", 1)[1].strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except Exception:
                row = {"text": text}
            if isinstance(row, dict) and isinstance(row.get("text"), str):
                chunks.append(row.get("text") or "")
            row_event = str(row.get("event") or event or "").strip().lower() if isinstance(row, dict) else event
            if isinstance(row, dict) and row_event == "router":
                routers.append(row)
            if isinstance(row, dict) and (row.get("done") is True or row.get("event") == "done"):
                done = row
    return {"ok": True, "text": "".join(chunks), "routers": routers, "done": done}


def _router_result_from_sse(res: Dict[str, Any]) -> Dict[str, Any]:
    routers = res.get("routers") if isinstance(res.get("routers"), list) else []
    for row in reversed(routers):
        if not isinstance(row, dict):
            continue
        result = row.get("router_result")
        if isinstance(result, dict):
            return dict(result)
    done = res.get("done") if isinstance(res.get("done"), dict) else {}
    ext = done.get("ext") if isinstance(done.get("ext"), dict) else {}
    result = ext.get("router_result") if isinstance(ext.get("router_result"), dict) else None
    return dict(result or {})


def _summarize_router_artifacts(result: Dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return ""
    route_id = str(result.get("route_id") or "").strip() or "router"
    image_path = str(result.get("image_path") or "").strip()
    image_url = str(result.get("image_url") or "").strip()
    video_path = str(result.get("video_path") or "").strip()
    video_url = str(result.get("video_url") or "").strip()
    settings = result.get("gen_settings") if isinstance(result.get("gen_settings"), dict) else {}
    width = settings.get("width") or result.get("width")
    height = settings.get("height") or result.get("height")
    lines: List[str] = []
    if image_path or image_url:
        suffix = f" ({width}x{height})" if width and height else ""
        lines.append("## Router Artifacts")
        lines.append(f"- {route_id}: image - {image_path or image_url}{suffix}")
        if image_url and image_url != image_path:
            lines.append(f"- {route_id}: image_url - {image_url}")
    elif video_path or video_url:
        lines.append("## Router Artifacts")
        lines.append(f"- {route_id}: video - {video_path or video_url}")
        if video_url and video_url != video_path:
            lines.append(f"- {route_id}: video_url - {video_url}")
    return "\n".join(lines).strip()


def _app_settings(app: Any) -> Dict[str, Any]:
    settings: Dict[str, Any] = {}
    try:
        getter = getattr(getattr(app, "state", None), "settings", None)
        raw = getter() if callable(getter) else getter
        if isinstance(raw, dict):
            settings.update(raw)
    except Exception:
        pass
    try:
        registry = getattr(getattr(app, "state", None), "model_loader_registry", None)
        if registry is not None:
            settings["__model_loader_registry"] = registry
    except Exception:
        pass
    return settings


def _chat_llm(app: Any) -> Any:
    try:
        getter = getattr(getattr(app, "state", None), "model", None)
        model = getter() if callable(getter) else getter
        if model is not None:
            return model
    except Exception:
        pass
    try:
        provider = getattr(getattr(app, "state", None), "main_text_llm_provider", None)
        return provider() if callable(provider) else None
    except Exception:
        return None


def _run_route_direct(app: Any, route_id: str, payload: Dict[str, Any], ext: Dict[str, Any], *, pid: str, sid: str, token: str = "") -> Dict[str, Any]:
    from plugins.ai_routes import load_routes
    from plugins.ai_routes.base import RouterCore

    settings = _app_settings(app)
    settings.update(_dict(ext))
    settings["__server_app"] = app
    settings["__pid"] = str(settings.get("__pid") or settings.get("pid") or settings.get("project_id") or pid or "").strip()
    settings["__sid"] = str(settings.get("__sid") or settings.get("sid") or settings.get("session_id") or sid or "").strip()
    if token:
        headers = dict(settings.get("__request_headers") or {})
        headers.setdefault("authorization", f"Bearer {token}")
        headers.setdefault("X-Gui-Enabled-Plugins", "agent_flow,model_deck,collab_chat,ai_jobs")
        settings["__request_headers"] = headers
    core = RouterCore(
        chat_llm=_chat_llm(app),
        backend_type=str(payload.get("backend_type") or "auto"),
        settings=settings,
    )
    route_by_id = {route.route_id: route for route in (load_routes(core) or [])}
    route = route_by_id.get(route_id)
    if route is None:
        raise RuntimeError(f"route_not_found:{route_id}")
    req = SimpleNamespace(
        messages=payload.get("messages") if isinstance(payload.get("messages"), list) else [],
        ext=ext,
        route_id=route_id,
        router_enabled_plugins=payload.get("router_enabled_plugins") if isinstance(payload.get("router_enabled_plugins"), list) else [route_id],
        model=str(payload.get("model") or ""),
        backend_type=str(payload.get("backend_type") or "auto"),
    )
    return route.handle(req)


def _active_model(app: Any) -> Any:
    try:
        getter = getattr(getattr(app, "state", None), "model", None)
        return getter() if callable(getter) else getter
    except Exception:
        return None


def _configured_parallel(app: Any) -> int:
    try:
        getter = getattr(getattr(app, "state", None), "settings", None)
        settings = getter() if callable(getter) else getter
        if isinstance(settings, dict):
            return _safe_int(settings.get("per_model_parallel"), 1, minimum=1, maximum=64)
    except Exception:
        pass
    return 1


def _cap_for_backend(app: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    if params.get("max_concurrent_jobs") not in (None, ""):
        cap = _safe_int(params.get("max_concurrent_jobs"), 3, minimum=1, maximum=64)
        return {"cap": cap, "source": "params.max_concurrent_jobs", "backend_mode": "override"}

    active = _active_model(app)
    backend_mode = str(getattr(active, "backend_mode", "") or "").strip().lower()
    if backend_mode == "llama_server":
        configured = _configured_parallel(app)
        llama_parallel = getattr(active, "parallel_slots", None)
        llama_parallel = _safe_int(llama_parallel, 0, minimum=0, maximum=64) if llama_parallel not in (None, "") else 0
        cont_batching = getattr(active, "cont_batching", None)
        cap = configured
        if configured <= 1 and cont_batching is not False and llama_parallel > 0:
            cap = max(1, llama_parallel)
        return {
            "cap": max(1, cap),
            "source": "local_llama_server_parallel_slots",
            "backend_mode": backend_mode,
            "parallel_slots": llama_parallel or None,
            "per_model_parallel": configured,
            "cont_batching": cont_batching,
        }

    default_remote_cap = _safe_int(_skill_setting(app, "remote_max_concurrent_jobs", 3), 3, minimum=1, maximum=64)
    return {"cap": default_remote_cap, "source": "skills_settings.remote_max_concurrent_jobs", "backend_mode": backend_mode or "remote_or_unknown"}


def _runtime_state(app: Any) -> Dict[str, Any]:
    state = getattr(app, "state", None)
    row = getattr(state, "workflow_spawn_ai_job_state", None)
    if not isinstance(row, dict):
        row = {"lock": threading.Lock(), "active": {}, "route_locks": {}}
        setattr(state, "workflow_spawn_ai_job_state", row)
    if "lock" not in row or not hasattr(row.get("lock"), "acquire"):
        row["lock"] = threading.Lock()
    if not isinstance(row.get("active"), dict):
        row["active"] = {}
    if not isinstance(row.get("route_locks"), dict):
        row["route_locks"] = {}
    return row


def _route_lock(app: Any, route_id: str) -> threading.Lock:
    runtime = _runtime_state(app)
    key = str(route_id or "").strip() or "route"
    with runtime["lock"]:
        locks = runtime.setdefault("route_locks", {})
        lock = locks.get(key)
        if not hasattr(lock, "acquire"):
            lock = threading.Lock()
            locks[key] = lock
        return lock


def _active_job_ids(app: Any) -> set[str]:
    ids: set[str] = set()
    runtime = _runtime_state(app)
    now = time.time()
    with runtime["lock"]:
        active = runtime["active"]
        for job_id, row in list(active.items()):
            if not isinstance(row, dict):
                active.pop(job_id, None)
                continue
            if row.get("done"):
                active.pop(job_id, None)
                continue
            if now - float(row.get("started_ts") or now) > 24 * 3600:
                active.pop(job_id, None)
                continue
            ids.add(str(job_id))
    try:
        reg = getattr(getattr(app, "state", None), "ai_jobs", None)
        rows = reg.snapshot() if reg is not None and hasattr(reg, "snapshot") else []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or row.get("state") or "").strip().lower()
            if status in {"queued", "running", "pending"}:
                jid = str(row.get("job_id") or "").strip()
                if jid:
                    ids.add(jid)
    except Exception:
        pass
    return ids


def _active_count(app: Any) -> int:
    return len(_active_job_ids(app))


def _reserve(app: Any, job_id: str, meta: Dict[str, Any], cap: int) -> bool:
    runtime = _runtime_state(app)
    registry_ids = _active_job_ids(app)
    registry_ids.discard(str(job_id))
    if len(registry_ids) >= cap:
        return False
    with runtime["lock"]:
        active = runtime["active"]
        for old_id, row in list(active.items()):
            if not isinstance(row, dict) or row.get("done"):
                active.pop(old_id, None)
        if len(active) >= cap:
            return False
        active[job_id] = {**meta, "started_ts": time.time(), "done": False}
        return True


def _release(app: Any, job_id: str) -> None:
    runtime = _runtime_state(app)
    with runtime["lock"]:
        row = runtime["active"].get(job_id)
        if isinstance(row, dict):
            row["done"] = True
            row["finished_ts"] = time.time()
        runtime["active"].pop(job_id, None)


def _ensure_session(app: Any, pid: str, sid: str, username: str) -> None:
    db = getattr(getattr(app, "state", None), "collab_db", None)
    if db is None:
        return
    try:
        db.ensure_session(pid, sid, sid, username, is_public=False)
    except Exception:
        pass


def _token(app: Any, username: str) -> str:
    db = getattr(getattr(app, "state", None), "collab_db", None)
    if db is None or not hasattr(db, "issue_token"):
        raise RuntimeError("collab_db_token_unavailable")
    return str(db.issue_token(username, ttl_s=3600) or "")


def _mark_job(app: Any, job_id: str, **fields: Any) -> None:
    try:
        reg = getattr(getattr(app, "state", None), "ai_jobs", None)
        if reg is not None and hasattr(reg, "upsert"):
            reg.upsert(job_id, **fields)
    except Exception:
        pass


def _remove_job(app: Any, job_id: str) -> None:
    try:
        reg = getattr(getattr(app, "state", None), "ai_jobs", None)
        if reg is not None and hasattr(reg, "remove"):
            reg.remove(job_id)
    except Exception:
        pass


def _job_snapshot(app: Any, job_ids: List[str] | None = None) -> List[Dict[str, Any]]:
    wanted = {str(x or "").strip() for x in (job_ids or []) if str(x or "").strip()}
    rows: List[Dict[str, Any]] = []
    try:
        reg = getattr(getattr(app, "state", None), "ai_jobs", None)
        snapshot = reg.snapshot() if reg is not None and hasattr(reg, "snapshot") else []
        for row in snapshot or []:
            if not isinstance(row, dict):
                continue
            jid = str(row.get("job_id") or "").strip()
            if wanted and jid not in wanted:
                continue
            rows.append(dict(row))
    except Exception:
        pass
    return rows


def _status_summary(app: Any, params: Dict[str, Any], cap: int, cap_info: Dict[str, Any]) -> Dict[str, Any]:
    job_ids = [str(_template(x, params, {}) or "").strip() for x in _list(params.get("job_ids")) if str(_template(x, params, {}) or "").strip()]
    jobs = _job_snapshot(app, job_ids if job_ids else None)
    active = _active_count(app)
    return {
        "action": "status",
        "active": active,
        "cap": cap,
        "available": max(0, cap - active),
        "can_spawn": active < cap,
        "cap_info": cap_info,
        "jobs": jobs,
    }


def _wait_for_jobs(app: Any, params: Dict[str, Any], cap: int, cap_info: Dict[str, Any]) -> Dict[str, Any]:
    job_ids = [str(_template(x, params, {}) or "").strip() for x in _list(params.get("job_ids")) if str(_template(x, params, {}) or "").strip()]
    timeout_s = _safe_int(params.get("timeout_s"), 120, minimum=0, maximum=86400)
    poll_s = max(0.25, min(10.0, float(params.get("poll_interval_s") or 1.0)))
    terminal = {"completed", "error", "cancelled", "canceled", "failed"}
    deadline = time.time() + timeout_s
    jobs: List[Dict[str, Any]] = []
    while True:
        jobs = _job_snapshot(app, job_ids if job_ids else None)
        if job_ids:
            seen = {str(row.get("job_id") or "").strip() for row in jobs}
            for missing in [jid for jid in job_ids if jid not in seen]:
                jobs.append({"job_id": missing, "status": "missing"})
        statuses = [str(row.get("status") or row.get("state") or "").strip().lower() for row in jobs]
        if jobs and all(status in terminal or status == "missing" for status in statuses):
            break
        if timeout_s <= 0 or time.time() >= deadline:
            break
        time.sleep(poll_s)
    active = _active_count(app)
    completed = [row for row in jobs if str(row.get("status") or "").strip().lower() == "completed"]
    errors = [row for row in jobs if str(row.get("status") or "").strip().lower() in {"error", "failed"}]
    return {
        "action": "wait",
        "active": active,
        "cap": cap,
        "available": max(0, cap - active),
        "cap_info": cap_info,
        "jobs": jobs,
        "completed_count": len(completed),
        "error_count": len(errors),
        "all_done": bool(jobs) and len(completed) + len(errors) == len(jobs),
        "timed_out": bool(jobs) and any(str(row.get("status") or "").strip().lower() not in terminal for row in jobs),
    }


def _cleanup_terminal_jobs(app: Any, jobs: List[Dict[str, Any]]) -> List[str]:
    terminal = {"completed", "error", "cancelled", "canceled", "failed", "missing"}
    removed: List[str] = []
    for row in jobs:
        if not isinstance(row, dict):
            continue
        job_id = str(row.get("job_id") or "").strip()
        status = str(row.get("status") or row.get("state") or "").strip().lower()
        if not job_id or status not in terminal:
            continue
        _remove_job(app, job_id)
        removed.append(job_id)
    return removed


def _jobs_report(jobs: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
    title = str(params.get("report_title") or "Tracked spawned job report").strip()
    lines = [f"# {title}", ""]
    if not jobs:
        lines.append("No spawned job records were found.")
        return "\n".join(lines).strip()

    completed = 0
    failed = 0
    running = 0
    for row in jobs:
        status = str(row.get("status") or row.get("state") or "").strip().lower()
        if status == "completed":
            completed += 1
        elif status in {"error", "failed", "cancelled", "canceled"}:
            failed += 1
        else:
            running += 1

    lines.extend(
        [
            f"- Jobs: {len(jobs)}",
            f"- Completed: {completed}",
            f"- Running/queued: {running}",
            f"- Failed/cancelled: {failed}",
            "",
            "## Completed Todo List",
        ]
    )
    for row in jobs:
        job_id = str(row.get("job_id") or "").strip()
        flow_name = str(row.get("flow_name") or row.get("route_id") or row.get("kind") or "job").strip()
        status = str(row.get("status") or row.get("state") or "unknown").strip()
        mark = "[x]" if status.lower() == "completed" else "[ ]"
        lines.append(f"- {mark} {job_id} - {flow_name} - {status}")

    lines.extend(["", "## Worker Handoffs"])
    max_chars = _safe_int(params.get("result_chars"), 1600, minimum=120, maximum=6000)
    for row in jobs:
        job_id = str(row.get("job_id") or "").strip()
        result = str(row.get("result_text") or row.get("text") or "").strip()
        artifacts = str(row.get("artifact_text") or "").strip()
        error = str(row.get("error") or "").strip()
        lines.append(f"### {job_id}")
        if artifacts:
            lines.append(artifacts[:max_chars])
            if result and artifacts not in result:
                remaining = max(120, max_chars - len(artifacts[:max_chars]))
                lines.append("")
                lines.append(result[:remaining])
        elif result:
            lines.append(result[:max_chars])
        elif error:
            lines.append(f"Error: {error}")
        else:
            lines.append("No result text recorded yet.")
        lines.append("")
    return "\n".join(lines).strip()


def _iter_tool_results(value: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    def visit(obj: Any, depth: int = 0) -> None:
        if depth > 5:
            return
        if isinstance(obj, dict):
            tr = obj.get("tool_results")
            if isinstance(tr, list):
                for row in tr:
                    if isinstance(row, dict):
                        rows.append(dict(row))
            for key in (
                "final_result_out",
                "flow_step_report",
                "last_step_report",
                "report",
                "data",
                "result",
                "activity",
            ):
                child = obj.get(key)
                if isinstance(child, (dict, list)):
                    visit(child, depth + 1)
            steps = obj.get("steps")
            if isinstance(steps, list):
                visit(steps, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    visit(item, depth + 1)

    visit(value)
    return rows


def _summarize_child_artifacts(final_state: Dict[str, Any]) -> str:
    rows = _iter_tool_results(final_state)
    if not rows:
        return ""
    lines = ["## Child Workflow Artifacts"]
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        skill = str(row.get("skill") or "").strip() or "tool"
        ok = row.get("ok")
        status = "ok" if ok is not False else "failed"
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        warnings = row.get("warnings") if isinstance(row.get("warnings"), list) else []
        path = str(
            data.get("path")
            or data.get("output_path")
            or data.get("file_path")
            or data.get("target_path")
            or ""
        ).strip()
        changed = data.get("changed")
        extra = []
        if changed is not None:
            extra.append(f"changed={bool(changed)}")
        if warnings:
            extra.append("warnings=" + ",".join(str(x) for x in warnings[:3]))
        suffix = f" ({'; '.join(extra)})" if extra else ""
        if path:
            line = f"- {skill}: {status} - {path}{suffix}"
        else:
            summary = str(
                data.get("summary")
                or data.get("message")
                or data.get("status")
                or row.get("text")
                or ""
            ).strip()
            line = f"- {skill}: {status}" + (f" - {summary[:180]}" if summary else "")
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
        if len(lines) >= 40:
            lines.append("- ...")
            break
    return "\n".join(lines).strip() if len(lines) > 1 else ""


def _cancelled(app: Any, *job_ids: str) -> bool:
    try:
        cancelled = getattr(getattr(app, "state", None), "ai_jobs_cancelled", None)
        if isinstance(cancelled, dict):
            return any(bool(cancelled.get(str(job_id or ""))) for job_id in job_ids if str(job_id or ""))
    except Exception:
        pass
    return False


def _job_payload(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    jobs = params.get("jobs")
    if isinstance(jobs, list):
        return [dict(row) for row in jobs if isinstance(row, dict)]
    return [dict(params)]


def _common_ext(ctx: Dict[str, Any], params: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    ext = {}
    for src in (_dict((ctx or {}).get("ext")), _dict(params.get("ext")), _dict(job.get("ext"))):
        ext.update(src)
    return ext


def _project_flow_map(pid: str, flow_name: str) -> Dict[str, Any]:
    wanted = str(flow_name or "").strip()
    if not wanted:
        return {}
    try:
        root = Path(__file__).resolve().parents[5]
        path = root / "data" / "projects" / "agent_flow" / f"{str(pid or '').strip() or 'default'}.json"
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        flows = data.get("flows") if isinstance(data.get("flows"), dict) else data
        if isinstance(flows, dict) and isinstance(flows.get(wanted), dict):
            return {wanted: flows.get(wanted)}
    except Exception:
        pass
    return {}


def _spawn_workflow(app: Any, base: str, token: str, job_id: str, pid: str, sid: str, text: str, ext: Dict[str, Any], job: Dict[str, Any], username: str) -> None:
    flow_name = str(job.get("flow_name") or ext.get("agent_flow_active_flow") or ext.get("agent_flow_default_flow") or "").strip()
    flows = job.get("flows") if isinstance(job.get("flows"), dict) else ext.get("agent_flow_flows")
    if not isinstance(flows, dict) and flow_name:
        flows = _project_flow_map(pid, flow_name)
    if isinstance(flows, dict):
        ext["agent_flow_flows"] = flows
    if flow_name:
        ext["agent_flow_active_flow"] = flow_name
        ext["agent_flow_default_flow"] = flow_name
    if not ext.get("agent_flow_max_steps"):
        ext["agent_flow_max_steps"] = _safe_int(job.get("agent_flow_max_steps") or job.get("max_steps"), 12, minimum=1, maximum=128)
    ext["agent_flow_internal_run"] = False
    enabled = "agent_flow,ai_jobs"
    _mark_job(app, job_id, status="running", kind="agent_flow", owner_username=username, owner_alias=username, pid=pid, sid=sid, flow_name=flow_name or "Agent Flow")
    run_id = ""
    final_state: Dict[str, Any] = {}
    try:
        run = _http_json(base, token, "POST", f"/v1/projects/{pid}/sessions/{sid}/agent_flow/run", {"text": text, "ext": ext}, enabled_plugins=enabled, timeout=180)
        run_id = str(run.get("run_id") or "").strip()
        if run_id and run_id != job_id:
            _mark_job(app, job_id, run_id=run_id, status="running")
        poll_s = max(0.5, float(job.get("poll_interval_s") or 2.0))
        while run_id:
            if _cancelled(app, job_id, run_id):
                try:
                    cancelled = getattr(getattr(app, "state", None), "ai_jobs_cancelled", None)
                    if isinstance(cancelled, dict):
                        cancelled[run_id] = True
                except Exception:
                    pass
                break
            st = _http_json(base, token, "GET", f"/v1/projects/{pid}/sessions/{sid}/agent_flow/status?run_id={run_id}", None, enabled_plugins=enabled, timeout=60)
            state = st.get("state") if isinstance(st.get("state"), dict) else {}
            final_state = state
            if not state.get("running"):
                break
            time.sleep(poll_s)
        step_output = ""
        steps = final_state.get("steps") if isinstance(final_state.get("steps"), list) else []
        for step_row in reversed(steps):
            if not isinstance(step_row, dict):
                continue
            candidate = str(step_row.get("output") or step_row.get("text") or step_row.get("result_text") or "").strip()
            if candidate:
                step_output = candidate
                break
        result_text = str(
            step_output
            or final_state.get("final_result")
            or final_state.get("final_result_text")
            or final_state.get("result_text")
            or final_state.get("text")
            or ""
        ).strip()
        artifact_text = _summarize_child_artifacts(final_state)
        if artifact_text:
            result_text = "\n\n".join(part for part in (artifact_text, result_text) if part and part not in artifact_text).strip()
        _mark_job(
            app,
            job_id,
            status="completed",
            run_id=run_id,
            result_text=result_text[:8000],
            artifact_text=artifact_text[:8000],
            final_state=final_state,
        )
    except Exception as exc:
        _mark_job(app, job_id, status="error", error=str(exc), run_id=run_id)
    finally:
        _release(app, job_id)
        if not bool(job.get("keep_job_record")):
            _remove_job(app, job_id)


def _spawn_router(app: Any, base: str, token: str, job_id: str, pid: str, sid: str, text: str, ext: Dict[str, Any], job: Dict[str, Any], username: str) -> None:
    route_id = str(job.get("route_id") or ext.get("route_id") or "").strip()
    kind = "ai_router" if route_id and route_id.lower() not in {"chat", "none", "__none__"} else "messages"
    enabled = [str(x or "").strip() for x in _list(job.get("router_enabled_plugins") or ext.get("router_enabled_plugins")) if str(x or "").strip()]
    if route_id and route_id.lower() not in {"auto", "chat", "none", "__none__"} and route_id not in enabled:
        enabled.append(route_id)
    route_settings = _dict(ext.get("router_plugin_settings"))
    route_settings.update(_dict(job.get("router_plugin_settings")))
    ext["router_plugin_settings"] = route_settings
    ext["route_id"] = route_id or ext.get("route_id") or "chat"
    ext["router_enabled_plugins"] = enabled
    ext["base_url"] = ext.get("base_url") or base
    payload = {
        "model": str(job.get("model") or ""),
        "messages": job.get("messages") if isinstance(job.get("messages"), list) else [{"role": "user", "content": text}],
        "stream": True,
        "route_id": route_id or "chat",
        "router_enabled_plugins": enabled,
        "backend_type": str(job.get("backend_type") or "auto"),
        "ext": ext,
    }
    if job.get("temperature") not in (None, ""):
        payload["temperature"] = job.get("temperature")
    if job.get("max_tokens") not in (None, ""):
        payload["max_tokens"] = job.get("max_tokens")
    _mark_job(app, job_id, status="running", kind=kind, owner_username=username, owner_alias=username, pid=pid, sid=sid, route_id=route_id or "chat")
    try:
        direct_error = ""
        router_result: Dict[str, Any] = {}
        res: Dict[str, Any] = {}
        use_direct = bool(job.get("direct", True)) and bool(route_id) and route_id.lower() not in {"chat", "none", "__none__"}
        if use_direct:
            try:
                if route_id in {"image_gen", "video_gen"}:
                    with _route_lock(app, route_id):
                        out = _run_route_direct(app, route_id, payload, ext, pid=pid, sid=sid, token=token)
                else:
                    out = _run_route_direct(app, route_id, payload, ext, pid=pid, sid=sid, token=token)
                router_result = dict(out) if isinstance(out, dict) else {"route_id": route_id, "result_text": str(out or "")}
                res = {"ok": bool(router_result.get("ok", True)), "text": str(router_result.get("text") or router_result.get("answer") or router_result.get("message") or router_result.get("result_text") or "")}
            except Exception as exc:
                direct_error = str(exc)
        if not router_result:
            res = _consume_sse(base, token, "/v1/chat/completions_stream", payload, enabled_plugins=",".join(["ai_jobs", *enabled]) or "ai_jobs", timeout=_safe_int(job.get("timeout_s"), 0, minimum=0, maximum=86400))
            router_result = _router_result_from_sse(res if isinstance(res, dict) else {})
        artifact_text = _summarize_router_artifacts(router_result)
        result_text = str((res or {}).get("text") or "").strip()
        if not result_text and isinstance(router_result, dict):
            result_text = str(router_result.get("message") or router_result.get("answer") or router_result.get("result_text") or "")
        if direct_error and isinstance(router_result, dict):
            router_result.setdefault("direct_route_error", direct_error)
        route_ok = bool(router_result.get("ok", True)) if isinstance(router_result, dict) else True
        _mark_job(
            app,
            job_id,
            status="completed" if route_ok else "error",
            result_text=result_text[:8000],
            artifact_text=artifact_text[:8000],
            router_result=router_result,
            error="" if route_ok else str(router_result.get("error") or "router_failed"),
        )
    except Exception as exc:
        _mark_job(app, job_id, status="error", error=str(exc))
    finally:
        _release(app, job_id)
        if not bool(job.get("keep_job_record")):
            _remove_job(app, job_id)


def _spawn_mpc(app: Any, job_id: str, pid: str, sid: str, text: str, ctx: Dict[str, Any], job: Dict[str, Any], username: str) -> None:
    _mark_job(app, job_id, status="running", kind="mpc", route_id="mpc", owner_username=username, owner_alias=username, pid=pid, sid=sid)
    try:
        from plugins.gui_helpers.agent_flow.skills import build_agent_flow_tool_registry

        built = build_agent_flow_tool_registry(app)
        reg = built.get("registry") if isinstance(built, dict) else None
        if reg is None or not hasattr(reg, "call_tool"):
            raise RuntimeError("agent_flow_tool_registry_unavailable")
        params: Dict[str, Any] = {}
        params.update(_dict(job.get("params")))
        params["action"] = str(job.get("action") or params.get("action") or "call")
        if job.get("mpc_id") not in (None, ""):
            params["mpc_id"] = str(job.get("mpc_id") or "").strip()
        if job.get("mpc") not in (None, ""):
            params["mpc"] = job.get("mpc")
        if job.get("generic_mpc") not in (None, ""):
            params["generic_mpc"] = job.get("generic_mpc")
        if "request_text" not in params and "text" not in params and text:
            params["request_text"] = text
        timeout_s = _safe_int(job.get("timeout_s") or params.get("timeout_s"), 30, minimum=1, maximum=86400)
        params["timeout_s"] = timeout_s
        tool_ctx = {
            **ctx,
            "app": app,
            "pid": pid,
            "sid": sid,
            "user_text": text,
            "original_request": text,
            "mpc": job.get("mpc") if isinstance(job.get("mpc"), dict) else ctx.get("mpc"),
            "generic_mpc": job.get("generic_mpc") if isinstance(job.get("generic_mpc"), dict) else ctx.get("generic_mpc"),
        }
        res = reg.call_tool("mpc.generic_mpc", tool_ctx, params)
        ok = bool(res.get("ok")) if isinstance(res, dict) else False
        data = res.get("data") if isinstance(res, dict) and isinstance(res.get("data"), dict) else {}
        _mark_job(
            app,
            job_id,
            status="completed" if ok else "error",
            mpc_id=str((data.get("mpc") if isinstance(data.get("mpc"), dict) else {}).get("id") or params.get("mpc_id") or ""),
            result_text=str(data.get("text") or "")[:4000],
            error="" if ok else str((res or {}).get("error") if isinstance(res, dict) else "mpc_call_failed"),
        )
    except Exception as exc:
        _mark_job(app, job_id, status="error", error=str(exc))
    finally:
        _release(app, job_id)
        if not bool(job.get("keep_job_record")):
            _remove_job(app, job_id)


def _start_background(target: Any, *args: Any) -> None:
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = dict(ctx or {})
    params = dict(params or {})
    app = ctx.get("app")
    if app is None:
        return {"ok": False, "data": {}, "warnings": ["app_unavailable"]}

    action = str(params.get("action") or params.get("mode") or "spawn").strip().lower()

    pid = str(params.get("pid") or ctx.get("pid") or "project2").strip() or "project2"
    username = str(params.get("username") or ctx.get("username") or "admin").strip() or "admin"
    base = _base_url(ctx, params)
    cap_info = _cap_for_backend(app, params)
    cap = int(cap_info.get("cap") or 3)
    active = _active_count(app)
    if action in {"status", "capacity", "cap", "inspect"}:
        return {"ok": True, "data": _status_summary(app, params, cap, cap_info), "warnings": []}
    if action in {"wait", "join", "results", "result"}:
        data = _wait_for_jobs(app, params, cap, cap_info)
        warnings = ["wait_timed_out"] if data.get("timed_out") else []
        if data.get("error_count"):
            warnings.append("some_jobs_failed")
        return {"ok": not bool(data.get("error_count")), "data": data, "warnings": warnings}
    if action in {"report", "summary"}:
        data = _wait_for_jobs(app, params, cap, cap_info)
        data["report_text"] = _jobs_report(_list(data.get("jobs")), params)
        if bool(params.get("cleanup_after_report") or params.get("cleanup_completed_jobs")):
            data["cleaned_job_ids"] = _cleanup_terminal_jobs(app, _list(data.get("jobs")))
        warnings = ["wait_timed_out"] if data.get("timed_out") else []
        if data.get("error_count"):
            warnings.append("some_jobs_failed")
        return {
            "ok": not bool(data.get("error_count")),
            "text": str(data.get("report_text") or ""),
            "data": data,
            "warnings": warnings,
        }
    try:
        token = str(params.get("auth_token") or "") or _token(app, username)
    except Exception as exc:
        return {"ok": False, "data": {"base_url": base}, "warnings": [f"token_unavailable:{exc}"]}

    jobs = _job_payload(params)
    spawned: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for index, job in enumerate(jobs):
        active_before = _active_count(app)
        job_id = str(_template(job.get("job_id"), params, ctx) or f"spawn_{secrets.token_hex(8)}").strip()
        if active_before >= cap:
            skipped.append({"index": index, "job_id": job_id, "reason": "concurrency_cap_reached", "active": active_before, "cap": cap})
            continue
        kind = str(job.get("kind") or job.get("type") or params.get("kind") or "router").strip().lower()
        text = str(_template(job.get("text") or job.get("request_text") or job.get("prompt") or params.get("text") or params.get("request_text") or ctx.get("user_text") or ctx.get("original_request") or "", params, ctx) or "").strip()
        if not text and kind not in {"workflow"}:
            skipped.append({"index": index, "job_id": job_id, "reason": "missing_text"})
            continue
        sid = str(job.get("sid") or params.get("sid") or "").strip()
        if not sid or not bool(job.get("same_session")):
            sid = f"{str(params.get('sid_prefix') or 'spawn').strip() or 'spawn'}_{secrets.token_hex(4)}"
        ext = _common_ext(ctx, params, job)
        _ensure_session(app, pid, sid, username)
        if not _reserve(app, job_id, {"pid": pid, "sid": sid, "kind": kind}, cap):
            skipped.append({"index": index, "job_id": job_id, "reason": "concurrency_cap_reached", "active": _active_count(app), "cap": cap})
            continue
        if kind in {"workflow", "agent_flow", "flow"}:
            _start_background(_spawn_workflow, app, base, token, job_id, pid, sid, text, ext, job, username)
            public_kind = "agent_flow"
        elif kind in {"mpc", "generic_mpc"}:
            _start_background(_spawn_mpc, app, job_id, pid, sid, text, ctx, job, username)
            public_kind = "mpc"
        elif kind in {"router", "ai_router", "route", "plugin", "chat", "message", "ai_job"}:
            _start_background(_spawn_router, app, base, token, job_id, pid, sid, text, ext, job, username)
            public_kind = "ai_router" if kind not in {"chat", "message"} else "messages"
        else:
            _release(app, job_id)
            skipped.append({"index": index, "job_id": job_id, "reason": f"unsupported_kind:{kind}"})
            continue
        spawned.append({"index": index, "job_id": job_id, "pid": pid, "sid": sid, "kind": public_kind, "status": "started"})

    return {
        "ok": True,
        "data": {
            "spawned": spawned,
            "skipped": skipped,
            "active": _active_count(app),
            "cap": cap,
            "cap_info": cap_info,
        },
        "warnings": ["some_jobs_skipped"] if skipped else [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow: Spawn AI Job",
    "description": "Inspect capacity, start another chat/router/MPC/Agent Flow workflow concurrently, wait for spawned job results, or build a deterministic report from preserved job records. Call action=status first when planning fan-out; spawn respects local llama-server slots or the configured remote cap.",
    "permissions": PERMISSIONS,
    "metadata": {
        "version": "1.0",
        "dev_status": "tested",
        "settings_skill_id": NAME,
        "planning_guidance": (
            "For multiple independent subjects, first call action=status. "
            "Create one job per subject/task up to data.available. The jobs array may "
            "mix different job kinds in the same call: kind=mpc for any configured "
            "mpc.generic_mpc template, kind=workflow for any Agent Flow workflow, "
            "kind=router/ai_router for any AI router plugin, and kind=chat for a plain "
            "model turn. For MPC fan-out, prefer kind=mpc with mpc_id plus per-job text; "
            "use kind=workflow when the MPC call is one step inside a larger workflow. "
            "For orchestration workflows that need to stitch worker outputs, set "
            "keep_job_record=true and deterministic job_id values, then call action=wait "
            "with job_ids to retrieve completed worker result_text values or action=report "
            "to produce a deterministic completed-job report. "
            "Do not pack unrelated subjects into one job unless the user asked for a "
            "combined result."
        ),
    },
    "params_schema": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["workflow", "router", "ai_router", "chat", "ai_job", "mpc"]},
            "action": {
                "type": "string",
                "enum": ["status", "spawn", "wait", "join", "results", "report", "summary"],
                "description": "Use status/capacity before spawning to learn active, cap, and available concurrent job slots. Use wait/join/results with job_ids to retrieve spawned job outputs. Use report/summary to return a deterministic markdown report from preserved jobs.",
            },
            "mode": {
                "type": "string",
                "enum": ["status", "spawn", "wait", "join", "results", "report", "summary"],
                "description": "Alias for action.",
            },
            "text": {"type": "string"},
            "request_text": {"type": "string"},
            "route_id": {"type": "string"},
            "mpc_id": {"type": "string", "description": "Configured MPC id to call when kind=mpc, such as wikipedia_summary or weather_open_meteo."},
            "mpc": {"type": "object", "description": "Optional MPC config object containing an mpcs list.", "additionalProperties": True},
            "generic_mpc": {"type": "object", "description": "Legacy alias for MPC config.", "additionalProperties": True},
            "router_enabled_plugins": {"type": "array", "items": {"type": "string"}},
            "router_plugin_settings": {"type": "object", "additionalProperties": True},
            "flow_name": {"type": "string"},
            "flows": {"type": "object", "additionalProperties": True},
            "jobs": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "job_ids": {"type": "array", "items": {"type": "string"}},
            "report_title": {"type": "string"},
            "result_chars": {"type": "integer"},
            "keep_job_record": {"type": "boolean"},
            "timeout_s": {"type": "integer"},
            "poll_interval_s": {"type": "number"},
            "max_concurrent_jobs": {"type": "integer", "description": "Optional per-call override. Defaults to local llama-server parallel slots or remote skill setting."},
            "pid": {"type": "string"},
            "sid": {"type": "string"},
            "same_session": {"type": "boolean"},
            "base_url": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
