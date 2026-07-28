from __future__ import annotations

from typing import Any, Dict

from .store import list_import_records, list_mirror_peers, list_mirror_records, list_public_records, list_published_records


def build_sync_status(app) -> Dict[str, Any]:
    local_published = list_published_records(app)
    public_records = list_public_records(app)
    mirror_peers = list_mirror_peers(app)
    mirror_records = list_mirror_records(app)
    imports = list_import_records(app)
    pending_installs = sum(1 for row in imports if isinstance(row, dict) and not bool(row.get("ready_to_flow")))
    last_peer = mirror_peers[0] if mirror_peers else {}
    return {
        "public_index_status": "ready" if local_published else "empty",
        "private_index_status": "ready" if any(str(row.get("visibility") or "").strip() == "private" for row in local_published) else "empty",
        "mirror_status": "ready" if mirror_peers or mirror_records else "empty",
        "pending_uploads": 0,
        "pending_installs": pending_installs,
        "local_published_count": len(local_published),
        "public_catalog_count": len(public_records),
        "mirror_peer_count": len(mirror_peers),
        "mirror_record_count": len(mirror_records),
        "last_mirror_id": str(last_peer.get("mirror_id") or ""),
        "last_mirror_sync_ts": int(last_peer.get("last_sync_ts") or 0),
    }
