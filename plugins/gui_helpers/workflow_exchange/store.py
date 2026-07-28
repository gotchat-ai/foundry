from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def _workdir_from_app(app) -> Path:
    raw = getattr(getattr(app, "state", None), "workdir", None)
    if isinstance(raw, str) and raw.strip():
        return Path(raw).resolve()
    return Path(".").resolve()


def data_root(app) -> Path:
    root = _workdir_from_app(app) / "llmloader2" / "data" / "workflow_exchange"
    root.mkdir(parents=True, exist_ok=True)
    return root


def imports_index_path(app) -> Path:
    return data_root(app) / "imports_index.json"


def published_index_path(app) -> Path:
    return data_root(app) / "published_index.json"


def mirrors_index_path(app) -> Path:
    return data_root(app) / "mirrors_index.json"


def public_index_path(app) -> Path:
    return data_root(app) / "public_index.json"


def identity_path(app) -> Path:
    return data_root(app) / "identity.json"


def now_ts() -> int:
    return int(time.time())


def read_imports_index(app) -> Dict[str, Any]:
    path = imports_index_path(app)
    if not path.is_file():
        return {"records": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"records": []}
    if not isinstance(payload, dict):
        return {"records": []}
    if not isinstance(payload.get("records"), list):
        payload["records"] = []
    return payload


def write_imports_index(app, payload: Dict[str, Any]) -> None:
    path = imports_index_path(app)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def read_published_index(app) -> Dict[str, Any]:
    path = published_index_path(app)
    if not path.is_file():
        return {"records": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"records": []}
    if not isinstance(payload, dict):
        return {"records": []}
    if not isinstance(payload.get("records"), list):
        payload["records"] = []
    return payload


def write_published_index(app, payload: Dict[str, Any]) -> None:
    path = published_index_path(app)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def read_public_index(app) -> Dict[str, Any]:
    path = public_index_path(app)
    if not path.is_file():
        return {"records": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"records": []}
    if not isinstance(payload, dict):
        return {"records": []}
    if not isinstance(payload.get("records"), list):
        payload["records"] = []
    return payload


def write_public_index(app, payload: Dict[str, Any]) -> None:
    path = public_index_path(app)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def read_identity(app) -> Dict[str, Any]:
    path = identity_path(app)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_identity(app, payload: Dict[str, Any]) -> None:
    path = identity_path(app)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def get_or_create_public_identity(app) -> Dict[str, Any]:
    payload = read_identity(app)
    anon_seed = str(payload.get("anon_seed") or "").strip()
    publisher_id = str(payload.get("publisher_id") or "").strip()
    if anon_seed and publisher_id:
        return {"anon_seed": anon_seed, "publisher_id": publisher_id}
    anon_seed = secrets.token_hex(16)
    publisher_id = f"anon-{secrets.token_hex(8)}"
    payload = {"anon_seed": anon_seed, "publisher_id": publisher_id, "created_ts": now_ts()}
    write_identity(app, payload)
    return {"anon_seed": anon_seed, "publisher_id": publisher_id}


def read_mirrors_index(app) -> Dict[str, Any]:
    path = mirrors_index_path(app)
    if not path.is_file():
        return {"peers": [], "records": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"peers": [], "records": []}
    if not isinstance(payload, dict):
        return {"peers": [], "records": []}
    if not isinstance(payload.get("peers"), list):
        payload["peers"] = []
    if not isinstance(payload.get("records"), list):
        payload["records"] = []
    return payload


def write_mirrors_index(app, payload: Dict[str, Any]) -> None:
    path = mirrors_index_path(app)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def list_import_records(app) -> List[Dict[str, Any]]:
    payload = read_imports_index(app)
    rows = [dict(row) for row in (payload.get("records") or []) if isinstance(row, dict)]
    return sorted(rows, key=lambda row: int(row.get("updated_ts") or 0), reverse=True)


def get_import_record(app, import_id: str) -> Optional[Dict[str, Any]]:
    wanted = str(import_id or "").strip()
    if not wanted:
        return None
    for row in list_import_records(app):
        if str(row.get("id") or "").strip() == wanted:
            return row
    return None


def upsert_import_record(app, record: Dict[str, Any]) -> Dict[str, Any]:
    payload = read_imports_index(app)
    rows = payload.get("records") if isinstance(payload.get("records"), list) else []
    wanted = str((record or {}).get("id") or "").strip()
    ts = now_ts()
    next_rows: List[Dict[str, Any]] = []
    updated: Optional[Dict[str, Any]] = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("id") or "").strip()
        if wanted and row_id == wanted and updated is None:
            merged = {**row, **dict(record or {})}
            merged["id"] = wanted
            merged["updated_ts"] = ts
            if "imported_ts" not in merged:
                merged["imported_ts"] = ts
            next_rows.append(merged)
            updated = merged
        else:
            next_rows.append(dict(row))
    if updated is None:
        merged = dict(record or {})
        if not wanted:
            wanted = f"wxi_{ts}_{len(rows) + 1}"
        merged["id"] = wanted
        merged["imported_ts"] = int(merged.get("imported_ts") or ts)
        merged["updated_ts"] = ts
        next_rows.append(merged)
        updated = merged
    payload["records"] = sorted(next_rows, key=lambda row: int(row.get("updated_ts") or 0), reverse=True)
    write_imports_index(app, payload)
    return dict(updated or {})


def list_published_records(app) -> List[Dict[str, Any]]:
    payload = read_published_index(app)
    rows = [dict(row) for row in (payload.get("records") or []) if isinstance(row, dict)]
    return sorted(rows, key=lambda row: int(row.get("updated_ts") or 0), reverse=True)


def get_published_record(app, publish_id: str) -> Optional[Dict[str, Any]]:
    wanted = str(publish_id or "").strip()
    if not wanted:
        return None
    for row in list_published_records(app):
        if str(row.get("id") or "").strip() == wanted:
            return row
    return None


def upsert_published_record(app, record: Dict[str, Any]) -> Dict[str, Any]:
    payload = read_published_index(app)
    rows = payload.get("records") if isinstance(payload.get("records"), list) else []
    wanted = str((record or {}).get("id") or "").strip()
    ts = now_ts()
    next_rows: List[Dict[str, Any]] = []
    updated: Optional[Dict[str, Any]] = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("id") or "").strip()
        if wanted and row_id == wanted and updated is None:
            merged = {**row, **dict(record or {})}
            merged["id"] = wanted
            merged["updated_ts"] = ts
            if "published_ts" not in merged:
                merged["published_ts"] = ts
            next_rows.append(merged)
            updated = merged
        else:
            next_rows.append(dict(row))
    if updated is None:
        merged = dict(record or {})
        if not wanted:
            wanted = f"wxp_{ts}_{len(rows) + 1}"
        merged["id"] = wanted
        merged["published_ts"] = int(merged.get("published_ts") or ts)
        merged["updated_ts"] = ts
        next_rows.append(merged)
        updated = merged
    payload["records"] = sorted(next_rows, key=lambda row: int(row.get("updated_ts") or 0), reverse=True)
    write_published_index(app, payload)
    return dict(updated or {})


def delete_published_record(app, publish_id: str) -> bool:
    wanted = str(publish_id or "").strip()
    if not wanted:
        return False
    payload = read_published_index(app)
    rows = payload.get("records") if isinstance(payload.get("records"), list) else []
    next_rows = [dict(row) for row in rows if isinstance(row, dict) and str(row.get("id") or "").strip() != wanted]
    changed = len(next_rows) != len(rows)
    if changed:
        payload["records"] = next_rows
        write_published_index(app, payload)
    return changed


def list_public_records(app) -> List[Dict[str, Any]]:
    payload = read_public_index(app)
    rows = [dict(row) for row in (payload.get("records") or []) if isinstance(row, dict)]
    return sorted(rows, key=lambda row: int(row.get("updated_ts") or 0), reverse=True)


def upsert_public_record(app, record: Dict[str, Any]) -> Dict[str, Any]:
    payload = read_public_index(app)
    rows = payload.get("records") if isinstance(payload.get("records"), list) else []
    wanted = str((record or {}).get("id") or "").strip()
    ts = now_ts()
    next_rows: List[Dict[str, Any]] = []
    updated: Optional[Dict[str, Any]] = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("id") or "").strip()
        if wanted and row_id == wanted and updated is None:
            merged = {**row, **dict(record or {})}
            merged["id"] = wanted
            merged["updated_ts"] = ts
            if "published_ts" not in merged:
                merged["published_ts"] = ts
            next_rows.append(merged)
            updated = merged
        else:
            next_rows.append(dict(row))
    if updated is None:
        merged = dict(record or {})
        if not wanted:
            wanted = f"wxpub_{ts}_{len(rows) + 1}"
        merged["id"] = wanted
        merged["published_ts"] = int(merged.get("published_ts") or ts)
        merged["updated_ts"] = ts
        next_rows.append(merged)
        updated = merged
    payload["records"] = sorted(next_rows, key=lambda row: int(row.get("updated_ts") or 0), reverse=True)
    write_public_index(app, payload)
    return dict(updated or {})


def delete_public_record(app, record_id: str) -> bool:
    wanted = str(record_id or "").strip()
    if not wanted:
        return False
    payload = read_public_index(app)
    rows = payload.get("records") if isinstance(payload.get("records"), list) else []
    next_rows = [dict(row) for row in rows if isinstance(row, dict) and str(row.get("id") or "").strip() != wanted]
    changed = len(next_rows) != len(rows)
    if changed:
        payload["records"] = next_rows
        write_public_index(app, payload)
    return changed


def list_mirror_peers(app) -> List[Dict[str, Any]]:
    payload = read_mirrors_index(app)
    rows = [dict(row) for row in (payload.get("peers") or []) if isinstance(row, dict)]
    return sorted(rows, key=lambda row: int(row.get("updated_ts") or 0), reverse=True)


def upsert_mirror_peer(app, record: Dict[str, Any]) -> Dict[str, Any]:
    payload = read_mirrors_index(app)
    rows = payload.get("peers") if isinstance(payload.get("peers"), list) else []
    wanted = str((record or {}).get("mirror_id") or (record or {}).get("id") or "").strip()
    ts = now_ts()
    next_rows: List[Dict[str, Any]] = []
    updated: Optional[Dict[str, Any]] = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("mirror_id") or row.get("id") or "").strip()
        if wanted and row_id == wanted and updated is None:
            merged = {**row, **dict(record or {})}
            merged["mirror_id"] = wanted
            merged["id"] = wanted
            merged["updated_ts"] = ts
            if "created_ts" not in merged:
                merged["created_ts"] = ts
            next_rows.append(merged)
            updated = merged
        else:
            next_rows.append(dict(row))
    if updated is None:
        merged = dict(record or {})
        if not wanted:
            wanted = f"mirror_{ts}_{len(rows) + 1}"
        merged["mirror_id"] = wanted
        merged["id"] = wanted
        merged["created_ts"] = int(merged.get("created_ts") or ts)
        merged["updated_ts"] = ts
        next_rows.append(merged)
        updated = merged
    payload["peers"] = sorted(next_rows, key=lambda row: int(row.get("updated_ts") or 0), reverse=True)
    payload["records"] = payload.get("records") if isinstance(payload.get("records"), list) else []
    write_mirrors_index(app, payload)
    return dict(updated or {})


def list_mirror_records(app) -> List[Dict[str, Any]]:
    payload = read_mirrors_index(app)
    rows = [dict(row) for row in (payload.get("records") or []) if isinstance(row, dict)]
    return sorted(rows, key=lambda row: int(row.get("updated_ts") or 0), reverse=True)


def upsert_mirror_record(app, record: Dict[str, Any]) -> Dict[str, Any]:
    payload = read_mirrors_index(app)
    rows = payload.get("records") if isinstance(payload.get("records"), list) else []
    wanted = str((record or {}).get("id") or "").strip()
    ts = now_ts()
    next_rows: List[Dict[str, Any]] = []
    updated: Optional[Dict[str, Any]] = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("id") or "").strip()
        if wanted and row_id == wanted and updated is None:
            merged = {**row, **dict(record or {})}
            merged["id"] = wanted
            merged["updated_ts"] = ts
            if "published_ts" not in merged:
                merged["published_ts"] = ts
            next_rows.append(merged)
            updated = merged
        else:
            next_rows.append(dict(row))
    if updated is None:
        merged = dict(record or {})
        if not wanted:
            mirror_id = str(merged.get("mirror_id") or "mirror").strip()
            source_id = str(merged.get("source_publish_id") or merged.get("workflow_id") or len(rows) + 1).strip()
            wanted = f"{mirror_id}:{source_id}"
        merged["id"] = wanted
        merged["published_ts"] = int(merged.get("published_ts") or ts)
        merged["updated_ts"] = ts
        next_rows.append(merged)
        updated = merged
    payload["records"] = sorted(next_rows, key=lambda row: int(row.get("updated_ts") or 0), reverse=True)
    payload["peers"] = payload.get("peers") if isinstance(payload.get("peers"), list) else []
    write_mirrors_index(app, payload)
    return dict(updated or {})
