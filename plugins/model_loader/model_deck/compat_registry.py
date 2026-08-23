from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from .runtime_profile_catalog import export_runtime_catalog, normalize_runtime_profile


def _root_dir() -> Path:
    return Path(__file__).resolve().parent / "tested_models"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_manifest_path(value: Any) -> Path:
    raw = str(value or "").strip()
    if not raw:
        return Path()
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return _project_root() / path


def _safe_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        raise HTTPException(500, f"invalid compatibility file: {path.name}: {exc}") from exc
    return dict(data) if isinstance(data, dict) else {}


def _load_optional_json(folder: Path, filename: str) -> Dict[str, Any]:
    path = folder / filename
    if not path.is_file():
        return {}
    data = _safe_json(path)
    return data if isinstance(data, dict) else {}


def _manifest_entry(type_id: str, folder: Path) -> Optional[Dict[str, Any]]:
    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file():
        return None
    manifest = _safe_json(manifest_path)
    manifest_id = str(manifest.get("id") or folder.name).strip()
    if not manifest_id:
        return None
    out = dict(manifest)
    out["id"] = manifest_id
    out["type_id"] = type_id
    out["folder"] = str(folder)
    out["template_json"] = _load_optional_json(folder, str(manifest.get("template_file") or "template.json"))
    out["assets_json"] = _load_optional_json(folder, str(manifest.get("assets_file") or "assets.json"))
    out["params_json"] = _load_optional_json(folder, str(manifest.get("params_file") or "params.json"))
    out["workflow_json"] = _load_optional_json(folder, str(manifest.get("workflow_file") or "workflow.json"))
    out["runtime_profile"] = normalize_runtime_profile(manifest.get("runtime_profile"))
    return out


def list_manifests(type_id: str) -> List[Dict[str, Any]]:
    root = _root_dir() / str(type_id or "").strip()
    if not root.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        entry = _manifest_entry(type_id, child)
        if entry:
            out.append(entry)
    return out


def _norm(text: Any) -> str:
    return str(text or "").strip().lower()


def _settings_texts(settings: Dict[str, Any]) -> List[str]:
    texts = [
        settings.get("model_id"),
        settings.get("model_path"),
        settings.get("gguf_path"),
        settings.get("gguf_filename"),
        settings.get("hf_source_repo_id"),
        settings.get("hf_source_filename"),
        settings.get("backend"),
    ]
    return [_norm(x) for x in texts if _norm(x)]


def match_manifest(type_id: str, settings: Dict[str, Any], manifest_id: str = "") -> Optional[Dict[str, Any]]:
    manifests = list_manifests(type_id)
    if manifest_id:
        target = _norm(manifest_id)
        for manifest in manifests:
            if _norm(manifest.get("id")) == target:
                return manifest
        # Older workflow/model rows can carry generated ids such as
        # "flux_gguf_diffusers_repo" that do not exactly match the tested
        # profile folder id ("flux_diffusers").  Do not hard-fail here: fall
        # back to alias scoring so a valid model_id/gguf_path can still select
        # the correct profile.  This keeps stale ids from pushing image GGUF
        # models into the generic Z-Image fallback loader.
    texts = _settings_texts(settings)
    backend = _norm(settings.get("backend"))
    best: Optional[Dict[str, Any]] = None
    best_score = -1
    for manifest in manifests:
        score = 0
        alias_hits = 0
        aliases = manifest.get("aliases")
        if isinstance(aliases, list):
            for alias in aliases:
                alias_text = _norm(alias)
                if alias_text and any(alias_text in text for text in texts):
                    score += 8
                    alias_hits += 1
        backends = manifest.get("backends")
        if alias_hits > 0 and isinstance(backends, list) and backend:
            if any(_norm(item) == backend for item in backends):
                score += 3
        if score > best_score:
            best = manifest
            best_score = score
    return best if best_score > 0 else None


def _slug(text: Any) -> str:
    value = _norm(text)
    return "".join(ch if ch.isalnum() else "_" for ch in value).strip("_")


def _merge_loader_symbol_requirements(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    requirements = [dict(item) for item in (manifest.get("requirements") or []) if isinstance(item, dict)]
    loader = manifest.get("diffusers_loader")
    runtime_profile = manifest.get("runtime_profile")
    if not isinstance(loader, dict):
        loader = {}
    seen_symbols = {
        (_norm(row.get("module")), _norm(row.get("symbol")))
        for row in requirements
        if _norm(row.get("kind") or "python_package") == "python_symbol"
    }

    def add_symbol(symbol_key: str, module_key: str, default_module: str, req_prefix: str) -> None:
        symbol = str(loader.get(symbol_key) or "").strip()
        module = str(loader.get(module_key) or default_module).strip() or default_module
        if not symbol:
            return
        pair = (_norm(module), _norm(symbol))
        if pair in seen_symbols:
            return
        requirements.append({
            "id": f"{req_prefix}_{_slug(symbol)}",
            "label": symbol,
            "kind": "python_symbol",
            "module": module,
            "symbol": symbol,
            "install": [module],
            "uninstall": [],
        })
        seen_symbols.add(pair)

    add_symbol("pipeline_class", "pipeline_module", "diffusers", "pipeline")
    add_symbol("transformer_class", "transformer_module", "diffusers", "transformer")
    add_symbol("transformer_quantization_class", "transformer_quantization_module", str(loader.get("transformer_module") or "diffusers"), "quantization")

    if isinstance(runtime_profile, dict):
        components = runtime_profile.get("components")
        if isinstance(components, list):
            for component in components:
                if not isinstance(component, dict):
                    continue
                symbol = str(component.get("class") or "").strip()
                module = str(component.get("module") or "diffusers").strip() or "diffusers"
                if not symbol:
                    continue
                pair = (_norm(module), _norm(symbol))
                if pair in seen_symbols:
                    continue
                role = _slug(component.get("role") or component.get("id") or "component") or "component"
                requirements.append({
                    "id": f"{role}_{_slug(symbol)}",
                    "label": symbol,
                    "kind": "python_symbol",
                    "module": module,
                    "symbol": symbol,
                    "install": [module],
                    "uninstall": [],
                })
                seen_symbols.add(pair)
        loader_steps = runtime_profile.get("loader_steps")
        if isinstance(loader_steps, list):
            for component in loader_steps:
                if not isinstance(component, dict):
                    continue
                for symbol_key, module_key in (
                    ("class_name", "class_module"),
                    ("quantization_class", "quantization_module"),
                ):
                    symbol = str(component.get(symbol_key) or "").strip()
                    module = str(component.get(module_key) or "diffusers").strip() or "diffusers"
                    if not symbol:
                        continue
                    pair = (_norm(module), _norm(symbol))
                    if pair in seen_symbols:
                        continue
                    role = _slug(component.get("kind") or component.get("id") or "step") or "step"
                    requirements.append({
                        "id": f"{role}_{_slug(symbol)}",
                        "label": symbol,
                        "kind": "python_symbol",
                        "module": module,
                        "symbol": symbol,
                        "install": [module],
                        "uninstall": [],
                    })
                    seen_symbols.add(pair)
        pipeline_defaults = runtime_profile.get("pipeline_defaults")
        if isinstance(pipeline_defaults, dict):
            symbol = str(pipeline_defaults.get("base_pipeline_class") or "").strip()
            module = str(pipeline_defaults.get("base_pipeline_module") or "diffusers").strip() or "diffusers"
            pair = (_norm(module), _norm(symbol))
            if symbol and pair not in seen_symbols:
                requirements.append({
                    "id": f"pipeline_{_slug(symbol)}",
                    "label": symbol,
                    "kind": "python_symbol",
                    "module": module,
                    "symbol": symbol,
                    "install": [module],
                    "uninstall": [],
                })
                seen_symbols.add(pair)
    return requirements


def _check_requirement(req: Dict[str, Any]) -> Dict[str, Any]:
    req_id = str(req.get("id") or "").strip()
    kind = _norm(req.get("kind") or "python_package")
    label = str(req.get("label") or req_id or kind).strip()
    detail = ""
    installed = False
    version = ""
    try:
        if kind == "python_symbol":
            module_name = str(req.get("module") or req.get("import_name") or "").strip()
            symbol_name = str(req.get("symbol") or "").strip()
            if not module_name or not symbol_name:
                detail = "module or symbol missing in manifest"
            else:
                mod = importlib.import_module(module_name)
                installed = hasattr(mod, symbol_name)
                detail = f"{module_name}.{symbol_name}" if installed else f"Missing {module_name}.{symbol_name}"
        elif kind in {"git_source", "source_checkout", "local_source"}:
            target_path = _resolve_manifest_path(req.get("target_path") or req.get("path"))
            url = str(req.get("url") or "").strip()
            installed = bool(str(target_path).strip() and target_path.exists())
            configured_detail = str(req.get("detail") or "").strip()
            path_detail = f"{target_path}"
            source_detail = f"Source: {url}" if url else ""
            if installed:
                detail = " | ".join(part for part in (configured_detail, f"Installed at: {path_detail}", source_detail) if part)
            else:
                hint = str(req.get("install_hint") or "").strip()
                detail = " | ".join(part for part in (configured_detail, f"Missing: {path_detail}", source_detail) if part)
                if hint:
                    detail = f"{detail} | {hint}".strip()
        else:
            package_name = str(req.get("package") or req.get("import_name") or "").strip()
            import_name = str(req.get("import_name") or package_name).strip()
            if package_name:
                try:
                    version = str(importlib.metadata.version(package_name))
                except Exception:
                    version = ""
            installed = bool(import_name and importlib.util.find_spec(import_name) is not None)
            detail = version or import_name or package_name
    except Exception as exc:
        installed = False
        detail = str(exc)
    return {
        "id": req_id,
        "label": label,
        "kind": kind,
        "installed": bool(installed),
        "detail": detail,
        "version": version,
        "optional": bool(req.get("optional")),
        "install": list(req.get("install") or []),
        "uninstall": list(req.get("uninstall") or []),
        "url": str(req.get("url") or "").strip(),
        "target_path": str(req.get("target_path") or req.get("path") or "").strip(),
        "install_hint": str(req.get("install_hint") or "").strip(),
    }


def manifest_status(type_id: str, settings: Dict[str, Any], manifest_id: str = "") -> Dict[str, Any]:
    manifest = match_manifest(type_id, settings, manifest_id)
    if not manifest:
        return {"matched": False, "manifest": None, "requirements": [], "all_installed": False}
    reqs = _merge_loader_symbol_requirements(manifest)
    rows = [_check_requirement(dict(item)) for item in reqs] if isinstance(reqs, list) else []
    all_installed = all(bool(row.get("installed")) or bool(row.get("optional")) for row in rows)
    return {
        "matched": True,
        "manifest": {
            "id": manifest.get("id"),
            "label": manifest.get("label") or manifest.get("id"),
            "description": manifest.get("description") or "",
            "type_id": manifest.get("type_id") or type_id,
            "backends": manifest.get("backends") or [],
            "aliases": manifest.get("aliases") or [],
            "diffusers_loader": manifest.get("diffusers_loader") or {},
            "runtime_profile": manifest.get("runtime_profile") or {},
            "template_json": manifest.get("template_json") or {},
            "assets_json": manifest.get("assets_json") or {},
            "params_json": manifest.get("params_json") or {},
            "workflow_json": manifest.get("workflow_json") or {},
        },
        "runtime_catalog": export_runtime_catalog(),
        "requirements": rows,
        "all_installed": bool(all_installed),
    }


def _run_pip(args: List[str]) -> Tuple[bool, str]:
    cmd = [sys.executable, "-m", "pip"] + [str(x) for x in args if str(x).strip()]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except Exception as exc:
        return False, str(exc)
    message = (proc.stdout or proc.stderr or "").strip()
    return int(proc.returncode or 0) == 0, message


def install_requirements(type_id: str, settings: Dict[str, Any], manifest_id: str, requirement_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    manifest = match_manifest(type_id, settings, manifest_id)
    if not manifest:
        raise HTTPException(404, f"compatibility manifest not found: {manifest_id}")
    wanted = {_norm(x) for x in (requirement_ids or []) if _norm(x)}
    ran: List[Dict[str, Any]] = []
    for req in _merge_loader_symbol_requirements(manifest):
        req = dict(req) if isinstance(req, dict) else {}
        req_id = _norm(req.get("id"))
        if wanted and req_id not in wanted:
            continue
        install_args = req.get("install")
        if not isinstance(install_args, list) or not install_args:
            continue
        ok, output = _run_pip(["install", *[str(x) for x in install_args]])
        checked = _check_requirement(req)
        final_ok = bool(ok and checked.get("installed"))
        detail = str(checked.get("detail") or "").strip()
        message = str(output or "").strip()
        if final_ok:
            if detail:
                message = f"{message}\nverified: {detail}".strip()
        else:
            suffix = f"verification failed: {detail or 'requirement still missing after install'}".strip()
            message = f"{message}\n{suffix}".strip()
        ran.append({
            "id": req.get("id"),
            "ok": final_ok,
            "installed_after": bool(checked.get("installed")),
            "detail_after": detail,
            "output": message,
        })
    return {"ok": True, "results": ran, **manifest_status(type_id, settings, manifest_id)}


def uninstall_requirements(type_id: str, settings: Dict[str, Any], manifest_id: str, requirement_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    manifest = match_manifest(type_id, settings, manifest_id)
    if not manifest:
        raise HTTPException(404, f"compatibility manifest not found: {manifest_id}")
    wanted = {_norm(x) for x in (requirement_ids or []) if _norm(x)}
    ran: List[Dict[str, Any]] = []
    for req in _merge_loader_symbol_requirements(manifest):
        req = dict(req) if isinstance(req, dict) else {}
        req_id = _norm(req.get("id"))
        if wanted and req_id not in wanted:
            continue
        uninstall_args = req.get("uninstall")
        if not isinstance(uninstall_args, list) or not uninstall_args:
            continue
        ok, output = _run_pip(["uninstall", "-y", *[str(x) for x in uninstall_args]])
        ran.append({"id": req.get("id"), "ok": ok, "output": output})
    return {"ok": True, "results": ran, **manifest_status(type_id, settings, manifest_id)}
