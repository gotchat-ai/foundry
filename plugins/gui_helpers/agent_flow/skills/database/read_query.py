from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from .._path_common import resolve_path
except Exception:
    import importlib.util
    _P = Path(__file__).resolve().parent.parent / "_path_common.py"
    _S = importlib.util.spec_from_file_location("agent_flow_path_common", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    resolve_path = _M.resolve_path


NAME = "database.read_query"
PERMISSIONS = ["database.read_query", "database.*"]

_META = {
    "version": "1.0",
    "created_at": "2026-06-16T00:00:00+00:00",
    "last_updated": "2026-06-16T00:00:00+00:00",
    "dev_status": "tested",
    "test_status": {"state": "tested", "verified_by": "synthetic_workflow_harness", "verified_at": "2026-06-16T00:00:00+00:00"},
}

_READ_ONLY_RE = re.compile(r"^\s*(select|with|pragma|explain)\b", flags=re.IGNORECASE)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _rows_to_dicts(cursor, rows: List[Tuple[Any, ...]]) -> Tuple[List[str], List[Dict[str, Any]]]:
    columns = [str(col[0] or "") for col in (cursor.description or [])]
    out: List[Dict[str, Any]] = []
    for row in rows:
        item: Dict[str, Any] = {}
        for idx, key in enumerate(columns):
            item[key] = _json_safe(row[idx] if idx < len(row) else None)
        out.append(item)
    return columns, out


def _sqlite_query(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    db_path = resolve_path(ctx or {}, params or {}, str((params or {}).get("path") or "").strip())
    query = str(params.get("query") or "").strip()
    args = params.get("params") if isinstance(params.get("params"), (list, tuple)) else []
    limit = max(1, min(int(params.get("limit") or 200), 500))
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        cur.execute(query, tuple(args))
        rows = cur.fetchmany(limit)
        columns, records = _rows_to_dicts(cur, rows)
        return {
            "ok": True,
            "columns": columns,
            "rows": records,
            "data": {
                "driver": "sqlite",
                "path": str(db_path),
                "query": query,
                "columns": columns,
                "rows": records,
                "row_count": len(records),
                "truncated": len(records) >= limit,
            },
            "warnings": [],
        }
    finally:
        con.close()


def _external_query(params: Dict[str, Any]) -> Dict[str, Any]:
    driver = str(params.get("driver") or "").strip().lower()
    query = str(params.get("query") or "").strip()
    limit = max(1, min(int(params.get("limit") or 200), 500))
    args = params.get("params") if isinstance(params.get("params"), (list, tuple)) else []
    if driver == "postgres":
        try:
            import psycopg
        except Exception as exc:
            return {"ok": False, "data": {}, "warnings": [f"postgres_driver_unavailable:{exc}"]}
        conn = psycopg.connect(
            host=str(params.get("host") or "").strip(),
            port=int(params.get("port") or 5432),
            user=str(params.get("username") or "").strip(),
            password=str(params.get("password") or "").strip(),
            dbname=str(params.get("database") or "").strip(),
        )
    elif driver == "mysql":
        try:
            import mysql.connector
        except Exception as exc:
            return {"ok": False, "data": {}, "warnings": [f"mysql_driver_unavailable:{exc}"]}
        conn = mysql.connector.connect(
            host=str(params.get("host") or "").strip(),
            port=int(params.get("port") or 3306),
            user=str(params.get("username") or "").strip(),
            password=str(params.get("password") or "").strip(),
            database=str(params.get("database") or "").strip(),
        )
    else:
        return {"ok": False, "data": {}, "warnings": [f"unsupported_driver:{driver}"]}
    try:
        cur = conn.cursor()
        cur.execute(query, tuple(args))
        rows = cur.fetchmany(limit)
        columns = [str(col[0] or "") for col in (cur.description or [])]
        records = []
        for row in rows:
            item: Dict[str, Any] = {}
            for idx, key in enumerate(columns):
                item[key] = _json_safe(row[idx] if idx < len(row) else None)
            records.append(item)
        return {
            "ok": True,
            "columns": columns,
            "rows": records,
            "data": {
                "driver": driver,
                "query": query,
                "columns": columns,
                "rows": records,
                "row_count": len(records),
                "truncated": len(records) >= limit,
                "connection": {
                    "host": str(params.get("host") or "").strip(),
                    "port": int(params.get("port") or 0),
                    "database": str(params.get("database") or "").strip(),
                },
            },
            "warnings": [],
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    query = str(params.get("query") or "").strip()
    if not query:
        return {"ok": False, "data": {}, "warnings": ["query_required"]}
    if not _READ_ONLY_RE.search(query):
        return {"ok": False, "data": {"query": query}, "warnings": ["read_only_queries_only"]}
    try:
        if str(params.get("driver") or "sqlite").strip().lower() == "sqlite":
            if not str(params.get("path") or "").strip():
                return {"ok": False, "data": {}, "warnings": ["path_required"]}
            return _sqlite_query(ctx, params)
        return _external_query(params)
    except Exception as exc:
        return {
            "ok": False,
            "data": {"driver": str(params.get("driver") or "sqlite").strip().lower(), "query": query},
            "warnings": [f"database_read_failed:{exc}"],
        }


TOOL_SPEC = {
    "id": NAME,
    "category": "database",
    "label": "Database: Read Query",
    "description": "Execute read-only SQL against SQLite directly and optionally Postgres/MySQL when their drivers are installed.",
    "permissions": PERMISSIONS,
    "metadata": _META,
    "params_schema": {
        "type": "object",
        "properties": {
            "driver": {"type": "string", "enum": ["sqlite", "postgres", "mysql"]},
            "path": {"type": "string"},
            "query": {"type": "string"},
            "params": {"type": "array", "items": {}},
            "limit": {"type": "integer"},
            "host": {"type": "string"},
            "port": {"type": "integer"},
            "username": {"type": "string"},
            "password": {"type": "string"},
            "database": {"type": "string"},
        },
        "required": ["query"],
        "additionalProperties": True,
    },
}
