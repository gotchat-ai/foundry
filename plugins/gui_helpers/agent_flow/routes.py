from __future__ import annotations

import json
import inspect
import os
import re
import secrets
import threading
import time
import hashlib
import shutil
import zipfile
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Query
from pydantic import BaseModel, Field

from awf_pass_log import append_pass_log_row
from plugins.gui_helpers._framework.services import get_plugin_service
from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled
from .skills import register_agent_flow_skills, build_agent_flow_tool_registry, discover_agent_flow_skills
from .skills.result.chart import normalize_chart_payload
from .skills.result import text as result_text_skill
from .skills.workflow import temp_library as workflow_temp_library
from .skills.workflow import export as workflow_export_skill
from .skills.workflow._common import (
    ensure_flow_payload,
    atomic_write_json_doc,
    atomic_write_text,
    slugify,
    extract_referenced_skills,
    _resolve_cross_env_generated_path,
)
from .skills.workflow import _workflow_store


GUI_PLUGIN_ID = "agent_flow"
PASS_LOG_PATH = Path(__file__).resolve().parents[3] / "awf_imported_passes_20260620.csv"


def _require_user(app: Any, request: Request) -> Any:
    collab = get_plugin_service(app, "collab_chat")
    fn = collab.get("require_user") if isinstance(collab, dict) else None
    if not callable(fn):
        raise HTTPException(status_code=503, detail="collab_chat service unavailable")
    return fn(request)


def _require_session_access(app: Any, user: Any, pid: str, sid: str) -> Any:
    collab = get_plugin_service(app, "collab_chat")
    fn = collab.get("require_session_access") if isinstance(collab, dict) else None
    if not callable(fn):
        raise HTTPException(status_code=503, detail="collab_chat service unavailable")
    return fn(user, pid, sid)


def _now_ts() -> int:
    return int(time.time())


class AgentFlowRunRequest(BaseModel):
    text: Optional[str] = None
    client_msg_id: Optional[str] = None
    ext: Dict[str, Any] = Field(default_factory=dict)


def install(app) -> None:
    if not hasattr(app.state, "agent_flow_runs"):
        app.state.agent_flow_runs = {}
    if not hasattr(app.state, "agent_flow_runs_lock"):
        app.state.agent_flow_runs_lock = threading.Lock()

    skill_load_info = register_agent_flow_skills(app)

    r = APIRouter()

    def _data_dir() -> str:
        cand = getattr(app.state, "data_dir", None) or getattr(app.state, "workdir", None) or None
        if isinstance(cand, str) and cand.strip():
            base = cand
        else:
            base = os.path.abspath("./data")
        path = os.path.join(base, "projects", "agent_flow")
        os.makedirs(path, exist_ok=True)
        return path

    def _generated_temp_library_root() -> Path:
        base = getattr(app.state, "data_dir", None) or getattr(app.state, "workdir", None) or None
        if isinstance(base, str) and base.strip():
            root = Path(base)
        else:
            root = Path(os.path.abspath("./data"))
        return root / "generated" / "workflow_blueprints" / "temp_library"

    def _resolve_generated_path(raw_path: str) -> Path:
        return _resolve_cross_env_generated_path({"app": app}, str(raw_path or "").strip())

    def _append_temp_library_pass_log(
        *,
        request_id: str = "",
        request_dir: str = "",
        request_file: str = "",
        source_file: str = "",
        record: Dict[str, Any],
        validation_profile: str,
        selected_flow_source: str,
        notes: str = "",
    ) -> None:
        if not isinstance(record, dict):
            return
        try:
            append_pass_log_row(
                PASS_LOG_PATH,
                {
                    "request_id": str(request_id or "").strip(),
                    "request_dir": str(request_dir or "").strip(),
                    "request_file": str(request_file or "").strip(),
                    "source_file": str(source_file or "").strip(),
                    "result_file": "",
                    "record_id": str(record.get("id") or record.get("workflow_id") or "").strip(),
                    "flow_name": str(record.get("flow_name") or "").strip(),
                    "workflow_file": str(record.get("workflow_file") or "").strip(),
                    "bundle_dir": str(record.get("bundle_dir") or "").strip(),
                    "validation_profile": str(validation_profile or "").strip(),
                    "selected_flow_source": str(selected_flow_source or "").strip(),
                    "judge_score": "",
                    "judge_reason": "",
                    "notes": str(notes or "").strip(),
                },
            )
        except Exception:
            return

    def _collect_flow_tool_names(flow_def: Any) -> List[str]:
        tools: List[str] = []

        def walk(obj: Any) -> None:
            if isinstance(obj, dict):
                tc = obj.get("tool_config")
                if isinstance(tc, dict):
                    tool = str(tc.get("tool") or "").strip()
                    if tool:
                        tools.append(tool)
                for value in obj.values():
                    walk(value)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(flow_def)
        seen = set()
        out: List[str] = []
        for tool in tools:
            key = tool.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(tool)
        return out

    def _candidate_temp_skill_names(flow_name: str, flow_def: Any) -> List[str]:
        names: List[str] = []

        def add(raw: Any) -> None:
            val = str(raw or "").strip()
            if val and val not in names:
                names.append(val)

        add(flow_name)
        if "__autoflow_runtime__" in str(flow_name or ""):
            left, right = str(flow_name).split("__autoflow_runtime__", 1)
            add(left)
            add(right)
        if isinstance(flow_def, dict):
            add(flow_def.get("name"))
            desc = str(flow_def.get("description") or "").strip()
            m = re.search(r"Generated capability-planned workflow for:\s*(.+)$", desc, flags=re.IGNORECASE)
            if m:
                slug = re.sub(r"[^a-z0-9]+", "_", m.group(1).lower()).strip("_")
                add(slug)
        return names

    def _infer_temp_skill_dirs_for_flow(flow_name: str, flow_def: Any, incoming_dirs: Any) -> List[str]:
        root = _generated_temp_library_root()
        dirs: List[str] = []
        inferred_dirs: List[str] = []

        def _resolve_dir(path: Any) -> str:
            text = str(path or "").strip()
            if not text:
                return ""
            p = Path(text)
            try:
                if p.is_dir():
                    return str(p.resolve())
                else:
                    return ""
            except Exception:
                return ""

        def add_dir(path: Any) -> None:
            resolved = _resolve_dir(path)
            if resolved and resolved not in dirs:
                dirs.append(resolved)

        def add_inferred_dir(path: Any) -> None:
            resolved = _resolve_dir(path)
            if resolved and resolved not in inferred_dirs:
                inferred_dirs.append(resolved)

        explicit_incoming = False
        if isinstance(incoming_dirs, list):
            for item in incoming_dirs:
                add_dir(item)
            explicit_incoming = bool(dirs)

        if root.is_dir() and not explicit_incoming:
            for name in _candidate_temp_skill_names(flow_name, flow_def):
                add_inferred_dir(root / name / "skills")

            tools = [t for t in _collect_flow_tool_names(flow_def) if str(t or "").strip().startswith("custom.")]
            wanted_files = []
            for tool in tools:
                mod = str(tool).split(".", 1)[1].strip()
                if mod:
                    wanted_files.append(Path(*mod.split(".")))
            if wanted_files:
                def dir_has_wanted_tool(skills_dir: Path, rel: Path) -> bool:
                    return (skills_dir / "custom" / f"{rel.name}.py").is_file() or (skills_dir / rel.with_suffix(".py")).is_file()

                try:
                    bundles = [bundle for bundle in root.iterdir() if bundle.is_dir()]
                    bundles.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
                    for bundle in bundles:
                        skills_dir = bundle / "skills"
                        if not skills_dir.is_dir():
                            continue
                        for rel in wanted_files:
                            if dir_has_wanted_tool(skills_dir, rel):
                                add_inferred_dir(skills_dir)
                                break
                except Exception:
                    pass
        if inferred_dirs and not explicit_incoming:
            inferred_dirs.sort(
                key=lambda text: Path(text).parent.stat().st_mtime if Path(text).parent.exists() else 0.0,
                reverse=True,
            )
            for item in inferred_dirs:
                add_dir(item)
        return dirs

    def _flows_path(pid: str) -> str:
        safe_pid = str(pid or "").strip()
        if not safe_pid or not all(c.isalnum() or c in "-_" for c in safe_pid):
            raise HTTPException(status_code=400, detail="invalid project id")
        return os.path.join(_data_dir(), f"{safe_pid}.json")

    def _load_project_flows(pid: str) -> Dict[str, Any]:
        return {"flows": _workflow_store.load_project_flows({"app": app, "pid": pid}, pid)}

    def _save_project_flows(pid: str, flows: Dict[str, Any], prior_ids_by_name: Optional[Dict[str, str]] = None) -> None:
        _workflow_store.replace_project_flows({"app": app, "pid": pid}, pid, flows or {}, prior_ids_by_name=prior_ids_by_name)

    def _default_flows_path() -> str:
        return os.path.join(_data_dir(), "default.json")

    def _load_default_flows_doc() -> Dict[str, Any]:
        return {"flows": _workflow_store.load_default_flows({"app": app})}

    def _save_default_flows(flows: Dict[str, Any]) -> None:
        _workflow_store.replace_default_flows({"app": app}, flows or {})

    def _uploads_dir_path_global() -> Path:
        base = getattr(app.state, "data_dir", None) or getattr(app.state, "workdir", None) or os.path.abspath("./data")
        up = Path(str(base)).resolve() / "uploads"
        up.mkdir(parents=True, exist_ok=True)
        return up

    def _unique_upload_name_global(name: str, suffix_seed: str = "") -> str:
        base = Path(str(name or "artifact.bin")).name or "artifact.bin"
        stem = Path(base).stem or "artifact"
        suf = Path(base).suffix or ""
        token = str(suffix_seed or secrets.token_hex(4)).strip()[:12]
        return f"{stem}_{token}{suf}" if token else base

    def _stage_path_for_download_global(src: Path, *, out_name: str = "", suffix_seed: str = "") -> Dict[str, Any]:
        resolved = src.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(str(resolved))
        name = _unique_upload_name_global(out_name or resolved.name, suffix_seed=suffix_seed)
        dst = _uploads_dir_path_global() / name
        shutil.copy2(str(resolved), str(dst))
        return {
            "name": Path(out_name or resolved.name).name,
            "staged_name": name,
            "path": str(resolved),
            "download_url": f"/uploads/{name}",
            "size_bytes": int(dst.stat().st_size),
        }

    def _stage_text_for_download_global(text: str, *, out_name: str, suffix_seed: str = "") -> Dict[str, Any]:
        name = _unique_upload_name_global(out_name or "agent_flow.json", suffix_seed=suffix_seed)
        dst = _uploads_dir_path_global() / name
        atomic_write_text(dst, str(text or ""), make_backup=False)
        return {
            "name": Path(out_name or "agent_flow.json").name,
            "staged_name": name,
            "path": str(dst),
            "download_url": f"/uploads/{name}",
            "size_bytes": int(dst.stat().st_size),
        }

    def _stage_directory_zip_for_download_global(src_dir: Path, *, archive_name: str, suffix_seed: str = "") -> Dict[str, Any]:
        resolved = src_dir.resolve()
        if not resolved.is_dir():
            raise FileNotFoundError(str(resolved))
        name = _unique_upload_name_global(archive_name or "agent_flow_result.zip", suffix_seed=suffix_seed)
        if not name.lower().endswith(".zip"):
            name = f"{name}.zip"
        dst = _uploads_dir_path_global() / name
        file_count = 0
        with zipfile.ZipFile(str(dst), "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for child in sorted(resolved.rglob("*")):
                if not child.is_file():
                    continue
                if "__pycache__" in child.parts or child.suffix.lower() == ".pyc":
                    continue
                zf.write(str(child), arcname=str(child.relative_to(resolved)))
                file_count += 1
        return {
            "name": Path(archive_name or "agent_flow_result.zip").name,
            "staged_name": name,
            "download_url": f"/uploads/{name}",
            "size_bytes": int(dst.stat().st_size),
            "file_count": file_count,
        }

    def _portable_flow_copy(flow_doc: Dict[str, Any]) -> Dict[str, Any]:
        try:
            cloned = json.loads(json.dumps(flow_doc if isinstance(flow_doc, dict) else {}, ensure_ascii=True))
        except Exception:
            cloned = dict(flow_doc or {})

        def walk(obj: Any) -> None:
            if isinstance(obj, dict):
                obj.pop("subflow_workflow_id", None)
                obj.pop("loop_subflow_workflow_id", None)
                for value in obj.values():
                    walk(value)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(cloned)
        return cloned if isinstance(cloned, dict) else {}

    def _extract_subflow_refs(flow_doc: Dict[str, Any]) -> List[Dict[str, str]]:
        nodes = flow_doc.get("nodes") if isinstance(flow_doc.get("nodes"), dict) else {}
        refs: List[Dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for node in nodes.values():
            if not isinstance(node, dict):
                continue
            plugin_id = str(node.get("plugin_id") or "").strip().lower()
            ps = node.get("plugin_settings") if isinstance(node.get("plugin_settings"), dict) else {}
            node_type = str(ps.get("node_type") or "").strip().lower()
            if plugin_id not in {"agent_flow_subflow", "flow_ref", "subflow"} and node_type != "fan_out_node":
                continue
            subflow_name = str(ps.get("subflow_name") or ps.get("loop_subflow_name") or "").strip()
            subflow_workflow_id = str(ps.get("subflow_workflow_id") or ps.get("loop_subflow_workflow_id") or "").strip()
            if not subflow_name and not subflow_workflow_id:
                continue
            key = (subflow_workflow_id, subflow_name)
            if key in seen:
                continue
            seen.add(key)
            refs.append({"flow_name": subflow_name, "workflow_id": subflow_workflow_id})
        return refs

    def _load_flow_doc_from_record(rec: Dict[str, Any]) -> tuple[Dict[str, Any], str]:
        flow_doc = rec.get("flow_json") if isinstance(rec.get("flow_json"), dict) else None
        flow_name = str(rec.get("flow_name") or "").strip()
        if isinstance(flow_doc, dict) and flow_doc:
            resolved_name = str(flow_doc.get("name") or flow_name).strip() or flow_name
            return dict(flow_doc), resolved_name
        workflow_file = _resolve_generated_path(str(rec.get("workflow_file") or "").strip())
        if not workflow_file.is_file():
            raise HTTPException(status_code=404, detail="workflow file not found")
        raw = workflow_file.read_text(encoding="utf-8")
        parsed_doc, parsed_name, warnings = ensure_flow_payload(raw, workflow_file.stem)
        if not isinstance(parsed_doc, dict):
            msg = ",".join([str(w) for w in warnings if str(w).strip()]) or "workflow_parse_failed"
            raise HTTPException(status_code=400, detail=f"workflow export invalid: {msg}")
        resolved_name = str(flow_name or parsed_name or parsed_doc.get("name") or workflow_file.stem).strip() or workflow_file.stem
        return parsed_doc, resolved_name

    def _flow_record_indexes(pid: str) -> Dict[str, Dict[str, Dict[str, Any]]]:
        by_id: Dict[str, Dict[str, Any]] = {}
        by_name: Dict[str, Dict[str, Any]] = {}

        def add_rows(rows: List[Dict[str, Any]]) -> None:
            for row in rows:
                if not isinstance(row, dict):
                    continue
                row_id = str(row.get("workflow_id") or row.get("id") or "").strip()
                row_name = str(row.get("flow_name") or "").strip()
                if row_id and row_id not in by_id:
                    by_id[row_id] = row
                if row_name and row_name not in by_name:
                    by_name[row_name] = row

        add_rows(_workflow_store.list_temp_library_records({"app": app, "pid": pid}))
        add_rows(_workflow_store.project_flow_records({"app": app, "pid": pid}, pid))
        add_rows(_workflow_store.default_flow_records({"app": app}))
        return {"by_id": by_id, "by_name": by_name}

    def _find_temp_library_record_from_filesystem(flow_name: str = "", workflow_id: str = "") -> Optional[Dict[str, Any]]:
        wanted_id = str(workflow_id or "").strip()
        wanted_name = str(flow_name or "").strip()
        root = _generated_temp_library_root()
        if not root.is_dir() or (not wanted_id and not wanted_name):
            return None
        candidates: List[Dict[str, Any]] = []
        for bundle_dir in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True):
            if not bundle_dir.is_dir():
                continue
            bundle_name = bundle_dir.name
            if wanted_id and bundle_name != wanted_id:
                if not wanted_name:
                    continue
            json_candidates: List[Path] = []
            if wanted_name:
                json_candidates.append(bundle_dir / f"{wanted_name}.json")
            json_candidates.extend(sorted(bundle_dir.glob("*.json")))
            for workflow_file in json_candidates:
                if not workflow_file.is_file():
                    continue
                try:
                    raw = workflow_file.read_text(encoding="utf-8")
                    flow_doc, parsed_name, warnings = ensure_flow_payload(raw, workflow_file.stem)
                except Exception:
                    continue
                if not isinstance(flow_doc, dict):
                    if wanted_id and bundle_name == wanted_id and not wanted_name:
                        continue
                    if warnings:
                        continue
                    continue
                resolved_name = str(parsed_name or flow_doc.get("name") or workflow_file.stem).strip() or workflow_file.stem
                if wanted_name and resolved_name != wanted_name and workflow_file.stem != wanted_name and bundle_name != wanted_name:
                    continue
                return {
                    "id": bundle_name,
                    "workflow_id": bundle_name,
                    "flow_name": resolved_name,
                    "flow_json": flow_doc,
                    "bundle_dir": str(bundle_dir.resolve()),
                    "workflow_file": str(workflow_file.resolve()),
                }
        return None

    def _resolve_export_flow_record(indexes: Dict[str, Dict[str, Dict[str, Any]]], *, flow_name: str = "", workflow_id: str = "") -> Optional[Dict[str, Any]]:
        by_id = indexes.get("by_id") if isinstance(indexes.get("by_id"), dict) else {}
        by_name = indexes.get("by_name") if isinstance(indexes.get("by_name"), dict) else {}
        wanted_id = str(workflow_id or "").strip()
        wanted_name = str(flow_name or "").strip()
        if wanted_id and wanted_id in by_id:
            return by_id[wanted_id]
        if wanted_name and wanted_name in by_name:
            return by_name[wanted_name]
        fs_row = _find_temp_library_record_from_filesystem(flow_name=wanted_name, workflow_id=wanted_id)
        if isinstance(fs_row, dict):
            row_id = str(fs_row.get("workflow_id") or fs_row.get("id") or "").strip()
            row_name = str(fs_row.get("flow_name") or "").strip()
            if row_id:
                by_id[row_id] = fs_row
            if row_name:
                by_name[row_name] = fs_row
            return fs_row
        return None

    def _compose_temp_library_export(pid: str, rec: Dict[str, Any]) -> Dict[str, Any]:
        root_record = dict(rec or {})
        root_id = str(root_record.get("workflow_id") or root_record.get("id") or "").strip()
        root_doc, root_name = _load_flow_doc_from_record(root_record)
        indexes = _flow_record_indexes(pid)
        if root_id:
            indexes.setdefault("by_id", {})[root_id] = root_record
        if root_name:
            indexes.setdefault("by_name", {})[root_name] = root_record

        flows: Dict[str, Dict[str, Any]] = {}
        records_by_name: Dict[str, Dict[str, Any]] = {}
        warnings: List[str] = []
        pending: List[Dict[str, Any]] = [{"record": root_record, "export_name": root_name}]
        seen: set[str] = set()

        while pending:
            item = pending.pop(0)
            row = item.get("record") if isinstance(item.get("record"), dict) else {}
            export_name = str(item.get("export_name") or row.get("flow_name") or "").strip()
            row_id = str(row.get("workflow_id") or row.get("id") or "").strip()
            seen_key = row_id or export_name
            if not seen_key or seen_key in seen:
                continue
            seen.add(seen_key)
            flow_doc, resolved_name = _load_flow_doc_from_record(row)
            portable = _portable_flow_copy(flow_doc)
            export_key = str(export_name or resolved_name or portable.get("name") or row.get("flow_name") or "workflow").strip() or "workflow"
            flows[export_key] = portable
            records_by_name[export_key] = row
            for ref in _extract_subflow_refs(flow_doc):
                sub_row = _resolve_export_flow_record(
                    indexes,
                    flow_name=str(ref.get("flow_name") or "").strip(),
                    workflow_id=str(ref.get("workflow_id") or "").strip(),
                )
                if not isinstance(sub_row, dict):
                    missing_bits = [str(ref.get("flow_name") or "").strip(), str(ref.get("workflow_id") or "").strip()]
                    missing_label = next((bit for bit in missing_bits if bit), "unknown_subflow")
                    warnings.append(f"subflow_export_missing:{missing_label}")
                    continue
                pending.append({"record": sub_row, "export_name": str(sub_row.get("flow_name") or ref.get("flow_name") or "").strip()})

        payload = {"flows": flows}
        canonical_json = json.dumps(payload, ensure_ascii=True, indent=2)
        return {
            "root_name": root_name,
            "payload": payload,
            "canonical_json": canonical_json,
            "records_by_name": records_by_name,
            "warnings": warnings,
        }

    def _stage_temp_library_export_bundle(pid: str, rec: Dict[str, Any]) -> Dict[str, Any]:
        export_payload = _compose_temp_library_export(pid, rec)
        root_name = str(export_payload.get("root_name") or rec.get("flow_name") or rec.get("id") or "workflow").strip() or "workflow"
        root_slug = re.sub(r"[^a-z0-9]+", "_", root_name.lower()).strip("_") or "workflow"
        stage_root = Path(tempfile.mkdtemp(prefix="agent_flow_export_"))
        try:
            workflow_json_path = stage_root / f"{root_slug}.json"
            atomic_write_text(workflow_json_path, str(export_payload.get("canonical_json") or ""), make_backup=False)

            records_by_name = export_payload.get("records_by_name") if isinstance(export_payload.get("records_by_name"), dict) else {}
            included_subflows = [name for name in records_by_name.keys() if str(name) != root_name]
            readme_lines = [
                f"# Workflow Bundle: {root_name}",
                "",
                "Contents:",
                f"- Portable workflow import: {workflow_json_path.name}",
                f"- Included flows: {len(records_by_name)}",
            ]
            if included_subflows:
                readme_lines.append(f"- Nested subflows: {', '.join(sorted(included_subflows))}")
            warnings = [str(item).strip() for item in export_payload.get("warnings") or [] if str(item).strip()]
            if warnings:
                readme_lines.extend(["", "Warnings:"])
                readme_lines.extend([f"- {item}" for item in warnings])
            atomic_write_text(stage_root / "README.md", "\n".join(readme_lines).strip() + "\n", make_backup=False)

            copied_bundle_sources: set[str] = set()

            def copy_bundle_dir(bundle_dir_raw: str, dest_dir: Path, *, skip_workflow_file: str = "") -> None:
                bundle_dir = _resolve_generated_path(str(bundle_dir_raw or "").strip())
                if not bundle_dir.is_dir():
                    return
                bundle_key = str(bundle_dir.resolve())
                if bundle_key in copied_bundle_sources:
                    return
                copied_bundle_sources.add(bundle_key)
                skip_file = str(_resolve_generated_path(str(skip_workflow_file or "").strip()).resolve()) if str(skip_workflow_file or "").strip() else ""
                for child in sorted(bundle_dir.rglob("*")):
                    if not child.is_file():
                        continue
                    if "__pycache__" in child.parts or child.suffix.lower() == ".pyc":
                        continue
                    child_resolved = str(child.resolve())
                    if skip_file and child_resolved == skip_file:
                        continue
                    rel = child.relative_to(bundle_dir)
                    out_path = dest_dir / rel
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(child), str(out_path))

            root_bundle_dir = str(rec.get("bundle_dir") or "").strip()
            root_workflow_file = str(rec.get("workflow_file") or "").strip()
            if root_bundle_dir:
                copy_bundle_dir(root_bundle_dir, stage_root / "root_bundle", skip_workflow_file=root_workflow_file)

            for name, row in sorted(records_by_name.items()):
                if not isinstance(row, dict) or name == root_name:
                    continue
                sub_bundle_dir = str(row.get("bundle_dir") or "").strip()
                sub_workflow_file = str(row.get("workflow_file") or "").strip()
                sub_slug = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_") or "subflow"
                if sub_bundle_dir:
                    copy_bundle_dir(sub_bundle_dir, stage_root / "subflows" / sub_slug, skip_workflow_file=sub_workflow_file)

            spec_rows, _ = discover_agent_flow_skills(app)
            skill_sources: Dict[str, Dict[str, str]] = {}
            for spec in spec_rows:
                if not isinstance(spec, dict):
                    continue
                skill_id = str(spec.get("id") or "").strip()
                skill_path = str(spec.get("_path") or "").strip()
                category = str(spec.get("category") or "").strip() or "uncategorized"
                if skill_id and skill_path:
                    skill_sources[skill_id] = {"path": skill_path, "category": category}

            referenced_skill_ids: set[str] = set()
            for flow_doc in (export_payload.get("payload", {}).get("flows") or {}).values():
                if isinstance(flow_doc, dict):
                    referenced_skill_ids.update(_collect_flow_tool_names(flow_doc))

            copied_skill_paths: set[str] = set()
            for skill_id in sorted(referenced_skill_ids):
                info = skill_sources.get(skill_id) or {}
                skill_path = Path(str(info.get("path") or "").strip())
                if not skill_path.is_file():
                    continue
                resolved_skill_path = str(skill_path.resolve())
                if resolved_skill_path in copied_skill_paths:
                    continue
                copied_skill_paths.add(resolved_skill_path)
                category = str(info.get("category") or "uncategorized").strip() or "uncategorized"
                dst = stage_root / "skills" / category / skill_path.name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(skill_path), str(dst))

            archive_name = f"{root_name}_bundle.zip"
            return _stage_directory_zip_for_download_global(stage_root, archive_name=archive_name, suffix_seed=str(rec.get("id") or ""))
        finally:
            shutil.rmtree(stage_root, ignore_errors=True)

    def _stage_zip_for_download_global(paths: List[Path], *, archive_name: str, suffix_seed: str = "") -> Dict[str, Any]:
        valid = [p.resolve() for p in paths if isinstance(p, Path) and p.exists()]
        if not valid:
            raise FileNotFoundError("no_files_to_zip")
        name = _unique_upload_name_global(archive_name or "agent_flow_result.zip", suffix_seed=suffix_seed)
        if not name.lower().endswith(".zip"):
            name = f"{name}.zip"
        dst = _uploads_dir_path_global() / name
        with zipfile.ZipFile(str(dst), "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for fp in valid:
                if fp.is_file():
                    zf.write(str(fp), arcname=fp.name)
                elif fp.is_dir():
                    for child in sorted(fp.rglob("*")):
                        if child.is_file():
                            zf.write(str(child), arcname=str(child.relative_to(fp.parent)))
        return {
            "name": Path(archive_name or "agent_flow_result.zip").name,
            "staged_name": name,
            "download_url": f"/uploads/{name}",
            "size_bytes": int(dst.stat().st_size),
            "file_count": sum(1 for fp in valid if fp.is_file()) or len(valid),
        }

    def _temp_library_ctx(pid: str) -> Dict[str, Any]:
        return {"app": app, "pid": pid, "settings": _runtime_base_settings()}

    def _temp_library_record(pid: str, record_id: str) -> Dict[str, Any]:
        out = workflow_temp_library.run(_temp_library_ctx(pid), {"action": "get", "record_id": record_id})
        if not isinstance(out, dict) or not out.get("ok"):
            raise HTTPException(status_code=404, detail="temp workflow not found")
        rec = out.get("record")
        if not isinstance(rec, dict):
            rec = out.get("data", {}).get("record") if isinstance(out.get("data"), dict) else None
        if not isinstance(rec, dict):
            raise HTTPException(status_code=404, detail="temp workflow not found")
        return rec

    def _temp_library_record_skill_access(user: Any, rec: Dict[str, Any]) -> Dict[str, Any]:
        workflow_file = _resolve_generated_path(str((rec or {}).get("workflow_file") or "").strip()).resolve()
        if not workflow_file.is_file():
            return {"allowed": False, "missing": [], "all": [], "warnings": ["workflow_file_not_found"]}
        try:
            flows_map, _root_flow_name, warnings = _load_import_flows_payload(workflow_file)
        except HTTPException:
            raise
        except Exception as exc:
            return {"allowed": False, "missing": [], "all": [], "warnings": [f"workflow_skill_scan_failed:{exc}"]}
        referenced = set()
        for flow_doc in flows_map.values() if isinstance(flows_map, dict) else []:
            if isinstance(flow_doc, dict):
                referenced.update(extract_referenced_skills(flow_doc))
        all_skills = sorted({str(x or "").strip() for x in referenced if str(x or "").strip()})
        try:
            from plugins.gui_helpers.permissions_manager.core import can_access_skill, compute_effective_permissions
            summary = compute_effective_permissions(app, user)
            if summary.get("is_admin"):
                return {"allowed": True, "missing": [], "all": all_skills, "warnings": list(warnings or [])}
            missing = [skill_id for skill_id in all_skills if not can_access_skill(summary, skill_id)]
            return {"allowed": len(missing) == 0, "missing": missing, "all": all_skills, "warnings": list(warnings or [])}
        except Exception:
            return {"allowed": True, "missing": [], "all": all_skills, "warnings": list(warnings or [])}

    def _require_temp_library_record_access(user: Any, rec: Dict[str, Any], *, action: str = "access") -> Dict[str, Any]:
        access = _temp_library_record_skill_access(user, rec)
        if not access.get("allowed"):
            raise HTTPException(
                status_code=403,
                detail={
                    "message": f"AWF library {action} denied: workflow uses skills not allowed for this user",
                    "denied_skills": list(access.get("missing") or []),
                    "workflow_skills": list(access.get("all") or []),
                },
            )
        return access

    async def _import_bundle_to_temp_library(pid: str, upload: UploadFile) -> Dict[str, Any]:
        filename = Path(str(getattr(upload, "filename", "") or "agent_flow_bundle.zip")).name
        if not filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="bundle_must_be_zip")
        token = secrets.token_hex(6)
        root = _generated_temp_library_root()
        stage_dir = root / f"import_bundle_{token}"
        tmp_zip = stage_dir.with_suffix(".zip")
        stage_dir.mkdir(parents=True, exist_ok=True)
        try:
            data = await upload.read()
            if not data:
                raise HTTPException(status_code=400, detail="bundle_upload_empty")
            tmp_zip.write_bytes(data)
            _safe_extract_zip_to_dir(tmp_zip, stage_dir)
            workflow_file = _find_bundle_workflow_file(stage_dir)
            flows_map, root_flow_name, warnings = _load_import_flows_payload(workflow_file)
            root_flow = flows_map.get(root_flow_name) if isinstance(flows_map.get(root_flow_name), dict) else {}
            public_meta = _derive_public_workflow_metadata(
                flow_name=root_flow_name,
                request_text="",
                summary=root_flow.get("description") or "",
                description=root_flow.get("description") or "",
                tags=[],
            )
            root_flow_name = str(public_meta.get("flow_name") or root_flow_name).strip() or "workflow"
            summary = str(public_meta.get("summary") or root_flow.get("description") or "").strip()
            record_id = f"{slugify(root_flow_name, 'workflow')}_{int(time.time())}"
            final_dir = root / record_id
            suffix = 2
            while final_dir.exists():
                final_dir = root / f"{record_id}_{suffix}"
                suffix += 1
            stage_dir.rename(final_dir)
            workflow_file_final = final_dir / workflow_file.relative_to(stage_dir)
            record = _workflow_store.upsert_temp_library_record(
                {"app": app, "pid": pid},
                {
                    "workflow_id": final_dir.name,
                    "id": final_dir.name,
                    "flow_name": root_flow_name,
                    "flow_json": root_flow,
                    "bundle_dir": str(final_dir.resolve()),
                    "workflow_file": str(workflow_file_final.resolve()),
                    "source_request": "",
                    "summary": summary,
                    "description": summary or f"Imported workflow bundle for {root_flow_name}.",
                    "tags": sorted({str(x).strip().lower() for x in re.findall(r"[A-Za-z0-9_]+", f"{root_flow_name} {summary}") if str(x).strip()}),
                    "validated": False,
                    "all_passed": False,
                    "pass_count": 0,
                    "fail_count": 0,
                    "installed": False,
                    "installed_ts": 0,
                    "installed_flow_name": "",
                    "installed_flow_names": [],
                    "installed_skill_files": [],
                    "installed_skill_ids": [],
                    "metadata": {
                        "imported_bundle": True,
                        "imported_bundle_filename": filename,
                        "imported_flow_names": sorted(flows_map.keys()),
                        "import_warnings": warnings,
                    },
                },
            )
            _append_temp_library_pass_log(
                request_id=final_dir.name,
                source_file=filename,
                record=record,
                validation_profile="agent_flow_bundle_import_register",
                selected_flow_source="agent_flow_bundle_import",
                notes=f"imported_bundle_filename={filename}",
            )
            return {
                "record": record,
                "flow_name": root_flow_name,
                "flow_names": sorted(flows_map.keys()),
                "warnings": warnings,
            }
        finally:
            try:
                if tmp_zip.exists():
                    tmp_zip.unlink()
            except Exception:
                pass
            try:
                if stage_dir.exists():
                    shutil.rmtree(stage_dir, ignore_errors=True)
            except Exception:
                pass

    def _temp_library_record_public(rec: Dict[str, Any], *, pid: str, sid: str) -> Dict[str, Any]:
        row = dict(rec or {})
        record_id = str(row.get("id") or "").strip()
        workflow_id = str(row.get("workflow_id") or row.get("id") or "").strip()
        updates = _workflow_store.list_workflow_updates(
            {"app": app, "pid": pid},
            workflow_id=workflow_id,
            flow_name="" if workflow_id else str(row.get("flow_name") or "").strip(),
            scope="temp_library",
            pid="__temp_library__",
            limit=6,
        )
        latest_update = updates[0] if updates else {}
        latest_status = str(latest_update.get("status_label") or "--").strip() or "--"
        latest_reason = str(latest_update.get("update_reason") or "").strip()
        latest_summary = str(latest_update.get("summary") or "").strip()
        latest_bugs = [str(x or "").strip() for x in (latest_update.get("bugs") if isinstance(latest_update.get("bugs"), list) else []) if str(x or "").strip()]
        knowledge_lines = [f"Latest update status: {latest_status}"]
        if latest_reason:
            knowledge_lines.append(f"Latest update reason: {latest_reason}")
        if latest_summary:
            knowledge_lines.append(f"Latest update summary: {latest_summary}")
        if latest_bugs:
            knowledge_lines.append("Latest fix notes:")
            knowledge_lines.extend([f"- {item}" for item in latest_bugs[:6]])
        row["workflow_updates"] = updates
        row["latest_update_status"] = latest_status
        row["latest_update_reason"] = latest_reason
        row["latest_knowledgebase_summary"] = "\n".join(knowledge_lines).strip()
        row["workflow_export_path"] = f"/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library/{record_id}/export_workflow"
        row["bundle_export_path"] = f"/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library/{record_id}/export_bundle"
        row["delete_path"] = f"/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library/{record_id}"
        row["install_path"] = f"/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library/{record_id}/install"
        row["uninstall_path"] = f"/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library/{record_id}/uninstall"
        row["validate_path"] = f"/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library/{record_id}/validate"
        return row

    def _temp_library_update(pid: str, record_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        out = workflow_temp_library.run(_temp_library_ctx(pid), {"action": "update", "record_id": record_id, "patch": patch or {}})
        if not isinstance(out, dict) or not out.get("ok"):
            raise HTTPException(status_code=404, detail="temp workflow not found")
        rec = out.get("record")
        if not isinstance(rec, dict):
            rec = out.get("data", {}).get("record") if isinstance(out.get("data"), dict) else None
        if not isinstance(rec, dict):
            raise HTTPException(status_code=404, detail="temp workflow not found")
        return rec

    def _extract_skill_id_from_text(raw: str) -> str:
        text = str(raw or "")
        for pat in [
            r"(?m)^\s*NAME\s*=\s*['\"]([^'\"]+)['\"]",
            r"['\"]id['\"]\s*:\s*['\"]([^'\"]+)['\"]",
        ]:
            m = re.search(pat, text)
            if m:
                return str(m.group(1) or "").strip()
        return ""

    def _patch_flow_skill_ids(obj: Any, mapping: Dict[str, str]) -> Any:
        if isinstance(obj, dict):
            return {k: _patch_flow_skill_ids(v, mapping) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_patch_flow_skill_ids(v, mapping) for v in obj]
        if isinstance(obj, str):
            return mapping.get(obj, obj)
        return obj

    def _safe_extract_zip_to_dir(zip_path: Path, dest_dir: Path) -> List[str]:
        extracted: List[str] = []
        root = dest_dir.resolve()
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            for member in zf.infolist():
                member_name = str(member.filename or "").replace("\\", "/").strip()
                if not member_name or member_name.endswith("/"):
                    continue
                if member_name.startswith("/") or member_name.startswith("../") or "/../" in member_name:
                    continue
                target = (root / member_name).resolve()
                try:
                    target.relative_to(root)
                except Exception:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member, "r") as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted.append(str(target))
        return extracted

    def _load_import_flows_payload(workflow_file: Path) -> tuple[Dict[str, Dict[str, Any]], str, List[str]]:
        try:
            raw = workflow_file.read_text(encoding="utf-8")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"workflow_file_read_failed:{exc}")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = None
        warnings: List[str] = []
        if isinstance(payload, dict) and isinstance(payload.get("flows"), dict) and payload.get("flows"):
            flows: Dict[str, Dict[str, Any]] = {}
            for name, flow_doc in payload.get("flows", {}).items():
                flow_name = str(name or "").strip()
                if flow_name and isinstance(flow_doc, dict):
                    flows[flow_name] = dict(flow_doc)
            if flows:
                root_name = next(iter(flows.keys()))
                return flows, root_name, warnings
        flow_def, flow_name, parse_warnings = ensure_flow_payload(raw, workflow_file.stem)
        warnings.extend(parse_warnings)
        if not isinstance(flow_def, dict) or not str(flow_name or "").strip():
            raise HTTPException(status_code=400, detail=f"workflow_invalid:{','.join(warnings or ['parse_failed'])}")
        return {str(flow_name): dict(flow_def)}, str(flow_name), warnings

    def _iter_bundle_skill_sources(bundle_dir: Path) -> List[Path]:
        roots: List[Path] = []
        for candidate in (
            bundle_dir / "skills",
            bundle_dir / "root_bundle" / "skills",
        ):
            if candidate.is_dir():
                roots.append(candidate)
        subflows_dir = bundle_dir / "subflows"
        if subflows_dir.is_dir():
            for child in sorted(subflows_dir.iterdir()):
                skill_root = child / "skills"
                if skill_root.is_dir():
                    roots.append(skill_root)
        deduped: List[Path] = []
        seen: set[str] = set()
        for item in roots:
            key = str(item.resolve())
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _find_bundle_workflow_file(bundle_dir: Path) -> Path:
        top_level = [p for p in sorted(bundle_dir.glob("*.json")) if p.is_file()]
        candidates = top_level or [
            p for p in sorted(bundle_dir.rglob("*.json"))
            if p.is_file() and "subflows" not in p.parts and "root_bundle" not in p.parts and "skills" not in p.parts
        ]
        best: Optional[Path] = None
        for fp in candidates:
            try:
                payload = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get("flows"), dict) and payload.get("flows"):
                return fp
            if best is None:
                best = fp
        if best is None:
            raise HTTPException(status_code=400, detail="bundle_workflow_json_not_found")
        return best

    def _install_temp_library_record(pid: str, record_id: str) -> Dict[str, Any]:
        rec = _temp_library_record(pid, record_id)
        workflow_file = _resolve_generated_path(str(rec.get("workflow_file") or "").strip()).resolve()
        bundle_dir = _resolve_generated_path(str(rec.get("bundle_dir") or "").strip()).resolve()
        if not workflow_file.is_file():
            raise HTTPException(status_code=404, detail="workflow file not found")
        if not bundle_dir.is_dir():
            raise HTTPException(status_code=404, detail="bundle directory not found")
        flows_map, root_flow_name, warnings = _load_import_flows_payload(workflow_file)

        skills_root = Path(__file__).resolve().parent / "skills"
        mapping: Dict[str, str] = {}
        installed_skill_files: List[str] = []
        installed_skill_ids: List[str] = []
        for bundle_skills_root in _iter_bundle_skill_sources(bundle_dir):
            for src in sorted(bundle_skills_root.rglob("*.py")):
                if "__pycache__" in src.parts or src.suffix.lower() == ".pyc":
                    continue
                try:
                    rel = src.relative_to(bundle_skills_root)
                except Exception:
                    continue
                parts = list(rel.parts)
                if len(parts) < 2:
                    continue
                category = str(parts[0] or "").strip()
                if not category:
                    continue
                try:
                    text = src.read_text(encoding="utf-8")
                except Exception:
                    continue
                original_id = _extract_skill_id_from_text(text)
                dest_dir = skills_root / category
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_name = f"awf_{record_id}__{src.name}"
                dest_path = dest_dir / dest_name
                updated_text = text
                if original_id:
                    base_tail = original_id.split(".", 1)[-1].strip() or src.stem
                    namespaced_tail = f"awf_{record_id}__{base_tail}"
                    new_id = f"{category}.{namespaced_tail}"
                    mapping[original_id] = new_id
                    updated_text = updated_text.replace(original_id, new_id)
                    installed_skill_ids.append(new_id)
                atomic_write_text(dest_path, updated_text, make_backup=False)
                installed_skill_files.append(str(dest_path))

        installed_flows: Dict[str, Dict[str, Any]] = {}
        for name, flow_def in flows_map.items():
            if not isinstance(flow_def, dict):
                continue
            installed_flows[str(name)] = _patch_flow_skill_ids(flow_def, mapping) if mapping else dict(flow_def)
        project_doc = _load_project_flows(pid)
        project_flows = project_doc.get("flows") if isinstance(project_doc, dict) and isinstance(project_doc.get("flows"), dict) else {}
        project_flows = dict(project_flows or {})
        for name, flow_def in installed_flows.items():
            project_flows[str(name)] = flow_def
        _save_project_flows(pid, project_flows)

        default_doc = _load_default_flows_doc()
        default_flows = default_doc.get("flows") if isinstance(default_doc, dict) and isinstance(default_doc.get("flows"), dict) else {}
        default_flows = dict(default_flows or {})
        for name, flow_def in installed_flows.items():
            default_flows[str(name)] = flow_def
        _save_default_flows(default_flows)

        skill_load_info_local = register_agent_flow_skills(app)
        installed_flow_names = sorted({str(name or "").strip() for name in installed_flows.keys() if str(name or "").strip()})
        updated = _temp_library_update(pid, record_id, {
            "installed": True,
            "installed_ts": _now_ts(),
            "installed_flow_name": str(root_flow_name),
            "installed_flow_names": installed_flow_names,
            "installed_skill_files": installed_skill_files,
            "installed_skill_ids": sorted(set(installed_skill_ids)),
        })
        return {
            "record": updated,
            "flow_name": str(root_flow_name),
            "flow_names": installed_flow_names,
            "skill_files": installed_skill_files,
            "skill_ids": sorted(set(installed_skill_ids)),
            "skill_load": skill_load_info_local,
            "warnings": warnings,
        }

    def _uninstall_temp_library_record(pid: str, record_id: str) -> Dict[str, Any]:
        rec = _temp_library_record(pid, record_id)
        flow_names = rec.get("installed_flow_names") if isinstance(rec.get("installed_flow_names"), list) else []
        normalized_flow_names = [str(item or "").strip() for item in flow_names if str(item or "").strip()]
        fallback_flow_name = str(rec.get("installed_flow_name") or rec.get("flow_name") or "").strip()
        if fallback_flow_name and fallback_flow_name not in normalized_flow_names:
            normalized_flow_names.append(fallback_flow_name)
        if normalized_flow_names:
            project_doc = _load_project_flows(pid)
            project_flows = project_doc.get("flows") if isinstance(project_doc, dict) and isinstance(project_doc.get("flows"), dict) else {}
            project_flows = dict(project_flows or {})
            for flow_name in normalized_flow_names:
                project_flows.pop(flow_name, None)
            _save_project_flows(pid, project_flows)

            default_doc = _load_default_flows_doc()
            default_flows = default_doc.get("flows") if isinstance(default_doc, dict) and isinstance(default_doc.get("flows"), dict) else {}
            default_flows = dict(default_flows or {})
            for flow_name in normalized_flow_names:
                default_flows.pop(flow_name, None)
            _save_default_flows(default_flows)

        removed_files: List[str] = []
        for raw_path in rec.get("installed_skill_files") or []:
            path_s = str(raw_path or "").strip()
            if not path_s:
                continue
            try:
                fp = Path(path_s).resolve()
                if fp.is_file():
                    fp.unlink()
                    removed_files.append(str(fp))
            except Exception:
                continue
        skill_load_info_local = register_agent_flow_skills(app)
        updated = _temp_library_update(pid, record_id, {
            "installed": False,
            "installed_ts": 0,
            "installed_flow_name": "",
            "installed_flow_names": [],
            "installed_skill_files": [],
            "installed_skill_ids": [],
        })
        return {
            "record": updated,
            "removed_files": removed_files,
            "skill_load": skill_load_info_local,
        }

    def _temp_library_validation_passed(*rows: Any) -> bool:
        for source in rows:
            if not isinstance(source, dict):
                continue
            tool_rows = source.get("tool_results") if isinstance(source.get("tool_results"), list) else []
            for row in tool_rows:
                if not isinstance(row, dict):
                    continue
                skill = str(row.get("skill") or "").strip().lower()
                if skill != "workflow.review_suite":
                    continue
                data = row.get("data") if isinstance(row.get("data"), dict) else {}
                if bool(data.get("all_passed")) or bool(row.get("all_passed")):
                    return True
                return False
        return False

    def _temp_library_validation_findings(*rows: Any) -> Dict[str, Any]:
        bugs: List[str] = []
        fixes: List[str] = []
        summary = ""

        def _append_unique(dest: List[str], values: Any) -> None:
            if not isinstance(values, list):
                return
            seen = {str(x or "").strip().lower() for x in dest if str(x or "").strip()}
            for item in values:
                text = str(item or "").strip()
                low = text.lower()
                if not text or low in seen:
                    continue
                seen.add(low)
                dest.append(text)

        for source in rows:
            if not isinstance(source, dict):
                continue
            tool_rows = source.get("tool_results") if isinstance(source.get("tool_results"), list) else []
            for row in tool_rows:
                if not isinstance(row, dict):
                    continue
                skill = str(row.get("skill") or "").strip().lower()
                if skill != "workflow.review_suite":
                    continue
                data = row.get("data") if isinstance(row.get("data"), dict) else {}
                _append_unique(bugs, data.get("bugs") if isinstance(data.get("bugs"), list) else row.get("bugs"))
                _append_unique(fixes, data.get("fixes") if isinstance(data.get("fixes"), list) else row.get("fixes"))
                if not summary:
                    summary = str(data.get("summary") or row.get("summary") or "").strip()
                return {"bugs": bugs[:12], "fixes": fixes[:12], "summary": summary}
        return {"bugs": bugs[:12], "fixes": fixes[:12], "summary": summary}

    def _canonical_hash(obj: Any) -> str:
        try:
            blob = json.dumps(obj if obj is not None else {}, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        except Exception:
            blob = "{}"
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _default_flow_library() -> Dict[str, Any]:
        return _workflow_store.load_default_flows({"app": app})

    def _flow_skill_access(user: Any, flow_def: Dict[str, Any]) -> Dict[str, Any]:
        referenced = sorted({str(x or "").strip() for x in extract_referenced_skills(flow_def or {}) if str(x or "").strip()})
        try:
            from plugins.gui_helpers.permissions_manager.core import can_access_skill, compute_effective_permissions
            summary = compute_effective_permissions(app, user)
            if summary.get("is_admin"):
                return {"allowed": True, "missing": [], "all": referenced}
            missing = [skill_id for skill_id in referenced if not can_access_skill(summary, skill_id)]
            return {"allowed": len(missing) == 0, "missing": missing, "all": referenced}
        except Exception:
            return {"allowed": True, "missing": [], "all": referenced}

    def _filter_flows_for_user(user: Any, flows: Dict[str, Any]) -> Dict[str, Any]:
        src = flows if isinstance(flows, dict) else {}
        out: Dict[str, Any] = {}
        for name, flow_def in src.items():
            if not isinstance(flow_def, dict):
                continue
            access = _flow_skill_access(user, flow_def)
            if access.get("allowed"):
                out[str(name)] = flow_def
        return out

    def _require_flow_access(user: Any, flow_name: str, flow_def: Dict[str, Any], *, action: str = "access") -> Dict[str, Any]:
        access = _flow_skill_access(user, flow_def)
        if not access.get("allowed"):
            raise HTTPException(
                status_code=403,
                detail={
                    "message": f"Flow {action} denied: workflow uses skills not allowed for this user",
                    "flow_name": str(flow_name or "").strip(),
                    "denied_skills": list(access.get("missing") or []),
                    "workflow_skills": list(access.get("all") or []),
                },
            )
        return access

    def _flow_version_diag(*, pid: str, active_flow: str, runtime_flows: Dict[str, Any] | None = None) -> Dict[str, Any]:
        proj_flows = _load_project_flows(pid).get("flows") if isinstance(_load_project_flows(pid), dict) else {}
        if not isinstance(proj_flows, dict):
            proj_flows = {}
        def_flows = _default_flow_library()
        run_flows = runtime_flows if isinstance(runtime_flows, dict) else {}
        active = str(active_flow or "").strip()
        run_def = run_flows.get(active) if active else None
        proj_def = proj_flows.get(active) if active else None
        def_def = def_flows.get(active) if active else None
        run_hash = _canonical_hash(run_def) if run_def is not None else ""
        proj_hash = _canonical_hash(proj_def) if proj_def is not None else ""
        def_hash = _canonical_hash(def_def) if def_def is not None else ""
        warnings: List[str] = []
        if run_hash and proj_hash and run_hash != proj_hash:
            warnings.append("active_flow_runtime_differs_from_project_file")
        if proj_hash and def_hash and proj_hash != def_hash:
            warnings.append("project_flow_differs_from_default_library")
        if run_hash and def_hash and run_hash != def_hash:
            warnings.append("active_flow_runtime_differs_from_default_library")
        return {
            "active_flow": active,
            "runtime_hash": run_hash,
            "project_hash": proj_hash,
            "default_hash": def_hash,
            "warnings": warnings,
        }

    def _agent_flow_state_key(pid: str, sid: str, run_id: str = "") -> str:
        rid = str(run_id or "").strip()
        return f"{pid}::{sid}::{rid}" if rid else f"{pid}::{sid}"

    def _agent_flow_get_state(pid: str, sid: str, run_id: str = "") -> Optional[Dict[str, Any]]:
        key = _agent_flow_state_key(pid, sid, run_id)
        lock = app.state.agent_flow_runs_lock
        with lock:
            state = app.state.agent_flow_runs.get(key)
            return dict(state) if isinstance(state, dict) else None

    def _agent_flow_set_state(pid: str, sid: str, state: Dict[str, Any], preserve_pause: bool = True) -> None:
        run_id = str((state or {}).get("run_id") or "").strip()
        key = _agent_flow_state_key(pid, sid, run_id)
        latest_key = _agent_flow_state_key(pid, sid)
        lock = app.state.agent_flow_runs_lock
        with lock:
            if preserve_pause and state.get("running"):
                current = app.state.agent_flow_runs.get(key)
                if isinstance(current, dict) and (current.get("paused") or current.get("pause_requested")) and not (state.get("paused") or state.get("pause_requested")):
                    state["paused"] = bool(current.get("paused"))
                    state["pause_requested"] = bool(current.get("pause_requested"))
                    state["status"] = current.get("status") or state.get("status") or "Paused"
            app.state.agent_flow_runs[key] = dict(state)
            app.state.agent_flow_runs[latest_key] = dict(state)

    def _agent_flow_clear_state(pid: str, sid: str, run_id: str = "") -> None:
        key = _agent_flow_state_key(pid, sid, run_id)
        lock = app.state.agent_flow_runs_lock
        with lock:
            app.state.agent_flow_runs.pop(key, None)

    def _agent_flow_publish_state(pid: str, sid: str, state: Dict[str, Any], update: Optional[Dict[str, Any]] = None) -> None:
        payload = dict(state or {})
        payload.update(update or {})
        payload["pid"] = pid
        payload["sid"] = sid
        payload["run_id"] = str(payload.get("run_id") or "").strip()
        try:
            app.state.collab_hub.publish(pid, sid, event="flow_status", data=payload)
        except Exception:
            pass

    def _agent_flow_running_state_is_orphaned(state: Dict[str, Any]) -> bool:
        if not isinstance(state, dict) or not state.get("running"):
            return False
        run_id0 = str(state.get("run_id") or "").strip()
        age_s = max(0, _now_ts() - int(state.get("ts") or 0))
        ai_jobs0 = getattr(app.state, "ai_jobs", None)
        if run_id0 and ai_jobs0 is not None and hasattr(ai_jobs0, "get"):
            try:
                if ai_jobs0.get(run_id0) is None:
                    return True
            except Exception:
                pass
        # If the job registry cannot be queried, do not keep an old in-memory
        # lock forever. Active workers update/finish the state before this age.
        return age_s > 15 * 60

    def _runtime_base_settings() -> Dict[str, Any]:
        try:
            state_settings = getattr(app.state, "settings", None)
            if callable(state_settings):
                loaded = state_settings()
                if isinstance(loaded, dict):
                    return dict(loaded)
            elif isinstance(state_settings, dict):
                return dict(state_settings)
        except Exception:
            pass
        return {}

    def _apply_system_prompt(messages: List[Dict[str, Any]], prompt: str) -> List[Dict[str, Any]]:
        text = str(prompt or "").strip()
        if not text:
            return messages
        system_msg = {"role": "system", "content": text}
        sys = [m for m in messages if (m.get("role") or "").lower() == "system"]
        rest = [m for m in messages if (m.get("role") or "").lower() != "system"]
        return sys + [system_msg] + rest

    def _default_condition_rule() -> Dict[str, Any]:
        return {"kind": "rule", "type": "always", "value": ""}

    def _normalize_transition_condition_node(condition: Any) -> Dict[str, Any]:
        raw = condition if isinstance(condition, dict) else {}
        if isinstance(raw.get("rules"), list):
            operator = str(raw.get("operator") or raw.get("mode") or "all").strip().lower()
            operator = "any" if operator == "any" else "all"
            rules = [_normalize_transition_condition_node(row) for row in (raw.get("rules") or [])]
            rules = [row for row in rules if isinstance(row, dict)]
            if not rules:
                rules = [_default_condition_rule()]
            return {"kind": "group", "operator": operator, "rules": rules}
        return {
            "kind": "rule",
            "type": str(raw.get("type") or "always").strip() or "always",
            "value": str(raw.get("value") or "").strip(),
        }

    def _normalize_transition_condition(condition: Any) -> Dict[str, Any]:
        normalized = _normalize_transition_condition_node(condition)
        if normalized.get("kind") == "group":
            return normalized
        return {"kind": "group", "operator": "all", "rules": [normalized]}

    def _is_always_transition_condition(condition: Any) -> bool:
        normalized = _normalize_transition_condition(condition)
        rules = normalized.get("rules") if isinstance(normalized.get("rules"), list) else []
        return len(rules) == 1 and str((rules[0] or {}).get("kind") or "") == "rule" and str((rules[0] or {}).get("type") or "") == "always"

    def _transition_action_config(transition: Any) -> Dict[str, Any]:
        if not isinstance(transition, dict):
            return {}
        nested = transition.get("edge_action") if isinstance(transition.get("edge_action"), dict) else {}
        out: Dict[str, Any] = {}
        tool = str(nested.get("tool") or transition.get("action_tool") or "").strip()
        if tool:
            out["tool"] = tool
        params = nested.get("params") if isinstance(nested.get("params"), dict) else transition.get("action_params")
        if isinstance(params, dict) and params:
            out["params"] = dict(params)
        params_from_input = (
            nested.get("params_from_input")
            if isinstance(nested.get("params_from_input"), list)
            else transition.get("action_params_from_input")
        )
        if isinstance(params_from_input, list) and params_from_input:
            out["params_from_input"] = [str(x or "").strip() for x in params_from_input if str(x or "").strip()]
        runtime_only = nested.get("runtime_only") if "runtime_only" in nested else transition.get("runtime_only")
        if runtime_only is not None:
            out["runtime_only"] = bool(runtime_only)
        return out

    def _transition_requires_runtime(transition: Any) -> bool:
        cfg = _transition_action_config(transition)
        return bool(cfg.get("tool")) or bool(cfg.get("runtime_only"))

    def _choose_default_transition(node: Dict[str, Any], visited: set[str], nodes: Dict[str, Any]) -> Optional[str]:
        transitions = node.get("transitions") if isinstance(node.get("transitions"), list) else []
        if not transitions:
            return None
        for row in transitions:
            target = str((row.get("target") if isinstance(row, dict) else row) or "").strip()
            if not target or target in visited or target not in nodes:
                continue
            if _transition_requires_runtime(row):
                continue
            if _is_always_transition_condition(row.get("condition") if isinstance(row, dict) else {}):
                return target
        # No default fallback for conditional transitions.
        # Conditional edges are injected at runtime after node output is available.
        return None

    def _step_report_text(report: Optional[Dict[str, Any]]) -> str:
        if not isinstance(report, dict):
            return ""
        parts: List[str] = []
        for key in ("did", "plan", "analysis", "response", "handoff"):
            v = str(report.get(key) or "").strip()
            if v:
                parts.append(v)
        for key in ("actions", "bugs", "fixes"):
            rows = report.get(key)
            if isinstance(rows, list):
                parts.extend(str(x or "").strip() for x in rows if str(x or "").strip())
        tr_rows = report.get("tool_results")
        if isinstance(tr_rows, list):
            for tr in tr_rows:
                if not isinstance(tr, dict):
                    continue
                data = tr.get("data") if isinstance(tr.get("data"), dict) else {}
                for key in (
                    "handoff",
                    "coverage_status",
                    "route",
                    "status",
                    "decision",
                    "flow_name",
                    "bundle_dir",
                    "workflow_file",
                ):
                    v = str(data.get(key) or tr.get(key) or "").strip()
                    if v:
                        parts.append(v)
        deduped: List[str] = []
        seen_parts = set()
        for part in parts:
            sval = str(part or "").strip()
            if not sval or sval in seen_parts:
                continue
            seen_parts.add(sval)
            deduped.append(sval)
        return "\n".join(deduped).strip()

    def _tool_result_list_field(rows: Any, field: str) -> List[str]:
        out: List[str] = []
        if not isinstance(rows, list):
            return out
        key = str(field or "").strip()
        if not key:
            return out
        for row in rows:
            if not isinstance(row, dict):
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            vals = data.get(key)
            if vals is None:
                vals = row.get(key)
            if isinstance(vals, list):
                for v in vals:
                    s = str(v or "").strip()
                    if s:
                        out.append(s)
            else:
                s = str(vals or "").strip()
                if s:
                    out.append(s)
        seen = set()
        uniq: List[str] = []
        for v in out:
            if v in seen:
                continue
            seen.add(v)
            uniq.append(v)
        return uniq

    def _parse_state_map_spec(raw: Any) -> Dict[str, str]:
        obj = raw
        if isinstance(obj, str):
            text = str(obj or "").strip()
            if not text:
                return {}
            try:
                obj = json.loads(text)
            except Exception:
                return {}
        if not isinstance(obj, dict):
            return {}
        out: Dict[str, str] = {}
        for key, value in obj.items():
            k = str(key or "").strip()
            v = str(value or "").strip()
            if k and v:
                out[k] = v
        return out

    def _read_path_value(source: Any, path: str) -> Any:
        cur = source
        for part in [p for p in str(path or "").split(".") if str(p or "").strip()]:
            if isinstance(cur, dict):
                if part not in cur:
                    return None
                cur = cur.get(part)
                continue
            if isinstance(cur, list):
                try:
                    idx = int(part)
                except Exception:
                    return None
                if idx < 0 or idx >= len(cur):
                    return None
                cur = cur[idx]
                continue
            return None
        return cur

    def _resolve_path_from_sources(path: str, *sources: Any) -> Any:
        p = str(path or "").strip()
        if not p:
            return None
        for source in sources:
            val = _read_path_value(source, p)
            if val not in (None, "", []):
                return val
        return None

    def _extract_candidate_file_from_text(text: str) -> str:
        s = str(text or "")
        if not s:
            return ""
        patterns = [
            r"([A-Za-z]:[/\\\\][^\s\"']+\.(?:xlsx|xlsm|xls|csv|tsv|pdf|json|txt|js|ts|py|png|jpg|jpeg|webp|bmp|tif|tiff))",
            r"(/[^\\s\"']+\.(?:xlsx|xlsm|xls|csv|tsv|pdf|json|txt|js|ts|py|png|jpg|jpeg|webp|bmp|tif|tiff))",
            r"([A-Za-z0-9_.\\/-]+\.(?:xlsx|xlsm|xls|csv|tsv|pdf|json|txt|js|ts|py|png|jpg|jpeg|webp|bmp|tif|tiff))",
        ]
        for pat in patterns:
            m = re.search(pat, s, flags=re.IGNORECASE)
            if m:
                return str(m.group(1) or "").strip().strip("'\"")
        return ""

    def _tool_result_paths(report: Optional[Dict[str, Any]]) -> List[str]:
        out: List[str] = []
        if not isinstance(report, dict):
            return out
        rows = report.get("tool_results")
        if not isinstance(rows, list):
            return out
        for row in rows:
            if not isinstance(row, dict):
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            for key in ("path", "file", "file_path", "output_path", "source_pdf_path", "input_path", "workflow_file", "readme_file", "download_path"):
                v = str(data.get(key) or row.get(key) or "").strip()
                if v:
                    out.append(v)
            for key in ("final_paths", "requested_paths", "changed_files", "files", "bundle_files", "stub_files"):
                vals = data.get(key) if isinstance(data.get(key), list) else []
                for v0 in vals:
                    v = str(v0 or "").strip()
                    if v:
                        out.append(v)
        seen = set()
        uniq: List[str] = []
        for v in out:
            if v in seen:
                continue
            seen.add(v)
            uniq.append(v)
        return uniq

    def _step_test_failure_count(report: Optional[Dict[str, Any]]) -> int:
        if not isinstance(report, dict):
            return 0
        total = 0
        rows = report.get("tool_results")
        if not isinstance(rows, list):
            return 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            skill = str(row.get("skill") or "").strip().lower()
            if not skill.startswith("tests."):
                continue
            if row.get("ok") is False:
                total += 1
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            parsed = data.get("parsed") if isinstance(data.get("parsed"), dict) else {}
            for key in ("failed", "failures", "tests_failed", "failed_tests"):
                try:
                    val = int(parsed.get(key))
                except Exception:
                    val = None
                if val is not None:
                    total = max(total, val)
        return total

    def _transition_matches(
        transition: Dict[str, Any],
        *,
        last_step_report: Optional[Dict[str, Any]],
        recent_changed_files: List[str],
    ) -> bool:
        text = _step_report_text(last_step_report).lower()
        bugs = last_step_report.get("bugs") if isinstance(last_step_report, dict) and isinstance(last_step_report.get("bugs"), list) else []
        did_text = str(last_step_report.get("did") or "").lower() if isinstance(last_step_report, dict) else ""
        handoff_text = str(last_step_report.get("handoff") or "").lower() if isinstance(last_step_report, dict) else ""
        skills_invoked = (
            [str(x or "").strip().lower() for x in (last_step_report.get("skills_invoked") or [])]
            if isinstance(last_step_report, dict) and isinstance(last_step_report.get("skills_invoked"), list)
            else []
        )
        test_failures = _step_test_failure_count(last_step_report)
        has_changes = bool(recent_changed_files)
        cond = _normalize_transition_condition(transition.get("condition") if isinstance(transition, dict) else {})

        def _match_rule(rule: Dict[str, Any]) -> bool:
            ctype = str(rule.get("type") or "always").strip()
            cvalue = str(rule.get("value") or "").lower()
            if ctype == "always":
                return True
            if ctype == "no_changed_files":
                return not has_changes
            if ctype == "changed_files_present":
                return has_changes
            if ctype == "bugs_present":
                return bool(bugs)
            if ctype == "no_bugs":
                return not bool(bugs)
            if ctype == "handoff_contains":
                return bool(cvalue) and cvalue in handoff_text
            if ctype == "did_contains":
                return bool(cvalue) and cvalue in did_text
            if ctype == "skills_invoked_contains":
                return bool(cvalue) and any(cvalue == s for s in skills_invoked)
            if ctype == "skills_invoked_not_contains":
                return bool(cvalue) and all(cvalue != s for s in skills_invoked)
            if ctype == "output_contains":
                return bool(cvalue) and cvalue in text
            if ctype == "output_not_contains":
                return bool(cvalue) and cvalue not in text
            if ctype == "test_failures_gte":
                try:
                    return test_failures >= int(cvalue)
                except Exception:
                    return False
            if ctype == "test_failures_lte":
                try:
                    return test_failures <= int(cvalue)
                except Exception:
                    return False
            return False

        def _match_node(node: Dict[str, Any]) -> bool:
            if not isinstance(node, dict):
                return False
            kind = str(node.get("kind") or "").strip()
            if kind == "group" or isinstance(node.get("rules"), list):
                operator = "any" if str(node.get("operator") or "all").strip().lower() == "any" else "all"
                children = node.get("rules") if isinstance(node.get("rules"), list) else []
                if not children:
                    return False
                child_matches = [_match_node(child) for child in children if isinstance(child, dict)]
                if not child_matches:
                    return False
                return any(child_matches) if operator == "any" else all(child_matches)
            return _match_rule(node)

        return _match_node(cond)

    def _is_explicit_chart_request(text: str) -> bool:
        q = str(text or "").lower()
        if not q:
            return False
        return bool(
            re.search(
                r"\b(charts?|graphs?|plots?|visuali[sz]e|visuali[sz]ation(?:s)?|bar\s+charts?|line\s+charts?|pie\s+charts?|donut\s+charts?|area\s+charts?|scatter(?:\s+plots?)?|histograms?|chart-ready|chart ready)\b",
                q,
            )
        )

    def _run_if_condition_matches(condition: Any, user_text: str) -> bool:
        if condition is None:
            return True
        if isinstance(condition, bool):
            return condition
        text = str(user_text or "")
        text_l = text.lower()
        if isinstance(condition, str):
            cond = condition.strip()
            cond_l = cond.lower()
            if not cond_l or cond_l in {"always", "true", "yes"}:
                return True
            if cond_l in {"never", "false", "no"}:
                return False
            if cond_l in {"explicit_chart_request", "chart_request", "chart"}:
                return _is_explicit_chart_request(text)
            if cond_l in {"not_explicit_chart_request", "no_explicit_chart_request", "non_chart_request", "text_request"}:
                return not _is_explicit_chart_request(text)
            if cond_l.startswith("contains:"):
                needle = cond_l.split(":", 1)[1].strip()
                return bool(needle) and needle in text_l
            if cond_l.startswith("not_contains:"):
                needle = cond_l.split(":", 1)[1].strip()
                return bool(needle) and needle not in text_l
            if cond_l.startswith("regex:"):
                pattern = cond.split(":", 1)[1].strip()
                try:
                    return bool(pattern) and re.search(pattern, text, flags=re.IGNORECASE) is not None
                except re.error:
                    return False
            if cond_l.startswith("not_regex:"):
                pattern = cond.split(":", 1)[1].strip()
                try:
                    return bool(pattern) and re.search(pattern, text, flags=re.IGNORECASE) is None
                except re.error:
                    return False
            return cond_l in text_l
        if isinstance(condition, dict):
            ctype = str(
                condition.get("type")
                or condition.get("kind")
                or condition.get("op")
                or condition.get("condition")
                or ""
            ).strip().lower()
            value = condition.get("value")
            if ctype in {"not", "unless"}:
                inner = condition.get("condition")
                if inner is None:
                    inner = value
                return not _run_if_condition_matches(inner, user_text)
            if ctype in {"all", "and"}:
                rules = condition.get("rules") if isinstance(condition.get("rules"), list) else []
                return bool(rules) and all(_run_if_condition_matches(rule, user_text) for rule in rules)
            if ctype in {"any", "or"}:
                rules = condition.get("rules") if isinstance(condition.get("rules"), list) else []
                return bool(rules) and any(_run_if_condition_matches(rule, user_text) for rule in rules)
            if ctype in {"explicit_chart_request", "chart_request", "chart"}:
                return _is_explicit_chart_request(text)
            if ctype in {"not_explicit_chart_request", "no_explicit_chart_request", "non_chart_request", "text_request"}:
                return not _is_explicit_chart_request(text)
            if ctype in {"contains", "text_contains"}:
                needle = str(value or "").strip().lower()
                return bool(needle) and needle in text_l
            if ctype in {"not_contains", "text_not_contains"}:
                needle = str(value or "").strip().lower()
                return bool(needle) and needle not in text_l
            if ctype == "regex":
                pattern = str(value or "").strip()
                try:
                    return bool(pattern) and re.search(pattern, text, flags=re.IGNORECASE) is not None
                except re.error:
                    return False
            if ctype == "not_regex":
                pattern = str(value or "").strip()
                try:
                    return bool(pattern) and re.search(pattern, text, flags=re.IGNORECASE) is None
                except re.error:
                    return False
            return True
        if isinstance(condition, list):
            return any(_run_if_condition_matches(item, user_text) for item in condition)
        return True

    def _action_skill_rule_applies(rule_obj: Dict[str, Any], user_text: str) -> bool:
        if not isinstance(rule_obj, dict):
            return True
        unless = rule_obj.get("unless")
        if unless is not None and _run_if_condition_matches(unless, user_text):
            return False
        run_if = rule_obj.get("run_if")
        if run_if is None:
            run_if = rule_obj.get("when")
        if run_if is None:
            run_if = rule_obj.get("condition")
        if run_if is None:
            return True
        return _run_if_condition_matches(run_if, user_text)
    
    def _clone_step_for_transition(base_step: Dict[str, Any], *, label_suffix: str = "", extra_system_prompt: str = "") -> Dict[str, Any]:
        out = dict(base_step or {})
        if label_suffix:
            out["label"] = f"{base_step.get('label') or base_step.get('node_id') or ''} / {label_suffix}".strip(" /")
        if extra_system_prompt:
            current = str(out.get("system_prompt") or "").strip()
            out["system_prompt"] = f"{current}\n\n{extra_system_prompt}".strip() if current else extra_system_prompt
        return out

    def _build_flow_steps(
        flow_def: Dict[str, Any],
        user_text: str,
        max_steps: int,
        flows: Optional[Dict[str, Any]] = None,
        _depth: int = 0,
        _flow_name: str = "",
        _flow_stack: Optional[List[str]] = None,
        _loop_once_used: Optional[Dict[str, bool]] = None,
    ) -> List[Dict[str, Any]]:
        if not flow_def or not isinstance(flow_def, dict):
            return []
        flow_stack = list(_flow_stack or [])
        loop_once_used = dict(_loop_once_used or {})
        if _flow_name:
            if _flow_name in flow_stack:
                return []
            flow_stack.append(_flow_name)
        if _depth > 4:
            return []
        nodes = flow_def.get("nodes") or {}
        start = flow_def.get("start")
        if not start or start not in nodes:
            return []
        steps: List[Dict[str, Any]] = []
        current = start
        visited: set[str] = set()
        count = 0
        while current and count < max_steps:
            node = nodes.get(current) or {}
            step = {
                "step_index": count,
                "node_id": current,
                "template_node_id": current,
                "label": node.get("label") or current,
                "plugin_id": node.get("plugin_id") or "chat",
                "system_prompt": node.get("system_prompt") or "",
                "return_only_text": node.get("return_only_text") is not False,
                "delay_ms": int(node.get("delay_ms") or 0),
                "transitions": node.get("transitions") or [],
                "plugin_settings": node.get("plugin_settings") or {},
                "initial_user_input": user_text if count == 0 else "",
            }
            steps.append(step)
            visited.add(current)
            count += 1
            current = _choose_default_transition(node, visited, nodes)
        return steps

    def _resolve_max_steps(flow_def: Dict[str, Any], raw_max_steps: Any, default_floor: int = 8) -> int:
        explicit = 0
        try:
            explicit = int(raw_max_steps or 0)
        except Exception:
            explicit = 0
        nodes = flow_def.get("nodes") if isinstance(flow_def, dict) and isinstance(flow_def.get("nodes"), dict) else {}
        node_count = len(nodes)
        # Keep headroom for runtime-injected conditional branches and review/fix loops.
        suggested = max(int(default_floor or 8), node_count + max(6, node_count // 2))
        if explicit > 0:
            return max(1, min(128, max(explicit, suggested)))
        return max(1, min(128, suggested))

    def _json_path_get(obj: Any, path_expr: str) -> Any:
        cur = obj
        parts = [str(x or "").strip() for x in str(path_expr or "").replace("[", ".").replace("]", "").split(".") if str(x or "").strip()]
        for part in parts:
            if isinstance(cur, dict):
                cur = cur.get(part)
                continue
            if isinstance(cur, list):
                try:
                    idx = int(part)
                except Exception:
                    return None
                if idx < 0 or idx >= len(cur):
                    return None
                cur = cur[idx]
                continue
            return None
        return cur

    def _coerce_iterable_items(value: Any) -> List[Any]:
        if isinstance(value, list):
            return list(value)
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, dict):
            for key in ("items", "records", "results", "requests", "planned_requests", "matches"):
                rows = value.get(key)
                if isinstance(rows, list):
                    return list(rows)
            return []
        return []

    def _extract_jsonish_block_outer(text: str) -> Any:
        raw = str(text or "").strip()
        if not raw:
            return None
        m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
        if m:
            raw = str(m.group(1) or "").strip()
        try:
            return json.loads(raw)
        except Exception:
            pass
        for pat in (r"(\{.*\})", r"(\[.*\])"):
            m2 = re.search(pat, raw, flags=re.DOTALL)
            if not m2:
                continue
            try:
                return json.loads(str(m2.group(1) or "").strip())
            except Exception:
                continue
        return None

    def _iteration_item_text(item: Any, fallback_text: str) -> str:
        if isinstance(item, str):
            return str(item).strip() or str(fallback_text or "").strip()
        if isinstance(item, dict):
            for key in ("request", "text", "prompt", "summary", "description", "name", "title"):
                val = str(item.get(key) or "").strip()
                if val:
                    return val
            try:
                return json.dumps(item, ensure_ascii=False)
            except Exception:
                return str(item)
        if item is None:
            return str(fallback_text or "").strip()
        return str(item)

    def _coerce_single_request(value: Any) -> Any:
        if isinstance(value, tuple):
            value = list(value)
        if isinstance(value, list):
            for row in value:
                if row in (None, "", []):
                    continue
                if isinstance(row, dict):
                    return row
                if isinstance(row, str):
                    text = row.strip()
                    if text:
                        return {"request": text, "request_text": text}
                try:
                    text = str(row).strip()
                    if text:
                        return {"request": text, "request_text": text}
                except Exception:
                    continue
            return {}
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            text = str(value).strip()
            return {"request": text, "request_text": text} if text else {}
        if value is None:
            return {}
        text = str(value).strip()
        return {"request": text, "request_text": text} if text else {}

    def _normalize_tracker_state(raw_state: Any) -> Dict[str, Any]:
        if not isinstance(raw_state, dict):
            return {}
        state = dict(raw_state)
        if "current_request" in state:
            coerced_current = _coerce_single_request(state.get("current_request"))
            if isinstance(coerced_current, dict):
                state["current_request"] = coerced_current
            else:
                state["current_request"] = _coerce_single_request(coerced_current)
        if "remaining_requests" in state:
            rem = state.get("remaining_requests")
            if isinstance(rem, tuple):
                rem = list(rem)
            if isinstance(rem, list):
                normalized: List[Any] = []
                for row in rem:
                    if row in (None, "", []):
                        continue
                    if isinstance(row, dict) or isinstance(row, str):
                        normalized.append(row)
                    else:
                        text = str(row).strip()
                        if text:
                            normalized.append({"request": text, "request_text": text})
                state["remaining_requests"] = normalized
            elif rem == []:
                state["remaining_requests"] = []
        return state

    def _request_seed_for_step(step: Dict[str, Any], user_text: str) -> str:
        step_input = step.get("input") if isinstance(step.get("input"), dict) else {}
        def _usable_seed(value: Any) -> str:
            text = str(value or "").strip()
            if not text:
                return ""
            if text.lower().startswith("interaction response:"):
                return ""
            return text
        seed = (
            _usable_seed(step_input.get("iteration_text"))
            or _usable_seed(step.get("initial_user_input"))
            or _usable_seed(user_text)
        ).strip()
        return seed or str(user_text or "").strip()

    def _resolve_iteration_items(
        *,
        ps: Dict[str, Any],
        step_ext: Dict[str, Any],
        last_step_report: Optional[Dict[str, Any]],
        last_output_raw: str,
        last_output_text: str,
    ) -> List[Any]:
        explicit = ps.get("items")
        if isinstance(explicit, list):
            return list(explicit)
        path_keys = []
        raw_keys = ps.get("iteration_keys")
        if isinstance(raw_keys, list):
            path_keys.extend(str(x or "").strip() for x in raw_keys if str(x or "").strip())
        single_key = str(ps.get("iteration_key") or ps.get("iteration_data_key") or "").strip()
        if single_key:
            path_keys.append(single_key)
        default_keys = [
            "planned_requests",
            "items",
            "records",
            "results",
            "requests",
            "matches",
            "best_match.items",
        ]
        path_keys.extend([k for k in default_keys if k not in path_keys])
        sources: List[Any] = []
        if isinstance(last_step_report, dict):
            sources.append(last_step_report)
        if isinstance(step_ext, dict):
            for report_key in ("agent_flow_previous_step_report_with_tools", "agent_flow_previous_step_report"):
                report_obj = step_ext.get(report_key)
                if isinstance(report_obj, dict):
                    sources.append(report_obj)
        parsed_raw = _extract_jsonish_block_outer(last_output_raw)
        if parsed_raw is not None:
            sources.append(parsed_raw)
        parsed_text = _extract_jsonish_block_outer(last_output_text)
        if parsed_text is not None:
            sources.append(parsed_text)
        for source in sources:
            for key in path_keys:
                val = _json_path_get(source, key)
                rows = _coerce_iterable_items(val)
                if rows:
                    return rows
            if isinstance(source, dict):
                tr = source.get("tool_results")
                if isinstance(tr, list):
                    for row in tr:
                        if not isinstance(row, dict):
                            continue
                        data0 = row.get("data") if isinstance(row.get("data"), dict) else {}
                        for key in path_keys:
                            val = _json_path_get(data0, key)
                            rows = _coerce_iterable_items(val)
                            if rows:
                                return rows
        return []

    def _extract_text_from_route(out: Any) -> str:
        if isinstance(out, str):
            return out
        if isinstance(out, dict):
            for key in ("answer", "text", "final_text", "content", "result", "description"):
                v = out.get(key)
                if isinstance(v, str):
                    return v
            tr = out.get("tool_results")
            if isinstance(tr, list):
                for row in tr:
                    if not isinstance(row, dict):
                        continue
                    data = row.get("data") if isinstance(row.get("data"), dict) else {}
                    for key in ("finalized_text", "final_answer", "markdown", "table_markdown", "content", "response", "answer", "summary", "text", "result", "message"):
                        v = data.get(key)
                        if v is None:
                            v = row.get(key)
                        if isinstance(v, str) and str(v).strip():
                            return str(v).strip()
            try:
                return out["choices"][0]["message"]["content"]
            except Exception:
                return ""
        return ""

    def _build_step_input(
        user_text: str,
        *,
        idx: int,
        step: Dict[str, Any],
        last_output_text: str,
        last_output_raw: str,
        last_step_report: Optional[Dict[str, Any]],
        recent_changed_files: List[str],
        steers: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        def _tool_result_lines(rows: Any) -> List[str]:
            def _compact(v: Any, *, depth: int = 0) -> Any:
                if depth >= 5:
                    return "..."
                if isinstance(v, dict):
                    out: Dict[str, Any] = {}
                    # Keep common keys first, then a bounded remainder.
                    ordered = []
                    for k in ("ok", "path", "warnings", "records", "data", "profile", "chart", "value", "metric", "column"):
                        if k in v:
                            ordered.append(k)
                    for k in v.keys():
                        if k not in ordered:
                            ordered.append(k)
                    for k in ordered[:24]:
                        val = v.get(k)
                        if isinstance(val, list):
                            if k == "records":
                                out["records_len"] = len(val)
                                out["record0"] = _compact(val[0], depth=depth + 1) if val else None
                            else:
                                out[k] = [_compact(x, depth=depth + 1) for x in val[:20]]
                                if len(val) > 20:
                                    out[f"{k}_truncated"] = True
                        else:
                            out[k] = _compact(val, depth=depth + 1)
                    return out
                if isinstance(v, list):
                    out = [_compact(x, depth=depth + 1) for x in v[:20]]
                    if len(v) > 20:
                        out.append("...<truncated>...")
                    return out
                return v

            out_lines: List[str] = []
            if not isinstance(rows, list):
                return out_lines
            for row in rows[:6]:
                if not isinstance(row, dict):
                    continue
                skill = str(row.get("skill") or "").strip()
                ok = bool(row.get("ok"))
                if skill:
                    out_lines.append(f"- {skill}: {'ok' if ok else 'failed'}")
                try:
                    compact = _compact(row)
                    out_lines.append(f"  result: {json.dumps(compact, ensure_ascii=True)}")
                except Exception:
                    pass
            return out_lines

        def _step_role_and_instruction() -> str:
            plugin_settings = step.get("plugin_settings") if isinstance(step.get("plugin_settings"), dict) else {}
            role = str(
                plugin_settings.get("member_role")
                or step.get("agent_kind")
                or step.get("label")
                or ""
            ).strip().lower()
            change_intent = bool(re.search(r"\b(create|generate|build|implement|write|make|develop)\b", str(user_text or "").lower()))
            has_changed = bool(recent_changed_files)
            if any(k in role for k in ["staff", "coding", "coder", "engineer"]) and change_intent:
                if has_changed:
                    return "You are in an execution stage. Modify or complete the implementation using write/patch tool calls. Do not switch to file verification unless you are fixing a concrete written artifact."
                return "You are in an execution stage. Create or write the requested implementation now using write/patch tool calls. Do not only describe the file and do not use read-only verification as your main action."
            if "designer" in role and change_intent:
                if has_changed:
                    return "You are supporting implementation. Improve or complete the created UI/game artifact if needed. Use write/patch actions when a file still needs to be created or completed."
                return "You are supporting implementation. Help produce the requested artifact now. If no file exists yet, do not only verify; create or contribute to the artifact."
            if any(k in role for k in ["qa", "security", "docs", "release", "architect"]) and not has_changed:
                return "No artifact has been written yet. Do not pretend to verify a missing file. If your role is blocked on missing implementation, say that build/create must happen first."
            return "Continue the workflow for your role. Stay aligned to the original user request."

        current_instruction = _step_role_and_instruction()
        request_seed = _request_seed_for_step(step, user_text)
        if idx == 0:
            seed = request_seed
            return f"{seed}\n\nCurrent instruction:\n{current_instruction}".strip()
        lines: List[str] = []
        lines.append("Original user request:")
        lines.append(request_seed)
        if isinstance(last_step_report, dict) and last_step_report:
            role = str(last_step_report.get("role") or "").strip()
            did = str(last_step_report.get("did") or "").strip()
            plan = str(last_step_report.get("plan") or "").strip()
            analysis = str(last_step_report.get("analysis") or "").strip()
            response = str(last_step_report.get("response") or "").strip()
            handoff = str(last_step_report.get("handoff") or "").strip()
            actions = last_step_report.get("actions") if isinstance(last_step_report.get("actions"), list) else []
            bugs = last_step_report.get("bugs") if isinstance(last_step_report.get("bugs"), list) else []
            fixes = last_step_report.get("fixes") if isinstance(last_step_report.get("fixes"), list) else []
            lines.append("")
            lines.append("Previous step context:")
            if role:
                lines.append(f"role: {role}")
            if did:
                lines.append(f"did: {did}")
            if plan:
                lines.append(f"plan: {plan}")
            if analysis:
                lines.append(f"analysis: {analysis}")
            if response:
                lines.append(f"response: {response}")
            if actions:
                lines.append("actions:")
                for a in actions[:6]:
                    av = str(a or "").strip()
                    if av:
                        lines.append(f"- {av}")
            if bugs:
                lines.append("bugs:")
                for b in bugs[:6]:
                    bv = str(b or "").strip()
                    if bv:
                        lines.append(f"- {bv}")
            if fixes:
                lines.append("fixes:")
                for f in fixes[:6]:
                    fv = str(f or "").strip()
                    if fv:
                        lines.append(f"- {fv}")
            if handoff:
                lines.append(f"handoff: {handoff}")
            tool_result_lines = _tool_result_lines(last_step_report.get("tool_results"))
            if tool_result_lines:
                lines.append("tool_results:")
                lines.extend(tool_result_lines)
        else:
            fallback = str(last_output_text or "").strip() or str(last_output_raw or "").strip()
            if fallback:
                lines.append("")
                lines.append("Previous step raw output:")
                lines.append(fallback[:3000])
        if recent_changed_files:
            lines.append("")
            lines.append("Changed files so far:")
            for cf in recent_changed_files[:20]:
                cv = str(cf or "").strip()
                if cv:
                    lines.append(f"- {cv}")
        steer_rows = steers if isinstance(steers, list) else []
        visible_steers = []
        for row in steer_rows[-8:]:
            if not isinstance(row, dict):
                continue
            msg = str(row.get("message") or "").strip()
            target = str(row.get("target") or "next").strip() or "next"
            if msg:
                visible_steers.append((target, msg))
        if visible_steers:
            lines.append("")
            lines.append("User steering guidance:")
            for target, msg in visible_steers:
                lines.append(f"- target={target}: {msg}")
        lines.append("")
        lines.append("Current instruction:")
        lines.append(current_instruction)
        ps_now = step.get("plugin_settings") if isinstance(step, dict) else {}
        allowed_skills_now = []
        node_type_now = ""
        if isinstance(ps_now, dict):
            raw_skills_now = ps_now.get("action_skills")
            if isinstance(raw_skills_now, list):
                allowed_skills_now = [str(x) for x in raw_skills_now if isinstance(x, str) and str(x).strip()]
            node_type_now = str(ps_now.get("node_type") or "").strip().lower()
        lines.append("Do not invent values.")
        if allowed_skills_now:
            result_only = all(str(s or "").strip().lower().startswith("result.") for s in allowed_skills_now)
            if result_only:
                lines.append("This node may call only result.* skills. Do not call sheet.*, repo.*, code.*, or other skills.")
                lines.append("If data is missing, output value_unavailable_from_tool_results instead of calling a non-result skill.")
            else:
                lines.append("If a required numeric/result value is missing from tool_results, call the appropriate tool again and report the returned value.")
            if node_type_now == "tool_node":
                lines.append("This is a tool_node. You must emit at least one tool call using allowed skills before finalizing this step.")
            # Optional per-skill run-if guidance from node editor.
            # Stored shape:
            #   action_skill_rules: {
            #     "sheet.aggregate": {"enforce_once": true, "guidance": "...when/format..."},
            #   }
            skill_rules = ps_now.get("action_skill_rules") if isinstance(ps_now.get("action_skill_rules"), dict) else {}
            if isinstance(skill_rules, dict) and skill_rules:
                allowed_set = {str(s).strip().lower() for s in allowed_skills_now}
                for sid, rule in skill_rules.items():
                    skill_id = str(sid or "").strip()
                    if not skill_id:
                        continue
                    if allowed_set and skill_id.lower() not in allowed_set:
                        continue
                    rule_obj = rule if isinstance(rule, dict) else {}
                    enforce_once = bool(rule_obj.get("enforce_once"))
                    guidance = str(rule_obj.get("guidance") or "").strip()
                    if enforce_once:
                        lines.append(f"Run-if enforce: skill '{skill_id}' must be called at least once when its run-if condition applies.")
                    if guidance:
                        lines.append(f"Run-if prompt for '{skill_id}': {guidance}")
        else:
            lines.append("This node has no tool execution permission. If a required value is missing from tool_results, output value_unavailable_from_tool_results and do not call tools.")
        return "\n".join(lines).strip()

    @r.post("/v1/projects/{pid}/sessions/{sid}/agent_flow/run")
    def agent_flow_run(pid: str, sid: str, req: AgentFlowRunRequest, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)

        ext = dict(req.ext or {})
        flows = ext.get("agent_flow_flows") or {}
        force_runtime_flow = bool(ext.get("agent_flow_force_runtime_flow"))
        if not isinstance(flows, dict) or not flows:
            raise HTTPException(status_code=400, detail="agent_flow_flows missing")

        flow_name = ext.get("agent_flow_active_flow") or ext.get("agent_flow_default_flow")
        if not flow_name and len(flows) == 1:
            flow_name = next(iter(flows.keys()))
        if not flow_name or flow_name not in flows:
            raise HTTPException(status_code=400, detail="agent_flow_active_flow missing or invalid")

        flow_for_run = dict(flows.get(flow_name) or {})
        _require_flow_access(u, str(flow_name), flow_for_run, action="run")
        user_text = str(req.text or "").strip()
        run_id = secrets.token_hex(8)
        version_diag = _flow_version_diag(pid=pid, active_flow=str(flow_name), runtime_flows=flows)
        # Prefer saved project flow when client/runtime payload is stale.
        # This avoids running outdated node configs from cached browser state.
        try:
            proj_doc = _load_project_flows(pid)
            proj_flows = proj_doc.get("flows") if isinstance(proj_doc, dict) else {}
            proj_flow = proj_flows.get(flow_name) if isinstance(proj_flows, dict) else None
            run_hash = str(version_diag.get("runtime_hash") or "").strip()
            proj_hash = str(version_diag.get("project_hash") or "").strip()
            if not force_runtime_flow and isinstance(proj_flow, dict) and run_hash and proj_hash and run_hash != proj_hash:
                flow_for_run = dict(proj_flow)
                # Keep _build_flow_steps references consistent.
                flows = dict(flows)
                flows[flow_name] = flow_for_run
                version_diag = _flow_version_diag(pid=pid, active_flow=str(flow_name), runtime_flows=flows)
                warns = version_diag.get("warnings") if isinstance(version_diag.get("warnings"), list) else []
                if "runtime_flow_replaced_with_project_flow" not in warns:
                    warns.append("runtime_flow_replaced_with_project_flow")
                version_diag["warnings"] = warns
        except Exception:
            pass
        max_steps = _resolve_max_steps(flow_for_run, ext.get("agent_flow_max_steps"), default_floor=8)
        steps = _build_flow_steps(
            flow_for_run,
            user_text,
            max_steps,
            flows=flows,
            _flow_name=str(flow_name),
            _flow_stack=[],
        )
        if not steps:
            raise HTTPException(status_code=400, detail="flow has no executable steps")

        state = {
            "run_id": run_id,
            "flow_name": flow_name,
            "running": True,
            "paused": False,
            "pause_requested": False,
            "status": f"Running 0/{len(steps)}",
            "step_index": -1,
            "steps_total": len(steps),
            "steps": [{"label": s.get("label") or s.get("node_id"), "state": "queued"} for s in steps],
            "interaction": None,
            "loop_cap": None,
            "steers": [],
            "ts": _now_ts(),
        }
        _agent_flow_set_state(pid, sid, state)

        hub = app.state.collab_hub
        db = app.state.collab_db
        ai_jobs = getattr(app.state, "ai_jobs", None)
        internal_run = bool(ext.get("agent_flow_internal_run"))
        if ai_jobs and not internal_run:
            ai_jobs.upsert(
                run_id,
                status="running",
                kind="agent_flow",
                owner_username=u.username,
                owner_alias=u.username,
                pid=pid,
                sid=sid,
                flow_name=flow_name,
            )

        def _publish_flow_status(update: Dict[str, Any]) -> None:
            payload = dict(state)
            payload.update(update or {})
            payload["run_id"] = run_id
            payload["pid"] = pid
            payload["sid"] = sid
            try:
                hub.publish(pid, sid, event="flow_status", data=payload)
            except Exception:
                pass

        def _run_flow() -> None:
            nonlocal state
            def _is_canceled() -> bool:
                try:
                    cancelled = getattr(app.state, "ai_jobs_cancelled", None)
                    if isinstance(cancelled, dict):
                        return bool(cancelled.get(run_id))
                except Exception:
                    return False
                return False

            def _mark_canceled() -> None:
                state["running"] = False
                state["paused"] = False
                state["pause_requested"] = False
                state["status"] = "Canceled"
                _agent_flow_set_state(pid, sid, state, preserve_pause=False)
                _publish_flow_status({"running": False, "paused": False, "pause_requested": False, "canceled": True})

            def _is_paused() -> bool:
                latest = _agent_flow_get_state(pid, sid, run_id)
                if isinstance(latest, dict):
                    state["paused"] = bool(latest.get("paused"))
                    state["pause_requested"] = bool(latest.get("pause_requested"))
                return bool(state.get("running")) and (bool(state.get("paused")) or bool(state.get("pause_requested")))

            def _wait_if_paused(step_idx: int) -> bool:
                announced = False
                while _is_paused():
                    if _is_canceled():
                        _mark_canceled()
                        return False
                    state["running"] = True
                    state["paused"] = True
                    state["pause_requested"] = False
                    state["step_index"] = step_idx
                    state["status"] = f"Paused {min(step_idx + 1, len(steps))}/{len(steps)}"
                    _agent_flow_set_state(pid, sid, state)
                    if not announced:
                        try:
                            _publish_run_line("[agent_flow] paused")
                            _persist_run_stream_snapshot()
                        except Exception:
                            pass
                        _publish_flow_status({})
                        announced = True
                    time.sleep(0.35)
                if announced and state.get("running"):
                    state["paused"] = False
                    state["pause_requested"] = False
                    state["status"] = f"Running {min(step_idx + 1, len(steps))}/{len(steps)}"
                    _agent_flow_set_state(pid, sid, state, preserve_pause=False)
                    _publish_flow_status({})
                return True

            def _extract_interaction_from_tool_results(out_obj: Any) -> Optional[Dict[str, Any]]:
                if not isinstance(out_obj, dict):
                    return None
                direct = out_obj.get("interaction")
                if isinstance(direct, dict) and str(direct.get("type") or "").strip():
                    return dict(direct)
                rows = out_obj.get("tool_results")
                if not isinstance(rows, list):
                    return None
                for row in rows:
                    if not isinstance(row, dict) or row.get("ok") is False:
                        continue
                    skill_id = str(row.get("skill") or "").strip().lower()
                    if not skill_id.startswith("interaction."):
                        continue
                    data = row.get("data") if isinstance(row.get("data"), dict) else {}
                    inter = data.get("interaction")
                    if isinstance(inter, dict) and str(inter.get("type") or "").strip():
                        return dict(inter)
                return None

            def _wait_for_interaction(interaction: Dict[str, Any], step_idx: int, label: str) -> Optional[Dict[str, Any]]:
                inter = dict(interaction or {})
                inter_id = str(inter.get("id") or secrets.token_hex(8)).strip()
                inter_type = str(inter.get("type") or "approval").strip().lower()
                question = str(inter.get("question") or "").strip() or "Continue workflow?"
                inter.update({"id": inter_id, "type": inter_type, "question": question, "status": "pending"})
                state["interaction"] = inter
                state["status"] = f"Awaiting {inter_type} {min(step_idx + 1, len(steps))}/{len(steps)}"
                state["step_index"] = step_idx
                state["ts"] = _now_ts()
                _agent_flow_set_state(pid, sid, state, preserve_pause=False)
                _publish_flow_status({})
                _publish_run_line(f"[agent_flow] {label}: awaiting {inter_type}: {question}")
                while True:
                    if _is_canceled():
                        _mark_canceled()
                        return None
                    latest = _agent_flow_get_state(pid, sid, run_id)
                    latest_inter = latest.get("interaction") if isinstance(latest, dict) else None
                    if isinstance(latest_inter, dict):
                        response = latest_inter.get("response")
                        if isinstance(response, dict):
                            state["interaction"] = None
                            state["last_interaction_response"] = response
                            state["ts"] = _now_ts()
                            _agent_flow_set_state(pid, sid, state, preserve_pause=False)
                            _publish_flow_status({})
                            action = str(response.get("action") or response.get("text") or "").strip()
                            _publish_run_line(f"[agent_flow] {label}: {inter_type} response: {action or 'submitted'}")
                            if inter_type == "approval" and str(response.get("action") or "").strip().lower() == "no":
                                state["running"] = False
                                state["paused"] = False
                                state["pause_requested"] = False
                                state["status"] = "Approval rejected"
                                _agent_flow_set_state(pid, sid, state, preserve_pause=False)
                                _publish_flow_status({"running": False, "paused": False, "pause_requested": False})
                                return None
                            return response
                    time.sleep(0.35)

            run_stream_msg_id = f"{run_id}_stream"
            run_stream_started = {"v": False}
            run_stream_parts: List[str] = []
            run_token_buffer: List[str] = []
            run_token_last_flush = {"v": 0.0}
            run_stream_last_snapshot = {"v": 0.0}
            flow_anchor_client_msg_id = {"v": str(req.client_msg_id or "").strip()}
            flow_user_ts = {"v": 0}
            flow_stream_ts = {"v": 0}

            def _flow_stream_meta() -> Dict[str, Any]:
                meta = {"flow": True, "flow_stream": True, "flow_stream_tokens": True, "flow_run_id": run_id}
                if flow_anchor_client_msg_id["v"]:
                    # Do not put the user's client_msg_id on assistant flow
                    # stream messages. chat_js uses client_msg_id to reconcile
                    # pending user messages, so sharing it here can replace the
                    # user bubble with the Agent Jobs container.
                    meta["flow_anchor_client_msg_id"] = flow_anchor_client_msg_id["v"]
                return meta

            def _ensure_run_stream_message(initial_text: str = "") -> None:
                if run_stream_started["v"]:
                    return
                run_stream_started["v"] = True
                if initial_text:
                    run_stream_parts.append(initial_text)
                ts_s = _now_ts()
                try:
                    hub.publish(
                        pid,
                        sid,
                        event="message",
                        data={
                            "msg": {
                                "msg_id": run_stream_msg_id,
                                "pid": pid,
                                "sid": sid,
                                "ts": ts_s,
                                "role": "assistant",
                                "kind": "model",
                                "author_username": u.username,
                                "author_alias": u.username,
                                "content": initial_text,
                                "meta": _flow_stream_meta(),
                            }
                        },
                    )
                except Exception:
                    pass

            def _flush_run_tokens(force: bool = False) -> None:
                if not run_token_buffer:
                    return
                now = time.time()
                buffered_len = sum(len(x) for x in run_token_buffer)
                if not force and buffered_len < 2048 and (now - float(run_token_last_flush["v"] or 0.0)) < 0.12:
                    return
                piece = "".join(run_token_buffer)
                run_token_buffer.clear()
                run_token_last_flush["v"] = now
                try:
                    hub.publish(
                        pid,
                        sid,
                        event="token",
                        data={
                            "pid": pid,
                            "sid": sid,
                            "role": "assistant",
                            "origin": u.username,
                            "text": piece,
                            "msg_id": run_stream_msg_id,
                        },
                    )
                except Exception:
                    pass

            def _publish_run_token(text_piece: str, *, flush: bool = False) -> None:
                piece = str(text_piece or "")
                if not piece:
                    return
                _ensure_run_stream_message("")
                run_stream_parts.append(piece)
                run_token_buffer.append(piece)
                _flush_run_tokens(force=flush)

            def _publish_run_line(text_line: str) -> None:
                t = str(text_line or "").strip()
                if not t:
                    return
                piece = f"{t}\n"
                if not run_stream_started["v"]:
                    _ensure_run_stream_message(piece)
                else:
                    _publish_run_token(piece, flush=True)
                try:
                    _persist_run_stream_snapshot(force=False)
                except Exception:
                    pass

            def _persist_run_stream_snapshot(force: bool = True) -> None:
                now = time.time()
                if not force and (now - float(run_stream_last_snapshot["v"] or 0.0)) < 0.8:
                    return
                if not run_stream_started["v"]:
                    _ensure_run_stream_message(f"[agent_flow] flow_name: {flow_name}\n[agent_flow] paused\n")
                _flush_run_tokens(force=True)
                text_snapshot = "".join(run_stream_parts)
                if not text_snapshot.strip():
                    return
                run_stream_last_snapshot["v"] = now
                ts_snap = max(_now_ts(), int(flow_user_ts["v"] or 0) + 1)
                flow_stream_ts["v"] = int(ts_snap)
                try:
                    db.add_message(
                        msg_id=run_stream_msg_id,
                        pid=pid,
                        sid=sid,
                        ts=ts_snap,
                        role="assistant",
                        kind="model",
                        author_username=u.username,
                        author_alias=u.username,
                        content=text_snapshot,
                        meta=_flow_stream_meta(),
                    )
                    set_content = getattr(db, "set_message_content", None)
                    if callable(set_content):
                        set_content(msg_id=run_stream_msg_id, content=text_snapshot)
                except Exception:
                    pass

            try:
                # persist user message
                user_msg_id = req.client_msg_id or secrets.token_hex(12)
                if not flow_anchor_client_msg_id["v"]:
                    flow_anchor_client_msg_id["v"] = str(user_msg_id)
                attachments = []
                if isinstance(ext.get("attachments"), list):
                    attachments = list(ext.get("attachments") or [])
                elif isinstance(ext.get("media_attachments"), list):
                    attachments = list(ext.get("media_attachments") or [])
                text = user_text or ("[image]" if attachments else "")
                meta_u = {"flow": True}
                if req.client_msg_id:
                    meta_u["client_msg_id"] = req.client_msg_id
                if attachments:
                    meta_u["attachments"] = attachments
                ts_u = _now_ts()
                flow_user_ts["v"] = int(ts_u)
                db.add_message(
                    msg_id=user_msg_id,
                    pid=pid,
                    sid=sid,
                    ts=ts_u,
                    role="user",
                    kind="human",
                    author_username=u.username,
                    author_alias=(u.username),
                    content=text,
                    meta=meta_u,
                )
                try:
                    hub.publish(
                        pid,
                        sid,
                        event="message",
                        data={
                            "msg": {
                                "msg_id": user_msg_id,
                                "pid": pid,
                                "sid": sid,
                                "ts": ts_u,
                                "role": "user",
                                "kind": "human",
                                "author_username": u.username,
                                "author_alias": (u.username),
                                "content": text,
                                "meta": meta_u,
                            }
                        },
                    )
                except Exception:
                    pass
                _publish_run_line(f"[agent_flow] flow_name: {flow_name}")
                _publish_run_line(f"[agent_flow] run_id: {run_id}")
                try:
                    _persist_run_stream_snapshot(force=True)
                except Exception:
                    pass

                from plugins.ai_routes import load_routes
                from plugins.ai_routes.base import RouterCore

                base_settings: Dict[str, Any] = _runtime_base_settings()
                settings = dict(base_settings)
                nested_base_rps = base_settings.get("router_plugin_settings") if isinstance(base_settings.get("router_plugin_settings"), dict) else {}
                if isinstance(nested_base_rps, dict):
                    for _plugin_id, _plugin_cfg in nested_base_rps.items():
                        if not isinstance(_plugin_cfg, dict):
                            continue
                        for _k, _v in _plugin_cfg.items():
                            settings[_k] = _v
                incoming_router_plugin_settings = ext.get("router_plugin_settings") if isinstance(ext.get("router_plugin_settings"), dict) else {}
                if isinstance(incoming_router_plugin_settings, dict):
                    for _plugin_id, _plugin_cfg in incoming_router_plugin_settings.items():
                        if not isinstance(_plugin_cfg, dict):
                            continue
                        for _k, _v in _plugin_cfg.items():
                            settings[_k] = _v
                server_base_url = str(ext.get("base_url") or ext.get("server_url") or "").strip().rstrip("/")
                if server_base_url:
                    settings["server_url"] = server_base_url
                    settings["download_base_url"] = server_base_url
                settings["__pid"] = pid
                settings["__sid"] = sid
                try:
                    settings["__request_base_url"] = str(request.base_url).rstrip("/")
                except Exception:
                    settings["__request_base_url"] = ""
                settings["__model_loader_registry"] = getattr(app.state, "model_loader_registry", None)
                try:
                    awmt = settings.get("agent_workflow_member_max_tokens")
                except Exception:
                    awmt = None
                settings["__agent_flow_boot_diag"] = {
                    "agent_workflow_member_max_tokens": awmt,
                }
                categories = getattr(app.state, "agent_flow_skill_categories", None)
                settings["__agent_flow_skill_categories"] = categories if isinstance(categories, dict) else {}
                raw_temp_skill_dirs = ext.get("agent_flow_temp_skill_dirs") if isinstance(ext.get("agent_flow_temp_skill_dirs"), list) else []
                disable_temp_skill_inference = ext.get("agent_flow_disable_temp_skill_inference") is True
                temp_skill_dirs = list(raw_temp_skill_dirs) if disable_temp_skill_inference else _infer_temp_skill_dirs_for_flow(str(flow_name or ""), flow_for_run, raw_temp_skill_dirs)
                if temp_skill_dirs and not raw_temp_skill_dirs:
                    _publish_run_line(f"[agent_flow] inferred generated skill overlay: {len(temp_skill_dirs)} dir(s)")
                reg = getattr(app.state, "agent_workflow_tools", None)
                if temp_skill_dirs:
                    try:
                        overlay = build_agent_flow_tool_registry(app, extra_skill_dirs=[str(x or "").strip() for x in temp_skill_dirs if str(x or "").strip()])
                        reg = overlay.get("registry") if isinstance(overlay, dict) else reg
                        if isinstance(overlay, dict):
                            settings["__agent_flow_sandbox_skill_specs"] = dict(overlay.get("skill_specs") or {})
                            settings["__agent_flow_sandbox_skill_categories"] = dict(overlay.get("categories") or {})
                            settings["__agent_flow_sandbox_skill_warnings"] = list(overlay.get("warnings") or [])
                    except Exception as exc:
                        _publish_run_line(f"[agent_flow] sandbox skill overlay failed: {exc}")
                if not temp_skill_dirs:
                    try:
                        reg_names = []
                        if reg is not None:
                            for attr in ("tools", "_tools", "registry", "_registry"):
                                raw_tools = getattr(reg, attr, None)
                                if isinstance(raw_tools, dict):
                                    reg_names = [str(x or "").strip() for x in raw_tools.keys()]
                                    break
                        needs_agent_flow_registry = False
                        for _step_probe in steps:
                            if not isinstance(_step_probe, dict):
                                continue
                            if str(_step_probe.get("plugin_id") or "").strip() != "agent_workflow_member":
                                continue
                            ps_probe = _step_probe.get("plugin_settings") if isinstance(_step_probe.get("plugin_settings"), dict) else {}
                            skills_probe = ps_probe.get("action_skills") if isinstance(ps_probe.get("action_skills"), list) else []
                            tc_probe = ps_probe.get("tool_config") if isinstance(ps_probe.get("tool_config"), dict) else {}
                            probe_names = [str(x or "").strip() for x in skills_probe]
                            probe_names.append(str(tc_probe.get("tool") or "").strip())
                            node_type_probe = str(ps_probe.get("node_type") or "").strip().lower()
                            if node_type_probe == "tool_node" and any(name and name not in reg_names for name in probe_names):
                                needs_agent_flow_registry = True
                                break
                            for skill_probe in skills_probe:
                                skill_id_probe = str(skill_probe or "").strip()
                                if skill_id_probe.startswith("workflow.") and skill_id_probe not in reg_names:
                                    needs_agent_flow_registry = True
                                    break
                            if needs_agent_flow_registry:
                                break
                        if needs_agent_flow_registry:
                            overlay = build_agent_flow_tool_registry(app, extra_skill_dirs=None)
                            reg = overlay.get("registry") if isinstance(overlay, dict) else reg
                            if isinstance(overlay, dict):
                                settings["__agent_flow_sandbox_skill_specs"] = dict(overlay.get("skill_specs") or {})
                                settings["__agent_flow_sandbox_skill_categories"] = dict(overlay.get("categories") or {})
                                settings["__agent_flow_sandbox_skill_warnings"] = list(overlay.get("warnings") or [])
                    except Exception as exc:
                        _publish_run_line(f"[agent_flow] workflow skill registry refresh failed: {exc}")
                try:
                    tool_registry_required = False
                    for _step_probe in steps:
                        if not isinstance(_step_probe, dict):
                            continue
                        if str(_step_probe.get("plugin_id") or "").strip().lower() != "agent_workflow_member":
                            continue
                        ps_probe = _step_probe.get("plugin_settings") if isinstance(_step_probe.get("plugin_settings"), dict) else {}
                        skills_probe = ps_probe.get("action_skills") if isinstance(ps_probe.get("action_skills"), list) else []
                        tc_probe = ps_probe.get("tool_config") if isinstance(ps_probe.get("tool_config"), dict) else {}
                        probe_names = [str(x or "").strip() for x in skills_probe]
                        probe_names.append(str(tc_probe.get("tool") or "").strip())
                        node_type_probe = str(ps_probe.get("node_type") or "").strip().lower()
                        if node_type_probe == "tool_node" and any(name for name in probe_names if name):
                            tool_registry_required = True
                            break
                        if any(name.startswith("workflow.") for name in probe_names if name):
                            tool_registry_required = True
                            break
                    if tool_registry_required and (reg is None or not hasattr(reg, "call_tool")):
                        overlay = build_agent_flow_tool_registry(app, extra_skill_dirs=None)
                        reg = overlay.get("registry") if isinstance(overlay, dict) else reg
                        if isinstance(overlay, dict):
                            settings["__agent_flow_sandbox_skill_specs"] = dict(overlay.get("skill_specs") or {})
                            settings["__agent_flow_sandbox_skill_categories"] = dict(overlay.get("categories") or {})
                            settings["__agent_flow_sandbox_skill_warnings"] = list(overlay.get("warnings") or [])
                except Exception as exc:
                    _publish_run_line(f"[agent_flow] workflow skill registry build failed: {exc}")
                if reg is not None and hasattr(reg, "call_tool"):
                    try:
                        app.state.agent_workflow_tools = reg
                    except Exception:
                        pass
                if reg is not None and hasattr(reg, "call_tool"):
                    def _aw_tool_call(name: str, ctx0: dict, params0: dict):
                        tool_name = str(name or "").strip()
                        try:
                            from plugins.gui_helpers.permissions_manager.core import can_access_skill, compute_effective_permissions
                            permission_summary = compute_effective_permissions(app, u)
                            if tool_name and not can_access_skill(permission_summary, tool_name):
                                return {
                                    "ok": False,
                                    "data": {
                                        "tool": tool_name,
                                        "permission_denied": True,
                                        "required_skill": tool_name,
                                        "role_ids": list(permission_summary.get("role_ids") or []),
                                    },
                                    "warnings": ["skill_access_denied"],
                                }
                        except Exception:
                            pass
                        return reg.call_tool(tool_name, dict(ctx0 or {}), dict(params0 or {}))
                    settings["__agent_workflow_tool_call"] = _aw_tool_call

                def _call_maybe_async(fn: Any, *args: Any, **kwargs: Any) -> Any:
                    out = fn(*args, **kwargs)
                    if inspect.isawaitable(out):
                        import asyncio
                        try:
                            loop = asyncio.get_running_loop()
                        except RuntimeError:
                            loop = None
                        if loop and loop.is_running():
                            new_loop = asyncio.new_event_loop()
                            try:
                                return new_loop.run_until_complete(out)
                            finally:
                                new_loop.close()
                        return asyncio.run(out)
                    return out

                def _ensure_main_text_model_loaded(preferred_sid: str | None = None) -> Any:
                    lreg = getattr(app.state, "model_loader_registry", None)
                    provider_fn = getattr(app.state, "main_text_llm_provider", None)
                    if not hasattr(lreg, "get"):
                        return None
                    gguf = lreg.get("model_loader.gguf")
                    if gguf is None:
                        return None
                    sid_pref = str(preferred_sid or "").strip() or "_default"
                    for sid_try in [sid_pref, "_default"]:
                        try:
                            loaded = gguf.get_model_for(sid_try, "text_llm_main")
                        except Exception:
                            loaded = None
                        if loaded is not None:
                            return loaded
                    try:
                        st = getattr(gguf, "_models", None)
                        if isinstance(st, dict):
                            for _k, m in st.items():
                                if m is not None:
                                    return m
                    except Exception:
                        pass
                    if not callable(provider_fn):
                        return None
                    try:
                        provider = provider_fn() or {}
                    except Exception:
                        return None
                    if isinstance(provider, str):
                        try:
                            provider = json.loads(provider)
                        except Exception:
                            return None
                    if not isinstance(provider, dict):
                        return None
                    loader_id = str(provider.get("loader_id") or "").strip()
                    model_id = str(provider.get("model_id") or "").strip()
                    if not model_id:
                        return None
                    if loader_id not in {"model_loader.gguf", "model_loader.model_deck.text_llm"}:
                        return None
                    load_settings = dict(provider.get("settings") or {})
                    load_settings.setdefault("model_id", model_id)
                    try:
                        res = _call_maybe_async(gguf.load_for, sid_pref, "text_llm_main", settings=load_settings)
                    except Exception:
                        return None
                    if not isinstance(res, dict) or not res.get("ok"):
                        return None
                    try:
                        return gguf.get_model_for(sid_pref, "text_llm_main") or gguf.get_model_for("_default", "text_llm_main")
                    except Exception:
                        return None

                def _resolve_chat_model() -> Any:
                    model_obj = None
                    try:
                        mf = getattr(app.state, "model", None)
                        model_obj = mf() if callable(mf) else mf
                    except Exception:
                        model_obj = None
                    if model_obj is not None:
                        return model_obj

                    try:
                        mm = getattr(app.state, "model_manager", None)
                        if mm is not None and hasattr(mm, "get_for"):
                            model_obj = mm.get_for(str(sid or "_default"))
                            if model_obj is not None:
                                return model_obj
                    except Exception:
                        model_obj = None
                    model_obj = _ensure_main_text_model_loaded(str(sid or "_default"))
                    return model_obj

                core = RouterCore(chat_llm=_resolve_chat_model(), backend_type="auto", settings=settings)
                core.settings["__resolve_chat_model"] = _resolve_chat_model
                routes = load_routes(core) or []
                route_by_id = {r.route_id: r for r in routes}

                last_output_text = ""
                last_output_raw = ""
                last_step_report: Optional[Dict[str, Any]] = None
                last_step_report_with_tools: Optional[Dict[str, Any]] = None
                recent_changed_files: List[str] = []
                final_result_mode: str = ""
                final_result_text: str = ""
                final_result_out: Dict[str, Any] = {}
                final_result_rows_accum: List[Dict[str, Any]] = []
                step_templates = {str(s.get("node_id") or ""): dict(s) for s in steps if str(s.get("node_id") or "").strip()}
                try:
                    runtime_nodes = flow_for_run.get("nodes") if isinstance(flow_for_run.get("nodes"), dict) else {}
                    for node_id, node in runtime_nodes.items():
                        node_key = str(node_id or "").strip()
                        if not node_key or node_key in step_templates or not isinstance(node, dict):
                            continue
                        step_templates[node_key] = {
                            "step_index": len(step_templates),
                            "node_id": node_key,
                            "template_node_id": node_key,
                            "label": node.get("label") or node_key,
                            "plugin_id": node.get("plugin_id") or "chat",
                            "system_prompt": node.get("system_prompt") or "",
                            "return_only_text": node.get("return_only_text") is not False,
                            "delay_ms": int(node.get("delay_ms") or 0),
                            "transitions": node.get("transitions") or [],
                            "plugin_settings": node.get("plugin_settings") or {},
                            "initial_user_input": "",
                        }
                except Exception:
                    pass
                loop_retry_counts: Dict[str, int] = {}
                fanout_results: Dict[str, Dict[str, Any]] = {}

                def _resolve_runtime_flow(flow_ref: str, workflow_id: str = "") -> Optional[Dict[str, Any]]:
                    key = str(flow_ref or "").strip()
                    wanted_id = str(workflow_id or "").strip()
                    if wanted_id:
                        try:
                            row = _workflow_store._fetch_record_by_id({"app": app, "pid": pid}, wanted_id)
                            candidate = row.get("flow_json") if isinstance(row, dict) else None
                            if isinstance(candidate, dict):
                                return dict(candidate)
                        except Exception:
                            pass
                    if not key and not wanted_id:
                        return None
                    candidate = flows.get(key) if isinstance(flows, dict) else None
                    if isinstance(candidate, dict):
                        return dict(candidate)
                    try:
                        proj_doc = _load_project_flows(pid)
                        proj_flows = proj_doc.get("flows") if isinstance(proj_doc, dict) else {}
                        candidate = proj_flows.get(key) if isinstance(proj_flows, dict) else None
                        if isinstance(candidate, dict):
                            return dict(candidate)
                    except Exception:
                        pass
                    try:
                        default_doc = _load_default_flows_doc()
                        default_flows = default_doc.get("flows") if isinstance(default_doc, dict) else {}
                        candidate = default_flows.get(key) if isinstance(default_flows, dict) else None
                        if isinstance(candidate, dict):
                            return dict(candidate)
                    except Exception:
                        pass
                    try:
                        temp_out = workflow_temp_library.run(_temp_library_ctx(pid), {"action": "resolve_flow", "flow_name": key, "workflow_id": wanted_id})
                        candidate = temp_out.get("workflow_json") if isinstance(temp_out, dict) else None
                        if isinstance(candidate, dict):
                            return dict(candidate)
                    except Exception:
                        pass
                    return None

                def _merge_step_reports(
                    base_report: Optional[Dict[str, Any]],
                    extra_report: Optional[Dict[str, Any]],
                ) -> Optional[Dict[str, Any]]:
                    if not isinstance(base_report, dict) and not isinstance(extra_report, dict):
                        return None
                    if not isinstance(base_report, dict):
                        return dict(extra_report or {})
                    if not isinstance(extra_report, dict):
                        return dict(base_report)
                    merged = dict(base_report)
                    for text_key in ("plan", "analysis", "response", "did", "handoff"):
                        extra_val = str(extra_report.get(text_key) or "").strip()
                        if extra_val:
                            merged[text_key] = extra_val
                    for list_key in ("actions", "bugs", "fixes", "skills_invoked", "tool_results"):
                        items: List[Any] = []
                        for source in (base_report.get(list_key), extra_report.get(list_key)):
                            if not isinstance(source, list):
                                continue
                            for row in source:
                                if row not in items:
                                    items.append(row)
                        if items:
                            merged[list_key] = items
                    for k, v in extra_report.items():
                        if k in {"plan", "analysis", "response", "did", "handoff", "actions", "bugs", "fixes", "skills_invoked", "tool_results"}:
                            continue
                        if v in (None, "", [], {}):
                            continue
                        merged[k] = v
                    return merged

                def _enrich_report_with_tool_results(report: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
                    if not isinstance(report, dict):
                        return report
                    tr_list = report.get("tool_results") if isinstance(report.get("tool_results"), list) else []
                    if not tr_list:
                        return report
                    enriched = dict(report)
                    for list_key in ("actions", "bugs", "fixes"):
                        merged_vals: List[str] = []
                        for source in (enriched.get(list_key), _tool_result_list_field(tr_list, list_key)):
                            if not isinstance(source, list):
                                continue
                            for row in source:
                                sval = str(row or "").strip()
                                if sval and sval not in merged_vals:
                                    merged_vals.append(sval)
                        if merged_vals:
                            enriched[list_key] = merged_vals
                    handoff_vals: List[str] = []
                    existing_handoff = str(enriched.get("handoff") or "").strip()
                    if existing_handoff:
                        handoff_vals.append(existing_handoff)
                    for tr in tr_list:
                        if not isinstance(tr, dict):
                            continue
                        data0 = tr.get("data") if isinstance(tr.get("data"), dict) else {}
                        for key0 in (
                            "handoff",
                            "coverage_status",
                            "route",
                            "status",
                            "decision",
                            "flow_name",
                            "bundle_dir",
                            "workflow_file",
                            "response",
                            "did",
                            "summary",
                            "text",
                        ):
                            sval = str(data0.get(key0) or tr.get(key0) or "").strip()
                            if sval and sval not in handoff_vals:
                                handoff_vals.append(sval)
                    if handoff_vals:
                        enriched["handoff"] = "\n".join(handoff_vals)
                    if not str(enriched.get("response") or "").strip():
                        for tr in tr_list:
                            if not isinstance(tr, dict):
                                continue
                            data0 = tr.get("data") if isinstance(tr.get("data"), dict) else {}
                            for key0 in ("response", "did", "summary", "text", "message", "result"):
                                sval = str(data0.get(key0) or tr.get(key0) or "").strip()
                                if sval:
                                    enriched["response"] = sval
                                    enriched["did"] = sval
                                    return enriched
                    return enriched

                def _carry_step_artifact_context(
                    report: Optional[Dict[str, Any]],
                    step_ext: Optional[Dict[str, Any]],
                ) -> Optional[Dict[str, Any]]:
                    if not isinstance(report, dict) or not isinstance(step_ext, dict):
                        return report
                    carried = dict(report)
                    artifact_keys = (
                        "bundle_dir",
                        "workflow_file",
                        "workflow_json_file",
                        "workflow_files",
                        "flow_name",
                        "pid",
                        "bundle_files",
                        "files",
                        "path",
                        "file",
                        "readme_file",
                        "archive_name",
                        "registered",
                        "reused_existing",
                        "all_passed",
                        "pass_count",
                        "fail_count",
                        "review_summary",
                    )
                    for key in artifact_keys:
                        if carried.get(key) not in (None, "", [], {}):
                            continue
                        value = step_ext.get(key)
                        if value in (None, "", [], {}):
                            continue
                        carried[key] = value
                    return carried

                def _run_transition_action(
                    transition: Dict[str, Any],
                    *,
                    step: Dict[str, Any],
                    step_ext: Dict[str, Any],
                    last_step_report: Optional[Dict[str, Any]] = None,
                    request_seed_text: str,
                    fallback_file_hint: str,
                ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
                    cfg = _transition_action_config(transition)
                    tool_name = str(cfg.get("tool") or "").strip()
                    aw_call = settings.get("__agent_workflow_tool_call")
                    if not tool_name or not callable(aw_call):
                        return None, None, None
                    merged_params: Dict[str, Any] = {}
                    merged_params.update(dict(cfg.get("params") or {}))
                    params_from_input = cfg.get("params_from_input") if isinstance(cfg.get("params_from_input"), list) else []

                    def _prior_value_for_param(name: str) -> Any:
                        pname = str(name or "").strip()
                        if not pname:
                            return None
                        for report_key in ("agent_flow_previous_step_report_with_tools", "agent_flow_previous_step_report"):
                            report_obj = step_ext.get(report_key)
                            if not isinstance(report_obj, dict):
                                continue
                            tr_rows = report_obj.get("tool_results") if isinstance(report_obj.get("tool_results"), list) else []
                            for tr_row in tr_rows:
                                if not isinstance(tr_row, dict):
                                    continue
                                data_row = tr_row.get("data") if isinstance(tr_row.get("data"), dict) else {}
                                if pname in data_row:
                                    return data_row.get(pname)
                                if pname in tr_row:
                                    return tr_row.get(pname)
                        report_source = last_step_report
                        if isinstance(report_source, dict):
                            if pname in report_source and report_source.get(pname) not in (None, "", [], {}):
                                return report_source.get(pname)
                            tr_rows = report_source.get("tool_results") if isinstance(report_source.get("tool_results"), list) else []
                            for tr_row in tr_rows:
                                if not isinstance(tr_row, dict):
                                    continue
                                data_row = tr_row.get("data") if isinstance(tr_row.get("data"), dict) else {}
                                if pname in data_row and data_row.get(pname) not in (None, "", [], {}):
                                    return data_row.get(pname)
                                if pname in tr_row and tr_row.get(pname) not in (None, "", [], {}):
                                    return tr_row.get(pname)
                        return None

                    for pkey0 in params_from_input:
                        pkey = str(pkey0 or "").strip()
                        if not pkey:
                            continue
                        if pkey == "text" and tool_name == "result.text":
                            v = _prior_value_for_param(pkey)
                            if v is None:
                                for alt_key in ("finalized_text", "execution_text", "response", "final_answer", "table_markdown", "markdown", "summary"):
                                    v = _prior_value_for_param(alt_key)
                                    if v not in (None, "", [], {}):
                                        break
                            if v in (None, "", [], {}):
                                v = str(last_output_text or "").strip()
                            if v is not None and str(v).strip():
                                merged_params[pkey] = v
                                continue
                        if (
                            pkey in merged_params
                            and str(merged_params.get(pkey) or "").strip()
                            and pkey not in {"current_request_text", "request_text", "user_request", "request", "text", "prompt", "query"}
                        ):
                            continue
                        v = _coalesce_param_value(
                            step_ext.get(pkey),
                            ext.get(pkey),
                            (step.get("input") if isinstance(step.get("input"), dict) else {}).get(pkey),
                        )
                        if v is None:
                            alias_key = {
                                "last_bundle_dir": "bundle_dir",
                                "last_workflow_file": "workflow_file",
                                "last_flow_name": "flow_name",
                            }.get(pkey)
                            if alias_key:
                                v = _coalesce_param_value(
                                    step_ext.get(alias_key),
                                    ext.get(alias_key),
                                    (step.get("input") if isinstance(step.get("input"), dict) else {}).get(alias_key),
                                )
                        if v is None:
                            v = _prior_value_for_param(pkey)
                        if v is None and pkey in {"file", "path", "file_path", "input_path", "source_pdf_path"}:
                            v = fallback_file_hint
                        if v is not None and str(v).strip():
                            merged_params[pkey] = v

                    if tool_name.startswith("sheet.") and not any(str(merged_params.get(k) or "").strip() for k in ("file", "path", "file_path")) and fallback_file_hint:
                        merged_params["path"] = fallback_file_hint

                    tool_ctx = {
                        "app": app,
                        "pid": pid,
                        "sid": sid,
                        "settings": settings,
                        "ext": dict(step_ext) if isinstance(step_ext, dict) else {},
                        "user_text": request_seed_text,
                        "original_request": request_seed_text,
                    }
                    raw_res = aw_call(tool_name, tool_ctx, merged_params)
                    if not isinstance(raw_res, dict):
                        raw_res = {"ok": False, "warnings": ["transition_action_invalid_result"], "data": {"result": raw_res}}
                    tr_row = {
                        "skill": tool_name,
                        "ok": bool(raw_res.get("ok")) if "ok" in raw_res else True,
                        "warnings": list(raw_res.get("warnings") or []) if isinstance(raw_res.get("warnings"), list) else [],
                        "data": dict(raw_res.get("data") or {}) if isinstance(raw_res.get("data"), dict) else {},
                    }
                    for k, v in raw_res.items():
                        if k in {"ok", "warnings", "data", "error"}:
                            continue
                        if k not in tr_row["data"]:
                            tr_row["data"][k] = v
                    data0 = tr_row.get("data") if isinstance(tr_row.get("data"), dict) else {}
                    text0 = ""
                    for key0 in ("text", "response", "summary", "did", "message", "result"):
                        text0 = str(data0.get(key0) or raw_res.get(key0) or "").strip()
                        if text0:
                            break
                    preserve_keys = {
                        "tracker_state",
                        "planned_requests",
                        "current_request",
                        "current_request_text",
                        "remaining_requests",
                        "completed_requests",
                        "completed_count",
                        "created_count",
                        "failed_count",
                        "total_requests",
                        "has_current",
                        "has_more",
                        "subflow_parent_state",
                        "subflow_result_state",
                    }
                    preserved = {}
                    for key0 in preserve_keys:
                        if isinstance(data0, dict) and data0.get(key0) not in (None, "", [], {}):
                            preserved[key0] = data0.get(key0)
                    edge_report = {
                        "step": 0,
                        "total": 0,
                        "role": str(step.get("label") or step.get("node_id") or "").strip(),
                        "plan": "",
                        "analysis": "",
                        "response": text0,
                        "did": text0,
                        "actions": list(data0.get("actions") or []) if isinstance(data0.get("actions"), list) else [],
                        "bugs": list(data0.get("bugs") or []) if isinstance(data0.get("bugs"), list) else [],
                        "fixes": list(data0.get("fixes") or []) if isinstance(data0.get("fixes"), list) else [],
                        "skills_invoked": [tool_name],
                        "handoff": str(data0.get("handoff") or raw_res.get("handoff") or text0 or "").strip(),
                        "tool_results": [tr_row],
                    }
                    edge_report.update(preserved)
                    return edge_report, tr_row, merged_params

                def _build_transition_path_steps(
                    target_id: str,
                    *,
                    retry_num: int,
                    label_suffix: str,
                    extra_system_prompt: str = "",
                ) -> List[Dict[str, Any]]:
                    target_key = str(target_id or "").strip()
                    if not target_key:
                        return []
                    runtime_nodes = flow_for_run.get("nodes") if isinstance(flow_for_run.get("nodes"), dict) else {}
                    active_runtime_flow_name = ""
                    try:
                        ps_current = step.get("plugin_settings") if isinstance(step.get("plugin_settings"), dict) else {}
                        active_runtime_flow_name = str(ps_current.get("runtime_flow_name") or "").strip()
                    except Exception:
                        active_runtime_flow_name = ""
                    if active_runtime_flow_name:
                        runtime_flow_ref = _resolve_runtime_flow(active_runtime_flow_name)
                        runtime_nodes_ref = runtime_flow_ref.get("nodes") if isinstance(runtime_flow_ref, dict) and isinstance(runtime_flow_ref.get("nodes"), dict) else {}
                        if runtime_nodes_ref:
                            runtime_nodes = runtime_nodes_ref
                    if target_key not in runtime_nodes:
                        return []
                    remaining = max(1, 128 - len(steps))
                    synthetic_flow = {
                        "start": target_key,
                        "nodes": runtime_nodes,
                    }
                    built = _build_flow_steps(
                        synthetic_flow,
                        user_text,
                        remaining,
                        flows=flows,
                        _flow_name=str(flow_name),
                        _flow_stack=[],
                        _loop_once_used={},
                    )
                    out_steps: List[Dict[str, Any]] = []
                    transition_origin_id = str(step.get("node_id") or target_key).strip()
                    transition_origin_slug = re.sub(r"[^A-Za-z0-9_.:-]+", "_", transition_origin_id).strip("_") or "origin"
                    for path_index, path_step in enumerate(built):
                        template_id = str(path_step.get("template_node_id") or path_step.get("node_id") or "").split("::")[0].strip()
                        base_template = step_templates.get(template_id) if template_id else None
                        base = dict(base_template or path_step)
                        clone = _clone_step_for_transition(
                            base,
                            label_suffix=label_suffix,
                            extra_system_prompt=extra_system_prompt if path_index == 0 else "",
                        )
                        clone["node_id"] = f"{template_id or target_key}::loopback::{retry_num}::from::{transition_origin_slug}::path::{path_index}"
                        clone["template_node_id"] = template_id or target_key
                        clone_ps = clone.get("plugin_settings") if isinstance(clone.get("plugin_settings"), dict) else {}
                        clone_ps = dict(clone_ps)
                        if active_runtime_flow_name:
                            clone_ps["runtime_flow_name"] = active_runtime_flow_name
                        clone["plugin_settings"] = clone_ps
                        out_steps.append(clone)
                    return out_steps

                def _build_runtime_subflow_steps(
                    parent_step: Dict[str, Any],
                    *,
                    parent_runtime_id: str,
                    subflow_name_ref: str,
                    subflow_workflow_id: str,
                    branch_items: List[Any],
                    default_input_text: str,
                ) -> List[Dict[str, Any]]:
                    target_flow = _resolve_runtime_flow(subflow_name_ref, subflow_workflow_id)
                    if not isinstance(target_flow, dict):
                        return []
                    try:
                        runtime_nodes = target_flow.get("nodes") if isinstance(target_flow.get("nodes"), dict) else {}
                        for node_id, node in runtime_nodes.items():
                            node_key = str(node_id or "").strip()
                            if not node_key or not isinstance(node, dict):
                                continue
                            if node_key in step_templates:
                                continue
                            step_templates[node_key] = {
                                "step_index": len(step_templates),
                                "node_id": node_key,
                                "template_node_id": node_key,
                                "label": node.get("label") or node_key,
                                "plugin_id": node.get("plugin_id") or "chat",
                                "system_prompt": node.get("system_prompt") or "",
                                "return_only_text": node.get("return_only_text") is not False,
                                "delay_ms": int(node.get("delay_ms") or 0),
                                "transitions": node.get("transitions") or [],
                                "plugin_settings": node.get("plugin_settings") or {},
                                "initial_user_input": "",
                            }
                    except Exception:
                        pass
                    injected: List[Dict[str, Any]] = []
                    parent_label = str(parent_step.get("label") or parent_runtime_id).strip()
                    parent_ps = parent_step.get("plugin_settings") if isinstance(parent_step.get("plugin_settings"), dict) else {}
                    input_map = _parse_state_map_spec(parent_ps.get("subflow_input_map"))
                    output_map = _parse_state_map_spec(parent_ps.get("subflow_output_map"))
                    def _prior_step_value(name: str) -> Any:
                        key = str(name or "").strip()
                        if not key:
                            return None
                        for report_obj in (
                            last_step_report_with_tools if isinstance(last_step_report_with_tools, dict) else {},
                            last_step_report if isinstance(last_step_report, dict) else {},
                        ):
                            if not isinstance(report_obj, dict):
                                continue
                            direct_val = report_obj.get(key)
                            if direct_val not in (None, "", [], {}):
                                return direct_val
                            tr_rows = report_obj.get("tool_results") if isinstance(report_obj.get("tool_results"), list) else []
                            for tr_row in tr_rows:
                                if not isinstance(tr_row, dict):
                                    continue
                                data_row = tr_row.get("data") if isinstance(tr_row.get("data"), dict) else {}
                                val = data_row.get(key) if key in data_row else tr_row.get(key)
                                if val not in (None, "", [], {}):
                                    return val
                        return None
                    for branch_index, item in enumerate(branch_items):
                        normalized_item = _coerce_single_request(item)
                        item_text = _iteration_item_text(item, default_input_text)
                        if not item_text and isinstance(normalized_item, dict):
                            item_text = _iteration_item_text(normalized_item, default_input_text)
                        branch_steps = _build_flow_steps(
                            target_flow,
                            item_text,
                            max(1, 128 - len(steps) - len(injected)),
                            flows=flows,
                            _flow_name=subflow_name_ref,
                            _flow_stack=[],
                        )
                        branch_total = len(branch_steps)
                        parent_input = parent_step.get("input") if isinstance(parent_step.get("input"), dict) else {}
                        parent_remaining = _resolve_path_from_sources(
                            "remaining_requests",
                            step_input_now,
                            step_ext,
                            last_step_report_with_tools if isinstance(last_step_report_with_tools, dict) else {},
                            last_step_report if isinstance(last_step_report, dict) else {},
                        )
                        if parent_remaining in (None, "", [], {}):
                            parent_remaining = _prior_step_value("remaining_requests")
                        parent_completed = _resolve_path_from_sources(
                            "completed_requests",
                            step_input_now,
                            step_ext,
                            last_step_report_with_tools if isinstance(last_step_report_with_tools, dict) else {},
                            last_step_report if isinstance(last_step_report, dict) else {},
                        )
                        if parent_completed in (None, "", [], {}):
                            parent_completed = _prior_step_value("completed_requests")
                        parent_tracker_state = _normalize_tracker_state(
                            _resolve_path_from_sources(
                                "tracker_state",
                                step_input_now,
                                step_ext,
                                last_step_report_with_tools if isinstance(last_step_report_with_tools, dict) else {},
                                last_step_report if isinstance(last_step_report, dict) else {},
                            )
                            or _prior_step_value("tracker_state")
                        )
                        parent_state = {
                            "current_request": normalized_item if isinstance(normalized_item, dict) and normalized_item else prior_current_req,
                            "current_request_text": str(prior_current_text or item_text or "").strip(),
                            "remaining_requests": parent_remaining if isinstance(parent_remaining, list) else [],
                            "completed_requests": parent_completed if isinstance(parent_completed, list) else [],
                            "completed_count": int(_resolve_path_from_sources(
                                "completed_count",
                                step_input_now,
                                step_ext,
                                last_step_report_with_tools if isinstance(last_step_report_with_tools, dict) else {},
                                last_step_report if isinstance(last_step_report, dict) else {},
                            ) or _prior_step_value("completed_count") or 0),
                            "created_count": int(_resolve_path_from_sources(
                                "created_count",
                                step_input_now,
                                step_ext,
                                last_step_report_with_tools if isinstance(last_step_report_with_tools, dict) else {},
                                last_step_report if isinstance(last_step_report, dict) else {},
                            ) or _prior_step_value("created_count") or 0),
                            "failed_count": int(_resolve_path_from_sources(
                                "failed_count",
                                step_input_now,
                                step_ext,
                                last_step_report_with_tools if isinstance(last_step_report_with_tools, dict) else {},
                                last_step_report if isinstance(last_step_report, dict) else {},
                            ) or _prior_step_value("failed_count") or 0),
                            "total_requests": int(_resolve_path_from_sources(
                                "total_requests",
                                step_input_now,
                                step_ext,
                                last_step_report_with_tools if isinstance(last_step_report_with_tools, dict) else {},
                                last_step_report if isinstance(last_step_report, dict) else {},
                            ) or _prior_step_value("total_requests") or 0),
                            "tracker_state": parent_tracker_state,
                            "iteration_index": branch_index,
                            "iteration_count": len(branch_items),
                            "subflow_name": subflow_name_ref,
                        }
                        mapped_input: Dict[str, Any] = {}
                        if input_map:
                            sources = (
                                item if isinstance(item, dict) else {"item": item},
                                {"item": item, "item_text": item_text, "iteration_index": branch_index, "iteration_count": len(branch_items)},
                                parent_input,
                                step_ext,
                                ext,
                                parent_state,
                            )
                            for target_key, source_path in input_map.items():
                                val = _resolve_path_from_sources(source_path, *sources)
                                if val is not None:
                                    if target_key == "current_request":
                                        val = _coerce_single_request(val)
                                    if target_key in {"remaining_requests", "completed_requests"}:
                                        if isinstance(val, tuple):
                                            val = list(val)
                                        if val is not None and not isinstance(val, list):
                                            val = [val]
                                    if target_key == "tracker_state":
                                        val = _normalize_tracker_state(val)
                                    mapped_input[target_key] = val
                        for child_index, child in enumerate(branch_steps):
                            clone = dict(child)
                            base_template_id = str(clone.get("template_node_id") or clone.get("node_id") or "").split("::")[0].strip()
                            branch_prefix = f"{parent_runtime_id}::branch::{branch_index}::{child_index}"
                            clone["node_id"] = branch_prefix
                            clone["template_node_id"] = base_template_id or str(clone.get("node_id") or "")
                            clone["label"] = f"{parent_label} / {branch_index + 1}/{len(branch_items)} / {clone.get('label') or clone.get('node_id') or ''}".strip(" /")
                            clone_ps = clone.get("plugin_settings") if isinstance(clone.get("plugin_settings"), dict) else {}
                            clone_ps = dict(clone_ps)
                            clone_ps["fanout_parent_id"] = parent_runtime_id
                            clone_ps["fanout_branch_index"] = branch_index
                            clone_ps["fanout_branch_total"] = len(branch_items)
                            clone_ps["fanout_branch_terminal"] = child_index == max(0, branch_total - 1)
                            clone_ps["runtime_flow_name"] = subflow_name_ref
                            clone["plugin_settings"] = clone_ps
                            clone["input"] = {
                                **(clone.get("input") if isinstance(clone.get("input"), dict) else {}),
                                "iteration_item": item,
                                "iteration_index": branch_index,
                                "iteration_count": len(branch_items),
                                "iteration_text": item_text,
                                "subflow_name": subflow_name_ref,
                                "subflow_parent_state": dict(parent_state),
                                **mapped_input,
                            }
                            injected.append(clone)
                    join_step = {
                        "step_index": len(steps) + len(injected),
                        "node_id": f"{parent_runtime_id}::fanin",
                        "template_node_id": str(parent_step.get("template_node_id") or parent_step.get("node_id") or "").split("::")[0].strip(),
                        "label": f"{parent_label} / Join",
                        "plugin_id": "agent_flow_fan_in_internal",
                        "system_prompt": str(parent_step.get("system_prompt") or ""),
                        "return_only_text": True,
                        "delay_ms": 0,
                        "transitions": list(parent_step.get("transitions") or []),
                        "plugin_settings": {
                            "node_type": "fan_in_node",
                            "fanout_parent_id": parent_runtime_id,
                            "subflow_name": subflow_name_ref,
                            "subflow_output_map": output_map,
                        },
                        "initial_user_input": "",
                    }
                    injected.append(join_step)
                    fanout_results[parent_runtime_id] = {
                        "items": list(branch_items),
                        "branches": [],
                        "subflow_name": subflow_name_ref,
                        "parent_label": parent_label,
                        "output_map": output_map,
                    }
                    return injected

                def _aggregate_fanout_report(parent_runtime_id: str) -> Dict[str, Any]:
                    bucket = fanout_results.get(parent_runtime_id) if isinstance(fanout_results.get(parent_runtime_id), dict) else {}
                    branches = bucket.get("branches") if isinstance(bucket.get("branches"), list) else []
                    item_total = len(bucket.get("items") or [])
                    actions: List[str] = []
                    bugs: List[str] = []
                    fixes: List[str] = []
                    handoffs: List[str] = []
                    skills_invoked: List[str] = []
                    for row in branches:
                        if not isinstance(row, dict):
                            continue
                        rep = row.get("report") if isinstance(row.get("report"), dict) else {}
                        for key, dest in (("actions", actions), ("bugs", bugs), ("fixes", fixes), ("skills_invoked", skills_invoked)):
                            vals = rep.get(key) if isinstance(rep.get(key), list) else []
                            for v in vals:
                                s = str(v or "").strip()
                                if s and s not in dest:
                                    dest.append(s)
                        h = str(rep.get("handoff") or rep.get("response") or rep.get("did") or "").strip()
                        if h:
                            handoffs.append(h)
                    latest_branch = branches[-1] if branches else {}
                    latest_report = latest_branch.get("report") if isinstance(latest_branch, dict) and isinstance(latest_branch.get("report"), dict) else {}
                    latest_input = latest_branch.get("input") if isinstance(latest_branch, dict) and isinstance(latest_branch.get("input"), dict) else {}
                    latest_report_state = latest_report.get("subflow_result_state") if isinstance(latest_report, dict) else {}
                    output_map = bucket.get("output_map") if isinstance(bucket.get("output_map"), dict) else {}
                    mapped_state: Dict[str, Any] = {}
                    if output_map:
                        sources = (
                            latest_report,
                            latest_report_state if isinstance(latest_report_state, dict) else {},
                            latest_report.get("tool_results") if isinstance(latest_report, dict) else [],
                            latest_input,
                            latest_input.get("subflow_parent_state") if isinstance(latest_input.get("subflow_parent_state"), dict) else {},
                            latest_branch,
                        )
                        for target_key, source_path in output_map.items():
                            val = _resolve_path_from_sources(source_path, *sources)
                            if val is not None:
                                if target_key == "current_request":
                                    val = _coerce_single_request(val)
                                elif target_key == "tracker_state":
                                    val = _normalize_tracker_state(val)
                                elif target_key in {"remaining_requests", "completed_requests"}:
                                    if isinstance(val, tuple):
                                        val = list(val)
                                    if val is not None and not isinstance(val, list):
                                        val = [val]
                                mapped_state[target_key] = val
                    if "tracker_state" not in mapped_state:
                        tracker_state0 = None
                        if isinstance(latest_report_state, dict) and isinstance(latest_report_state.get("tracker_state"), dict):
                            tracker_state0 = _normalize_tracker_state(latest_report_state.get("tracker_state"))
                        if tracker_state0 is None:
                            tracker_state0 = latest_input.get("tracker_state") if isinstance(latest_input.get("tracker_state"), dict) else None
                        if tracker_state0 is None:
                            parent_state0 = latest_input.get("subflow_parent_state") if isinstance(latest_input.get("subflow_parent_state"), dict) else {}
                            nested_state0 = parent_state0.get("tracker_state") if isinstance(parent_state0.get("tracker_state"), dict) else {}
                            if nested_state0:
                                tracker_state0 = _normalize_tracker_state(nested_state0)
                            elif parent_state0:
                                tracker_state0 = _normalize_tracker_state(parent_state0)
                        if tracker_state0:
                            mapped_state["tracker_state"] = _normalize_tracker_state(tracker_state0)
                    tracker_state_flat = mapped_state.get("tracker_state") if isinstance(mapped_state.get("tracker_state"), dict) else {}
                    if tracker_state_flat:
                        if "current_request" not in mapped_state and tracker_state_flat.get("current_request") is not None:
                            mapped_state["current_request"] = _coerce_single_request(tracker_state_flat.get("current_request"))
                        if "current_request_text" not in mapped_state:
                            current_text0 = str(
                                tracker_state_flat.get("current_request_text")
                                or (
                                    tracker_state_flat.get("current_request", {}).get("request_text")
                                    if isinstance(tracker_state_flat.get("current_request"), dict)
                                    else ""
                                )
                                or (
                                    tracker_state_flat.get("current_request", {}).get("request")
                                    if isinstance(tracker_state_flat.get("current_request"), dict)
                                    else ""
                                )
                                or ""
                            ).strip()
                            if current_text0:
                                mapped_state["current_request_text"] = current_text0
                        if "remaining_requests" not in mapped_state and isinstance(tracker_state_flat.get("remaining_requests"), list):
                            mapped_state["remaining_requests"] = list(tracker_state_flat.get("remaining_requests") or [])
                        if "completed_requests" not in mapped_state and isinstance(tracker_state_flat.get("completed_requests"), list):
                            mapped_state["completed_requests"] = list(tracker_state_flat.get("completed_requests") or [])
                        if "total_requests" not in mapped_state and tracker_state_flat.get("total_requests") not in (None, ""):
                            mapped_state["total_requests"] = tracker_state_flat.get("total_requests")
                    if "subflow_parent_state" not in mapped_state:
                        parent_state0 = latest_input.get("subflow_parent_state") if isinstance(latest_input.get("subflow_parent_state"), dict) else {}
                        if not parent_state0 and isinstance(latest_report_state, dict):
                            parent_state0 = latest_report_state if isinstance(latest_report_state, dict) else {}
                        if parent_state0:
                            mapped_state["subflow_parent_state"] = parent_state0
                    passthrough_state_keys = (
                        "bundle_dir",
                        "workflow_file",
                        "flow_name",
                        "input_path",
                        "file_path",
                        "path",
                        "file",
                        "flow_ext",
                        "validated_request_text",
                        "request_text",
                        "execution_text",
                        "execution_files",
                        "execution_zip",
                    )
                    latest_report_rows = latest_report.get("tool_results") if isinstance(latest_report.get("tool_results"), list) else []
                    passthrough_sources = (
                        latest_report,
                        latest_report_state if isinstance(latest_report_state, dict) else {},
                        latest_input,
                        latest_input.get("subflow_parent_state") if isinstance(latest_input.get("subflow_parent_state"), dict) else {},
                        latest_branch,
                    )
                    for pkey in passthrough_state_keys:
                        if mapped_state.get(pkey) not in (None, "", [], {}):
                            continue
                        val = _resolve_path_from_sources(pkey, *passthrough_sources)
                        if val in (None, "", [], {}):
                            alias_key = {
                                "bundle_dir": "last_bundle_dir",
                                "workflow_file": "last_workflow_file",
                                "flow_name": "last_flow_name",
                            }.get(pkey)
                            if alias_key:
                                val = _resolve_path_from_sources(alias_key, *passthrough_sources)
                        if val in (None, "", [], {}):
                            row_vals = _tool_result_list_field(latest_report_rows, pkey)
                            if row_vals:
                                val = row_vals[-1]
                        if val not in (None, "", [], {}):
                            mapped_state[pkey] = val
                    status_text = f"Completed {len(branches)}/{item_total} subflow branch(es) for {str(bucket.get('subflow_name') or '').strip() or 'subflow'}."
                    out_report = {
                        "step": 0,
                        "total": 0,
                        "role": str(bucket.get("parent_label") or "Fan In").strip(),
                        "plan": "",
                        "analysis": status_text,
                        "response": status_text,
                        "did": status_text,
                        "actions": actions,
                        "bugs": bugs,
                        "fixes": fixes,
                        "skills_invoked": skills_invoked,
                        "handoff": "\n".join(handoffs[:12]).strip(),
                        "tool_results": [],
                        "branch_results": branches,
                    }
                    if mapped_state:
                        out_report["subflow_result_state"] = dict(mapped_state)
                        for mk, mv in mapped_state.items():
                            out_report[mk] = mv
                    return out_report

                def _result_mode_from_plugin_settings(ps: Dict[str, Any]) -> str:
                    if not isinstance(ps, dict):
                        return ""
                    skills = ps.get("action_skills") if isinstance(ps.get("action_skills"), list) else []
                    cats = ps.get("action_skill_categories") if isinstance(ps.get("action_skill_categories"), list) else []
                    skill_rules = ps.get("action_skill_rules") if isinstance(ps.get("action_skill_rules"), dict) else {}
                    skills_norm = []
                    for x in skills:
                        sid = str(x or "").strip().lower()
                        if not sid:
                            continue
                        rule_obj = skill_rules.get(sid)
                        if rule_obj is None:
                            rule_obj = skill_rules.get(str(x or "").strip())
                        if isinstance(rule_obj, dict) and not _action_skill_rule_applies(rule_obj, user_text):
                            continue
                        skills_norm.append(sid)
                    cats_norm = {str(x or "").strip().lower().replace(".*", "") for x in cats}
                    for sid_norm in skills_norm:
                        if sid_norm.startswith("result."):
                            mode = sid_norm.split(".", 1)[1].strip()
                            if mode:
                                return mode
                    if "result" in cats_norm:
                        return "result"
                    return ""

                def _result_skill_mode(skill_id: str) -> str:
                    sid_l = str(skill_id or "").strip().lower()
                    if not sid_l.startswith("result."):
                        return ""
                    return sid_l.split(".", 1)[1].strip()

                def _result_tool_rows(*reports: Any) -> List[Dict[str, Any]]:
                    rows: List[Dict[str, Any]] = []
                    for report in reports:
                        if not isinstance(report, dict):
                            continue
                        tr = report.get("tool_results")
                        if not isinstance(tr, list):
                            continue
                        for row in tr:
                            if not isinstance(row, dict):
                                continue
                            if row.get("ok") is False:
                                continue
                            if not _result_skill_mode(str(row.get("skill") or "")):
                                continue
                            rows.append(row)
                    return rows

                def _extract_result_emit(mode_hint: str, *reports: Any) -> Dict[str, Any]:
                    rows = _result_tool_rows(*reports)
                    if not rows:
                        return {}
                    hint = str(mode_hint or "").strip().lower()
                    chosen = None
                    for row in rows:
                        smode = _result_skill_mode(str(row.get("skill") or ""))
                        if hint and hint not in {"result", "*"} and smode == hint:
                            chosen = row
                            break
                    if chosen is None:
                        chosen = rows[-1]
                    data = chosen.get("data") if isinstance(chosen.get("data"), dict) else {}
                    smode = _result_skill_mode(str(chosen.get("skill") or ""))
                    mode = str(data.get("mode") or chosen.get("mode") or smode or hint or "result").strip().lower()
                    content = ""
                    for key in ("content", "text", "result", "message"):
                        val = data.get(key)
                        if val is None:
                            val = chosen.get(key)
                        val_s = str(val or "").strip()
                        if val_s:
                            content = val_s
                            break
                    extra_contents: List[str] = []
                    for row in rows:
                        if row is chosen:
                            continue
                        data_extra = row.get("data") if isinstance(row.get("data"), dict) else {}
                        extra_text = ""
                        for key in ("content", "text", "result", "message"):
                            val = data_extra.get(key)
                            if val is None:
                                val = row.get(key)
                            val_s = str(val or "").strip()
                            if val_s:
                                extra_text = val_s
                                break
                        if extra_text and extra_text not in extra_contents and extra_text != content:
                            extra_contents.append(extra_text)
                    if extra_contents:
                        parts = [part for part in [content, *extra_contents] if str(part or "").strip()]
                        content = "\n\n".join(parts).strip()
                    meta_payload: Dict[str, Any] = {}
                    skip_keys = {"ok", "mode", "content", "text", "result", "message", "warnings", "skill", "reason"}
                    meta_sources: List[Dict[str, Any]] = []
                    for row in rows:
                        data_row = row.get("data") if isinstance(row.get("data"), dict) else {}
                        if isinstance(data_row, dict):
                            meta_sources.append(data_row)
                        if isinstance(row, dict):
                            meta_sources.append(row)
                    for src in meta_sources:
                        for key, val in src.items():
                            key_s = str(key or "").strip()
                            if not key_s or key_s in skip_keys:
                                continue
                            if not (isinstance(val, (dict, list, str, int, float, bool)) or val is None):
                                continue
                            if key_s == "staged_files" and isinstance(val, list):
                                existing_files = meta_payload.get("files") if isinstance(meta_payload.get("files"), list) else []
                                merged_files = list(existing_files)
                                seen_file_urls = {str((item or {}).get("download_url") or "") for item in merged_files if isinstance(item, dict)}
                                for item in val:
                                    if not isinstance(item, dict):
                                        continue
                                    file_url = str(item.get("download_url") or "").strip()
                                    file_name = str(item.get("name") or "").strip()
                                    if file_url and file_url in seen_file_urls:
                                        continue
                                    if not file_url and file_name and any(str((row_item or {}).get("name") or "") == file_name for row_item in merged_files if isinstance(row_item, dict)):
                                        continue
                                    merged_files.append(item)
                                    if file_url:
                                        seen_file_urls.add(file_url)
                                if merged_files:
                                    meta_payload["files"] = merged_files
                                continue
                            if key_s == "files" and isinstance(val, list):
                                existing_files = meta_payload.get("files") if isinstance(meta_payload.get("files"), list) else []
                                merged_files = list(existing_files)
                                seen_file_urls = {str((item or {}).get("download_url") or "") for item in merged_files if isinstance(item, dict)}
                                for item in val:
                                    if not isinstance(item, dict):
                                        continue
                                    file_url = str(item.get("download_url") or "").strip()
                                    file_name = str(item.get("name") or "").strip()
                                    if file_url and file_url in seen_file_urls:
                                        continue
                                    if not file_url and file_name and any(str((row_item or {}).get("name") or "") == file_name for row_item in merged_files if isinstance(row_item, dict)):
                                        continue
                                    merged_files.append(item)
                                    if file_url:
                                        seen_file_urls.add(file_url)
                                if merged_files:
                                    meta_payload["files"] = merged_files
                                continue
                            if key_s == "zip" and isinstance(val, dict):
                                if not isinstance(meta_payload.get("zip"), dict) or not meta_payload.get("zip"):
                                    meta_payload["zip"] = val
                                continue
                            meta_payload[key_s] = val
                    return {"mode": mode, "content": content, "meta": meta_payload, "row": chosen}

                def _json_safe(value: Any) -> Any:
                    if value is None or isinstance(value, (str, int, float, bool)):
                        return value
                    if isinstance(value, Path):
                        return str(value)
                    if isinstance(value, dict):
                        out: Dict[str, Any] = {}
                        for key, val in value.items():
                            key_s = str(key or "").strip()
                            if not key_s:
                                continue
                            out[key_s] = _json_safe(val)
                        return out
                    if isinstance(value, (list, tuple, set)):
                        return [_json_safe(v) for v in value]
                    try:
                        json.dumps(value)
                        return value
                    except Exception:
                        return str(value)

                def _humanize_result_fallback(raw_text: str, report: Optional[Dict[str, Any]]) -> str:
                    rep = report if isinstance(report, dict) else {}
                    response = str(rep.get("response") or rep.get("did") or "").strip()
                    actions = rep.get("actions") if isinstance(rep.get("actions"), list) else []
                    fixes = rep.get("fixes") if isinstance(rep.get("fixes"), list) else []
                    bugs = rep.get("bugs") if isinstance(rep.get("bugs"), list) else []
                    if response:
                        lines: List[str] = [response]
                        if fixes:
                            lines.append("")
                            lines.append("**Fixes Applied**")
                            lines.extend(f"- {str(x or '').strip()}" for x in fixes if str(x or "").strip())
                        if bugs:
                            lines.append("")
                            lines.append("**Notes**")
                            lines.extend(f"- {str(x or '').strip()}" for x in bugs if str(x or "").strip())
                        if actions:
                            lines.append("")
                            lines.append("**Delivered**")
                            lines.extend(f"- {str(x or '').strip()}" for x in actions if str(x or "").strip())
                        return "\n".join(lines).strip()
                    text = str(raw_text or "").strip()
                    if not text:
                        return ""
                    if text.lower().startswith("role:") or "\nresponse:" in text.lower() or "\ndid:" in text.lower():
                        fields: Dict[str, str] = {}
                        current_key = ""
                        buffer: List[str] = []
                        for line in text.splitlines():
                            m = re.match(r"^([A-Za-z_][A-Za-z0-9_ ]*):\s*(.*)$", str(line or ""))
                            if m:
                                if current_key:
                                    fields[current_key] = "\n".join(buffer).strip()
                                current_key = str(m.group(1) or "").strip().lower()
                                buffer = [str(m.group(2) or "").rstrip()]
                            elif current_key:
                                buffer.append(str(line or "").rstrip())
                        if current_key:
                            fields[current_key] = "\n".join(buffer).strip()
                        preferred = (
                            fields.get("response")
                            or fields.get("did")
                            or fields.get("analysis")
                            or fields.get("summary")
                            or ""
                        ).strip()
                        if preferred:
                            return preferred
                    return text

                def _extract_json_block_maybe(text: str) -> Any:
                    raw = str(text or "").strip()
                    if not raw:
                        return None
                    m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
                    if m:
                        raw = str(m.group(1) or "").strip()
                    # Handle double-encoded JSON strings, e.g. "{\"chart\":...}".
                    if len(raw) >= 2 and ((raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'"))):
                        q = raw[0]
                        if raw[-1] == q:
                            inner = raw[1:-1].strip()
                            if inner:
                                raw = inner
                    try:
                        return json.loads(raw)
                    except Exception:
                        pass
                    # Try unescaping common backslash-escaped JSON payloads.
                    try:
                        unescaped = bytes(raw, "utf-8").decode("unicode_escape")
                        if unescaped and unescaped != raw:
                            try:
                                return json.loads(unescaped)
                            except Exception:
                                pass
                    except Exception:
                        pass
                    for pat in (r"(\{.*\})", r"(\[.*\])"):
                        m2 = re.search(pat, raw, flags=re.DOTALL)
                        if not m2:
                            continue
                        try:
                            return json.loads(str(m2.group(1) or "").strip())
                        except Exception:
                            continue
                    # Fallback: extract JSON object/array from unescaped content.
                    try:
                        unescaped2 = bytes(raw, "utf-8").decode("unicode_escape")
                    except Exception:
                        unescaped2 = ""
                    if unescaped2:
                        for pat in (r"(\{.*\})", r"(\[.*\])"):
                            m3 = re.search(pat, unescaped2, flags=re.DOTALL)
                            if not m3:
                                continue
                            try:
                                return json.loads(str(m3.group(1) or "").strip())
                            except Exception:
                                continue
                    return None

                def _to_chart_payload(obj: Any) -> Optional[Dict[str, Any]]:
                    return normalize_chart_payload(obj, user_request=str(user_text or ""))

                def _uploads_dir_path() -> Path:
                    base = getattr(app.state, "data_dir", None) or getattr(app.state, "workdir", None) or os.path.abspath("./data")
                    up = Path(str(base)).resolve() / "uploads"
                    up.mkdir(parents=True, exist_ok=True)
                    return up

                def _unique_upload_name(name: str) -> str:
                    base = Path(name).name or "artifact.bin"
                    stem = Path(base).stem or "artifact"
                    suf = Path(base).suffix or ""
                    return f"{stem}_{run_id[:8]}{suf}"

                def _resolve_existing_file(path_like: str) -> Optional[Path]:
                    raw = str(path_like or "").strip()
                    if not raw:
                        return None
                    candidates: List[Path] = []
                    p0 = Path(raw)
                    if p0.is_absolute():
                        candidates.append(p0)
                    else:
                        candidates.append(Path(os.getcwd()) / p0)
                        tr = str(ext.get("target_repo_root") or ext.get("agent_workflow_target_repo_root") or "").strip()
                        if tr:
                            candidates.append(Path(tr) / p0)
                    for cand in candidates:
                        try:
                            c = cand.resolve()
                            if c.is_file():
                                return c
                        except Exception:
                            continue
                    return None

                def _collect_result_files(out_obj: Dict[str, Any], fallback_changed: List[str]) -> List[Path]:
                    raw_paths: List[str] = []

                    def _append_raw(value: Any) -> None:
                        if isinstance(value, list):
                            raw_paths.extend(str(v or "").strip() for v in value if str(v or "").strip())
                        elif isinstance(value, str) and value.strip():
                            raw_paths.append(value.strip())

                    def _scan_report_dict(obj: Any) -> None:
                        if not isinstance(obj, dict):
                            return
                        for key in (
                            "files",
                            "paths",
                            "path",
                            "file",
                            "file_path",
                            "output_path",
                            "final_path",
                            "zip_path",
                            "workflow_file",
                            "workflow_json_file",
                            "last_workflow_file",
                            "download_path",
                            "readme_file",
                            "workflow_files",
                            "bundle_files",
                            "stub_files",
                            "changed_files",
                            "final_paths",
                            "requested_paths",
                        ):
                            _append_raw(obj.get(key))
                        for nested_key in ("data", "result", "export"):
                            nested = obj.get(nested_key)
                            if isinstance(nested, dict):
                                _scan_report_dict(nested)

                    if isinstance(out_obj, dict):
                        _scan_report_dict(out_obj)
                        tr = out_obj.get("tool_results")
                        if isinstance(tr, list):
                            for row in tr:
                                if isinstance(row, dict):
                                    _scan_report_dict(row)
                    for p in fallback_changed or []:
                        s = str(p or "").strip()
                        if s:
                            raw_paths.append(s)
                    seen = set()
                    out: List[Path] = []
                    for raw in raw_paths:
                        if raw in seen:
                            continue
                        seen.add(raw)
                        fp = _resolve_existing_file(raw)
                        if fp is not None and fp not in out:
                            out.append(fp)
                    return out

                def _collect_result_files_any(fallback_changed: List[str], *reports: Any) -> List[Path]:
                    seen: List[Path] = []
                    for report in reports:
                        if not isinstance(report, dict):
                            continue
                        for fp in _collect_result_files(report, fallback_changed):
                            if fp not in seen:
                                seen.append(fp)
                    return seen

                def _report_has_file_hints(*reports: Any) -> bool:
                    def _scan(obj: Any) -> bool:
                        if isinstance(obj, dict):
                            for key in (
                                "file",
                                "path",
                                "download_path",
                                "workflow_file",
                                "workflow_json_file",
                                "last_workflow_file",
                                "workflow_files",
                                "files",
                                "bundle_files",
                                "readme_file",
                                "archive_name",
                            ):
                                value = obj.get(key)
                                if isinstance(value, str) and value.strip():
                                    return True
                                if isinstance(value, list) and any(str(v or "").strip() for v in value):
                                    return True
                            if isinstance(obj.get("tool_results"), list):
                                for row in obj.get("tool_results") or []:
                                    if _scan(row):
                                        return True
                            for nested_key in ("data", "result", "export"):
                                if _scan(obj.get(nested_key)):
                                    return True
                        elif isinstance(obj, list):
                            for item in obj:
                                if _scan(item):
                                    return True
                        return False

                    for report in reports:
                        if _scan(report):
                            return True
                    return False

                def _stage_file_for_download(src: Path) -> Optional[Dict[str, Any]]:
                    try:
                        up = _uploads_dir_path()
                        name = _unique_upload_name(src.name)
                        dst = up / name
                        shutil.copy2(str(src), str(dst))
                        return {
                            "name": src.name,
                            "staged_name": name,
                            "path": str(src),
                            "download_url": f"/uploads/{name}",
                            "size_bytes": int(dst.stat().st_size),
                        }
                    except Exception:
                        return None

                _publish_run_line(
                    "[agent_flow] workflow core settings: "
                    f"agent_workflow_member_max_tokens={settings.get('agent_workflow_member_max_tokens', '')}"
                )
                try:
                    fv_warn = ",".join(version_diag.get("warnings") or []) if isinstance(version_diag, dict) else ""
                    _publish_run_line(
                        "[agent_flow] flow version: "
                        f"active={version_diag.get('active_flow','') if isinstance(version_diag, dict) else ''} "
                        f"runtime_hash={version_diag.get('runtime_hash','') if isinstance(version_diag, dict) else ''} "
                        f"project_hash={version_diag.get('project_hash','') if isinstance(version_diag, dict) else ''} "
                        f"default_hash={version_diag.get('default_hash','') if isinstance(version_diag, dict) else ''} "
                        f"warnings={fv_warn or 'none'}"
                    )
                except Exception:
                    pass
                try:
                    incoming_rps = ext.get("router_plugin_settings") if isinstance(ext.get("router_plugin_settings"), dict) else {}
                    incoming_aw = incoming_rps.get("agent_workflow_member") if isinstance(incoming_rps.get("agent_workflow_member"), dict) else {}
                    _publish_run_line(
                        "[agent_flow] workflow request router settings: "
                        f"agent_workflow_member_max_tokens={incoming_aw.get('agent_workflow_member_max_tokens', '')}"
                    )
                except Exception:
                    pass
                if "agent_workflow_member_max_tokens" not in settings:
                    _publish_run_line(
                        "[agent_flow] workflow core settings warning: "
                        "agent_workflow_member_max_tokens missing from inherited app settings; node fallback defaults may apply"
                    )

                def _workflow_int_setting(name: str, fallback: int) -> int:
                    raw = settings.get(name)
                    if raw is None:
                        return fallback
                    try:
                        if isinstance(raw, str) and not str(raw).strip():
                            return fallback
                        value = int(raw)
                    except Exception:
                        return fallback
                    return value if value >= 0 else fallback

                def _workflow_float_setting(name: str, fallback: float) -> float:
                    raw = settings.get(name)
                    if raw is None:
                        return fallback
                    try:
                        if isinstance(raw, str) and not str(raw).strip():
                            return fallback
                        value = float(raw)
                    except Exception:
                        return fallback
                    return value if value >= 0 else fallback

                def _workflow_bool_setting(name: str, fallback: bool = False) -> bool:
                    raw = settings.get(name)
                    if isinstance(raw, bool):
                        return raw
                    if isinstance(raw, (int, float)):
                        return raw != 0
                    if isinstance(raw, str):
                        sval = str(raw).strip().lower()
                        if not sval:
                            return fallback
                        if sval in {"1", "true", "yes", "on"}:
                            return True
                        if sval in {"0", "false", "no", "off"}:
                            return False
                    return fallback

                workflow_loop_max_default = _workflow_int_setting("agent_flow_loop_max_passes", 16)
                workflow_force_loop_max = _workflow_bool_setting("agent_flow_force_loop_max_passes", False)
                workflow_request_timeout_s = _workflow_float_setting("agent_flow_request_timeout_s", 45.0)

                def _format_loop_cap(value: int) -> str:
                    return "unlimited" if int(value) <= 0 else str(int(value))

                enabled_plugins = ext.get("agent_flow_enabled_plugins")
                if not isinstance(enabled_plugins, list):
                    enabled_plugins = []
                enabled_plugins = [str(x or "").strip() for x in enabled_plugins if str(x or "").strip()]

                idx = 0
                while idx < len(steps):
                    step = steps[idx]
                    prev_step_report = dict(last_step_report) if isinstance(last_step_report, dict) else None
                    prev_step_report_with_tools = dict(last_step_report_with_tools) if isinstance(last_step_report_with_tools, dict) else None
                    if _is_canceled():
                        _mark_canceled()
                        break
                    if not state.get("running"):
                        break
                    if not _wait_if_paused(idx):
                        break
                    state["step_index"] = idx
                    state["status"] = f"Running {idx + 1}/{len(steps)}"
                    state["paused"] = False
                    state["pause_requested"] = False
                    state["steps"][idx]["state"] = "running"
                    _agent_flow_set_state(pid, sid, state)
                    _publish_flow_status({})

                    delay_ms = int(step.get("delay_ms") or 0)
                    if delay_ms:
                        time.sleep(delay_ms / 1000.0)
                    if _is_canceled():
                        _mark_canceled()
                        break
                    if not _wait_if_paused(idx):
                        break

                    msg_id = secrets.token_hex(12)
                    label = step.get("label") or step.get("node_id") or ""
                    plugin_id = str(step.get("plugin_id") or "chat")
                    internal_runtime_plugins = {"agent_flow_subflow", "agent_flow_fan_in_internal"}
                    if (
                        enabled_plugins
                        and plugin_id not in {"", "chat", "main", "default"}
                        and plugin_id not in internal_runtime_plugins
                        and plugin_id not in enabled_plugins
                    ):
                        _publish_step_stream(f"[agent_flow] {label}: skipped; plugin '{plugin_id}' is disabled for this session")
                        state["steps"][idx]["state"] = "error"
                        state["steps"][idx]["output"] = f"plugin_disabled:{plugin_id}"
                        _agent_flow_set_state(pid, sid, state)
                        _publish_flow_status({})
                        continue
                    stream_last_line = {"text": ""}
                    stream_last_ts = {"v": 0.0}

                    def _publish_step_stream(text_line: str) -> None:
                        t = str(text_line or "").strip()
                        if not t:
                            return
                        now = time.time()
                        if t == stream_last_line["text"] and (now - float(stream_last_ts["v"] or 0.0)) < 1.25:
                            return
                        stream_last_line["text"] = t
                        stream_last_ts["v"] = now
                        _publish_run_line(t)

                    def _emit_status(data: Dict[str, Any]) -> None:
                        payload = dict(data or {})
                        payload["msg_id"] = msg_id
                        payload["flow_run_id"] = run_id
                        payload["flow_step_index"] = idx
                        payload["flow_step_total"] = len(steps)
                        payload["flow_node_label"] = label
                        try:
                            hub.publish(pid, sid, event="diag", data=payload)
                        except Exception:
                            pass
                        member_stream = str(payload.get("member_stream") or "").strip()
                        if member_stream:
                            _publish_step_stream(f"[agent_flow] {label}: {member_stream}")
                        member_model_response = payload.get("member_model_response")
                        if isinstance(member_model_response, dict):
                            mt = str(member_model_response.get("text") or "").strip()
                            if mt:
                                lines = mt.splitlines()
                                for ln in lines[:3]:
                                    lnv = str(ln or "").strip()
                                    if lnv:
                                        _publish_step_stream(f"[agent_flow] {label}: model: {lnv}")
                                if bool(member_model_response.get("truncated")) or len(lines) > 3:
                                    _publish_step_stream(f"[agent_flow] {label}: model: [truncated]")
                        member_model_stream = payload.get("member_model_stream")
                        if isinstance(member_model_stream, dict):
                            ms = str(member_model_stream.get("text") or "")
                            if ms:
                                _publish_run_token(ms)
                        member_analysis = payload.get("member_analysis")
                        if isinstance(member_analysis, dict):
                            a_plan = str(member_analysis.get("plan") or "").strip()
                            a_analysis = str(member_analysis.get("analysis") or "").strip()
                            a_response = str(member_analysis.get("response") or "").strip()
                            a_summary = str(member_analysis.get("summary") or "").strip()
                            a_bugs = member_analysis.get("bugs") if isinstance(member_analysis.get("bugs"), list) else []
                            a_fixes = member_analysis.get("fixes") if isinstance(member_analysis.get("fixes"), list) else []
                            a_actions = member_analysis.get("actions") if isinstance(member_analysis.get("actions"), list) else []
                            if a_plan:
                                _publish_step_stream(f"[agent_flow] {label}: plan: {a_plan}")
                            if a_analysis:
                                _publish_step_stream(f"[agent_flow] {label}: analysis: {a_analysis}")
                            if a_response:
                                _publish_step_stream(f"[agent_flow] {label}: response: {a_response}")
                            if a_summary:
                                _publish_step_stream(f"[agent_flow] {label}: analysis: {a_summary}")
                            for b in a_bugs[:6]:
                                bv = str(b or "").strip()
                                if bv:
                                    _publish_step_stream(f"[agent_flow] {label}: bug: {bv}")
                            for f in a_fixes[:6]:
                                fv = str(f or "").strip()
                                if fv:
                                    _publish_step_stream(f"[agent_flow] {label}: fix: {fv}")
                            for act in a_actions[:5]:
                                a = str(act or "").strip()
                                if a:
                                    _publish_step_stream(f"[agent_flow] {label}: analysis action: {a}")
                        member_skill_calls = payload.get("member_skill_calls")
                        if isinstance(member_skill_calls, list):
                            for row in member_skill_calls[:8]:
                                if not isinstance(row, dict):
                                    continue
                                s_name = str(row.get("skill") or "").strip() or "unknown"
                                s_reason = str(row.get("reason") or "").strip()
                                if s_reason:
                                    _publish_step_stream(f"[agent_flow] {label}: skill call: {s_name} | reason: {s_reason}")
                                else:
                                    _publish_step_stream(f"[agent_flow] {label}: skill call: {s_name}")
                        member_handoff = payload.get("member_handoff")
                        if isinstance(member_handoff, dict):
                            h_to = str(member_handoff.get("to") or "").strip()
                            if h_to:
                                _publish_step_stream(f"[agent_flow] {label}: handoff detail: {h_to}")
                        member_tool_results = payload.get("member_tool_results")
                        if isinstance(member_tool_results, list):
                            for tr in member_tool_results[:8]:
                                if not isinstance(tr, dict):
                                    continue
                                t_skill = str(tr.get("skill") or "").strip()
                                t_ok = bool(tr.get("ok"))
                                t_warn = tr.get("warnings") if isinstance(tr.get("warnings"), list) else []
                                t_data = tr.get("data") if isinstance(tr.get("data"), dict) else {}
                                if t_skill:
                                    _publish_step_stream(f"[agent_flow] {label}: skill result: {t_skill} => {'ok' if t_ok else 'failed'}")
                                changed = t_data.get("changed_files") if isinstance(t_data, dict) and isinstance(t_data.get("changed_files"), list) else []
                                if changed:
                                    for cf in changed[:6]:
                                        cfv = str(cf or "").strip()
                                        if cfv:
                                            _publish_step_stream(f"[agent_flow] {label}: changed file: {cfv}")
                                requested_paths = t_data.get("requested_paths") if isinstance(t_data, dict) and isinstance(t_data.get("requested_paths"), list) else []
                                final_paths = t_data.get("final_paths") if isinstance(t_data, dict) and isinstance(t_data.get("final_paths"), list) else []
                                rewritten = t_data.get("rewritten_paths") if isinstance(t_data, dict) and isinstance(t_data.get("rewritten_paths"), list) else []
                                if requested_paths:
                                    for rp in requested_paths[:3]:
                                        rpv = str(rp or "").strip()
                                        if rpv:
                                            _publish_step_stream(f"[agent_flow] {label}: requested path: {rpv}")
                                if final_paths:
                                    for fp in final_paths[:3]:
                                        fpv = str(fp or "").strip()
                                        if fpv:
                                            _publish_step_stream(f"[agent_flow] {label}: final path: {fpv}")
                                if rewritten:
                                    for rw in rewritten[:3]:
                                        if not isinstance(rw, dict):
                                            continue
                                        req_p = str(rw.get("requested") or "").strip()
                                        fin_p = str(rw.get("final") or "").strip()
                                        if req_p and fin_p:
                                            _publish_step_stream(f"[agent_flow] {label}: rewritten path: {req_p} -> {fin_p}")
                                path_v = str(t_data.get("path") or "").strip() if isinstance(t_data, dict) else ""
                                if path_v:
                                    _publish_step_stream(f"[agent_flow] {label}: path: {path_v}")
                                errors = t_data.get("errors") if isinstance(t_data, dict) and isinstance(t_data.get("errors"), list) else []
                                if errors:
                                    for ev in errors[:5]:
                                        evs = str(ev or "").strip()
                                        if evs:
                                            _publish_step_stream(f"[agent_flow] {label}: skill error: {evs}")
                                op_count = t_data.get("op_count") if isinstance(t_data, dict) else None
                                if isinstance(op_count, int) and op_count > 0:
                                    _publish_step_stream(f"[agent_flow] {label}: skill op_count: {op_count}")
                                for w in t_warn[:3]:
                                    wv = str(w or "").strip()
                                    if wv:
                                        _publish_step_stream(f"[agent_flow] {label}: skill warning: {wv}")

                    core.settings["__router_diag_cb"] = _emit_status
                    core.settings["__cancel_cb"] = _is_canceled
                    _publish_step_stream(f"Flow step {idx + 1}/{len(steps)}: {label}\nUsing \"{plugin_id}\" ...")

                    next_input = _build_step_input(
                        user_text,
                        idx=idx,
                        step=step,
                        last_output_text=last_output_text,
                        last_output_raw=last_output_raw,
                        last_step_report=last_step_report,
                        recent_changed_files=recent_changed_files,
                        steers=state.get("steers") if isinstance(state.get("steers"), list) else [],
                    )
                    messages = [{"role": "user", "content": next_input or ""}]
                    messages = _apply_system_prompt(messages, step.get("system_prompt") or "")
                    if idx == 0 and attachments:
                        messages[0]["meta"] = {"attachments": attachments}

                    step_ext = {"pid": pid, "sid": sid}
                    if str(last_output_text or "").strip():
                        step_ext["agent_flow_previous_output_text"] = str(last_output_text)
                    if str(last_output_raw or "").strip():
                        step_ext["agent_flow_previous_output_raw"] = str(last_output_raw)
                    if isinstance(last_step_report, dict):
                        step_ext["agent_flow_previous_step_report"] = dict(last_step_report)
                        tr_prev = last_step_report.get("tool_results")
                        if isinstance(tr_prev, list):
                            step_ext["agent_flow_previous_tool_results"] = list(tr_prev[:12])
                    if isinstance(last_step_report_with_tools, dict):
                        step_ext["agent_flow_previous_step_report_with_tools"] = dict(last_step_report_with_tools)
                    try:
                        # State keys that must always reflect the most recent node output.
                        force_refresh_state_keys = {
                            "current_request",
                            "current_request_text",
                            "remaining_requests",
                            "completed_requests",
                            "completed_count",
                            "created_count",
                            "failed_count",
                            "total_requests",
                            "has_current",
                            "has_more",
                            "tracker_state",
                            "subflow_parent_state",
                            "subflow_result_state",
                            "planned_requests",
                            "handoff",
                        }
                        promote_keys = {
                            "bundle_dir",
                            "workflow_file",
                            "flow_name",
                            "input_path",
                            "file_path",
                            "path",
                            "file",
                            "validated_request_text",
                            "execution_text",
                            "execution_files",
                            "execution_zip",
                            "result_mode",
                            "pid",
                            "target_type",
                            "missing_skill_specs",
                            "skill_files",
                            "bundle_files",
                            "test_requests",
                            "flow_ext",
                            "workflow_json",
                            "planned_requests",
                            "current_request",
                            "current_request_text",
                            "remaining_requests",
                            "completed_requests",
                            "completed_count",
                            "created_count",
                            "failed_count",
                            "total_requests",
                            "has_current",
                            "has_more",
                            "handoff",
                            "tracker_state",
                            "subflow_parent_state",
                            "subflow_result_state",
                            "text",
                        }
                        for report_obj in (last_step_report_with_tools, last_step_report):
                            if not isinstance(report_obj, dict):
                                continue
                            for pkey in promote_keys:
                                v = report_obj.get(pkey, None)
                                if v in (None, "", [], {}):
                                    continue
                                if pkey == "current_request":
                                    v = _coerce_single_request(v)
                                elif pkey == "tracker_state":
                                    v = _normalize_tracker_state(v)
                                if pkey in force_refresh_state_keys or pkey not in step_ext or step_ext.get(pkey) in (None, "", [], {}):
                                    # Keep queue/tracker state in sync with the current step report,
                                    # even when step_ext already had a previous non-empty value.
                                    step_ext[pkey] = v
                            tr_rows = report_obj.get("tool_results") if isinstance(report_obj.get("tool_results"), list) else []
                            for tr_row in tr_rows:
                                if not isinstance(tr_row, dict):
                                    continue
                                data_row = tr_row.get("data") if isinstance(tr_row.get("data"), dict) else {}
                                for pkey in promote_keys:
                                    v = None
                                    if pkey in data_row:
                                        v = data_row.get(pkey)
                                    elif pkey in tr_row:
                                        v = tr_row.get(pkey)
                                    if v in (None, "", [], {}):
                                        continue
                                    if pkey == "current_request":
                                        v = _coerce_single_request(v)
                                    elif pkey == "tracker_state":
                                        v = _normalize_tracker_state(v)
                                    if pkey in force_refresh_state_keys or pkey not in step_ext or step_ext.get(pkey) in (None, "", [], {}):
                                        # Keep queue/tracker state in sync with the latest tool result.
                                        step_ext[pkey] = v
                    except Exception:
                        pass
                    # Carry top-level router settings into each node step so tools can resolve
                    # target repo root and other shared plugin settings.
                    if isinstance(ext.get("router_plugin_settings"), dict):
                        step_ext["router_plugin_settings"] = dict(ext.get("router_plugin_settings") or {})
                    if str(ext.get("agent_workflow_target_repo_root") or "").strip():
                        step_ext["agent_workflow_target_repo_root"] = str(ext.get("agent_workflow_target_repo_root") or "").strip()
                    if str(ext.get("target_repo_root") or "").strip():
                        step_ext["target_repo_root"] = str(ext.get("target_repo_root") or "").strip()
                    base_url = str(ext.get("base_url") or ext.get("server_url") or "").strip()
                    if base_url:
                        step_ext["base_url"] = base_url
                    if idx == 0 and attachments:
                        step_ext["attachments"] = attachments
                    if recent_changed_files:
                        step_ext["agent_flow_changed_files"] = list(recent_changed_files[:40])
                    for control_key in (
                        "validation_profile",
                        "min_requests",
                        "max_requests",
                        "max_request_wait_s",
                        "poll_interval_s",
                        "final_step_grace_s",
                        "agent_flow_max_steps",
                        "clarify_default",
                        "agent_flow_autobuild_sandbox_profile",
                        "agent_flow_autobuild_lightweight_max_requests",
                        "agent_flow_autobuild_lightweight_wait_s",
                        "agent_flow_autobuild_lightweight_final_grace_s",
                        "agent_flow_autobuild_independent_max_requests",
                        "agent_flow_autobuild_independent_wait_s",
                        "agent_flow_autobuild_independent_final_grace_s",
                    ):
                        control_value = ext.get(control_key)
                        if control_value not in (None, "", [], {}):
                            step_ext[control_key] = control_value
                    step_ext["agent_flow_loop_max_passes"] = workflow_loop_max_default
                    step_ext["agent_flow_force_loop_max_passes"] = workflow_force_loop_max
                    step_ext["agent_flow_request_timeout_s"] = workflow_request_timeout_s
                    step_ext["request_timeout_s"] = workflow_request_timeout_s
                    if step_ext.get("max_request_wait_s") in (None, "", [], {}):
                        step_ext["max_request_wait_s"] = workflow_request_timeout_s
                    step_ext["agent_flow_node_id"] = str(step.get("node_id") or "")
                    step_ext["agent_flow_node"] = dict(step or {})
                    plugin_settings = dict(step.get("plugin_settings") or {})
                    if plugin_id == "image_reader" and attachments:
                        plugin_settings.setdefault("image_reader_image_source", "url")
                    if plugin_settings and plugin_id:
                        step_ext[f"{plugin_id}_settings"] = dict(plugin_settings)
                        # Preserve full session router plugin settings (including agent_workflow target_repo_root)
                        # and only overlay current node plugin settings.
                        existing_rps = step_ext.get("router_plugin_settings")
                        if not isinstance(existing_rps, dict):
                            existing_rps = {}
                        merged_rps = dict(existing_rps)
                        prior_plugin_settings = merged_rps.get(plugin_id)
                        merged_plugin_settings = (
                            dict(prior_plugin_settings)
                            if isinstance(prior_plugin_settings, dict)
                            else {}
                        )
                        merged_plugin_settings.update(dict(plugin_settings))
                        merged_rps[plugin_id] = merged_plugin_settings
                        step_ext["router_plugin_settings"] = merged_rps
                    if plugin_id == "agent_workflow_member":
                        existing_rps = step_ext.get("router_plugin_settings")
                        if not isinstance(existing_rps, dict):
                            existing_rps = {}
                        merged_rps = dict(existing_rps)
                        prior_aw = merged_rps.get("agent_workflow_member")
                        merged_aw = dict(prior_aw) if isinstance(prior_aw, dict) else {}
                        if "agent_workflow_member_max_tokens" in settings and "agent_workflow_member_max_tokens" not in merged_aw:
                            merged_aw["agent_workflow_member_max_tokens"] = settings.get("agent_workflow_member_max_tokens")
                        if "agent_workflow_member_temperature" in settings and "agent_workflow_member_temperature" not in merged_aw:
                            merged_aw["agent_workflow_member_temperature"] = settings.get("agent_workflow_member_temperature")
                        merged_rps["agent_workflow_member"] = merged_aw
                        step_ext["router_plugin_settings"] = merged_rps
                        direct_aw = step_ext.get("agent_workflow_member_settings")
                        merged_direct_aw = dict(direct_aw) if isinstance(direct_aw, dict) else {}
                        for key in ("agent_workflow_member_max_tokens", "agent_workflow_member_temperature"):
                            if key in merged_aw and key not in merged_direct_aw:
                                merged_direct_aw[key] = merged_aw.get(key)
                        if merged_direct_aw:
                            step_ext["agent_workflow_member_settings"] = merged_direct_aw

                    def _runtime_prior_step_value(name: str) -> Any:
                        for src in (
                            last_step_report_with_tools if isinstance(last_step_report_with_tools, dict) else {},
                            last_step_report if isinstance(last_step_report, dict) else {},
                        ):
                            val = _resolve_path_from_sources(name, src)
                            if val not in (None, "", [], {}):
                                return val
                            tool_rows = src.get("tool_results") if isinstance(src.get("tool_results"), list) else []
                            for row in reversed(tool_rows):
                                if not isinstance(row, dict):
                                    continue
                                data0 = row.get("data") if isinstance(row.get("data"), dict) else {}
                                val = _resolve_path_from_sources(name, data0, row)
                                if val not in (None, "", [], {}):
                                    return val
                        return None

                    def _resolve_runtime_subflow_name(ps: Dict[str, Any], step_input_now: Dict[str, Any]) -> str:
                        mapped = ps.get("subflow_name_map") if isinstance(ps.get("subflow_name_map"), dict) else {}
                        source_path = str(ps.get("subflow_name_source") or "").strip()
                        if mapped and source_path:
                            selected = _resolve_path_from_sources(
                                source_path,
                                step_input_now,
                                step_ext,
                                last_step_report_with_tools if isinstance(last_step_report_with_tools, dict) else {},
                                last_step_report if isinstance(last_step_report, dict) else {},
                                ext if isinstance(ext, dict) else {},
                            )
                            selected_key = str(selected or "").strip()
                            if selected_key:
                                mapped_name = str(mapped.get(selected_key) or mapped.get(selected_key.lower()) or "").strip()
                                if mapped_name:
                                    return mapped_name
                        return str(
                            ps.get("subflow_name")
                            or ps.get("flow_name")
                            or ""
                        ).strip()

                    def _resolve_runtime_subflow_workflow_id(ps: Dict[str, Any]) -> str:
                        return str(
                            ps.get("subflow_workflow_id")
                            or ps.get("workflow_id")
                            or ""
                        ).strip()

                    runtime_parent_id_base = str(step.get("node_id") or f"step::{idx}").strip()
                    runtime_parent_id = f"{runtime_parent_id_base}::exec::{idx}"
                    if plugin_id.lower() in {"agent_flow_subflow", "flow_ref", "subflow"} or str(plugin_settings.get("node_type") or "").strip().lower() == "fan_out_node":
                        step_input_now = step.get("input") if isinstance(step.get("input"), dict) else {}
                        subflow_name_ref = _resolve_runtime_subflow_name(plugin_settings, step_input_now)
                        subflow_workflow_id = _resolve_runtime_subflow_workflow_id(plugin_settings)
                        prior_current_req = _coerce_single_request(
                            _resolve_path_from_sources(
                                "current_request",
                                step_input_now,
                                step_ext,
                                last_step_report_with_tools if isinstance(last_step_report_with_tools, dict) else {},
                                last_step_report if isinstance(last_step_report, dict) else {},
                            )
                            or _runtime_prior_step_value("current_request")
                        )
                        prior_current_text = str(
                            _resolve_path_from_sources(
                                "current_request_text",
                                step_input_now,
                                step_ext,
                                last_step_report_with_tools if isinstance(last_step_report_with_tools, dict) else {},
                                last_step_report if isinstance(last_step_report, dict) else {},
                            )
                            or _runtime_prior_step_value("current_request_text")
                            or (prior_current_req.get("request_text") if isinstance(prior_current_req, dict) else "")
                            or (prior_current_req.get("request") if isinstance(prior_current_req, dict) else "")
                            or ""
                        ).strip()
                        current_req_ext = prior_current_req
                        default_input_text = str(
                            step_input_now.get("iteration_text")
                            or prior_current_text
                            or (current_req_ext.get("request") if isinstance(current_req_ext, dict) else "")
                            or last_output_text
                            or user_text
                            or ""
                        ).strip()
                        if default_input_text.lower().startswith("interaction response:"):
                            default_input_text = str(
                                prior_current_text
                                or (current_req_ext.get("request") if isinstance(current_req_ext, dict) else "")
                                or user_text
                                or ""
                            ).strip()
                        branch_items = [(
                            step_input_now.get("iteration_item")
                            or current_req_ext
                            or prior_current_req
                            or step_ext.get("planned_request")
                        )]
                        normalized_branch_items: List[Any] = []
                        for raw_item in branch_items:
                            if isinstance(raw_item, list):
                                normalized_branch_items.extend(raw_item[:1] if raw_item else [])
                            else:
                                normalized_branch_items.append(raw_item)
                        branch_items = normalized_branch_items
                        if len(branch_items) == 1 and isinstance(branch_items[0], (list, tuple)):
                            coerced = _coerce_single_request(branch_items[0])
                            branch_items = [coerced] if coerced else []
                        if str(plugin_settings.get("node_type") or "").strip().lower() == "fan_out_node":
                            branch_items = _resolve_iteration_items(
                                ps=plugin_settings,
                                step_ext=step_ext,
                                last_step_report=last_step_report,
                                last_output_raw=last_output_raw,
                                last_output_text=last_output_text,
                            )
                        branch_items = [x for x in branch_items if x not in (None, "", [])]
                        if not branch_items:
                            branch_items = [default_input_text or user_text]
                        branch_preview = _iteration_item_text(branch_items[0], default_input_text or user_text) if branch_items else ""
                        branch_preview = re.sub(r"\s+", " ", str(branch_preview or "").strip())
                        if len(branch_preview) > 140:
                            branch_preview = branch_preview[:137] + "..."
                        injected_steps = _build_runtime_subflow_steps(
                            step,
                            parent_runtime_id=runtime_parent_id,
                            subflow_name_ref=subflow_name_ref,
                            subflow_workflow_id=subflow_workflow_id,
                            branch_items=branch_items,
                            default_input_text=default_input_text or user_text,
                        )
                        if not injected_steps:
                            state["steps"][idx]["state"] = "done"
                            state["steps"][idx]["output"] = "subflow unavailable"
                            last_step_report = {
                                "step": idx + 1,
                                "total": len(steps),
                                "role": str(label or ""),
                                "plan": "",
                                "analysis": "",
                                "response": f"Subflow {subflow_name_ref or 'unknown'} was not available.",
                                "did": f"Subflow {subflow_name_ref or 'unknown'} was not available.",
                                "actions": [],
                                "bugs": [f"subflow_not_found:{subflow_name_ref or 'unknown'}"],
                                "fixes": [],
                                "skills_invoked": [],
                                "handoff": "",
                                "tool_results": [],
                            }
                            _agent_flow_set_state(pid, sid, state)
                            _publish_flow_status({})
                            idx += 1
                            continue
                        for offset, injected in enumerate(injected_steps, start=1):
                            steps.insert(idx + offset, injected)
                            state["steps"].insert(idx + offset, {"label": injected.get("label") or injected.get("node_id"), "state": "queued"})
                        state["steps"][idx]["state"] = "done"
                        state["steps"][idx]["output"] = (
                            f"expanded {len(branch_items)} item(s)"
                            + (f": {branch_preview}" if branch_preview else "")
                        )
                        state["steps_total"] = len(steps)
                        last_step_report = {
                            "step": idx + 1,
                            "total": len(steps),
                            "role": str(label or ""),
                            "plan": "",
                            "analysis": f"Expanded runtime subflow {subflow_name_ref or ''} into executable child steps.",
                            "response": f"Expanded {len(branch_items)} iteration item(s) into subflow {subflow_name_ref or ''}.",
                            "did": f"Expanded {len(branch_items)} iteration item(s) into subflow {subflow_name_ref or ''}.",
                            "actions": [f"subflow_expand:{subflow_name_ref}:{len(branch_items)}"],
                            "bugs": [],
                            "fixes": [],
                            "skills_invoked": [],
                            "handoff": f"Runtime subflow {subflow_name_ref} expanded.",
                            "tool_results": [],
                        }
                        last_output_text = str(last_step_report.get("response") or "")
                        try:
                            last_output_raw = json.dumps(last_step_report, ensure_ascii=False)
                        except Exception:
                            last_output_raw = last_output_text
                        _agent_flow_set_state(pid, sid, state)
                        _publish_flow_status({})
                        _publish_step_stream(
                            f"[agent_flow] {label}: runtime subflow expanded -> {subflow_name_ref} ({len(branch_items)} item(s))"
                            + (f" | request={branch_preview}" if branch_preview else "")
                        )
                        idx += 1
                        continue

                    precomputed_out = None
                    if plugin_id.lower() == "agent_flow_fan_in_internal" or str(plugin_settings.get("node_type") or "").strip().lower() == "fan_in_node":
                        fanin_parent_id = str(plugin_settings.get("fanout_parent_id") or runtime_parent_id).strip()
                        aggregated = _aggregate_fanout_report(fanin_parent_id)
                        precomputed_out = {
                            "ok": True,
                            "flow_step_report": aggregated,
                            "fan_in_aggregated": True,
                            "fanout_parent_id": fanin_parent_id,
                        }
                    if precomputed_out is None:
                        ps_pre = step.get("plugin_settings") if isinstance(step.get("plugin_settings"), dict) else {}
                        node_type_pre = str(ps_pre.get("node_type") or "").strip().lower()
                        allowed_pre = ps_pre.get("action_skills") if isinstance(ps_pre.get("action_skills"), list) else []
                        allowed_result_pre = [
                            str(skill or "").strip()
                            for skill in allowed_pre
                            if str(skill or "").strip().lower().startswith("result.")
                        ]
                        if (
                            str(plugin_id or "").strip().lower() == "agent_workflow_member"
                            and node_type_pre == "output_node"
                            and allowed_result_pre
                            and len(allowed_result_pre) == len([str(skill or "").strip() for skill in allowed_pre if str(skill or "").strip()])
                        ):
                            aw_call_pre = settings.get("__agent_workflow_tool_call")
                            if callable(aw_call_pre):
                                tool_rows_pre: List[Dict[str, Any]] = []
                                summary_text_pre = _humanize_result_fallback(
                                    str((last_step_report or {}).get("response") or last_output_text or "").strip(),
                                    last_step_report if isinstance(last_step_report, dict) else None,
                                )
                                file_seed_pre = [
                                    str(p)
                                    for p in _collect_result_files_any(
                                        recent_changed_files,
                                        final_result_out,
                                        last_step_report,
                                        last_step_report_with_tools,
                                        prev_step_report,
                                        prev_step_report_with_tools,
                                    )
                                ]
                                archive_name_pre = "agent_flow_result_bundle.zip"
                                flow_name_hint_pre = str(
                                    _coalesce_param_value(
                                        step_ext.get("flow_name"),
                                        ext.get("flow_name") if isinstance(ext, dict) else None,
                                        (last_step_report or {}).get("flow_name") if isinstance(last_step_report, dict) else None,
                                        (last_step_report or {}).get("last_flow_name") if isinstance(last_step_report, dict) else None,
                                    )
                                    or ""
                                ).strip()
                                if flow_name_hint_pre:
                                    archive_name_pre = f"{flow_name_hint_pre}.zip"
                                for skill_id_pre in allowed_result_pre:
                                    sid_pre = str(skill_id_pre or "").strip().lower()
                                    params_pre: Dict[str, Any] = {"user_request": user_text}
                                    if sid_pre == "result.text":
                                        params_pre.update({
                                            "text": summary_text_pre,
                                            "summary": str((last_step_report or {}).get("summary") or "").strip() if isinstance(last_step_report, dict) else "",
                                            "analysis": str((last_step_report or {}).get("analysis") or "").strip() if isinstance(last_step_report, dict) else "",
                                            "response": str((last_step_report or {}).get("response") or "").strip() if isinstance(last_step_report, dict) else "",
                                            "actions": list((last_step_report or {}).get("actions") or []) if isinstance(last_step_report, dict) else [],
                                        })
                                    elif sid_pre in {"result.file", "result.files"}:
                                        if file_seed_pre:
                                            params_pre["files"] = list(file_seed_pre)
                                    elif sid_pre == "result.zip":
                                        if file_seed_pre:
                                            params_pre["files"] = list(file_seed_pre)
                                            params_pre["archive_name"] = archive_name_pre
                                    raw_pre = aw_call_pre(skill_id_pre, {"app": app, "pid": pid, "sid": sid, "settings": settings}, params_pre)
                                    if not isinstance(raw_pre, dict):
                                        raw_pre = {"ok": False, "warnings": ["result_output_invalid_result"], "data": {"result": raw_pre}}
                                    tr_pre = {
                                        "skill": skill_id_pre,
                                        "ok": bool(raw_pre.get("ok")) if "ok" in raw_pre else True,
                                        "warnings": list(raw_pre.get("warnings") or []) if isinstance(raw_pre.get("warnings"), list) else [],
                                        "data": dict(raw_pre.get("data") or {}) if isinstance(raw_pre.get("data"), dict) else {},
                                    }
                                    for k_pre, v_pre in raw_pre.items():
                                        if k_pre in {"ok", "warnings", "data", "error"}:
                                            continue
                                        if k_pre not in tr_pre["data"]:
                                            tr_pre["data"][k_pre] = v_pre
                                    tool_rows_pre.append(tr_pre)
                                    _publish_step_stream(f"[agent_flow] {label}: direct output_node executed -> {skill_id_pre}")
                                precomputed_out = {
                                    "ok": any(bool(row.get("ok")) for row in tool_rows_pre) if tool_rows_pre else True,
                                    "tool_results": tool_rows_pre,
                                    "output_node_direct_executed": True,
                                    "output_node_direct_skills": list(allowed_result_pre),
                                }

                    step_req = SimpleNamespace(
                        messages=messages,
                        ext=step_ext,
                        route_id=plugin_id,
                        router_enabled_plugins=[plugin_id],
                        model="",
                        backend_type="auto",
                    )

                    if plugin_id == "agent_workflow_member":
                        try:
                            rps0 = step_ext.get("router_plugin_settings") if isinstance(step_ext.get("router_plugin_settings"), dict) else {}
                            aw0 = rps0.get("agent_workflow_member") if isinstance(rps0.get("agent_workflow_member"), dict) else {}
                            awd0 = step_ext.get("agent_workflow_member_settings") if isinstance(step_ext.get("agent_workflow_member_settings"), dict) else {}
                            _publish_step_stream(
                                f"[agent_flow] {label}: step router settings: "
                                f"agent_workflow_member_max_tokens={aw0.get('agent_workflow_member_max_tokens', '')} "
                                f"direct={awd0.get('agent_workflow_member_max_tokens', '')}"
                            )
                        except Exception:
                            pass

                    def _prior_value_for_param_local(name: str) -> Any:
                        pname = str(name or "").strip()
                        if not pname:
                            return None
                        for report_key in ("agent_flow_previous_step_report_with_tools", "agent_flow_previous_step_report"):
                            report_obj = step_ext.get(report_key)
                            if not isinstance(report_obj, dict):
                                continue
                            if pname in report_obj and report_obj.get(pname) not in (None, "", [], {}):
                                return report_obj.get(pname)
                            tr_rows = report_obj.get("tool_results") if isinstance(report_obj.get("tool_results"), list) else []
                            for tr_row in tr_rows:
                                if not isinstance(tr_row, dict):
                                    continue
                                data_row = tr_row.get("data") if isinstance(tr_row.get("data"), dict) else {}
                                if pname in data_row:
                                    return data_row.get(pname)
                                if pname in tr_row:
                                    return tr_row.get(pname)
                        for raw_key in ("agent_flow_previous_output_raw", "agent_flow_previous_output_text"):
                            raw_val = str(step_ext.get(raw_key) or "").strip()
                            if not raw_val:
                                continue
                            parsed_prev = _extract_json_block_maybe(raw_val)
                            if isinstance(parsed_prev, dict):
                                if pname in parsed_prev:
                                    return parsed_prev.get(pname)
                                data_prev = parsed_prev.get("data") if isinstance(parsed_prev.get("data"), dict) else {}
                                if pname in data_prev:
                                    return data_prev.get(pname)
                        return None

                    def _coalesce_param_value(*values: Any) -> Any:
                        for value in values:
                            if value is None:
                                continue
                            if isinstance(value, str) and not value.strip():
                                continue
                            if isinstance(value, (list, dict)) and not value:
                                continue
                            return value
                        return None

                    request_seed_text = _request_seed_for_step(step, user_text)

                    def _direct_tool_node_out() -> Optional[Dict[str, Any]]:
                        ps_direct = step.get("plugin_settings") if isinstance(step.get("plugin_settings"), dict) else {}
                        ext_plugin_settings = step_ext.get(f"{plugin_id}_settings") if isinstance(step_ext.get(f"{plugin_id}_settings"), dict) else {}
                        ext_direct_settings = step_ext.get("agent_workflow_member_settings") if isinstance(step_ext.get("agent_workflow_member_settings"), dict) else {}
                        if ext_plugin_settings or ext_direct_settings:
                            merged_ext_ps: Dict[str, Any] = {}
                            merged_ext_ps.update(dict(ext_plugin_settings or {}))
                            merged_ext_ps.update(dict(ext_direct_settings or {}))
                            merged_ext_ps.update(dict(ps_direct or {}))
                            ps_direct = merged_ext_ps
                        if isinstance(plugin_settings, dict) and plugin_settings:
                            merged_ps_direct = dict(plugin_settings)
                            merged_ps_direct.update(dict(ps_direct or {}))
                            ps_direct = merged_ps_direct
                        if str(plugin_id or "").strip().lower() != "agent_workflow_member":
                            return None
                        raw_allowed_direct = ps_direct.get("action_skills")
                        allowed_direct = raw_allowed_direct if isinstance(raw_allowed_direct, list) else []
                        tc_direct = ps_direct.get("tool_config") if isinstance(ps_direct.get("tool_config"), dict) else {}
                        node_type_direct = str(ps_direct.get("node_type") or "").strip().lower()
                        tool_name = str(tc_direct.get("tool") or "").strip()
                        if not tool_name and len(allowed_direct) == 1:
                            tool_name = str(allowed_direct[0] or "").strip()
                        if node_type_direct != "tool_node" and not tool_name:
                            return None
                        allowed_names = {
                            str(x or "").strip().lower()
                            for x in (allowed_direct or [])
                            if str(x or "").strip()
                        }
                        if allowed_names and tool_name and tool_name.lower() not in allowed_names:
                            return {
                                "ok": False,
                                "tool_results": [
                                    {
                                        "skill": tool_name,
                                        "ok": False,
                                        "warnings": ["tool_node_skill_not_allowed"],
                                        "data": {"tool": tool_name, "allowed": sorted(allowed_names)},
                                    }
                                ],
                                "tool_node_direct_executed": True,
                                "tool_node_direct_skill": tool_name,
                                "tool_node_direct_params": {},
                            }
                        aw_call = settings.get("__agent_workflow_tool_call")
                        if not tool_name:
                            return {
                                "ok": False,
                                "tool_results": [
                                    {
                                        "skill": "",
                                        "ok": False,
                                        "warnings": ["tool_node_missing_configured_tool"],
                                        "data": {"allowed": sorted(allowed_names)},
                                    }
                                ],
                                "tool_node_direct_executed": True,
                                "tool_node_direct_skill": "",
                                "tool_node_direct_params": {},
                            }
                        if not callable(aw_call):
                            _publish_step_stream(f"[agent_flow] {label}: direct tool_node unavailable -> {tool_name}")
                            return {
                                "ok": False,
                                "tool_results": [
                                    {
                                        "skill": tool_name,
                                        "ok": False,
                                        "warnings": ["agent_workflow_tool_call_unavailable"],
                                        "data": {"tool": tool_name},
                                    }
                                ],
                                "tool_node_direct_executed": True,
                                "tool_node_direct_skill": tool_name,
                                "tool_node_direct_params": {},
                            }
                        merged_params: Dict[str, Any] = {}
                        cfg_params = tc_direct.get("params") if isinstance(tc_direct.get("params"), dict) else {}
                        fallback_params = tc_direct.get("fallback_params") if isinstance(tc_direct.get("fallback_params"), dict) else {}
                        merged_params.update(dict(cfg_params))
                        merged_params.update(dict(fallback_params))
                        params_from_input = tc_direct.get("params_from_input") if isinstance(tc_direct.get("params_from_input"), list) else []
                        prior_paths = _tool_result_paths(last_step_report)
                        user_file_hint = _extract_candidate_file_from_text(user_text)
                        if user_file_hint:
                            prior_paths.append(user_file_hint)
                        file_hint = str(prior_paths[0] if prior_paths else "").strip()
                        for pkey0 in params_from_input:
                            pkey = str(pkey0 or "").strip()
                            if not pkey:
                                continue
                            if pkey == "text" and tool_name == "result.text":
                                v = None
                                for alt_key in ("finalized_text", "execution_text", "response", "final_answer", "table_markdown", "markdown", "summary"):
                                    v = _coalesce_param_value(
                                        merged_params.get(alt_key),
                                        (step.get("input") if isinstance(step.get("input"), dict) else {}).get(alt_key),
                                        step_ext.get(alt_key),
                                        ext.get(alt_key),
                                    )
                                    if v in (None, "", [], {}):
                                        v = _prior_value_for_param_local(alt_key)
                                    if v not in (None, "", [], {}):
                                        break
                                if v in (None, "", [], {}):
                                    v = str(last_output_text or "").strip()
                                if v in (None, "", [], {}):
                                    v = _coalesce_param_value(
                                        merged_params.get("text"),
                                        (step.get("input") if isinstance(step.get("input"), dict) else {}).get("text"),
                                        step_ext.get("text"),
                                        ext.get("text"),
                                    )
                                if v in (None, "", [], {}):
                                    v = _prior_value_for_param_local(pkey)
                                if v is not None and str(v).strip():
                                    merged_params[pkey] = v
                                    continue
                            if pkey in {"current_request_text", "request_text", "user_request", "request", "prompt", "query"}:
                                merged_params[pkey] = request_seed_text
                                continue
                            if pkey == "text":
                                merged_params[pkey] = request_seed_text
                                continue
                            if (
                                pkey in merged_params
                                and str(merged_params.get(pkey) or "").strip()
                                and pkey not in {"current_request_text", "request_text", "user_request", "request", "text", "prompt", "query"}
                            ):
                                continue
                            v = _coalesce_param_value(
                                step_ext.get(pkey),
                                ext.get(pkey),
                                (step.get("input") if isinstance(step.get("input"), dict) else {}).get(pkey),
                            )
                            if v is None:
                                alias_key = {
                                    "last_bundle_dir": "bundle_dir",
                                    "last_workflow_file": "workflow_file",
                                    "last_flow_name": "flow_name",
                                }.get(pkey)
                                if alias_key:
                                    v = _coalesce_param_value(
                                        step_ext.get(alias_key),
                                        ext.get(alias_key),
                                        (step.get("input") if isinstance(step.get("input"), dict) else {}).get(alias_key),
                                    )
                            if v is None:
                                v = _prior_value_for_param_local(pkey)
                            if v is None and pkey in {"file", "path", "file_path", "input_path", "source_pdf_path"}:
                                v = file_hint
                            if v is not None and (not isinstance(v, str) or str(v).strip()):
                                merged_params[pkey] = v
                        try:
                            raw_res = aw_call(
                                tool_name,
                                {
                                    "app": app,
                                    "pid": pid,
                                    "sid": sid,
                                    "settings": settings,
                                    "ext": dict(step_ext) if isinstance(step_ext, dict) else {},
                                    "user_text": request_seed_text,
                                    "original_request": request_seed_text,
                                },
                                merged_params,
                            )
                        except Exception as exc:
                            _publish_step_stream(f"[agent_flow] {label}: direct tool_node failed -> {tool_name}: {type(exc).__name__}")
                            raw_res = {
                                "ok": False,
                                "warnings": ["tool_node_direct_exception", type(exc).__name__],
                                "data": {"error": str(exc), "tool": tool_name},
                            }
                        if not isinstance(raw_res, dict):
                            raw_res = {"ok": False, "warnings": ["tool_direct_invalid_result"], "data": {"result": raw_res}}
                        tr_row = {
                            "skill": tool_name,
                            "ok": bool(raw_res.get("ok")) if "ok" in raw_res else True,
                            "warnings": list(raw_res.get("warnings") or []) if isinstance(raw_res.get("warnings"), list) else [],
                            "data": dict(raw_res.get("data") or {}) if isinstance(raw_res.get("data"), dict) else {},
                        }
                        for k, v in raw_res.items():
                            if k in {"ok", "warnings", "data", "error"}:
                                continue
                            if k not in tr_row["data"]:
                                tr_row["data"][k] = v
                        _publish_step_stream(f"[agent_flow] {label}: direct tool_node executed -> {tool_name}")
                        route_text = _extract_text_from_route(raw_res)
                        route_out = {
                            "ok": tr_row["ok"],
                            "tool_results": [tr_row],
                            "tool_node_direct_executed": True,
                            "tool_node_direct_skill": tool_name,
                            "tool_node_direct_params": merged_params,
                        }
                        if route_text:
                            route_out["text"] = route_text
                        return route_out

                    if isinstance(precomputed_out, dict):
                        out = dict(precomputed_out)
                    else:
                        route = route_by_id.get(plugin_id)
                        if not route:
                            out = {"route_id": plugin_id, "ok": False, "error": "route_not_found"}
                        else:
                            try:
                                hub.publish(
                                    pid,
                                    sid,
                                    event="diag",
                                    data={
                                        "flow_step_index": idx,
                                        "flow_step_total": len(steps),
                                        "flow_node_label": label,
                                        "flow_node_plugin": plugin_id,
                                        "router_status": "node_start",
                                    },
                                )
                            except Exception:
                                pass
                            is_configured_tool_node = (
                                str(plugin_id or "").strip().lower() == "agent_workflow_member"
                                and (
                                    str((step.get("plugin_settings") if isinstance(step.get("plugin_settings"), dict) else {}).get("node_type") or "").strip().lower() == "tool_node"
                                    or bool(str((((step.get("plugin_settings") if isinstance(step.get("plugin_settings"), dict) else {}).get("tool_config") if isinstance((step.get("plugin_settings") if isinstance(step.get("plugin_settings"), dict) else {}).get("tool_config"), dict) else {}).get("tool") or "")).strip())
                                    or bool([str(x or "").strip() for x in (((step.get("plugin_settings") if isinstance(step.get("plugin_settings"), dict) else {}).get("action_skills")) if isinstance((step.get("plugin_settings") if isinstance(step.get("plugin_settings"), dict) else {}).get("action_skills"), list) else []) if str(x or "").strip()])
                                )
                            )
                            direct_out = None
                            direct_exception_text = ""
                            try:
                                direct_out = _direct_tool_node_out()
                            except Exception as exc:
                                direct_exception_text = f"{type(exc).__name__}: {exc}"
                                try:
                                    _publish_step_stream(f"[agent_flow] {label}: direct tool_node skipped by exception -> {type(exc).__name__}: {exc}")
                                except Exception:
                                    pass
                                direct_out = None
                            if isinstance(direct_out, dict):
                                out = direct_out
                            elif is_configured_tool_node:
                                out = {
                                    "ok": False,
                                    "tool_results": [
                                        {
                                            "skill": "",
                                            "ok": False,
                                            "warnings": ["tool_node_direct_execution_missing"],
                                            "data": {
                                                "node_label": str(label or ""),
                                                "plugin_id": str(plugin_id or ""),
                                                "node_type": str((plugin_settings or {}).get("node_type") or ""),
                                                "plugin_settings_keys": sorted([str(k) for k in (plugin_settings or {}).keys()]) if isinstance(plugin_settings, dict) else [],
                                                "exception": direct_exception_text,
                                            },
                                        }
                                    ],
                                    "tool_node_direct_executed": False,
                                }
                            else:
                                out = route.handle(step_req)
                        # Enforce per-node skill policy at flow runtime:
                        # when a node has no action_skills, discard any tool_results
                        # emitted by the member route to prevent unintended writes.
                            try:
                                ps_guard = step.get("plugin_settings") if isinstance(step.get("plugin_settings"), dict) else {}
                                allowed_now = ps_guard.get("action_skills") if isinstance(ps_guard.get("action_skills"), list) else None
                                node_type_guard = str(ps_guard.get("node_type") or "").strip().lower()
                                tc_guard = ps_guard.get("tool_config") if isinstance(ps_guard.get("tool_config"), dict) else {}
                                configured_tool = str(tc_guard.get("tool") or "").strip().lower()
                                if isinstance(out, dict) and isinstance(allowed_now, list) and len(allowed_now) == 0:
                                    tr_bad = out.get("tool_results")
                                    direct_configured_tool_ok = False
                                    if (
                                        node_type_guard == "tool_node"
                                        and configured_tool
                                        and isinstance(tr_bad, list)
                                        and tr_bad
                                    ):
                                        direct_configured_tool_ok = all(
                                            isinstance(row, dict)
                                            and str(row.get("skill") or "").strip().lower() == configured_tool
                                            for row in tr_bad
                                        )
                                    if isinstance(tr_bad, list) and tr_bad and not direct_configured_tool_ok:
                                        out["tool_results"] = []
                                        out["tool_results_blocked_by_flow_policy"] = True
                                        _publish_step_stream(f"[agent_flow] {label}: blocked tool_results (node action_skills is empty)")
                            except Exception:
                                pass
                            try:
                                hub.publish(
                                    pid,
                                    sid,
                                    event="diag",
                                    data={
                                        "flow_step_index": idx,
                                        "flow_step_total": len(steps),
                                        "flow_node_label": label,
                                        "flow_node_plugin": plugin_id,
                                        "router_status": "node_done",
                                    },
                                )
                            except Exception:
                                pass
                    if _is_canceled():
                        _mark_canceled()
                        break
                    if isinstance(out, dict) and str(out.get("error") or "").lower() == "canceled":
                        _mark_canceled()
                        break

                    # Generic tool-node fallback:
                    # if a tool_node returns no tool_results, execute configured tool once
                    # using node tool_config and inferred input params.
                    try:
                        ps_now = step.get("plugin_settings") if isinstance(step.get("plugin_settings"), dict) else {}
                        node_type_now = str(ps_now.get("node_type") or "").strip().lower()
                        tc_now = ps_now.get("tool_config") if isinstance(ps_now.get("tool_config"), dict) else {}
                        tr_now = out.get("tool_results") if isinstance(out, dict) and isinstance(out.get("tool_results"), list) else []
                        allowed_now = ps_now.get("action_skills") if isinstance(ps_now.get("action_skills"), list) else []
                        allowed_workflow_skills = [
                            str(skill or "").strip()
                            for skill in allowed_now
                            if str(skill or "").strip().lower().startswith("workflow.")
                        ]
                        inferred_single_workflow_tool = ""
                        if len(allowed_workflow_skills) == 1:
                            inferred_single_workflow_tool = allowed_workflow_skills[0]
                        if not tc_now and inferred_single_workflow_tool:
                            tc_now = {
                                "tool": inferred_single_workflow_tool,
                                "params_from_input": [
                                    "pid",
                                    "user_request",
                                    "request",
                                    "prompt",
                                    "text",
                                    "current_request_text",
                                    "flow_name",
                                    "workflow_file",
                                    "bundle_dir",
                                    "missing_skill_specs",
                                    "force_new_workflow",
                                    "avoid_flow_names",
                                ],
                            }
                        require_data_keys = tc_now.get("require_data_keys") if isinstance(tc_now.get("require_data_keys"), list) else []
                        missing_required_data = False
                        if tr_now and require_data_keys:
                            missing_required_data = True
                            for tr0 in tr_now:
                                if not isinstance(tr0, dict):
                                    continue
                                data0 = tr0.get("data") if isinstance(tr0.get("data"), dict) else {}
                                def _has_required(k: str) -> bool:
                                    v = data0.get(k) if k in data0 else tr0.get(k)
                                    if v in (None, "", []):
                                        return False
                                    if isinstance(v, dict) and not v:
                                        return False
                                    return True
                                if all(_has_required(k) for k in require_data_keys):
                                    missing_required_data = False
                                    break
                        needs_fallback_tool = (
                            str(plugin_id or "").strip().lower() == "agent_workflow_member"
                            and (node_type_now == "tool_node" or bool(inferred_single_workflow_tool))
                            and isinstance(tc_now, dict)
                            and (not tr_now or missing_required_data)
                        )
                        if needs_fallback_tool:
                            tool_name = str(tc_now.get("tool") or "").strip()
                            aw_call = settings.get("__agent_workflow_tool_call")
                            if tool_name and callable(aw_call):
                                merged_params: Dict[str, Any] = {}
                                cfg_params = tc_now.get("params") if isinstance(tc_now.get("params"), dict) else {}
                                fallback_params = tc_now.get("fallback_params") if isinstance(tc_now.get("fallback_params"), dict) else {}
                                merged_params.update(dict(cfg_params))
                                merged_params.update(dict(fallback_params))
                                params_from_input = tc_now.get("params_from_input") if isinstance(tc_now.get("params_from_input"), list) else []
                                def _prior_value_for_param(name: str) -> Any:
                                    pname = str(name or "").strip()
                                    if not pname:
                                        return None
                                    for report_key in ("agent_flow_previous_step_report_with_tools", "agent_flow_previous_step_report"):
                                        report_obj = step_ext.get(report_key)
                                        if not isinstance(report_obj, dict):
                                            continue
                                        tr_rows = report_obj.get("tool_results") if isinstance(report_obj.get("tool_results"), list) else []
                                        if pname == "data":
                                            for tr_row in tr_rows:
                                                if not isinstance(tr_row, dict):
                                                    continue
                                                data_row = tr_row.get("data") if isinstance(tr_row.get("data"), dict) else {}
                                                if data_row:
                                                    return data_row
                                        if pname == "execution_text":
                                            for tr_row in tr_rows:
                                                if not isinstance(tr_row, dict):
                                                    continue
                                                data_row = tr_row.get("data") if isinstance(tr_row.get("data"), dict) else {}
                                                for alt_key in ("finalized_text", "execution_text", "response", "final_answer", "table_markdown", "markdown", "text", "summary"):
                                                    sval = data_row.get(alt_key)
                                                    if sval not in (None, "", [], {}):
                                                        return sval
                                                    sval = tr_row.get(alt_key)
                                                    if sval not in (None, "", [], {}):
                                                        return sval
                                            for alt_key in ("finalized_text", "execution_text", "response", "final_answer", "table_markdown", "markdown", "text", "summary"):
                                                sval = report_obj.get(alt_key)
                                                if sval not in (None, "", [], {}):
                                                    return sval
                                        if pname in {"response", "final_answer", "finalized_text"}:
                                            for tr_row in tr_rows:
                                                if not isinstance(tr_row, dict):
                                                    continue
                                                data_row = tr_row.get("data") if isinstance(tr_row.get("data"), dict) else {}
                                                sval = data_row.get(pname)
                                                if sval not in (None, "", [], {}):
                                                    return sval
                                                sval = tr_row.get(pname)
                                                if sval not in (None, "", [], {}):
                                                    return sval
                                        if pname in report_obj and report_obj.get(pname) not in (None, "", [], {}):
                                            return report_obj.get(pname)
                                        for tr_row in tr_rows:
                                            if not isinstance(tr_row, dict):
                                                continue
                                            data_row = tr_row.get("data") if isinstance(tr_row.get("data"), dict) else {}
                                            if pname in data_row:
                                                return data_row.get(pname)
                                            if pname in tr_row:
                                                return tr_row.get(pname)
                                    for raw_key in ("agent_flow_previous_output_raw", "agent_flow_previous_output_text"):
                                        raw_val = str(step_ext.get(raw_key) or "").strip()
                                        if not raw_val:
                                            continue
                                        parsed_prev = _extract_json_block_maybe(raw_val)
                                        if isinstance(parsed_prev, dict):
                                            if pname == "data":
                                                data_prev = parsed_prev.get("data") if isinstance(parsed_prev.get("data"), dict) else {}
                                                if data_prev:
                                                    return data_prev
                                            if pname == "execution_text":
                                                for alt_key in ("finalized_text", "execution_text", "response", "final_answer", "table_markdown", "markdown", "text", "summary"):
                                                    sval = parsed_prev.get(alt_key)
                                                    if sval not in (None, "", [], {}):
                                                        return sval
                                                data_prev = parsed_prev.get("data") if isinstance(parsed_prev.get("data"), dict) else {}
                                                for alt_key in ("finalized_text", "execution_text", "response", "final_answer", "table_markdown", "markdown", "text", "summary"):
                                                    sval = data_prev.get(alt_key)
                                                    if sval not in (None, "", [], {}):
                                                        return sval
                                            if pname in parsed_prev:
                                                return parsed_prev.get(pname)
                                            data_prev = parsed_prev.get("data") if isinstance(parsed_prev.get("data"), dict) else {}
                                            if pname in data_prev:
                                                return data_prev.get(pname)
                                    return None

                                # Gather candidate path/file hints from prior step tool results and user request.
                                prior_paths = _tool_result_paths(last_step_report)
                                user_file_hint = _extract_candidate_file_from_text(user_text)
                                if user_file_hint:
                                    prior_paths.append(user_file_hint)
                                file_hint = str(prior_paths[0] if prior_paths else "").strip()

                                for pkey0 in params_from_input:
                                    pkey = str(pkey0 or "").strip()
                                    if not pkey:
                                        continue
                                    if pkey == "text" and tool_name == "result.text":
                                        v = None
                                        for alt_key in ("finalized_text", "execution_text", "response", "final_answer", "table_markdown", "markdown", "summary"):
                                            v = _coalesce_param_value(
                                                merged_params.get(alt_key),
                                                (step.get("input") if isinstance(step.get("input"), dict) else {}).get(alt_key),
                                                step_ext.get(alt_key),
                                                ext.get(alt_key),
                                            )
                                            if v in (None, "", [], {}):
                                                v = _prior_value_for_param(alt_key)
                                            if v not in (None, "", [], {}):
                                                break
                                        if v in (None, "", [], {}):
                                            v = str(last_output_text or "").strip()
                                        if v in (None, "", [], {}):
                                            v = _coalesce_param_value(
                                                merged_params.get("text"),
                                                (step.get("input") if isinstance(step.get("input"), dict) else {}).get("text"),
                                                step_ext.get("text"),
                                                ext.get("text"),
                                            )
                                        if v in (None, "", [], {}):
                                            v = _prior_value_for_param(pkey)
                                        if v is not None and str(v).strip():
                                            merged_params[pkey] = v
                                            continue
                                    if pkey in {"current_request_text", "request_text", "user_request", "request", "prompt", "query"}:
                                        merged_params[pkey] = request_seed_text
                                        continue
                                    if pkey == "text":
                                        merged_params[pkey] = request_seed_text
                                        continue
                                    if (
                                        pkey in merged_params
                                        and str(merged_params.get(pkey) or "").strip()
                                        and pkey not in {"current_request_text", "request_text", "user_request", "request", "text", "prompt", "query"}
                                    ):
                                        continue
                                    v = _coalesce_param_value(
                                        step_ext.get(pkey),
                                        ext.get(pkey),
                                        (step.get("input") if isinstance(step.get("input"), dict) else {}).get(pkey),
                                    )
                                    if v is None:
                                        alias_key = {
                                            "last_bundle_dir": "bundle_dir",
                                            "last_workflow_file": "workflow_file",
                                            "last_flow_name": "flow_name",
                                        }.get(pkey)
                                        if alias_key:
                                            v = _coalesce_param_value(
                                                step_ext.get(alias_key),
                                                ext.get(alias_key),
                                                (step.get("input") if isinstance(step.get("input"), dict) else {}).get(alias_key),
                                            )
                                    if v is None:
                                        v = _prior_value_for_param(pkey)
                                    if v is None and pkey in {"file", "path", "file_path", "input_path", "source_pdf_path"}:
                                        v = file_hint
                                    if v is not None and str(v).strip():
                                        merged_params[pkey] = v

                                # Last-resort path/file mapping for common tools.
                                if tool_name.startswith("sheet.") and not any(str(merged_params.get(k) or "").strip() for k in ("file", "path", "file_path")) and file_hint:
                                    merged_params["path"] = file_hint
                                if tool_name.startswith("pdf.") and not any(str(merged_params.get(k) or "").strip() for k in ("file", "path", "file_path", "source_pdf_path")) and file_hint:
                                    merged_params["path"] = file_hint
                                # For sheet tools, prefer the inferred spreadsheet path from context.
                                # This avoids model-emitted hallucinated plugin paths.
                                if tool_name.startswith("sheet.") and file_hint:
                                    for k in ("path", "file", "file_path", "input_path"):
                                        if str(merged_params.get(k) or "").strip():
                                            merged_params[k] = file_hint

                                tool_ctx = {
                                    "app": app,
                                    "pid": pid,
                                    "sid": sid,
                                    "settings": settings,
                                    "ext": dict(step_ext) if isinstance(step_ext, dict) else {},
                                    "user_text": request_seed_text,
                                    "original_request": request_seed_text,
                                }
                                raw_res = aw_call(tool_name, tool_ctx, merged_params)
                                if not isinstance(raw_res, dict):
                                    raw_res = {"ok": False, "warnings": ["tool_fallback_invalid_result"], "data": {"result": raw_res}}
                                tr_row = {
                                    "skill": tool_name,
                                    "ok": bool(raw_res.get("ok")) if "ok" in raw_res else True,
                                    "warnings": list(raw_res.get("warnings") or []) if isinstance(raw_res.get("warnings"), list) else [],
                                    "data": dict(raw_res.get("data") or {}) if isinstance(raw_res.get("data"), dict) else {},
                                }
                                for k, v in raw_res.items():
                                    if k in {"ok", "warnings", "data", "error"}:
                                        continue
                                    if k not in tr_row["data"]:
                                        tr_row["data"][k] = v
                                if isinstance(out, dict):
                                    out.setdefault("tool_results", [])
                                    if isinstance(out.get("tool_results"), list):
                                        out["tool_results"].append(tr_row)
                                    if not str(out.get("text") or "").strip():
                                        fallback_text = _extract_text_from_route(raw_res)
                                        if fallback_text:
                                            out["text"] = fallback_text
                                    out["tool_node_fallback_executed"] = True
                                    out["tool_node_fallback_skill"] = tool_name
                                    out["tool_node_fallback_params"] = merged_params
                                    try:
                                        reason = "missing required data" if missing_required_data else "no tool result"
                                        _publish_step_stream(f"[agent_flow] {label}: tool_node fallback executed -> {tool_name} ({reason})")
                                    except Exception:
                                        pass
                    except Exception:
                        pass

                    text_out = _extract_text_from_route(out)
                    if text_out:
                        last_output_text = text_out
                    try:
                        last_output_raw = json.dumps(out, ensure_ascii=False)
                    except Exception:
                        last_output_raw = str(out)

                    output_summary = ""
                    if text_out:
                        output_summary = text_out
                    elif isinstance(out, dict):
                        if out.get("image_url") or out.get("image_path"):
                            output_summary = "image generated"
                        elif out.get("video_url") or out.get("video_path"):
                            output_summary = "video generated"
                    if output_summary:
                        state["steps"][idx]["output"] = output_summary

                    if isinstance(out, dict):
                        out["flow_node_label"] = f"Flow step {idx + 1}/{len(steps)}: {label}".strip()
                        # Capture changed files from tool results for downstream review stages.
                        try:
                            tr_list = out.get("tool_results")
                            if isinstance(tr_list, list):
                                changed_acc: List[str] = []
                                for tr in tr_list:
                                    if not isinstance(tr, dict):
                                        continue
                                    data0 = tr.get("data") if isinstance(tr.get("data"), dict) else {}
                                    cfs = data0.get("changed_files") if isinstance(data0, dict) else None
                                    if isinstance(cfs, list):
                                        for cf in cfs:
                                            p = str(cf or "").strip().replace("\\", "/")
                                            if p:
                                                changed_acc.append(p)
                                if changed_acc:
                                    recent_changed_files = changed_acc[:80]
                        except Exception:
                            pass
                        activity = out.get("activity")
                        if isinstance(activity, dict):
                            out["flow_step_report"] = {
                                "step": idx + 1,
                                "total": len(steps),
                                "role": str(activity.get("role") or label or ""),
                                "plan": str(activity.get("plan") or ""),
                                "analysis": str(activity.get("analysis") or ""),
                                "response": str(activity.get("response") or ""),
                                "did": str(activity.get("did") or ""),
                                "actions": list(activity.get("actions") or []),
                                "bugs": list(activity.get("bugs") or []),
                                "fixes": list(activity.get("fixes") or []),
                                "skills_invoked": list(activity.get("skills_invoked") or []),
                                "handoff": str(activity.get("handoff") or ""),
                                "tool_results": list(tr_list or []) if isinstance(tr_list, list) else [],
                            }
                            out["flow_step_report"] = _enrich_report_with_tool_results(out["flow_step_report"]) or out["flow_step_report"]
                            out["flow_step_report"] = _carry_step_artifact_context(out["flow_step_report"], step_ext) or out["flow_step_report"]
                            last_step_report = dict(out["flow_step_report"])
                            tr_keep = last_step_report.get("tool_results") if isinstance(last_step_report.get("tool_results"), list) else []
                            if tr_keep:
                                last_step_report_with_tools = dict(last_step_report)
                        else:
                            tr_list_fallback = out.get("tool_results") if isinstance(out.get("tool_results"), list) else []
                            if isinstance(tr_list_fallback, list) and tr_list_fallback:
                                skills_invoked = []
                                fallback_actions = _tool_result_list_field(tr_list_fallback, "actions")
                                fallback_bugs = _tool_result_list_field(tr_list_fallback, "bugs")
                                fallback_fixes = _tool_result_list_field(tr_list_fallback, "fixes")
                                fallback_response = ""
                                fallback_handoff = ""
                                for tr0 in tr_list_fallback:
                                    if isinstance(tr0, dict):
                                        skill0 = str(tr0.get("skill") or "").strip()
                                        if skill0:
                                            skills_invoked.append(skill0)
                                        data0 = tr0.get("data") if isinstance(tr0.get("data"), dict) else {}
                                        if not fallback_response:
                                            for k0 in ("review_summary", "summary", "response", "did", "message", "text", "content", "result"):
                                                v0 = str(data0.get(k0) or tr0.get(k0) or "").strip()
                                                if v0:
                                                    fallback_response = v0
                                                    break
                                        if not fallback_response:
                                            status_bits = []
                                            for k0 in ("handoff", "coverage_status", "route", "status", "decision", "flow_name", "node_label", "node_type", "plugin_id", "plugin_settings_keys", "exception"):
                                                v0 = str(data0.get(k0) or tr0.get(k0) or "").strip()
                                                if v0:
                                                    status_bits.append(f"{k0}: {v0}")
                                            warnings0 = tr0.get("warnings") if isinstance(tr0.get("warnings"), list) else []
                                            if warnings0:
                                                status_bits.append("warnings: " + ", ".join(str(x or "").strip() for x in warnings0 if str(x or "").strip()))
                                            if status_bits:
                                                fallback_response = "; ".join(status_bits)
                                        if not fallback_handoff:
                                            fallback_handoff = str(data0.get("handoff") or tr0.get("handoff") or "").strip()
                                out["flow_step_report"] = {
                                    "step": idx + 1,
                                    "total": len(steps),
                                    "role": str(label or ""),
                                    "plan": "",
                                    "analysis": "",
                                    "response": str(text_out or fallback_response or ""),
                                    "did": str(text_out or fallback_response or ""),
                                    "actions": fallback_actions,
                                    "bugs": fallback_bugs,
                                    "fixes": fallback_fixes,
                                    "skills_invoked": skills_invoked,
                                    "handoff": str(text_out or fallback_handoff or fallback_response or ""),
                                    "tool_results": list(tr_list_fallback),
                                }
                                out["flow_step_report"] = _enrich_report_with_tool_results(out["flow_step_report"]) or out["flow_step_report"]
                                out["flow_step_report"] = _carry_step_artifact_context(out["flow_step_report"], step_ext) or out["flow_step_report"]
                                last_step_report = dict(out["flow_step_report"])
                                try:
                                    visible_summary = _step_report_text(last_step_report)
                                    if visible_summary:
                                        state["steps"][idx]["output"] = visible_summary[:4000]
                                except Exception:
                                    pass
                                tr_keep = last_step_report.get("tool_results") if isinstance(last_step_report.get("tool_results"), list) else []
                                if tr_keep:
                                    last_step_report_with_tools = dict(last_step_report)
                                    try:
                                        if not final_result_mode:
                                            used_result_modes_fb = [
                                                _result_skill_mode(str((tr.get("skill") if isinstance(tr, dict) else "") or ""))
                                                for tr in tr_keep
                                                if isinstance(tr, dict) and tr.get("ok") is not False
                                            ]
                                            used_result_modes_fb = [m for m in used_result_modes_fb if m]
                                            if used_result_modes_fb:
                                                final_result_mode = used_result_modes_fb[-1]
                                                final_result_text = str(text_out or "").strip()
                                                final_result_out = {"tool_results": list(tr_keep)}
                                    except Exception:
                                        pass
                            else:
                                last_step_report = None

                        # Hard per-node skill enforcement:
                        # If action_skill_rules marks a skill as enforce_once and this step did
                        # not invoke it, run the skill once before transitions/finalization.
                        try:
                            ps_enf = step.get("plugin_settings") if isinstance(step.get("plugin_settings"), dict) else {}
                            rules_enf = ps_enf.get("action_skill_rules") if isinstance(ps_enf.get("action_skill_rules"), dict) else {}
                            allowed_enf = ps_enf.get("action_skills") if isinstance(ps_enf.get("action_skills"), list) else []
                            allowed_set_enf = {str(s or "").strip().lower() for s in allowed_enf if str(s or "").strip()}
                            enforced = []
                            for rule_skill_id, rule in rules_enf.items():
                                rule_skill = str(rule_skill_id or "").strip()
                                if not rule_skill:
                                    continue
                                rule0 = rule if isinstance(rule, dict) else {}
                                if not bool(rule0.get("enforce_once")):
                                    continue
                                if not _action_skill_rule_applies(rule0, user_text):
                                    continue
                                if allowed_set_enf and rule_skill.lower() not in allowed_set_enf:
                                    continue
                                enforced.append(rule_skill)
                            if enforced and plugin_id == "agent_workflow_member":
                                invoked = set()
                                if isinstance(last_step_report, dict):
                                    tr0 = last_step_report.get("tool_results")
                                    if isinstance(tr0, list):
                                        for tr in tr0:
                                            if isinstance(tr, dict):
                                                if tr.get("ok") is False:
                                                    continue
                                                sk0 = str(tr.get("skill") or "").strip().lower()
                                                if sk0:
                                                    invoked.add(sk0)
                                missing = [skill_name for skill_name in enforced if skill_name.lower() not in invoked]
                                aw_call_enf = settings.get("__agent_workflow_tool_call")
                                if missing and callable(aw_call_enf):
                                    out.setdefault("tool_results", [])
                                    if not isinstance(out.get("tool_results"), list):
                                        out["tool_results"] = []
                                    for skill_id in missing:
                                        params_enf: Dict[str, Any] = {}
                                        sid_l = skill_id.lower()
                                        if sid_l == "result.chart":
                                            chart_seed = None
                                            # Prefer explicit chart payload from prior tool results.
                                            tr_seed = out.get("tool_results") if isinstance(out.get("tool_results"), list) else []
                                            for tr in tr_seed:
                                                if not isinstance(tr, dict):
                                                    continue
                                                d0 = tr.get("data") if isinstance(tr.get("data"), dict) else {}
                                                c0 = d0.get("chart")
                                                if not isinstance(c0, (dict, list)):
                                                    c0 = tr.get("chart")
                                                if isinstance(c0, (dict, list)):
                                                    chart_seed = c0
                                                    break
                                                r0 = d0.get("records")
                                                if not isinstance(r0, list):
                                                    r0 = tr.get("records")
                                                if isinstance(r0, list) and r0:
                                                    chart_seed = {"records": r0}
                                                    break
                                            # Fallback to most recent report with tool rows.
                                            if chart_seed is None and isinstance(last_step_report_with_tools, dict):
                                                tr_seed2 = last_step_report_with_tools.get("tool_results")
                                                if isinstance(tr_seed2, list):
                                                    for tr in tr_seed2:
                                                        if not isinstance(tr, dict):
                                                            continue
                                                        d1 = tr.get("data") if isinstance(tr.get("data"), dict) else {}
                                                        r1 = d1.get("records")
                                                        if not isinstance(r1, list):
                                                            r1 = tr.get("records")
                                                        if isinstance(r1, list) and r1:
                                                            chart_seed = {"records": r1}
                                                            break
                                            norm_chart = normalize_chart_payload(chart_seed, user_request=user_text) if chart_seed is not None else None
                                            params_enf = {
                                                "chart": norm_chart if isinstance(norm_chart, dict) else chart_seed,
                                                "user_request": user_text,
                                            }
                                        elif sid_l in {"result.file", "result.files", "result.zip"}:
                                            file_seed = _tool_result_paths(last_step_report)
                                            if not file_seed and isinstance(last_step_report_with_tools, dict):
                                                file_seed = _tool_result_paths(last_step_report_with_tools)
                                            if not file_seed and isinstance(prev_step_report_with_tools, dict):
                                                file_seed = _tool_result_paths(prev_step_report_with_tools)
                                            if file_seed:
                                                params_enf = {"files": file_seed}
                                                if sid_l == "result.zip":
                                                    params_enf["archive_name"] = "agent_flow_result_bundle.zip"
                                        else:
                                            tc_enf = ps_enf.get("tool_config") if isinstance(ps_enf.get("tool_config"), dict) else {}
                                            if str(tc_enf.get("tool") or "").strip().lower() == sid_l:
                                                p_cfg = tc_enf.get("params") if isinstance(tc_enf.get("params"), dict) else {}
                                                p_fb = tc_enf.get("fallback_params") if isinstance(tc_enf.get("fallback_params"), dict) else {}
                                                params_enf.update(dict(p_cfg))
                                                params_enf.update(dict(p_fb))
                                            if not params_enf:
                                                params_enf = {"user_request": user_text}
                                            if sid_l.startswith("result."):
                                                params_enf.setdefault("user_request", user_text)
                                                if recent_changed_files:
                                                    params_enf.setdefault("changed_files", list(recent_changed_files))
                                        tool_ctx_enf = {"app": app, "pid": pid, "sid": sid, "settings": settings}
                                        raw_enf = aw_call_enf(skill_id, tool_ctx_enf, params_enf)
                                        if not isinstance(raw_enf, dict):
                                            raw_enf = {"ok": False, "warnings": ["enforce_once_invalid_result"], "data": {"result": raw_enf}}
                                        tr_enf = {
                                            "skill": skill_id,
                                            "ok": bool(raw_enf.get("ok")) if "ok" in raw_enf else True,
                                            "warnings": list(raw_enf.get("warnings") or []) if isinstance(raw_enf.get("warnings"), list) else [],
                                            "data": dict(raw_enf.get("data") or {}) if isinstance(raw_enf.get("data"), dict) else {},
                                        }
                                        for k, v in raw_enf.items():
                                            if k in {"ok", "warnings", "data", "error"}:
                                                continue
                                            if k not in tr_enf["data"]:
                                                tr_enf["data"][k] = v
                                        out["tool_results"].append(tr_enf)
                                        _publish_step_stream(f"[agent_flow] {label}: run-if enforce executed -> {skill_id}")
                                    # Rebuild fallback report skills/tool_results after enforcement.
                                    tr_list_post = out.get("tool_results") if isinstance(out.get("tool_results"), list) else []
                                    skills_post = []
                                    for tr in tr_list_post:
                                        if isinstance(tr, dict):
                                            skp = str(tr.get("skill") or "").strip()
                                            if skp:
                                                skills_post.append(skp)
                                    out["flow_step_report"] = {
                                        "step": idx + 1,
                                        "total": len(steps),
                                        "role": str(label or ""),
                                        "plan": "",
                                        "analysis": "",
                                        "response": str(text_out or ""),
                                        "did": str(text_out or ""),
                                        "actions": [],
                                        "bugs": [],
                                        "fixes": [],
                                        "skills_invoked": skills_post,
                                        "handoff": str(text_out or ""),
                                        "tool_results": list(tr_list_post),
                                    }
                                    out["flow_step_report"] = _carry_step_artifact_context(out["flow_step_report"], step_ext) or out["flow_step_report"]
                                    last_step_report = dict(out["flow_step_report"])
                                    if tr_list_post:
                                        last_step_report_with_tools = dict(last_step_report)
                                elif missing:
                                    _publish_step_stream(f"[agent_flow] {label}: run-if enforce missing but tool caller unavailable -> {', '.join(missing)}")
                        except Exception:
                            pass

                        try:
                            ps_branch = step.get("plugin_settings") if isinstance(step.get("plugin_settings"), dict) else {}
                            parent_bucket_id = str(ps_branch.get("fanout_parent_id") or "").strip()
                            is_terminal_branch_step = bool(ps_branch.get("fanout_branch_terminal"))
                            if parent_bucket_id and is_terminal_branch_step:
                                bucket = fanout_results.get(parent_bucket_id)
                                if isinstance(bucket, dict):
                                    branches = bucket.get("branches") if isinstance(bucket.get("branches"), list) else []
                                    branch_entry = {
                                        "index": int(ps_branch.get("fanout_branch_index") or 0),
                                        "item": (step.get("input") if isinstance(step.get("input"), dict) else {}).get("iteration_item"),
                                        "text": str((step.get("input") if isinstance(step.get("input"), dict) else {}).get("iteration_text") or "").strip(),
                                        "input": dict(step.get("input") or {}) if isinstance(step.get("input"), dict) else {},
                                        "report": dict(last_step_report) if isinstance(last_step_report, dict) else {},
                                        "output_text": str(last_output_text or "").strip(),
                                        "changed_files": list(recent_changed_files or []),
                                    }
                                    replaced = False
                                    for pos, existing in enumerate(branches):
                                        if isinstance(existing, dict) and int(existing.get("index") or -1) == branch_entry["index"]:
                                            branches[pos] = branch_entry
                                            replaced = True
                                            break
                                    if not replaced:
                                        branches.append(branch_entry)
                                    bucket["branches"] = branches
                                    fanout_results[parent_bucket_id] = bucket
                        except Exception:
                            pass

                        try:
                            interaction_req = _extract_interaction_from_tool_results(out)
                            if isinstance(interaction_req, dict):
                                interaction_response = _wait_for_interaction(interaction_req, idx, label)
                                if interaction_response is None:
                                    break
                                if isinstance(last_step_report, dict):
                                    last_step_report["interaction_response"] = dict(interaction_response)
                                    existing_actions = last_step_report.get("actions") if isinstance(last_step_report.get("actions"), list) else []
                                    action_s = str(interaction_response.get("action") or interaction_response.get("text") or "").strip()
                                    if action_s:
                                        last_step_report["actions"] = list(existing_actions) + [f"interaction_response:{action_s}"]
                                interaction_text = f"Interaction response: {json.dumps(interaction_response, ensure_ascii=True)}"
                                if not str(last_output_text or "").strip():
                                    last_output_text = interaction_text
                        except Exception as exc:
                            _publish_step_stream(f"[agent_flow] {label}: interaction wait failed: {exc}")

                        # Conditional transition loopback/retry injection.
                        try:
                            transitions_now = step.get("transitions") if isinstance(step.get("transitions"), list) else []
                            current_template_id = str(step.get("template_node_id") or str(step.get("node_id") or "").split("::")[0]).strip()
                            current_template = step_templates.get(current_template_id) if current_template_id else None
                            request_seed_for_transition = _request_seed_for_step(step, user_text)
                            prior_paths_transition = _tool_result_paths(last_step_report)
                            user_file_hint_transition = _extract_candidate_file_from_text(request_seed_for_transition)
                            if user_file_hint_transition:
                                prior_paths_transition.append(user_file_hint_transition)
                            fallback_file_hint_transition = str(prior_paths_transition[0] if prior_paths_transition else "").strip()
                            for tr in transitions_now:
                                if not isinstance(tr, dict):
                                    continue
                                cond = _normalize_transition_condition(tr.get("condition"))
                                runtime_transition = _transition_requires_runtime(tr)
                                if _is_always_transition_condition(tr.get("condition")) and not runtime_transition:
                                    continue
                                target_id = str(tr.get("target") or "").strip()
                                if not target_id:
                                    continue
                                target_template = step_templates.get(target_id)
                                if not isinstance(target_template, dict):
                                    continue
                                transition_report = last_step_report
                                transition_tr_row = None
                                if runtime_transition:
                                    cached = _run_transition_action(
                                        tr,
                                        step=step,
                                        step_ext=step_ext,
                                        last_step_report=last_step_report,
                                        request_seed_text=request_seed_for_transition,
                                        fallback_file_hint=fallback_file_hint_transition,
                                    )
                                    action_report, transition_tr_row, _ = cached
                                    if isinstance(action_report, dict):
                                        transition_report = _merge_step_reports(last_step_report, action_report)
                                if not _transition_matches(tr, last_step_report=transition_report, recent_changed_files=recent_changed_files):
                                    continue
                                try:
                                    next_step = steps[idx + 1] if idx + 1 < len(steps) else None
                                    next_state = state["steps"][idx + 1] if idx + 1 < len(state.get("steps") or []) else None
                                    next_template_id = (
                                        str((next_step or {}).get("template_node_id") or (next_step or {}).get("node_id") or "").split("::")[0].strip()
                                        if isinstance(next_step, dict)
                                        else ""
                                    )
                                    next_is_queued = isinstance(next_state, dict) and str(next_state.get("state") or "").strip().lower() == "queued"
                                    if next_template_id == target_id and next_is_queued:
                                        if isinstance(transition_report, dict):
                                            last_step_report = dict(transition_report)
                                            tr_keep_edge = last_step_report.get("tool_results") if isinstance(last_step_report.get("tool_results"), list) else []
                                            if tr_keep_edge:
                                                last_step_report_with_tools = dict(last_step_report)
                                        _publish_step_stream(
                                            f"[agent_flow] {label}: conditional transition matched existing next node -> {target_id}"
                                        )
                                        break
                                except Exception:
                                    pass
                                cond_sig = json.dumps(cond, sort_keys=True, ensure_ascii=True)
                                current_runtime_transition_id = str(
                                    current_template_id
                                    or step.get("template_node_id")
                                    or step.get("node_id")
                                    or ""
                                ).strip()
                                step_ps_for_edge = step.get("plugin_settings") if isinstance(step.get("plugin_settings"), dict) else {}
                                fanout_parent_edge = str(step_ps_for_edge.get("fanout_parent_id") or "").strip()
                                if fanout_parent_edge:
                                    edge_scope_id = f"{fanout_parent_edge}:{current_template_id or current_runtime_transition_id or target_id}"
                                else:
                                    edge_scope_id = current_runtime_transition_id or current_template_id or target_id
                                edge_key = f"transition:{edge_scope_id}->{target_id}:{cond_sig}"
                                explicit_edge_max = tr.get("loop_max_passes")
                                raw_edge_max = workflow_loop_max_default if workflow_force_loop_max else explicit_edge_max
                                if raw_edge_max is None or (isinstance(raw_edge_max, str) and not str(raw_edge_max).strip()):
                                    edge_max = workflow_loop_max_default
                                    edge_cap_source = "workflow-default"
                                else:
                                    try:
                                        edge_max = int(raw_edge_max)
                                    except Exception:
                                        edge_max = workflow_loop_max_default
                                        edge_cap_source = "workflow-default"
                                    else:
                                        edge_cap_source = "workflow-override" if workflow_force_loop_max else "edge-explicit"
                                    if edge_max < 0:
                                        edge_max = workflow_loop_max_default
                                        edge_cap_source = "workflow-default"
                                if edge_max > 0 and loop_retry_counts.get(edge_key, 0) >= edge_max:
                                    continue
                                retry_num = int(loop_retry_counts.get(edge_key, 0)) + 1
                                loop_retry_counts[edge_key] = retry_num
                                if isinstance(transition_report, dict):
                                    last_step_report = dict(transition_report)
                                    tr_keep_edge = last_step_report.get("tool_results") if isinstance(last_step_report.get("tool_results"), list) else []
                                    if tr_keep_edge:
                                        last_step_report_with_tools = dict(last_step_report)
                                if isinstance(transition_tr_row, dict):
                                    out.setdefault("tool_results", [])
                                    if isinstance(out.get("tool_results"), list) and transition_tr_row not in out["tool_results"]:
                                        out["tool_results"].append(transition_tr_row)
                                extra_prompt = str(tr.get("system_prompt") or "").strip()
                                injected_steps = _build_transition_path_steps(
                                    target_id,
                                    retry_num=retry_num,
                                    label_suffix=f"loop {retry_num}",
                                    extra_system_prompt=extra_prompt,
                                )
                                if not injected_steps:
                                    target_clone = _clone_step_for_transition(
                                        target_template,
                                        label_suffix=f"loop {retry_num}",
                                        extra_system_prompt=extra_prompt,
                                    )
                                    target_clone["node_id"] = f"{target_id}::loopback::{retry_num}::target"
                                    target_clone["template_node_id"] = target_id
                                    injected_steps = [target_clone]
                                if injected_steps:
                                    branch_ps = step.get("plugin_settings") if isinstance(step.get("plugin_settings"), dict) else {}
                                    branch_input = dict(step.get("input") or {}) if isinstance(step.get("input"), dict) else {}
                                    transition_input_keys = {
                                        "current_request",
                                        "current_request_text",
                                        "last_completed_request_text",
                                        "remaining_requests",
                                        "completed_requests",
                                        "completed_count",
                                        "created_count",
                                        "failed_count",
                                        "total_requests",
                                        "has_current",
                                        "has_more",
                                        "handoff",
                                        "tracker_state",
                                        "subflow_parent_state",
                                        "subflow_result_state",
                                        "planned_requests",
                                        "request_text",
                                        "user_request",
                                        "request",
                                        "text",
                                        "prompt",
                                        "bundle_dir",
                                        "workflow_file",
                                        "flow_name",
                                        "last_bundle_dir",
                                        "last_workflow_file",
                                        "last_flow_name",
                                        "input_path",
                                        "file_path",
                                        "path",
                                        "file",
                                        "validated_request_text",
                                        "flow_ext",
                                        "execution_text",
                                        "execution_files",
                                        "execution_zip",
                                        "result_mode",
                                        "status",
                                        "pid",
                                        "target_type",
                                        "bugs",
                                        "all_passed",
                                        "pass_count",
                                        "fail_count",
                                    }
                                    latest_transition_input = dict(branch_input)
                                    transition_sources = []
                                    if isinstance(step_ext, dict):
                                        transition_sources.append(step_ext)
                                    if isinstance(transition_report, dict):
                                        transition_sources.append(transition_report)
                                        tr_rows_now = transition_report.get("tool_results") if isinstance(transition_report.get("tool_results"), list) else []
                                        for tr_row_now in tr_rows_now:
                                            if not isinstance(tr_row_now, dict):
                                                continue
                                            data_now = tr_row_now.get("data") if isinstance(tr_row_now.get("data"), dict) else {}
                                            transition_sources.append(tr_row_now)
                                            if data_now:
                                                transition_sources.append(data_now)
                                    for source in transition_sources:
                                        if not isinstance(source, dict):
                                            continue
                                        for pkey in transition_input_keys:
                                            if pkey not in source:
                                                continue
                                            v = source.get(pkey)
                                            if v in (None, "", [], {}):
                                                continue
                                            if pkey == "current_request":
                                                v = _coerce_single_request(v)
                                            elif pkey == "tracker_state":
                                                v = _normalize_tracker_state(v)
                                            elif pkey in {"remaining_requests", "completed_requests"}:
                                                if isinstance(v, tuple):
                                                    v = list(v)
                                                if v is not None and not isinstance(v, list):
                                                    v = [v]
                                            latest_transition_input[pkey] = v
                                    for offset, injected in enumerate(injected_steps, start=1):
                                        injected_ps = injected.get("plugin_settings") if isinstance(injected.get("plugin_settings"), dict) else {}
                                        injected_ps = dict(injected_ps)
                                        if str(branch_ps.get("fanout_parent_id") or "").strip():
                                            injected_ps["fanout_parent_id"] = branch_ps.get("fanout_parent_id")
                                            injected_ps["fanout_branch_index"] = branch_ps.get("fanout_branch_index")
                                            injected_ps["fanout_branch_total"] = branch_ps.get("fanout_branch_total")
                                            injected_ps["fanout_branch_terminal"] = offset == len(injected_steps)
                                            injected["plugin_settings"] = injected_ps
                                        if latest_transition_input and offset == 1:
                                            cur_input = injected.get("input") if isinstance(injected.get("input"), dict) else {}
                                            merged_input = dict(latest_transition_input)
                                            merged_input.update(cur_input)
                                            injected["input"] = merged_input
                                        steps.insert(idx + offset, injected)
                                        state["steps"].insert(idx + offset, {"label": injected.get("label") or injected.get("node_id"), "state": "queued"})
                                    state["steps_total"] = len(steps)
                                    state["loop_cap"] = {
                                        "kind": "transition",
                                        "source": edge_cap_source,
                                        "value": 0 if edge_max <= 0 else int(edge_max),
                                        "value_label": _format_loop_cap(edge_max),
                                        "retry": retry_num,
                                        "node_label": str(label or ""),
                                        "target_id": str(target_id or ""),
                                    }
                                    state["ts"] = _now_ts()
                                    _agent_flow_set_state(pid, sid, state)
                                    _publish_flow_status({})
                                    _publish_step_stream(
                                        f"[agent_flow] {label}: conditional transition matched; queued {', '.join(str(s.get('label') or s.get('node_id')) for s in injected_steps)}"
                                    )
                                    _publish_step_stream(
                                        f"[agent_flow] {label}: loop cap source={edge_cap_source} value={_format_loop_cap(edge_max)} retry={retry_num}"
                                    )
                                    break
                        except Exception:
                            pass

                        # Optional dynamic retry injection when a step completed without producing changed files.
                        try:
                            ps_retry = step.get("plugin_settings") if isinstance(step.get("plugin_settings"), dict) else {}
                            retry_target = str((ps_retry or {}).get("loop_on_no_changes_target") or "").strip()
                            explicit_retry_max = (ps_retry or {}).get("loop_max_passes")
                            raw_retry_max = workflow_loop_max_default if workflow_force_loop_max else explicit_retry_max
                            try:
                                retry_max = int(raw_retry_max) if raw_retry_max not in (None, "") else 0
                                if raw_retry_max in (None, ""):
                                    retry_cap_source = "workflow-default"
                                else:
                                    retry_cap_source = "workflow-override" if workflow_force_loop_max else "edge-explicit"
                            except Exception:
                                retry_max = workflow_loop_max_default if workflow_force_loop_max else 0
                                retry_cap_source = "workflow-default" if workflow_force_loop_max else "edge-explicit"
                            retry_key = f"{step.get('node_id') or ''}->{retry_target}"
                            retry_allowed = retry_target and not recent_changed_files and (
                                retry_max <= 0 or loop_retry_counts.get(retry_key, 0) < retry_max
                            )
                            if retry_allowed:
                                target_step = step_templates.get(retry_target)
                                if isinstance(target_step, dict):
                                    retry_num = int(loop_retry_counts.get(retry_key, 0)) + 1
                                    loop_retry_counts[retry_key] = retry_num
                                    injected = dict(target_step)
                                    injected["label"] = f"{target_step.get('label') or retry_target} / retry {retry_num}"
                                    injected["node_id"] = f"{retry_target}::retry::{retry_num}"
                                    steps.insert(idx + 1, injected)
                                    state["steps_total"] = len(steps)
                                    state["loop_cap"] = {
                                        "kind": "retry",
                                        "source": retry_cap_source,
                                        "value": 0 if retry_max <= 0 else int(retry_max),
                                        "value_label": _format_loop_cap(retry_max),
                                        "retry": retry_num,
                                        "node_label": str(label or ""),
                                        "target_id": str(retry_target or ""),
                                    }
                                    state["ts"] = _now_ts()
                                    state["steps"].insert(idx + 1, {"label": injected.get("label") or injected.get("node_id"), "state": "queued"})
                                    _agent_flow_set_state(pid, sid, state)
                                    _publish_flow_status({})
                                    _publish_step_stream(f"[agent_flow] {label}: no changed files; queued retry node {injected.get('label')}")
                                    _publish_step_stream(
                                        f"[agent_flow] {label}: retry cap source={retry_cap_source} value={_format_loop_cap(retry_max)} retry={retry_num}"
                                    )
                        except Exception:
                            pass

                    # Capture final result-mode output from a node that opts into result skills.
                    try:
                        ps_now = step.get("plugin_settings") if isinstance(step.get("plugin_settings"), dict) else {}
                        rmode = _result_mode_from_plugin_settings(ps_now)
                        # Prefer the result skill actually invoked by this node when present.
                        if isinstance(out, dict):
                            tr_now = out.get("tool_results")
                            if isinstance(tr_now, list):
                                used_result_modes = [
                                    _result_skill_mode(str((tr.get("skill") if isinstance(tr, dict) else "") or ""))
                                    for tr in tr_now
                                    if isinstance(tr, dict) and tr.get("ok") is not False
                                ]
                                used_result_modes = [m for m in used_result_modes if m]
                                if used_result_modes:
                                    rmode = used_result_modes[-1]
                        if rmode:
                            tr_now_all = out.get("tool_results") if isinstance(out, dict) and isinstance(out.get("tool_results"), list) else []
                            if tr_now_all:
                                for row in tr_now_all:
                                    if not isinstance(row, dict):
                                        continue
                                    row_mode = _result_skill_mode(str(row.get("skill") or ""))
                                    if not row_mode or row.get("ok") is False:
                                        continue
                                    final_result_rows_accum.append(dict(row))
                            final_result_mode = rmode
                            if str(text_out or "").strip():
                                final_result_text = str(text_out or "").strip()
                            captured_result_out = dict(out) if isinstance(out, dict) else {}
                            for prior_report in (
                                prev_step_report_with_tools if isinstance(prev_step_report_with_tools, dict) else None,
                                prev_step_report if isinstance(prev_step_report, dict) else None,
                                final_result_out if isinstance(final_result_out, dict) else None,
                            ):
                                merged_report = _merge_step_reports(prior_report, captured_result_out)
                                if isinstance(merged_report, dict):
                                    captured_result_out = merged_report
                            final_result_out = captured_result_out
                            if final_result_rows_accum:
                                final_result_out["tool_results"] = list(final_result_rows_accum)
                    except Exception:
                        pass

                    state["steps"][idx]["state"] = "done"
                    _agent_flow_set_state(pid, sid, state)
                    _publish_flow_status({})
                    if not _wait_if_paused(idx + 1):
                        break
                    idx += 1

                if not state.get("running"):
                    _flush_run_tokens(force=True)
                    _agent_flow_set_state(pid, sid, state)
                    _publish_flow_status({"running": False, "paused": False, "pause_requested": False})
                    return

                state["running"] = False
                state["paused"] = False
                state["pause_requested"] = False
                state["status"] = "Completed"
                try:
                    validation_record_id = str(ext.get("agent_flow_temp_library_record_id") or "").strip()
                    if validation_record_id and str(flow_name or "").strip() == "workflow_designer_validator_sandbox":
                        validation_ok = _temp_library_validation_passed(
                            final_result_out,
                            last_step_report,
                            last_step_report_with_tools,
                            prev_step_report,
                            prev_step_report_with_tools,
                        )
                        validation_findings = _temp_library_validation_findings(
                            final_result_out,
                            last_step_report,
                            last_step_report_with_tools,
                            prev_step_report,
                            prev_step_report_with_tools,
                        )
                        _temp_library_update(pid, validation_record_id, {
                            "validated": bool(validation_ok),
                            "all_passed": bool(validation_ok),
                            "validation_pending": False,
                            "last_validation_ok": bool(validation_ok),
                            "last_validation_status": "passed" if validation_ok else "failed",
                            "last_validation_ts": _now_ts(),
                            "last_validation_run_id": run_id,
                            "bugs": list(validation_findings.get("bugs") or []),
                            "fixes": list(validation_findings.get("fixes") or []),
                            "fix_summary": str(validation_findings.get("summary") or "").strip(),
                        })
                except Exception:
                    pass
                _flush_run_tokens(force=True)
                if run_stream_started["v"]:
                    final_stream_text = "".join(run_stream_parts)
                    ts_done = max(_now_ts(), int(flow_user_ts["v"] or 0) + 1)
                    flow_stream_ts["v"] = int(ts_done)
                    try:
                        db.add_message(
                            msg_id=run_stream_msg_id,
                            pid=pid,
                            sid=sid,
                            ts=ts_done,
                            role="assistant",
                            kind="model",
                            author_username=u.username,
                            author_alias=u.username,
                            content=final_stream_text,
                            meta=_flow_stream_meta(),
                        )
                    except Exception:
                        pass
                    try:
                        hub.publish(
                            pid,
                            sid,
                            event="message",
                            data={
                                "msg": {
                                    "msg_id": run_stream_msg_id,
                                    "pid": pid,
                                    "sid": sid,
                                    "ts": ts_done,
                                    "role": "assistant",
                                    "kind": "model",
                                    "author_username": u.username,
                                    "author_alias": u.username,
                                    "content": final_stream_text,
                                    "meta": _flow_stream_meta(),
                                }
                            },
                        )
                        hub.publish(pid, sid, event="done", data={"msg_id": run_stream_msg_id, "ok": True})
                    except Exception:
                        pass
                # Emit final result as a normal assistant message outside Agent Jobs stream when
                # a node selected Result skills (result.text/result.chart).
                try:
                    if final_result_mode:
                        _publish_step_stream(f"[agent_flow] final result mode: {final_result_mode}")
                        ts_res = _now_ts()
                        msg_id_res = f"{run_id}_result"
                        content_res = _humanize_result_fallback(
                            final_result_text or str(last_output_text or "").strip(),
                            last_step_report,
                        )
                        meta_res: Dict[str, Any] = {
                            "flow": True,
                            "flow_result": True,
                            "flow_result_mode": final_result_mode,
                            "flow_run_id": run_id,
                            "flow_result_for_run_id": run_id,
                        }
                        result_emit = _extract_result_emit(
                            final_result_mode,
                            final_result_out,
                            last_step_report,
                            last_step_report_with_tools,
                        )
                        generic_result_content_used = False
                        if isinstance(result_emit, dict) and result_emit:
                            emit_mode = str(result_emit.get("mode") or final_result_mode or "result").strip().lower()
                            if emit_mode:
                                final_result_mode = emit_mode
                                meta_res["flow_result_mode"] = emit_mode
                            emit_meta = result_emit.get("meta") if isinstance(result_emit.get("meta"), dict) else {}
                            for key, val in emit_meta.items():
                                meta_res[str(key)] = val
                            emit_content = str(result_emit.get("content") or "").strip()
                            if emit_content:
                                content_res = emit_content
                                generic_result_content_used = True
                        if not str(content_res or "").strip():
                            content_res = _humanize_result_fallback(
                                str(last_output_text or "").strip(),
                                last_step_report,
                            )
                        if str(final_result_mode or "").strip().lower() == "text":
                            try:
                                request_file_hint_text = _extract_candidate_file_from_text(user_text)
                                prior_paths_text = _tool_result_paths(last_step_report) + _tool_result_paths(last_step_report_with_tools)
                                file_hint_text = str(request_file_hint_text or "").strip()
                                if not file_hint_text:
                                    file_hint_text = str(prior_paths_text[0] if prior_paths_text else "").strip()
                                content_low = str(content_res or "").lower()
                                should_normalize_text = bool(
                                    (
                                        content_low.startswith("role:")
                                        or "\nresponse:" in content_low
                                        or "\ndid:" in content_low
                                    )
                                    or (
                                        file_hint_text
                                        and re.search(r"\b(compare|variance|flag|breakdown|increase|decrease|changed)\b", str(user_text or ""), flags=re.IGNORECASE)
                                        and (
                                            "## tabular breakdown" not in content_low
                                            or "[value]" in content_low
                                            or "[team" in content_low
                                        )
                                    )
                                )
                                if should_normalize_text:
                                    normalized_text_res = result_text_skill.run(
                                        {
                                            "app": app,
                                            "pid": pid,
                                            "sid": sid,
                                            "settings": settings,
                                            "user_text": user_text,
                                            "original_request": user_text,
                                        },
                                        {
                                            "text": str(content_res or ""),
                                            "user_request": str(user_text or ""),
                                            "path": file_hint_text,
                                            "file_path": file_hint_text,
                                            "input_path": file_hint_text,
                                        },
                                    )
                                    if isinstance(normalized_text_res, dict):
                                        normalized_text = str(
                                            normalized_text_res.get("text")
                                            or (normalized_text_res.get("data", {}) if isinstance(normalized_text_res.get("data"), dict) else {}).get("text")
                                            or ""
                                        ).strip()
                                        if normalized_text:
                                            content_res = normalized_text
                                            meta_res["data"] = {"mode": "text", "text": normalized_text}
                                            generic_result_content_used = True
                            except Exception:
                                pass
                        emit_rows_now = _result_tool_rows(final_result_out, last_step_report, last_step_report_with_tools)
                        file_requested_by_result = any(
                            _result_skill_mode(str((row.get("skill") if isinstance(row, dict) else "") or "")) in {"file", "files"}
                            and (not isinstance(row, dict) or row.get("ok") is not False)
                            for row in emit_rows_now
                        )
                        zip_requested_by_result = any(
                            _result_skill_mode(str((row.get("skill") if isinstance(row, dict) else "") or "")) == "zip"
                            and (not isinstance(row, dict) or row.get("ok") is not False)
                            for row in emit_rows_now
                        )
                        has_file_artifact = isinstance(meta_res.get("files"), list) and bool(meta_res.get("files"))
                        has_zip_artifact = isinstance(meta_res.get("zip"), dict) and bool(meta_res.get("zip"))

                        file_hints_present = _report_has_file_hints(
                            final_result_out,
                            last_step_report,
                            last_step_report_with_tools,
                            prev_step_report,
                            prev_step_report_with_tools,
                        )
                        substantive_text_result = len(str(content_res or "").strip()) >= 80
                        text_mode_selected = str(final_result_mode or "").strip().lower() == "text"
                        should_attach_files = (
                            final_result_mode == "files"
                            or file_requested_by_result
                            or (file_hints_present and not text_mode_selected and not substantive_text_result)
                        )
                        if should_attach_files and not has_file_artifact:
                            resolved_files = _collect_result_files_any(
                                recent_changed_files,
                                final_result_out,
                                last_step_report,
                                last_step_report_with_tools,
                                prev_step_report,
                                prev_step_report_with_tools,
                            )
                            staged = []
                            for fp in resolved_files:
                                item = _stage_file_for_download(fp)
                                if item:
                                    staged.append(item)
                            if staged:
                                lines = ["Files ready for download:"]
                                for item in staged:
                                    lines.append(f"- [{item.get('name')}]({item.get('download_url')})")
                                staged_text = "\n".join(lines)
                                content_res = f"{content_res}\n\n{staged_text}".strip() if str(content_res or "").strip() else staged_text
                                meta_res["files"] = staged
                            elif not content_res:
                                content_res = "No downloadable files were found."
                            has_file_artifact = isinstance(meta_res.get("files"), list) and bool(meta_res.get("files"))
                        if (final_result_mode == "zip" or zip_requested_by_result) and not has_zip_artifact:
                            resolved_files = _collect_result_files_any(
                                recent_changed_files,
                                final_result_out,
                                last_step_report,
                                last_step_report_with_tools,
                                prev_step_report,
                                prev_step_report_with_tools,
                            )
                            archive_name = "agent_flow_result.zip"
                            if isinstance(final_result_out, dict):
                                archive_name = str(final_result_out.get("archive_name") or archive_name).strip() or archive_name
                            if not archive_name.lower().endswith(".zip"):
                                archive_name = f"{archive_name}.zip"
                            staged_zip = None
                            if resolved_files:
                                try:
                                    up = _uploads_dir_path()
                                    zip_name = _unique_upload_name(archive_name)
                                    zip_path = up / zip_name
                                    with zipfile.ZipFile(str(zip_path), "w", compression=zipfile.ZIP_DEFLATED) as zf:
                                        for fp in resolved_files:
                                            zf.write(str(fp), arcname=fp.name)
                                    staged_zip = {
                                        "name": Path(archive_name).name,
                                        "staged_name": zip_name,
                                        "download_url": f"/uploads/{zip_name}",
                                        "size_bytes": int(zip_path.stat().st_size),
                                        "file_count": len(resolved_files),
                                    }
                                except Exception:
                                    staged_zip = None
                            if staged_zip:
                                zip_text = f"ZIP ready: [{staged_zip.get('name')}]({staged_zip.get('download_url')})"
                                content_res = f"{zip_text}\n\n{content_res}".strip() if str(content_res or "").strip() else zip_text
                                meta_res["zip"] = staged_zip
                                final_result_mode = "zip"
                                meta_res["flow_result_mode"] = "zip"
                            elif not content_res:
                                content_res = "No files were available to zip."
                        rendered_links = str(content_res or "")
                        existing_files = meta_res.get("files") if isinstance(meta_res.get("files"), list) else []
                        if existing_files and not (str(final_result_mode or "").strip().lower() == "text" and substantive_text_result and not file_requested_by_result):
                            file_lines = []
                            for item in existing_files:
                                if not isinstance(item, dict):
                                    continue
                                name = str(item.get("name") or "").strip()
                                url = str(item.get("download_url") or "").strip()
                                if not name or not url or url in rendered_links:
                                    continue
                                file_lines.append(f"- [{name}]({url})")
                            if file_lines:
                                file_text = "Files ready for download:\n" + "\n".join(file_lines)
                                content_res = f"{content_res}\n\n{file_text}".strip() if str(content_res or "").strip() else file_text
                                rendered_links = str(content_res or "")
                        existing_zip = meta_res.get("zip") if isinstance(meta_res.get("zip"), dict) else {}
                        zip_name = str(existing_zip.get("name") or "").strip()
                        zip_url = str(existing_zip.get("download_url") or "").strip()
                        if zip_name and zip_url and zip_url not in rendered_links:
                            zip_text = f"ZIP ready: [{zip_name}]({zip_url})"
                            content_res = f"{zip_text}\n\n{content_res}".strip() if str(content_res or "").strip() else zip_text
                        if not content_res:
                            content_res = "Result ready."
                        meta_res = _json_safe(meta_res) if isinstance(meta_res, dict) else {}
                        state["final_result"] = str(content_res or "")
                        state["final_result_mode"] = str(final_result_mode or meta_res.get("flow_result_mode") or "text").strip().lower() or "text"
                        ts_res = max(int(ts_res), int(flow_stream_ts["v"] or 0) + 1)
                        msg_payload = {
                            "msg_id": msg_id_res,
                            "pid": pid,
                            "sid": sid,
                            "ts": ts_res,
                            "role": "assistant",
                            "kind": "model",
                            "author_username": u.username,
                            "author_alias": u.username,
                            "content": content_res,
                            "meta": meta_res,
                        }
                        persist_exc: Optional[Exception] = None
                        for _attempt in range(3):
                            try:
                                db.add_message(
                                    msg_id=msg_id_res,
                                    pid=pid,
                                    sid=sid,
                                    ts=ts_res,
                                    role="assistant",
                                    kind="model",
                                    author_username=u.username,
                                    author_alias=u.username,
                                    content=content_res,
                                    meta=meta_res,
                                )
                                persist_exc = None
                                break
                            except Exception as exc:
                                persist_exc = exc
                                time.sleep(0.05)
                        if persist_exc is not None:
                            raise persist_exc
                        try:
                            hub.publish(
                                pid,
                                sid,
                                event="message",
                                data={"msg": msg_payload},
                            )
                        except Exception:
                            pass
                        _publish_step_stream("[agent_flow] final result message emitted")
                except Exception as exc:
                    try:
                        import traceback as _traceback
                        print("[agent_flow_final_result_error]", _traceback.format_exc(), flush=True)
                        _publish_step_stream(f"[agent_flow] final result message failed; using stream fallback ({type(exc).__name__}: {exc})")
                        fallback_text = str(content_res or "").strip() or _humanize_result_fallback(
                            str(last_output_text or "").strip(),
                            last_step_report,
                        ) or "Result ready."
                        fallback_meta = _json_safe({
                            "flow": True,
                            "flow_result": True,
                            "flow_result_mode": str(final_result_mode or "text").strip().lower() or "text",
                            "flow_run_id": run_id,
                            "flow_result_for_run_id": run_id,
                            "flow_result_fallback": True,
                        })
                        state["final_result"] = str(fallback_text or "")
                        state["final_result_mode"] = str(final_result_mode or "text").strip().lower() or "text"
                        try:
                            db.add_message(
                                msg_id=f"{run_id}_result_fallback",
                                pid=pid,
                                sid=sid,
                                ts=max(int(_now_ts()), int(flow_stream_ts["v"] or 0) + 1),
                                role="assistant",
                                kind="model",
                                author_username=u.username,
                                author_alias=u.username,
                                content=fallback_text,
                                meta=fallback_meta,
                            )
                            try:
                                hub.publish(
                                    pid,
                                    sid,
                                    event="message",
                                    data={
                                        "msg": {
                                            "msg_id": f"{run_id}_result_fallback",
                                            "pid": pid,
                                            "sid": sid,
                                            "ts": max(int(_now_ts()), int(flow_stream_ts["v"] or 0) + 1),
                                            "role": "assistant",
                                            "kind": "model",
                                            "author_username": u.username,
                                            "author_alias": u.username,
                                            "content": fallback_text,
                                            "meta": fallback_meta,
                                        }
                                    },
                                )
                            except Exception:
                                pass
                        except Exception:
                            pass
                        if final_result_mode and str(content_res or "").strip():
                            _publish_step_stream("<<<AW_FINAL_RESULT>>>")
                            _publish_step_stream(str(content_res))
                            _publish_step_stream("<<<END_AW_FINAL_RESULT>>>")
                    except Exception:
                        pass
                _agent_flow_set_state(pid, sid, state, preserve_pause=False)
                _publish_flow_status({"running": False, "paused": False, "pause_requested": False})
            except Exception as exc:
                state["running"] = False
                state["paused"] = False
                state["pause_requested"] = False
                state["status"] = f"Error: {exc}"
                _agent_flow_set_state(pid, sid, state, preserve_pause=False)
                try:
                    validation_record_id = str(ext.get("agent_flow_temp_library_record_id") or "").strip()
                    if validation_record_id and str(flow_name or "").strip() == "workflow_designer_validator_sandbox":
                        _temp_library_update(pid, validation_record_id, {
                            "validated": False,
                            "validation_pending": False,
                            "last_validation_ok": False,
                            "last_validation_status": f"error:{exc}",
                            "last_validation_ts": _now_ts(),
                            "last_validation_run_id": run_id,
                            "bugs": [str(exc)],
                            "fix_summary": "Validator flow errored before completion.",
                        })
                except Exception:
                    pass
                try:
                    _publish_run_line(f"[agent_flow] error: {exc}")
                    _flush_run_tokens(force=True)
                except Exception:
                    pass
                if run_stream_started["v"]:
                    final_stream_text = "".join(run_stream_parts)
                    try:
                        ts_err = max(_now_ts(), int(flow_user_ts["v"] or 0) + 1)
                        flow_stream_ts["v"] = int(ts_err)
                        db.add_message(
                            msg_id=run_stream_msg_id,
                            pid=pid,
                            sid=sid,
                            ts=ts_err,
                            role="assistant",
                            kind="model",
                            author_username=u.username,
                            author_alias=u.username,
                            content=final_stream_text,
                            meta=_flow_stream_meta(),
                        )
                    except Exception:
                        pass
                    try:
                        hub.publish(pid, sid, event="done", data={"msg_id": run_stream_msg_id, "ok": False, "error": str(exc)})
                    except Exception:
                        pass
                _publish_flow_status({"running": False, "paused": False, "pause_requested": False, "error": str(exc)})
            finally:
                if ai_jobs:
                    ai_jobs.remove(run_id)
                try:
                    cancelled = getattr(app.state, "ai_jobs_cancelled", None)
                    if isinstance(cancelled, dict):
                        cancelled.pop(run_id, None)
                except Exception:
                    pass

        threading.Thread(target=_run_flow, daemon=True).start()

        _publish_flow_status({})
        return {"ok": True, "run_id": run_id, "flow_name": flow_name, "flow_version": version_diag, "state": state}

    @r.get("/v1/projects/{pid}/sessions/{sid}/agent_flow/status")
    def agent_flow_status(pid: str, sid: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        run_id = str(request.query_params.get("run_id") or "").strip()
        state = _agent_flow_get_state(pid, sid, run_id)
        return {"ok": True, "state": state or {"running": False}}

    @r.post("/v1/projects/{pid}/sessions/{sid}/agent_flow/pause")
    def agent_flow_pause(pid: str, sid: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        run_id = str(request.query_params.get("run_id") or "").strip()
        state = _agent_flow_get_state(pid, sid, run_id)
        if not state:
            raise HTTPException(status_code=404, detail="agent flow run not found")
        if not state.get("running"):
            return {"ok": True, "state": state}
        step_index = int(state.get("step_index") or 0)
        steps_total = int(state.get("steps_total") or len(state.get("steps") or []) or 0)
        state["paused"] = False
        state["pause_requested"] = True
        state["status"] = f"Pausing after current node {min(step_index + 1, steps_total)}/{steps_total}" if steps_total else "Pausing"
        state["ts"] = _now_ts()
        _agent_flow_set_state(pid, sid, state, preserve_pause=False)
        _agent_flow_publish_state(pid, sid, state)
        return {"ok": True, "state": state}

    @r.post("/v1/projects/{pid}/sessions/{sid}/agent_flow/resume")
    def agent_flow_resume(pid: str, sid: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        run_id = str(request.query_params.get("run_id") or "").strip()
        state = _agent_flow_get_state(pid, sid, run_id)
        if not state:
            raise HTTPException(status_code=404, detail="agent flow run not found")
        if not state.get("running"):
            return {"ok": True, "state": state}
        step_index = int(state.get("step_index") or 0)
        steps_total = int(state.get("steps_total") or len(state.get("steps") or []) or 0)
        state["paused"] = False
        state["pause_requested"] = False
        state["status"] = f"Running {min(step_index + 1, steps_total)}/{steps_total}" if steps_total else "Running"
        state["ts"] = _now_ts()
        _agent_flow_set_state(pid, sid, state, preserve_pause=False)
        _agent_flow_publish_state(pid, sid, state)
        return {"ok": True, "state": state}

    @r.post("/v1/projects/{pid}/sessions/{sid}/agent_flow/interaction")
    def agent_flow_interaction(pid: str, sid: str, payload: Dict[str, Any], request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        run_id = str((payload or {}).get("run_id") or request.query_params.get("run_id") or "").strip()
        state = _agent_flow_get_state(pid, sid, run_id)
        if not state:
            raise HTTPException(status_code=404, detail="agent flow run not found")
        interaction = state.get("interaction") if isinstance(state.get("interaction"), dict) else None
        if not interaction:
            raise HTTPException(status_code=400, detail="no pending interaction")
        incoming_id = str((payload or {}).get("interaction_id") or (payload or {}).get("id") or "").strip()
        current_id = str(interaction.get("id") or "").strip()
        if incoming_id and current_id and incoming_id != current_id:
            raise HTTPException(status_code=409, detail="interaction id mismatch")
        response = {
            "action": str((payload or {}).get("action") or "").strip().lower(),
            "text": str((payload or {}).get("text") or "").strip(),
            "username": getattr(u, "username", ""),
            "ts": _now_ts(),
        }
        if str(interaction.get("type") or "").strip().lower() == "approval":
            if response["action"] not in {"yes", "no", "skip"}:
                raise HTTPException(status_code=400, detail="approval action must be yes, no, or skip")
        elif not response["text"] and not response["action"]:
            raise HTTPException(status_code=400, detail="clarification text required")
        interaction = dict(interaction)
        interaction["status"] = "answered"
        interaction["response"] = response
        state["interaction"] = interaction
        state["ts"] = _now_ts()
        _agent_flow_set_state(pid, sid, state, preserve_pause=False)
        _agent_flow_publish_state(pid, sid, state)
        return {"ok": True, "state": state}

    @r.post("/v1/projects/{pid}/sessions/{sid}/agent_flow/steer")
    def agent_flow_steer(pid: str, sid: str, payload: Dict[str, Any], request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        run_id = str((payload or {}).get("run_id") or request.query_params.get("run_id") or "").strip()
        state = _agent_flow_get_state(pid, sid, run_id)
        if not state:
            raise HTTPException(status_code=404, detail="agent flow run not found")
        if not state.get("running"):
            return {"ok": True, "state": state}
        message = str((payload or {}).get("message") or (payload or {}).get("text") or "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="steer message required")
        steers = state.get("steers") if isinstance(state.get("steers"), list) else []
        steers.append({
            "message": message,
            "target": str((payload or {}).get("target") or "next").strip() or "next",
            "username": getattr(u, "username", ""),
            "ts": _now_ts(),
        })
        state["steers"] = steers[-50:]
        state["ts"] = _now_ts()
        _agent_flow_set_state(pid, sid, state, preserve_pause=False)
        _agent_flow_publish_state(pid, sid, state)
        return {"ok": True, "state": state}

    @r.get("/v1/projects/{pid}/sessions/{sid}/agent_flow/skills")
    def agent_flow_skills(pid: str, sid: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        current = getattr(app.state, "agent_flow_skill_specs", None)
        if not isinstance(current, dict):
            register_agent_flow_skills(app)
            current = getattr(app.state, "agent_flow_skill_specs", None)
        categories = getattr(app.state, "agent_flow_skill_categories", None)
        warnings = getattr(app.state, "agent_flow_skill_load_warnings", None)
        current_skills = current if isinstance(current, dict) else {}
        current_categories = categories if isinstance(categories, dict) else {}
        try:
            from plugins.gui_helpers.permissions_manager.core import can_access_skill, compute_effective_permissions
            permission_summary = compute_effective_permissions(app, u)
            if not permission_summary.get("is_admin"):
                allowed_ids = {sid for sid in current_skills.keys() if can_access_skill(permission_summary, sid)}
                current_skills = {sid: spec for sid, spec in current_skills.items() if sid in allowed_ids}
                current_categories = {
                    cat: [sid for sid in rows if sid in allowed_ids]
                    for cat, rows in current_categories.items()
                    if isinstance(rows, list) and [sid for sid in rows if sid in allowed_ids]
                }
        except Exception:
            pass
        return {
            "ok": True,
            "skills": current_skills,
            "categories": current_categories,
            "warnings": warnings if isinstance(warnings, list) else [],
            "initial_load": skill_load_info if isinstance(skill_load_info, dict) else {},
        }

    @r.get("/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library")
    def agent_flow_temp_library_list(
        pid: str,
        sid: str,
        request: Request,
        q: str = Query(""),
        page: int = Query(1, ge=1),
        page_size: int = Query(12, ge=1, le=50),
    ):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        query = str(q or "").strip()
        requested_page_size = max(1, min(int(page_size or 12), 50))
        requested_page = max(1, int(page or 1))
        offset = (requested_page - 1) * requested_page_size
        rows, total = _workflow_store.fetch_scope_rows_page(
            _temp_library_ctx(pid),
            scope="temp_library",
            pid="__temp_library__",
            query=query,
            limit=requested_page_size,
            offset=offset,
        )

        items: List[Dict[str, Any]] = []
        hidden_count = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            access = _temp_library_record_skill_access(u, row)
            if not access.get("allowed"):
                hidden_count += 1
                continue
            items.append(_temp_library_record_public(row, pid=pid, sid=sid))

        total_pages = max(1, (total + requested_page_size - 1) // requested_page_size) if total else 1
        page = min(requested_page, total_pages)
        return {
            "ok": True,
            "records": items,
            "count": len(items),
            "total": total,
            "page": page,
            "page_size": requested_page_size,
            "total_pages": total_pages,
            "query": query,
            "hidden_count": hidden_count,
        }

    @r.post("/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library/import_bundle")
    async def agent_flow_temp_library_import_bundle(pid: str, sid: str, request: Request, file: UploadFile = File(...)):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        out = await _import_bundle_to_temp_library(pid, file)
        rec = out.get("record") if isinstance(out, dict) and isinstance(out.get("record"), dict) else None
        if not isinstance(rec, dict):
            raise HTTPException(status_code=400, detail="bundle_import_failed")
        return {
            "ok": True,
            "record": _temp_library_record_public(rec, pid=pid, sid=sid),
            "flow_name": out.get("flow_name"),
            "flow_names": out.get("flow_names") or [],
            "warnings": out.get("warnings") or [],
        }

    @r.delete("/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library/{record_id}")
    def agent_flow_temp_library_delete(pid: str, sid: str, record_id: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        out = workflow_temp_library.run(_temp_library_ctx(pid), {"action": "delete", "record_id": record_id})
        if not isinstance(out, dict) or not out.get("ok"):
            raise HTTPException(status_code=404, detail="temp workflow not found")
        return {"ok": True, "deleted": True, "record_id": record_id}

    @r.post("/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library/{record_id}/export_workflow")
    def agent_flow_temp_library_export_workflow(pid: str, sid: str, record_id: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        rec = _temp_library_record(pid, record_id)
        _require_temp_library_record_access(u, rec, action="export")
        wf = _resolve_generated_path(str(rec.get("workflow_file") or "").strip()).resolve()
        if not wf.is_file():
            raise HTTPException(status_code=404, detail="workflow file not found")
        export_payload = _compose_temp_library_export(pid, rec)
        canonical_json = str(export_payload.get("canonical_json") or "")
        staged = _stage_text_for_download_global(
            canonical_json,
            out_name=wf.name,
            suffix_seed=record_id,
        )
        return {"ok": True, "record": _temp_library_record_public(rec, pid=pid, sid=sid), "file": staged, "download_url": staged.get("download_url")}

    @r.post("/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library/{record_id}/export_bundle")
    def agent_flow_temp_library_export_bundle(pid: str, sid: str, record_id: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        rec = _temp_library_record(pid, record_id)
        _require_temp_library_record_access(u, rec, action="export")
        staged = _stage_temp_library_export_bundle(pid, rec)
        return {"ok": True, "record": _temp_library_record_public(rec, pid=pid, sid=sid), "zip": staged, "download_url": staged.get("download_url")}

    @r.post("/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library/{record_id}/install")
    def agent_flow_temp_library_install(pid: str, sid: str, record_id: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        rec0 = _temp_library_record(pid, record_id)
        _require_temp_library_record_access(u, rec0, action="install")
        out = _install_temp_library_record(pid, record_id)
        rec = out.get("record") if isinstance(out, dict) and isinstance(out.get("record"), dict) else _temp_library_record(pid, record_id)
        return {
            "ok": True,
            "record": _temp_library_record_public(rec, pid=pid, sid=sid),
            "flow_name": out.get("flow_name"),
            "skill_files": out.get("skill_files") or [],
            "skill_ids": out.get("skill_ids") or [],
            "skill_load": out.get("skill_load") if isinstance(out.get("skill_load"), dict) else {},
        }

    @r.post("/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library/{record_id}/uninstall")
    def agent_flow_temp_library_uninstall(pid: str, sid: str, record_id: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        rec0 = _temp_library_record(pid, record_id)
        _require_temp_library_record_access(u, rec0, action="uninstall")
        out = _uninstall_temp_library_record(pid, record_id)
        rec = out.get("record") if isinstance(out, dict) and isinstance(out.get("record"), dict) else _temp_library_record(pid, record_id)
        return {
            "ok": True,
            "record": _temp_library_record_public(rec, pid=pid, sid=sid),
            "removed_files": out.get("removed_files") or [],
            "skill_load": out.get("skill_load") if isinstance(out.get("skill_load"), dict) else {},
        }

    @r.post("/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library/{record_id}/validate")
    def agent_flow_temp_library_validate(pid: str, sid: str, record_id: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        rec = _temp_library_record(pid, record_id)
        _require_temp_library_record_access(u, rec, action="validate")
        request_text = f"Validate the temp library workflow {str(rec.get('flow_name') or record_id).strip() or 'workflow'} and confirm whether it still passes the sandbox suite."
        _temp_library_update(pid, record_id, {
            "validation_pending": True,
            "last_validation_status": "running",
            "last_validation_run_id": "",
            "last_validation_ts": _now_ts(),
        })

        try:
            from plugins.gui_helpers.agent_flow.skills.workflow._common import load_workflow_target as _load_workflow_target_direct
            from plugins.gui_helpers.agent_flow.skills.workflow.run_suite import _looks_like_direct_custom_tool_flow as _looks_like_direct_custom_tool_flow_direct
            from plugins.gui_helpers.agent_flow.skills.workflow.run_suite_capability import run as _run_suite_capability_direct

            direct_ctx = {
                "app": app,
                "pid": pid,
                "settings": {},
                "user_text": request_text,
                "original_request": request_text,
            }
            target = _load_workflow_target_direct(
                direct_ctx,
                {
                    "bundle_dir": str(rec.get("bundle_dir") or "").strip(),
                    "workflow_file": str(rec.get("workflow_file") or "").strip(),
                    "flow_name": str(rec.get("flow_name") or "").strip(),
                    "pid": pid,
                },
            )
            target_flow = target.get("workflow_json") if isinstance(target.get("workflow_json"), dict) else {}
            if target.get("ok") and _looks_like_direct_custom_tool_flow_direct(target_flow):
                source_request = str(rec.get("last_request") or rec.get("source_request") or request_text).strip() or request_text
                direct_result = _run_suite_capability_direct(
                    direct_ctx,
                    {
                        "bundle_dir": str(rec.get("bundle_dir") or "").strip(),
                        "workflow_file": str(rec.get("workflow_file") or "").strip(),
                        "flow_name": str(rec.get("flow_name") or "").strip(),
                        "pid": pid,
                        "request_text": source_request,
                        "current_request_text": source_request,
                        "user_request": source_request,
                        "min_requests": 1,
                        "max_requests": 1,
                        "max_request_wait_s": 25,
                        "poll_interval_s": 1,
                    },
                )
                validation_ok = bool((direct_result or {}).get("all_passed"))
                validation_bugs = list((direct_result or {}).get("bugs") or []) if isinstance((direct_result or {}).get("bugs"), list) else []
                summary = f"Direct validation completed with {int((direct_result or {}).get('pass_count') or 0)} pass and {int((direct_result or {}).get('fail_count') or 0)} fail result(s)."
                _temp_library_update(pid, record_id, {
                    "validated": validation_ok,
                    "all_passed": validation_ok,
                    "pass_count": int((direct_result or {}).get("pass_count") or 0),
                    "fail_count": int((direct_result or {}).get("fail_count") or 0),
                    "validation_pending": False,
                    "last_validation_ok": validation_ok,
                    "last_validation_status": "passed" if validation_ok else "failed",
                    "last_validation_ts": _now_ts(),
                    "last_validation_run_id": "",
                    "bugs": validation_bugs,
                    "fixes": [],
                    "fix_summary": summary,
                })
                rec2 = _temp_library_record(pid, record_id)
                return {
                    "ok": True,
                    "record": _temp_library_record_public(rec2, pid=pid, sid=sid),
                    "run": {
                        "ok": True,
                        "run_id": "",
                        "state": {
                            "running": False,
                            "paused": False,
                            "pause_requested": False,
                            "status": "Completed",
                            "step_index": 3,
                            "steps_total": 4,
                        },
                    },
                    "validation_result": direct_result,
                    "validation_mode": "direct_custom_tool",
                }
        except Exception:
            pass

        validator_flow = "workflow_designer_validator_sandbox"
        flows_doc = _load_project_flows(pid)
        flows = flows_doc.get("flows") if isinstance(flows_doc, dict) and isinstance(flows_doc.get("flows"), dict) else {}
        if not isinstance(flows, dict) or validator_flow not in flows:
            flows = _default_flow_library() or {}
        if validator_flow not in flows:
            raise HTTPException(status_code=404, detail="validator workflow not found")
        req2 = AgentFlowRunRequest(
            text=request_text,
            ext={
                "agent_flow_flows": flows,
                "agent_flow_active_flow": validator_flow,
                "agent_flow_default_flow": validator_flow,
                "bundle_dir": str(rec.get("bundle_dir") or "").strip(),
                "workflow_file": str(rec.get("workflow_file") or "").strip(),
                "flow_name": str(rec.get("flow_name") or "").strip(),
                "agent_flow_temp_library_record_id": record_id,
                "pid": pid,
            },
        )
        try:
            out = agent_flow_run(pid, sid, req2, request)
        except Exception:
            try:
                _temp_library_update(pid, record_id, {
                    "validation_pending": False,
                    "last_validation_status": "failed_to_start",
                    "last_validation_ts": _now_ts(),
                })
            except Exception:
                pass
            raise
        rec2 = _temp_library_record(pid, record_id)
        return {"ok": True, "record": _temp_library_record_public(rec2, pid=pid, sid=sid), "run": out}

    @r.get("/v1/projects/{pid}/sessions/{sid}/agent_flow/flows")
    def agent_flow_flows(pid: str, sid: str, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        data = _load_project_flows(pid)
        flows = data.get("flows") if isinstance(data, dict) and isinstance(data.get("flows"), dict) else {}
        project_records = _workflow_store.project_flow_records({"app": app, "pid": pid}, pid)
        default_records = _workflow_store.default_flow_records({"app": app})
        if not flows:
            # Fallback to bundled defaults so a missing/empty project file does not
            # present "no flow" in the UI.
            flows = _default_flow_library() or {}
        visible_flows = _filter_flows_for_user(u, flows)
        visible_default_flows = _filter_flows_for_user(u, _default_flow_library() or {})
        visible_names = set(visible_flows.keys())
        return {
            "ok": True,
            "flows": visible_flows,
            "flow_ids_by_name": {k: v for k, v in _workflow_store.flow_ids_by_name(project_records).items() if k in visible_names},
            "default_flow_ids_by_name": {k: v for k, v in _workflow_store.flow_ids_by_name(default_records).items() if k in visible_names},
            "flow_hashes": {str(k): _canonical_hash(v) for k, v in visible_flows.items()},
            "default_flow_hashes": {str(k): _canonical_hash(v) for k, v in visible_default_flows.items()},
            "hidden_count": max(0, len(flows or {}) - len(visible_flows)),
        }

    @r.post("/v1/projects/{pid}/sessions/{sid}/agent_flow/flows")
    def agent_flow_flows_save(pid: str, sid: str, payload: Dict[str, Any], request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        flows = payload.get("flows") if isinstance(payload, dict) else None
        prior_ids_by_name = payload.get("flow_ids_by_name") if isinstance(payload, dict) else None
        if not isinstance(flows, dict):
            raise HTTPException(status_code=400, detail="flows required")
        _save_project_flows(pid, flows, prior_ids_by_name if isinstance(prior_ids_by_name, dict) else None)
        records = _workflow_store.project_flow_records({"app": app, "pid": pid}, pid)
        visible_flows = _filter_flows_for_user(u, flows)
        visible_names = set(visible_flows.keys())
        return {
            "ok": True,
            "flows": visible_flows,
            "flow_ids_by_name": {k: v for k, v in _workflow_store.flow_ids_by_name(records).items() if k in visible_names},
            "hidden_count": max(0, len(flows or {}) - len(visible_flows)),
        }

    @r.post("/v1/projects/{pid}/sessions/{sid}/agent_flow/flows/import")
    def agent_flow_flows_import(pid: str, sid: str, payload: Dict[str, Any], request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)

        raw = payload.get("import")
        replace_mode = bool(payload.get("replace"))
        # Imports merge by default so one import source cannot wipe unrelated flows.
        # Use {replace: true} only for an explicit destructive replace/reset operation.
        merge_mode = not replace_mode if "merge" not in payload else bool(payload.get("merge"))
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"invalid import JSON: {exc}")
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="import payload must be object or JSON string")

        if isinstance(raw.get("agent_flow"), dict):
            raw = dict(raw.get("agent_flow") or {})
        flows = raw.get("flows") if isinstance(raw.get("flows"), dict) else {}
        if not flows and isinstance(raw.get("agent_flow_flows"), dict):
            flows = dict(raw.get("agent_flow_flows") or {})
        if not isinstance(flows, dict) or not flows:
            raise HTTPException(status_code=400, detail="import must include non-empty flows")

        default_flow = str(
            raw.get("default_flow")
            or raw.get("agent_flow_default_flow")
            or ""
        ).strip()
        active_flow = str(
            raw.get("active_flow")
            or raw.get("agent_flow_active_flow")
            or ""
        ).strip()
        mode = str(raw.get("mode") or raw.get("agent_flow_mode") or "execute").strip().lower() or "execute"

        if merge_mode:
            existing = _load_project_flows(pid).get("flows") or {}
            if not isinstance(existing, dict):
                existing = {}
            flows = {**existing, **flows}

        _save_project_flows(pid, flows)
        records = _workflow_store.project_flow_records({"app": app, "pid": pid}, pid)
        visible_flows = _filter_flows_for_user(u, flows)
        visible_names = set(visible_flows.keys())
        flow_hashes = {str(k): _canonical_hash(v) for k, v in visible_flows.items()}
        selected_flow_name = active_flow or default_flow
        selected_flow = visible_flows.get(selected_flow_name) if selected_flow_name and isinstance(visible_flows.get(selected_flow_name), dict) else {}
        visible_default_flow = default_flow if default_flow in visible_flows else ""
        visible_active_flow = active_flow if active_flow in visible_flows else (visible_default_flow or (next(iter(visible_flows.keys())) if visible_flows else ""))
        max_steps = _resolve_max_steps(selected_flow, raw.get("max_steps") or raw.get("agent_flow_max_steps"), default_floor=8)
        return {
            "ok": True,
            "flows": visible_flows,
            "flow_ids_by_name": {k: v for k, v in _workflow_store.flow_ids_by_name(records).items() if k in visible_names},
            "flow_hashes": flow_hashes,
            "hidden_count": max(0, len(flows or {}) - len(visible_flows)),
            "agent_flow_settings": {
                "agent_flow_flows": visible_flows,
                "agent_flow_default_flow": visible_default_flow,
                "agent_flow_active_flow": visible_active_flow,
                "agent_flow_max_steps": max(1, min(128, max_steps)),
                "agent_flow_mode": mode,
            },
        }

    @r.post("/v1/projects/{pid}/sessions/{sid}/agent_flow/flows/export_workflow")
    def agent_flow_flows_export_workflow(pid: str, sid: str, payload: Dict[str, Any], request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        flow_name = str((payload or {}).get("flow_name") or "").strip()
        flow_value = (payload or {}).get("workflow_json")
        flow_doc, resolved_name, warnings = ensure_flow_payload(flow_value, flow_name)
        if not isinstance(flow_doc, dict):
            raise HTTPException(status_code=400, detail="workflow_json required")
        _require_flow_access(u, str(resolved_name or flow_name), flow_doc, action="export")
        ctx2 = _temp_library_ctx(pid)
        out = workflow_export_skill.run(ctx2, {"workflow_json": flow_doc, "flow_name": resolved_name or flow_name})
        workflow_file = Path(str(out.get("workflow_file") or "").strip()).resolve()
        if not workflow_file.is_file():
            raise HTTPException(status_code=500, detail="exported workflow file not found")
        staged = _stage_path_for_download_global(
            workflow_file,
            out_name=workflow_file.name,
            suffix_seed=str(resolved_name or flow_name or "workflow"),
        )
        return {
            "ok": True,
            "flow_name": str(out.get("flow_name") or resolved_name or flow_name),
            "file": staged,
            "download_url": staged.get("download_url"),
            "warnings": list(warnings or []) + list(out.get("warnings") or []),
        }

    @r.post("/v1/projects/{pid}/sessions/{sid}/agent_flow/flows/export_bundle")
    def agent_flow_flows_export_bundle(pid: str, sid: str, payload: Dict[str, Any], request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        flow_name = str((payload or {}).get("flow_name") or "").strip()
        flow_value = (payload or {}).get("workflow_json")
        flow_doc, resolved_name, warnings = ensure_flow_payload(flow_value, flow_name)
        if not isinstance(flow_doc, dict):
            raise HTTPException(status_code=400, detail="workflow_json required")
        _require_flow_access(u, str(resolved_name or flow_name), flow_doc, action="export")
        ctx2 = _temp_library_ctx(pid)
        out = workflow_export_skill.run(ctx2, {"workflow_json": flow_doc, "flow_name": resolved_name or flow_name})
        bundle_dir = Path(str(out.get("bundle_dir") or "").strip()).resolve()
        if not bundle_dir.is_dir():
            raise HTTPException(status_code=500, detail="exported bundle directory not found")
        export_name = str(out.get("flow_name") or resolved_name or flow_name or "workflow").strip() or "workflow"
        export_slug = re.sub(r"[^a-z0-9]+", "_", export_name.lower()).strip("_") or "workflow"
        staged = _stage_directory_zip_for_download_global(
            bundle_dir,
            archive_name=f"{export_slug}_bundle.zip",
            suffix_seed=export_slug,
        )
        return {
            "ok": True,
            "flow_name": export_name,
            "zip": staged,
            "download_url": staged.get("download_url"),
            "warnings": list(warnings or []) + list(out.get("warnings") or []),
        }

    app.include_router(r)
    print("[gui_helpers] agent_flow routes installed")
    @r.post("/v1/projects/{pid}/sessions/{sid}/agent_flow/flows/export_workflow")
    def agent_flow_flows_export_workflow(pid: str, sid: str, payload: Dict[str, Any], request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        flow_name = str((payload or {}).get("flow_name") or "").strip()
        flow_value = (payload or {}).get("workflow_json")
        flow_doc, resolved_name, warnings = ensure_flow_payload(flow_value, flow_name)
        if not isinstance(flow_doc, dict):
            raise HTTPException(status_code=400, detail="workflow_json required")
        _require_flow_access(u, str(resolved_name or flow_name), flow_doc, action="export")
        ctx2 = _temp_library_ctx(pid)
        out = workflow_export_skill.run(ctx2, {"workflow_json": flow_doc, "flow_name": resolved_name or flow_name})
        workflow_file = Path(str(out.get("workflow_file") or "").strip()).resolve()
        if not workflow_file.is_file():
            raise HTTPException(status_code=500, detail="exported workflow file not found")
        staged = _stage_path_for_download_global(
            workflow_file,
            out_name=workflow_file.name,
            suffix_seed=str(resolved_name or flow_name or "workflow"),
        )
        return {
            "ok": True,
            "flow_name": str(out.get("flow_name") or resolved_name or flow_name),
            "file": staged,
            "download_url": staged.get("download_url"),
            "warnings": list(warnings or []) + list(out.get("warnings") or []),
        }

    @r.post("/v1/projects/{pid}/sessions/{sid}/agent_flow/flows/export_bundle")
    def agent_flow_flows_export_bundle(pid: str, sid: str, payload: Dict[str, Any], request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        u = _require_user(app, request)
        _require_session_access(app, u, pid, sid)
        flow_name = str((payload or {}).get("flow_name") or "").strip()
        flow_value = (payload or {}).get("workflow_json")
        flow_doc, resolved_name, warnings = ensure_flow_payload(flow_value, flow_name)
        if not isinstance(flow_doc, dict):
            raise HTTPException(status_code=400, detail="workflow_json required")
        _require_flow_access(u, str(resolved_name or flow_name), flow_doc, action="export")
        ctx2 = _temp_library_ctx(pid)
        out = workflow_export_skill.run(ctx2, {"workflow_json": flow_doc, "flow_name": resolved_name or flow_name})
        bundle_dir = Path(str(out.get("bundle_dir") or "").strip()).resolve()
        if not bundle_dir.is_dir():
            raise HTTPException(status_code=500, detail="exported bundle directory not found")
        export_name = str(out.get("flow_name") or resolved_name or flow_name or "workflow").strip() or "workflow"
        export_slug = re.sub(r"[^a-z0-9]+", "_", export_name.lower()).strip("_") or "workflow"
        staged = _stage_directory_zip_for_download_global(
            bundle_dir,
            archive_name=f"{export_slug}_bundle.zip",
            suffix_seed=export_slug,
        )
        return {
            "ok": True,
            "flow_name": export_name,
            "zip": staged,
            "download_url": staged.get("download_url"),
            "warnings": list(warnings or []) + list(out.get("warnings") or []),
        }

    app.include_router(r)
    print("[gui_helpers] agent_flow routes installed")
