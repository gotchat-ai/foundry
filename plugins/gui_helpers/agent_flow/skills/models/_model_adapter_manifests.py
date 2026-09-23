from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def _agent_flow_root() -> Path:
    # .../agent_flow/skills/models/_model_adapter_manifests.py -> .../agent_flow
    return Path(__file__).resolve().parents[2]


def default_model_adapters_root() -> Path:
    return _agent_flow_root() / "model_adapters"


def _safe_id(value: Any) -> str:
    return str(value or "").strip()


def _load_manifest(path: Path) -> Tuple[Dict[str, Any] | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"model_adapter_manifest_load_failed:{path}:{exc}"
    if not isinstance(data, dict):
        return None, f"model_adapter_manifest_not_object:{path}"
    adapter_id = _safe_id(data.get("id") or path.parent.name)
    if not adapter_id:
        return None, f"model_adapter_manifest_missing_id:{path}"
    data["id"] = adapter_id
    data.setdefault("schema_version", 1)
    data.setdefault("name", adapter_id)
    data.setdefault("skills", {})
    data.setdefault("asset_keys", {})
    data.setdefault("setting_schema_refs", {})
    data.setdefault("examples", [])
    data["_manifest_path"] = str(path)
    data["_adapter_dir"] = str(path.parent)
    return data, None


def discover_model_adapter_manifests(extra_roots: Iterable[str | Path] | None = None) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    roots: List[Path] = [default_model_adapters_root()]
    for raw in extra_roots or []:
        try:
            p = Path(raw).expanduser().resolve()
        except Exception:
            continue
        if p not in roots:
            roots.append(p)

    adapters: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for manifest in sorted(root.glob("*/adapter.json")):
            data, warning = _load_manifest(manifest)
            if warning:
                warnings.append(warning)
                continue
            assert data is not None
            adapter_id = _safe_id(data.get("id"))
            if adapter_id in adapters:
                warnings.append(f"model_adapter_manifest_duplicate_id:{adapter_id}:{manifest}")
                continue
            adapters[adapter_id] = data
    return adapters, warnings


def adapter_stage_tool_map_from_manifests(adapters: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    for adapter_id, manifest in (adapters or {}).items():
        skills = manifest.get("skills")
        if not isinstance(skills, dict):
            continue
        mapped: Dict[str, str] = {}
        for stage, tool_id in skills.items():
            stage_key = _safe_id(stage)
            tool = _safe_id(tool_id)
            if not stage_key or not tool.startswith("models."):
                continue
            mapped[stage_key] = tool.split(".", 1)[1]
        if mapped:
            out[adapter_id] = mapped
    return out


def adapter_alias_maps_from_manifests(adapters: Dict[str, Dict[str, Any]]) -> Tuple[Dict[str, str], Dict[str, str]]:
    profile_aliases: Dict[str, str] = {}
    family_aliases: Dict[str, str] = {}
    for adapter_id, manifest in (adapters or {}).items():
        for raw in manifest.get("aliases") or []:
            key = _safe_id(raw).lower()
            if key:
                profile_aliases[key] = adapter_id
        for raw in manifest.get("families") or []:
            key = _safe_id(raw).lower()
            if key:
                family_aliases[key] = adapter_id
    return profile_aliases, family_aliases


def get_model_adapter_catalog() -> Dict[str, Any]:
    adapters, warnings = discover_model_adapter_manifests()
    return {
        "adapters": adapters,
        "warnings": warnings,
    }
