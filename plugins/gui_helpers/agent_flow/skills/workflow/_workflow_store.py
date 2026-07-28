from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


_TEMP_LIBRARY_PID = "__temp_library__"
_DEFAULT_PID = "__default__"


def _now_ts() -> int:
    return int(time.time())


def _app_paths(ctx: Dict[str, Any]) -> Tuple[Path, Path]:
    app = (ctx or {}).get("app") if isinstance(ctx, dict) else None
    data_dir_raw = getattr(getattr(app, "state", None), "data_dir", None) if app is not None else None
    workdir_raw = getattr(getattr(app, "state", None), "workdir", None) if app is not None else None
    data_dir = Path(str(data_dir_raw or "./data")).resolve()
    workdir = Path(str(workdir_raw or os.getcwd())).resolve()
    return data_dir, workdir


def _flows_dir(ctx: Dict[str, Any]) -> Path:
    data_dir, _ = _app_paths(ctx)
    path = data_dir / "projects" / "agent_flow"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _generated_dir(ctx: Dict[str, Any]) -> Path:
    data_dir, _ = _app_paths(ctx)
    path = data_dir / "generated" / "workflow_blueprints"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _temp_library_root(ctx: Dict[str, Any]) -> Path:
    root = _generated_dir(ctx) / "temp_library"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _project_flows_path(ctx: Dict[str, Any], pid: str) -> Path:
    safe_pid = re.sub(r"[^A-Za-z0-9_-]+", "", str(pid or "project2")) or "project2"
    return _flows_dir(ctx) / f"{safe_pid}.json"


def _default_flows_path(ctx: Dict[str, Any]) -> Path:
    return _flows_dir(ctx) / "default.json"


def _temp_index_path(ctx: Dict[str, Any]) -> Path:
    return _temp_library_root(ctx) / "index.json"


def _read_json_doc(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    for enc in ("utf-8", "utf-8-sig", "utf-16"):
        try:
            with path.open("r", encoding=enc) as fh:
                row = json.load(fh)
            return row if isinstance(row, dict) else {}
        except Exception:
            continue
    return {}


def _cross_env_path_uncheckable(path_str: str) -> bool:
    text = str(path_str or "").strip().replace("\\", "/")
    if not text:
        return False
    if os.name == "nt" and text.startswith("/app/"):
        return True
    return False


def _write_json_doc(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload if isinstance(payload, dict) else {}, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _db_path(ctx: Dict[str, Any]) -> Path:
    app = (ctx or {}).get("app") if isinstance(ctx, dict) else None
    collab_db = getattr(getattr(app, "state", None), "collab_db", None) if app is not None else None
    db_path = getattr(collab_db, "path", None)
    if isinstance(db_path, str) and db_path.strip():
        return Path(db_path).resolve()
    data_dir, _ = _app_paths(ctx)
    return (data_dir / "collab_chat.db").resolve()


def _connect(ctx: Dict[str, Any]) -> sqlite3.Connection:
    con = sqlite3.connect(str(_db_path(ctx)), check_same_thread=False)
    con.row_factory = sqlite3.Row
    _init_schema(con)
    return con


def _init_schema(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_flow_workflows (
            workflow_id TEXT PRIMARY KEY,
            pid TEXT NOT NULL,
            scope TEXT NOT NULL,
            flow_name TEXT NOT NULL,
            flow_json TEXT,
            bundle_dir TEXT,
            workflow_file TEXT,
            source_request TEXT,
            summary TEXT,
            description TEXT,
            tags_json TEXT NOT NULL DEFAULT '[]',
            validated INTEGER NOT NULL DEFAULT 0,
            all_passed INTEGER NOT NULL DEFAULT 0,
            pass_count INTEGER NOT NULL DEFAULT 0,
            fail_count INTEGER NOT NULL DEFAULT 0,
            validation_profile TEXT,
            generator_signature TEXT,
            registration_run_id TEXT,
            installed INTEGER NOT NULL DEFAULT 0,
            installed_ts INTEGER NOT NULL DEFAULT 0,
            installed_flow_name TEXT,
            installed_skill_files_json TEXT NOT NULL DEFAULT '[]',
            installed_skill_ids_json TEXT NOT NULL DEFAULT '[]',
            request_aliases_json TEXT NOT NULL DEFAULT '[]',
            last_request TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_ts INTEGER NOT NULL,
            updated_ts INTEGER NOT NULL
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_agent_flow_workflows_scope_pid_name ON agent_flow_workflows(scope, pid, flow_name)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_agent_flow_workflows_scope_pid_updated ON agent_flow_workflows(scope, pid, updated_ts DESC)")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_flow_workflow_updates (
            update_id TEXT PRIMARY KEY,
            workflow_id TEXT,
            pid TEXT NOT NULL,
            scope TEXT NOT NULL,
            flow_name TEXT NOT NULL,
            request_text TEXT,
            update_reason TEXT,
            update_target TEXT,
            status_label TEXT NOT NULL,
            pass_count INTEGER NOT NULL DEFAULT 0,
            fail_count INTEGER NOT NULL DEFAULT 0,
            validation_profile TEXT,
            summary TEXT,
            bugs_json TEXT NOT NULL DEFAULT '[]',
            skill_ids_json TEXT NOT NULL DEFAULT '[]',
            skill_files_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_ts INTEGER NOT NULL
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_agent_flow_workflow_updates_workflow ON agent_flow_workflow_updates(workflow_id, created_ts DESC)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_agent_flow_workflow_updates_scope_pid ON agent_flow_workflow_updates(scope, pid, created_ts DESC)")
    con.commit()


def _json_loads_list(raw: Any) -> List[Any]:
    if isinstance(raw, list):
        return list(raw)
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        row = json.loads(text)
    except Exception:
        return []
    return list(row) if isinstance(row, list) else []


def _json_loads_dict(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        row = json.loads(text)
    except Exception:
        return {}
    return dict(row) if isinstance(row, dict) else {}


def _row_to_record(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
    raw = dict(row or {})
    flow_json = _json_loads_dict(raw.get("flow_json"))
    metadata = _json_loads_dict(raw.get("metadata_json"))
    record = {
        "workflow_id": str(raw.get("workflow_id") or "").strip(),
        "id": str(raw.get("workflow_id") or "").strip(),
        "pid": str(raw.get("pid") or "").strip(),
        "scope": str(raw.get("scope") or "").strip(),
        "flow_name": str(raw.get("flow_name") or "").strip(),
        "flow_json": flow_json,
        "bundle_dir": str(raw.get("bundle_dir") or "").strip(),
        "workflow_file": str(raw.get("workflow_file") or "").strip(),
        "source_request": str(raw.get("source_request") or "").strip(),
        "summary": str(raw.get("summary") or "").strip(),
        "description": str(raw.get("description") or "").strip(),
        "tags": [str(x or "").strip() for x in _json_loads_list(raw.get("tags_json")) if str(x or "").strip()],
        "validated": bool(int(raw.get("validated") or 0)),
        "all_passed": bool(int(raw.get("all_passed") or 0)),
        "pass_count": int(raw.get("pass_count") or 0),
        "fail_count": int(raw.get("fail_count") or 0),
        "validation_profile": str(raw.get("validation_profile") or "").strip(),
        "generator_signature": str(raw.get("generator_signature") or "").strip(),
        "registration_run_id": str(raw.get("registration_run_id") or "").strip(),
        "installed": bool(int(raw.get("installed") or 0)),
        "installed_ts": int(raw.get("installed_ts") or 0),
        "installed_flow_name": str(raw.get("installed_flow_name") or "").strip(),
        "installed_skill_files": [str(x or "").strip() for x in _json_loads_list(raw.get("installed_skill_files_json")) if str(x or "").strip()],
        "installed_skill_ids": [str(x or "").strip() for x in _json_loads_list(raw.get("installed_skill_ids_json")) if str(x or "").strip()],
        "request_aliases": [str(x or "").strip() for x in _json_loads_list(raw.get("request_aliases_json")) if str(x or "").strip()],
        "last_request": str(raw.get("last_request") or "").strip(),
        "created_ts": int(raw.get("created_ts") or 0),
        "updated_ts": int(raw.get("updated_ts") or 0),
    }
    for key, value in metadata.items():
        if key not in record and value not in (None, "", [], {}):
            record[key] = value
    return record


def _scope_pid(scope: str, pid: str = "") -> str:
    scope_key = str(scope or "").strip().lower()
    if scope_key == "default":
        return _DEFAULT_PID
    if scope_key == "temp_library":
        return _TEMP_LIBRARY_PID
    return str(pid or "project2").strip() or "project2"


def _new_workflow_id(prefix: str = "wf") -> str:
    return f"{prefix}_{secrets.token_hex(12)}"


def _normalize_id_map(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    out: Dict[str, str] = {}
    for name, workflow_id in value.items():
        key = str(name or "").strip()
        row_id = str(workflow_id or "").strip()
        if key and row_id:
            out[key] = row_id
    return out


def _flow_hash(flow: Any) -> str:
    if not isinstance(flow, dict):
        return ""
    try:
        payload = json.dumps(flow, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except Exception:
        return ""
    return hashlib.sha256(payload).hexdigest()


def _fetch_scope_rows(ctx: Dict[str, Any], *, scope: str, pid: str) -> List[Dict[str, Any]]:
    wanted_pid = _scope_pid(scope, pid)
    con = _connect(ctx)
    try:
        rows = con.execute(
            """
            SELECT * FROM agent_flow_workflows
            WHERE scope=? AND pid=?
            ORDER BY updated_ts DESC, flow_name ASC, workflow_id ASC
            """,
            (str(scope or "").strip().lower(), wanted_pid),
        ).fetchall()
    finally:
        con.close()
    return [_row_to_record(row) for row in rows]


def _scope_query_sql(query: str) -> tuple[str, List[str]]:
    needle = str(query or "").strip()
    if not needle:
        return "", []
    like = f"%{needle.lower()}%"
    clause = """
        AND (
            lower(workflow_id) LIKE ? OR
            lower(flow_name) LIKE ? OR
            lower(description) LIKE ? OR
            lower(summary) LIKE ? OR
            lower(source_request) LIKE ? OR
            lower(bundle_dir) LIKE ?
        )
    """
    return clause, [like, like, like, like, like, like]


def fetch_scope_rows_page(
    ctx: Dict[str, Any],
    *,
    scope: str,
    pid: str,
    query: str = "",
    limit: int = 20,
    offset: int = 0,
) -> tuple[List[Dict[str, Any]], int]:
    wanted_pid = _scope_pid(scope, pid)
    scope_key = str(scope or "").strip().lower()
    limit = max(1, int(limit or 20))
    offset = max(0, int(offset or 0))
    where_sql, where_params = _scope_query_sql(query)
    con = _connect(ctx)
    try:
        total = int(
            con.execute(
                f"""
                SELECT COUNT(1)
                FROM agent_flow_workflows
                WHERE scope=? AND pid=? {where_sql}
                """,
                [scope_key, wanted_pid, *where_params],
            ).fetchone()[0]
        )
        rows = con.execute(
            f"""
            SELECT * FROM agent_flow_workflows
            WHERE scope=? AND pid=? {where_sql}
            ORDER BY updated_ts DESC, flow_name ASC, workflow_id ASC
            LIMIT ? OFFSET ?
            """,
            [scope_key, wanted_pid, *where_params, limit, offset],
        ).fetchall()
    finally:
        con.close()
    return ([_row_to_record(row) for row in rows], total)


def _fetch_record_by_id(ctx: Dict[str, Any], workflow_id: str) -> Optional[Dict[str, Any]]:
    wanted = str(workflow_id or "").strip()
    if not wanted:
        return None
    con = _connect(ctx)
    try:
        row = con.execute("SELECT * FROM agent_flow_workflows WHERE workflow_id=?", (wanted,)).fetchone()
    finally:
        con.close()
    return _row_to_record(row) if row else None


def _write_scope_rows(
    ctx: Dict[str, Any],
    *,
    scope: str,
    pid: str,
    records: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    scope_key = str(scope or "").strip().lower()
    wanted_pid = _scope_pid(scope_key, pid)
    now_ts = _now_ts()
    prepared: List[Dict[str, Any]] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        flow_name = str(row.get("flow_name") or "").strip()
        workflow_id = str(row.get("workflow_id") or row.get("id") or "").strip() or _new_workflow_id("wf")
        prepared.append(
            {
                **dict(row),
                "workflow_id": workflow_id,
                "id": workflow_id,
                "scope": scope_key,
                "pid": wanted_pid,
                "flow_name": flow_name,
                "created_ts": int(row.get("created_ts") or now_ts),
                "updated_ts": int(row.get("updated_ts") or now_ts),
            }
        )
    con = _connect(ctx)
    try:
        con.execute("DELETE FROM agent_flow_workflows WHERE scope=? AND pid=?", (scope_key, wanted_pid))
        for row in prepared:
            con.execute(
                """
                INSERT INTO agent_flow_workflows (
                    workflow_id, pid, scope, flow_name, flow_json, bundle_dir, workflow_file,
                    source_request, summary, description, tags_json, validated, all_passed,
                    pass_count, fail_count, validation_profile, generator_signature,
                    registration_run_id, installed, installed_ts, installed_flow_name,
                    installed_skill_files_json, installed_skill_ids_json, request_aliases_json,
                    last_request, metadata_json, created_ts, updated_ts
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row["workflow_id"],
                    wanted_pid,
                    scope_key,
                    str(row.get("flow_name") or "").strip(),
                    json.dumps(row.get("flow_json") if isinstance(row.get("flow_json"), dict) else {}, ensure_ascii=True, default=str),
                    str(row.get("bundle_dir") or "").strip(),
                    str(row.get("workflow_file") or "").strip(),
                    str(row.get("source_request") or "").strip(),
                    str(row.get("summary") or "").strip(),
                    str(row.get("description") or "").strip(),
                    json.dumps(row.get("tags") if isinstance(row.get("tags"), list) else [], ensure_ascii=True),
                    1 if row.get("validated") else 0,
                    1 if row.get("all_passed") else 0,
                    int(row.get("pass_count") or 0),
                    int(row.get("fail_count") or 0),
                    str(row.get("validation_profile") or "").strip(),
                    str(row.get("generator_signature") or "").strip(),
                    str(row.get("registration_run_id") or "").strip(),
                    1 if row.get("installed") else 0,
                    int(row.get("installed_ts") or 0),
                    str(row.get("installed_flow_name") or "").strip(),
                    json.dumps(row.get("installed_skill_files") if isinstance(row.get("installed_skill_files"), list) else [], ensure_ascii=True),
                    json.dumps(row.get("installed_skill_ids") if isinstance(row.get("installed_skill_ids"), list) else [], ensure_ascii=True),
                    json.dumps(row.get("request_aliases") if isinstance(row.get("request_aliases"), list) else [], ensure_ascii=True),
                    str(row.get("last_request") or "").strip(),
                    json.dumps({k: v for k, v in row.items() if k not in {
                        "workflow_id", "id", "pid", "scope", "flow_name", "flow_json", "bundle_dir", "workflow_file",
                        "source_request", "summary", "description", "tags", "validated", "all_passed",
                        "pass_count", "fail_count", "validation_profile", "generator_signature", "registration_run_id",
                        "installed", "installed_ts", "installed_flow_name", "installed_skill_files",
                        "installed_skill_ids", "request_aliases", "last_request", "created_ts", "updated_ts",
                    }}, ensure_ascii=True, default=str),
                    int(row.get("created_ts") or now_ts),
                    int(row.get("updated_ts") or now_ts),
                ),
            )
        con.commit()
    finally:
        con.close()
    return _fetch_scope_rows(ctx, scope=scope_key, pid=wanted_pid)


def _sync_project_legacy_file(ctx: Dict[str, Any], pid: str, records: List[Dict[str, Any]]) -> None:
    flows = {
        str(row.get("flow_name") or "").strip(): dict(row.get("flow_json") or {})
        for row in records
        if str(row.get("flow_name") or "").strip() and isinstance(row.get("flow_json"), dict)
    }
    _write_json_doc(_project_flows_path(ctx, pid), {"flows": flows})


def _sync_default_legacy_file(ctx: Dict[str, Any], records: List[Dict[str, Any]]) -> None:
    flows = {
        str(row.get("flow_name") or "").strip(): dict(row.get("flow_json") or {})
        for row in records
        if str(row.get("flow_name") or "").strip() and isinstance(row.get("flow_json"), dict)
    }
    _write_json_doc(_default_flows_path(ctx), {"flows": flows})


def _sync_temp_legacy_index(ctx: Dict[str, Any], records: List[Dict[str, Any]]) -> None:
    compat_rows: List[Dict[str, Any]] = []
    for row in records:
        compat = dict(row)
        compat.pop("workflow_id", None)
        compat["id"] = str(row.get("workflow_id") or row.get("id") or "").strip()
        compat.pop("scope", None)
        compat.pop("pid", None)
        compat.pop("flow_json", None)
        compat_rows.append(compat)
    _write_json_doc(_temp_index_path(ctx), {"records": compat_rows})


def _legacy_flow_candidates(ctx: Dict[str, Any]) -> List[Path]:
    here = Path(__file__).resolve()
    _, workdir = _app_paths(ctx)
    return [
        _default_flows_path(ctx),
        here.parents[4] / "data" / "projects" / "agent_flow" / "default.json",
        workdir / "llmloader2" / "data" / "projects" / "agent_flow" / "default.json",
        workdir / "data" / "projects" / "agent_flow" / "default.json",
    ]


def _import_legacy_project_flows(ctx: Dict[str, Any], pid: str) -> List[Dict[str, Any]]:
    path = _project_flows_path(ctx, pid)
    payload = _read_json_doc(path)
    flows = payload.get("flows") if isinstance(payload.get("flows"), dict) else {}
    if not flows:
        return []
    return replace_project_flows(ctx, pid, flows)


def _import_legacy_default_flows(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    for path in _legacy_flow_candidates(ctx):
        payload = _read_json_doc(path)
        flows = payload.get("flows") if isinstance(payload.get("flows"), dict) else {}
        if flows:
            return replace_default_flows(ctx, flows)
    return []


def _import_legacy_temp_library(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    payload = _read_json_doc(_temp_index_path(ctx))
    records = payload.get("records") if isinstance(payload.get("records"), list) else []
    if not records:
        return []
    now_ts = _now_ts()
    prepared: List[Dict[str, Any]] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        workflow_id = str(row.get("id") or row.get("workflow_id") or "").strip() or _new_workflow_id("wf")
        prepared.append(
            {
                **dict(row),
                "workflow_id": workflow_id,
                "id": workflow_id,
                "flow_name": str(row.get("flow_name") or "").strip(),
                "flow_json": {},
                "created_ts": int(row.get("created_ts") or row.get("updated_ts") or now_ts),
                "updated_ts": int(row.get("updated_ts") or now_ts),
            }
        )
    rows = _write_scope_rows(ctx, scope="temp_library", pid=_TEMP_LIBRARY_PID, records=prepared)
    _sync_temp_legacy_index(ctx, rows)
    return rows


def load_project_flows(ctx: Dict[str, Any], pid: str = "project2") -> Dict[str, Any]:
    rows = _fetch_scope_rows(ctx, scope="project", pid=pid)
    if not rows:
        rows = _import_legacy_project_flows(ctx, pid)
    return {
        str(row.get("flow_name") or "").strip(): dict(row.get("flow_json") or {})
        for row in rows
        if str(row.get("flow_name") or "").strip() and isinstance(row.get("flow_json"), dict)
    }


def _replace_scope_flows(
    ctx: Dict[str, Any],
    *,
    scope: str,
    pid: str,
    flows: Dict[str, Any],
    prior_ids_by_name: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    existing_rows = _fetch_scope_rows(ctx, scope=scope, pid=pid)
    existing = {str(row.get("flow_name") or "").strip(): row for row in existing_rows}
    existing_by_id = {
        str(row.get("workflow_id") or row.get("id") or "").strip(): row
        for row in existing_rows
        if str(row.get("workflow_id") or row.get("id") or "").strip()
    }
    existing_hash_rows: Dict[str, List[Dict[str, Any]]] = {}
    for row in existing_rows:
        row_hash = _flow_hash(row.get("flow_json") or {})
        if row_hash:
            existing_hash_rows.setdefault(row_hash, []).append(row)
    prior_map = _normalize_id_map(prior_ids_by_name)
    claimed_ids: set[str] = set()
    now_ts = _now_ts()
    records: List[Dict[str, Any]] = []
    for name, flow in (flows or {}).items():
        flow_name = str(name or "").strip()
        if not flow_name or not isinstance(flow, dict):
            continue
        prior = existing.get(flow_name) or {}
        prior_id = str(prior.get("workflow_id") or prior.get("id") or "").strip()
        if not prior and prior_map.get(flow_name):
            hinted = existing_by_id.get(str(prior_map.get(flow_name) or "").strip()) or {}
            hinted_id = str(hinted.get("workflow_id") or hinted.get("id") or "").strip()
            if hinted_id and hinted_id not in claimed_ids:
                prior = hinted
                prior_id = hinted_id
        if not prior:
            flow_hash = _flow_hash(flow)
            matches = [
                row for row in existing_hash_rows.get(flow_hash, [])
                if str(row.get("workflow_id") or row.get("id") or "").strip() not in claimed_ids
            ]
            if len(matches) == 1:
                prior = matches[0]
                prior_id = str(prior.get("workflow_id") or prior.get("id") or "").strip()
        workflow_id = str(prior.get("workflow_id") or prior.get("id") or "").strip() or _new_workflow_id("wf")
        claimed_ids.add(workflow_id)
        records.append(
            {
                **prior,
                "workflow_id": workflow_id,
                "id": workflow_id,
                "flow_name": flow_name,
                "flow_json": dict(flow),
                "created_ts": int(prior.get("created_ts") or now_ts),
                "updated_ts": now_ts,
            }
        )
    return _write_scope_rows(ctx, scope=scope, pid=pid, records=records)


def replace_project_flows(
    ctx: Dict[str, Any],
    pid: str,
    flows: Dict[str, Any],
    prior_ids_by_name: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    rows = _replace_scope_flows(ctx, scope="project", pid=pid, flows=flows, prior_ids_by_name=prior_ids_by_name)
    _sync_project_legacy_file(ctx, pid, rows)
    return rows


def project_flow_records(ctx: Dict[str, Any], pid: str = "project2") -> List[Dict[str, Any]]:
    rows = _fetch_scope_rows(ctx, scope="project", pid=pid)
    if not rows:
        rows = _import_legacy_project_flows(ctx, pid)
    return rows


def load_default_flows(ctx: Dict[str, Any]) -> Dict[str, Any]:
    rows = _fetch_scope_rows(ctx, scope="default", pid=_DEFAULT_PID)
    if not rows:
        rows = _import_legacy_default_flows(ctx)
    return {
        str(row.get("flow_name") or "").strip(): dict(row.get("flow_json") or {})
        for row in rows
        if str(row.get("flow_name") or "").strip() and isinstance(row.get("flow_json"), dict)
    }


def replace_default_flows(
    ctx: Dict[str, Any],
    flows: Dict[str, Any],
    prior_ids_by_name: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    rows = _replace_scope_flows(ctx, scope="default", pid=_DEFAULT_PID, flows=flows, prior_ids_by_name=prior_ids_by_name)
    _sync_default_legacy_file(ctx, rows)
    return rows


def default_flow_records(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = _fetch_scope_rows(ctx, scope="default", pid=_DEFAULT_PID)
    if not rows:
        rows = _import_legacy_default_flows(ctx)
    return rows


def list_temp_library_records(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = _fetch_scope_rows(ctx, scope="temp_library", pid=_TEMP_LIBRARY_PID)
    if not rows:
        rows = _import_legacy_temp_library(ctx)
    cleaned: List[Dict[str, Any]] = []
    dirty = False
    for row in rows:
        bundle_dir_str = str(row.get("bundle_dir") or "").strip()
        workflow_file_str = str(row.get("workflow_file") or "").strip()
        if _cross_env_path_uncheckable(bundle_dir_str) or _cross_env_path_uncheckable(workflow_file_str):
            cleaned.append(row)
            continue
        bundle_dir = Path(bundle_dir_str) if bundle_dir_str else None
        workflow_file = Path(workflow_file_str) if workflow_file_str else None
        if not bundle_dir or not bundle_dir.is_dir() or not workflow_file or not workflow_file.is_file():
            dirty = True
            continue
        cleaned.append(row)
    if dirty:
        _write_scope_rows(ctx, scope="temp_library", pid=_TEMP_LIBRARY_PID, records=cleaned)
        _sync_temp_legacy_index(ctx, cleaned)
    return cleaned


def get_temp_library_record(ctx: Dict[str, Any], record_id: str) -> Optional[Dict[str, Any]]:
    row = _fetch_record_by_id(ctx, record_id)
    if row and str(row.get("scope") or "").strip() == "temp_library":
        return row
    return None


def replace_temp_library_records(ctx: Dict[str, Any], records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = _write_scope_rows(ctx, scope="temp_library", pid=_TEMP_LIBRARY_PID, records=records)
    _sync_temp_legacy_index(ctx, rows)
    return rows


def upsert_temp_library_record(ctx: Dict[str, Any], record: Dict[str, Any]) -> Dict[str, Any]:
    rows = list_temp_library_records(ctx)
    wanted = str((record or {}).get("workflow_id") or (record or {}).get("id") or "").strip()
    now_ts = _now_ts()
    next_rows: List[Dict[str, Any]] = []
    updated: Optional[Dict[str, Any]] = None
    for row in rows:
        row_id = str(row.get("workflow_id") or row.get("id") or "").strip()
        if wanted and row_id == wanted and updated is None:
            merged = {**row, **dict(record or {})}
            merged["workflow_id"] = wanted
            merged["id"] = wanted
            merged["updated_ts"] = int(merged.get("updated_ts") or now_ts)
            next_rows.append(merged)
            updated = merged
            continue
        next_rows.append(row)
    if updated is None:
        merged = dict(record or {})
        workflow_id = wanted or _new_workflow_id("wf")
        merged["workflow_id"] = workflow_id
        merged["id"] = workflow_id
        merged["created_ts"] = int(merged.get("created_ts") or now_ts)
        merged["updated_ts"] = int(merged.get("updated_ts") or now_ts)
        next_rows.append(merged)
        updated = merged
    rows2 = replace_temp_library_records(ctx, next_rows)
    for row in rows2:
        if str(row.get("workflow_id") or "").strip() == str(updated.get("workflow_id") or "").strip():
            return row
    return updated


def delete_temp_library_record(ctx: Dict[str, Any], record_id: str) -> Optional[Dict[str, Any]]:
    rows = list_temp_library_records(ctx)
    wanted = str(record_id or "").strip()
    next_rows: List[Dict[str, Any]] = []
    removed: Optional[Dict[str, Any]] = None
    for row in rows:
        row_id = str(row.get("workflow_id") or row.get("id") or "").strip()
        if row_id == wanted and removed is None:
            removed = row
            continue
        next_rows.append(row)
    if removed is None:
        return None
    replace_temp_library_records(ctx, next_rows)
    return removed


def flow_ids_by_name(records: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in records:
        if not isinstance(row, dict):
            continue
        name = str(row.get("flow_name") or "").strip()
        workflow_id = str(row.get("workflow_id") or row.get("id") or "").strip()
        if name and workflow_id and name not in out:
            out[name] = workflow_id
    return out


def record_workflow_update(ctx: Dict[str, Any], entry: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(entry or {})
    now_ts = _now_ts()
    update_id = str(row.get("update_id") or "").strip() or _new_workflow_id("wfu")
    scope = str(row.get("scope") or "project").strip().lower() or "project"
    pid = _scope_pid(scope, str(row.get("pid") or "project2").strip() or "project2")
    payload = {
        "update_id": update_id,
        "workflow_id": str(row.get("workflow_id") or "").strip(),
        "pid": pid,
        "scope": scope,
        "flow_name": str(row.get("flow_name") or "").strip(),
        "request_text": str(row.get("request_text") or "").strip(),
        "update_reason": str(row.get("update_reason") or "").strip(),
        "update_target": str(row.get("update_target") or "").strip(),
        "status_label": str(row.get("status_label") or "needs_improvements").strip() or "needs_improvements",
        "pass_count": int(row.get("pass_count") or 0),
        "fail_count": int(row.get("fail_count") or 0),
        "validation_profile": str(row.get("validation_profile") or "").strip(),
        "summary": str(row.get("summary") or "").strip(),
        "bugs": row.get("bugs") if isinstance(row.get("bugs"), list) else [],
        "skill_ids": row.get("skill_ids") if isinstance(row.get("skill_ids"), list) else [],
        "skill_files": row.get("skill_files") if isinstance(row.get("skill_files"), list) else [],
        "metadata": row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
        "created_ts": int(row.get("created_ts") or now_ts),
    }
    con = _connect(ctx)
    try:
        con.execute(
            """
            INSERT INTO agent_flow_workflow_updates (
                update_id, workflow_id, pid, scope, flow_name, request_text, update_reason,
                update_target, status_label, pass_count, fail_count, validation_profile,
                summary, bugs_json, skill_ids_json, skill_files_json, metadata_json, created_ts
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payload["update_id"],
                payload["workflow_id"],
                payload["pid"],
                payload["scope"],
                payload["flow_name"],
                payload["request_text"],
                payload["update_reason"],
                payload["update_target"],
                payload["status_label"],
                payload["pass_count"],
                payload["fail_count"],
                payload["validation_profile"],
                payload["summary"],
                json.dumps(payload["bugs"], ensure_ascii=True, default=str),
                json.dumps(payload["skill_ids"], ensure_ascii=True, default=str),
                json.dumps(payload["skill_files"], ensure_ascii=True, default=str),
                json.dumps(payload["metadata"], ensure_ascii=True, default=str),
                payload["created_ts"],
            ),
        )
        con.commit()
    finally:
        con.close()
    return payload


def list_workflow_updates(
    ctx: Dict[str, Any],
    *,
    workflow_id: str = "",
    flow_name: str = "",
    scope: str = "",
    pid: str = "",
    limit: int = 50,
) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    values: List[Any] = []
    wanted_workflow_id = str(workflow_id or "").strip()
    wanted_flow_name = str(flow_name or "").strip()
    wanted_scope = str(scope or "").strip().lower()
    wanted_pid = str(pid or "").strip()
    if wanted_workflow_id:
        clauses.append("workflow_id=?")
        values.append(wanted_workflow_id)
    if wanted_flow_name:
        clauses.append("flow_name=?")
        values.append(wanted_flow_name)
    if wanted_scope:
        clauses.append("scope=?")
        values.append(wanted_scope)
    if wanted_pid:
        clauses.append("pid=?")
        values.append(_scope_pid(wanted_scope or "project", wanted_pid))
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    con = _connect(ctx)
    try:
        rows = con.execute(
            f"""
            SELECT * FROM agent_flow_workflow_updates
            {where_sql}
            ORDER BY created_ts DESC, update_id DESC
            LIMIT ?
            """,
            (*values, max(1, int(limit or 50))),
        ).fetchall()
    finally:
        con.close()
    out: List[Dict[str, Any]] = []
    for row in rows:
        raw = dict(row or {})
        out.append(
            {
                "update_id": str(raw.get("update_id") or "").strip(),
                "workflow_id": str(raw.get("workflow_id") or "").strip(),
                "pid": str(raw.get("pid") or "").strip(),
                "scope": str(raw.get("scope") or "").strip(),
                "flow_name": str(raw.get("flow_name") or "").strip(),
                "request_text": str(raw.get("request_text") or "").strip(),
                "update_reason": str(raw.get("update_reason") or "").strip(),
                "update_target": str(raw.get("update_target") or "").strip(),
                "status_label": str(raw.get("status_label") or "").strip(),
                "pass_count": int(raw.get("pass_count") or 0),
                "fail_count": int(raw.get("fail_count") or 0),
                "validation_profile": str(raw.get("validation_profile") or "").strip(),
                "summary": str(raw.get("summary") or "").strip(),
                "bugs": _json_loads_list(raw.get("bugs_json")),
                "skill_ids": _json_loads_list(raw.get("skill_ids_json")),
                "skill_files": _json_loads_list(raw.get("skill_files_json")),
                "metadata": _json_loads_dict(raw.get("metadata_json")),
                "created_ts": int(raw.get("created_ts") or 0),
            }
        )
    return out
