from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys
import importlib.util as _importlib_util
import re

_HERE = _Path(__file__).resolve().parent
_WF_DIR = _HERE.parent / "workflow"
if str(_WF_DIR) in _sys.path:
    _sys.path.remove(str(_WF_DIR))
_sys.path.insert(0, str(_WF_DIR))

from pathlib import Path
from typing import Any, Dict, List

_COMMON_SPEC = _importlib_util.spec_from_file_location("agent_flow_workflow_common_for_exchange_repair", _WF_DIR / "_common.py")
if _COMMON_SPEC is None or _COMMON_SPEC.loader is None:
    raise RuntimeError("cannot_load_agent_flow_workflow_common_for_repair")
_COMMON_MOD = _importlib_util.module_from_spec(_COMMON_SPEC)
_sys.modules[_COMMON_SPEC.name] = _COMMON_MOD
_COMMON_SPEC.loader.exec_module(_COMMON_MOD)

_IMPLEMENT_SPEC = _importlib_util.spec_from_file_location("agent_flow_workflow_implement_skills_for_exchange_repair", _WF_DIR / "implement_skills.py")
if _IMPLEMENT_SPEC is None or _IMPLEMENT_SPEC.loader is None:
    raise RuntimeError("cannot_load_agent_flow_workflow_implement_skills_for_repair")
_IMPLEMENT_MOD = _importlib_util.module_from_spec(_IMPLEMENT_SPEC)
_sys.modules[_IMPLEMENT_SPEC.name] = _IMPLEMENT_MOD
_IMPLEMENT_SPEC.loader.exec_module(_IMPLEMENT_MOD)

atomic_write_text = _COMMON_MOD.atomic_write_text
ensure_flow_payload = _COMMON_MOD.ensure_flow_payload
extract_referenced_skills = _COMMON_MOD.extract_referenced_skills
normalize_missing_skill_specs = _COMMON_MOD.normalize_missing_skill_specs
generate_skill_files = _IMPLEMENT_MOD.generate_skill_files


NAME = "workflow_exchange.local_skill_repair"
PERMISSIONS = ["workflow_exchange.local_skill_repair", "workflow_exchange.*", "workflow.*"]
_META = {
    "version": "1.0",
    "created_at": "2026-06-16T00:00:00+00:00",
    "last_updated": "2026-06-16T00:00:00+00:00",
    "dev_status": "untested",
}

_SMALL_FILE_BYTES = 64 * 1024
_HEAD_LINES = 160
_TAIL_LINES = 80


def _resolve_specs(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = params.get("missing_skill_specs")
    if raw is None:
        raw = params.get("skill_specs")
    specs = normalize_missing_skill_specs(raw)
    if specs:
        return specs
    rows = params.get("skill_specs") if isinstance(params.get("skill_specs"), list) else []
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "id": str(row.get("skill_id") or row.get("id") or "").strip(),
                "label": str(row.get("label") or row.get("skill_id") or row.get("id") or "").strip(),
                "description": str(row.get("description") or row.get("intent") or "").strip(),
                "reason": str(row.get("intent") or "").strip(),
                "category": str(row.get("category") or "custom").strip(),
                "params_schema": dict(row.get("params_schema") or {}) if isinstance(row.get("params_schema"), dict) else {},
                "metadata": dict(row.get("metadata") or {}) if isinstance(row.get("metadata"), dict) else {},
                "implementation_hint": str(row.get("implementation_hint") or "").strip(),
            }
        )
    return normalize_missing_skill_specs(out)


def _bug_signals(params: Dict[str, Any]) -> List[str]:
    rows: List[str] = []
    for raw in (
        params.get("bugs"),
        ((params.get("comparison") or {}).get("candidate") or {}).get("bugs") if isinstance(params.get("comparison"), dict) else [],
        ((params.get("comparison") or {}).get("baseline") or {}).get("bugs") if isinstance(params.get("comparison"), dict) else [],
    ):
        if not isinstance(raw, list):
            continue
        for item in raw:
            text = str(item or "").strip()
            if text and text not in rows:
                rows.append(text)
    review_summary = str(params.get("review_summary") or "").strip()
    if review_summary:
        rows.append(f"review_summary:{review_summary}")
    return rows[:32]


def _skill_file_summary(path: Path) -> Dict[str, Any]:
    size = 0
    try:
        size = int(path.stat().st_size)
    except Exception:
        pass
    summary: Dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": size,
        "mode": "missing",
        "has_run": False,
        "has_tool_spec": False,
        "has_name": False,
        "looks_stub": False,
        "looks_generated": False,
        "line_count_estimate": 0,
        "sample": "",
    }
    if not path.exists():
        return summary
    if size <= _SMALL_FILE_BYTES:
        text = path.read_text(encoding="utf-8", errors="replace")
        low = text.lower()
        summary["mode"] = "full"
        summary["line_count_estimate"] = text.count("\n") + (1 if text else 0)
        summary["has_run"] = "def run(" in text
        summary["has_tool_spec"] = "TOOL_SPEC =" in text
        summary["has_name"] = "NAME =" in text
        summary["looks_stub"] = "todo_skill_not_implemented" in text
        summary["looks_generated"] = "Generated a bounded authored deliverable." in text or "TOOL_SPEC =" in text
        summary["sample"] = text[:8000]
        summary["syntax_signals"] = {
            "future_annotations": "from __future__ import annotations" in text,
            "imports_json": "import json" in text,
            "imports_path": "from pathlib import Path" in text,
            "balanced_run": text.count("def run("),
        }
        summary["low_markers"] = [
            marker
            for marker in (
                "todo_skill_not_implemented",
                "generated a bounded authored deliverable",
                "tool_spec =",
                "def run(",
            )
            if marker in low
        ]
        return summary
    head: List[str] = []
    tail: List[str] = []
    line_no = 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line_no += 1
            if len(head) < _HEAD_LINES:
                head.append(raw.rstrip("\n"))
            tail.append(raw.rstrip("\n"))
            if len(tail) > _TAIL_LINES:
                tail.pop(0)
    sample = "\n".join(head + ["", "# ... large file middle omitted ...", ""] + tail)
    summary["mode"] = "sampled"
    summary["line_count_estimate"] = line_no
    summary["sample"] = sample[:12000]
    summary["has_run"] = "def run(" in sample
    summary["has_tool_spec"] = "TOOL_SPEC =" in sample
    summary["has_name"] = "NAME =" in sample
    low = sample.lower()
    summary["looks_stub"] = "todo_skill_not_implemented" in low
    summary["looks_generated"] = "generated a bounded authored deliverable" in low or "tool_spec =" in low
    return summary


def _target_path(bundle_dir: Path, rel_path: str) -> Path:
    return bundle_dir / str(rel_path or "").strip().replace("\\", "/")


def _bugs_for_skill(skill_id: str, bugs: List[str]) -> List[str]:
    low_id = str(skill_id or "").strip().lower()
    out = []
    for bug in bugs:
        low = str(bug or "").lower()
        if low_id and low_id in low:
            out.append(str(bug))
            continue
        if any(token in low for token in ("todo_skill_not_implemented", "capability_missing:", "invalid", "syntax", "traceback", "exception", "importerror", "modulenotfounderror")):
            out.append(str(bug))
    return out[:12]


def _repair_strategy(summary: Dict[str, Any], skill_id: str, bugs: List[str], desired_content: str) -> str:
    if not summary.get("exists"):
        return "write_missing"
    if summary.get("mode") == "full" and str(summary.get("sample") or "") == str(desired_content or ""):
        return "unchanged"
    if not summary.get("has_run") or not summary.get("has_tool_spec") or not summary.get("has_name"):
        return "overwrite_structural_repair"
    if summary.get("looks_stub"):
        return "overwrite_stub"
    skill_bugs = _bugs_for_skill(skill_id, bugs)
    if summary.get("mode") == "sampled":
        if skill_bugs:
            return "overwrite_large_generated_repair"
        return "preserve_large_existing"
    if skill_bugs and summary.get("looks_generated"):
        return "overwrite_bug_repair"
    if skill_bugs:
        return "preserve_manual_review"
    return "preserve_existing"


def _short_diff_summary(existing_sample: str, desired_content: str) -> Dict[str, Any]:
    existing_lines = [line for line in str(existing_sample or "").splitlines() if line.strip()]
    desired_lines = [line for line in str(desired_content or "").splitlines() if line.strip()]
    existing_defs = [line.strip() for line in existing_lines if line.strip().startswith("def ")][:12]
    desired_defs = [line.strip() for line in desired_lines if line.strip().startswith("def ")][:12]
    return {
        "existing_defs": existing_defs,
        "desired_defs": desired_defs,
        "existing_line_count": len(existing_lines),
        "desired_line_count": len(desired_lines),
    }


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    bundle_dir_raw = str(params.get("bundle_dir") or "").strip()
    workflow_value = params.get("workflow_json") if params.get("workflow_json") is not None else params.get("workflow")
    flow, flow_name, warnings = ensure_flow_payload(workflow_value, str(params.get("flow_name") or "").strip())
    if not bundle_dir_raw:
        return {"ok": False, "error": "bundle_dir_missing", "warnings": ["bundle_dir_missing"], "data": {}}
    bundle_dir = Path(bundle_dir_raw)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    specs = _resolve_specs(params)
    generated = generate_skill_files(specs)
    bugs = _bug_signals(params)
    results: List[Dict[str, Any]] = []
    written: List[str] = []
    repaired_ids: List[str] = []
    preserved_ids: List[str] = []
    manual_review_ids: List[str] = []
    for row in generated:
        rel_path = str(row.get("path") or "").strip().replace("\\", "/")
        skill_id = str(row.get("skill_id") or "").strip()
        if not rel_path or not skill_id:
            continue
        out_path = _target_path(bundle_dir, rel_path)
        existing = _skill_file_summary(out_path)
        desired_content = str(row.get("content") or "")
        strategy = _repair_strategy(existing, skill_id, bugs, desired_content)
        item = {
            "skill_id": skill_id,
            "path": str(out_path),
            "existing": {
                "exists": existing.get("exists"),
                "mode": existing.get("mode"),
                "size_bytes": existing.get("size_bytes"),
                "line_count_estimate": existing.get("line_count_estimate"),
                "has_run": existing.get("has_run"),
                "has_tool_spec": existing.get("has_tool_spec"),
                "has_name": existing.get("has_name"),
                "looks_stub": existing.get("looks_stub"),
                "looks_generated": existing.get("looks_generated"),
            },
            "strategy": strategy,
            "bug_signals": _bugs_for_skill(skill_id, bugs),
            "diff_summary": _short_diff_summary(existing.get("sample") or "", desired_content),
        }
        if strategy in {"write_missing", "overwrite_structural_repair", "overwrite_stub", "overwrite_large_generated_repair", "overwrite_bug_repair"}:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(out_path, desired_content, make_backup=True)
            written.append(str(out_path))
            repaired_ids.append(skill_id)
            item["changed"] = True
        else:
            item["changed"] = False
            if strategy == "preserve_manual_review":
                manual_review_ids.append(skill_id)
            else:
                preserved_ids.append(skill_id)
        results.append(item)
    referenced = extract_referenced_skills(flow) if isinstance(flow, dict) else []
    implemented_ids = [str(row.get("skill_id") or "") for row in generated if str(row.get("skill_id") or "").strip()]
    unresolved = sorted({skill_id for skill_id in referenced if skill_id and skill_id not in set(implemented_ids)})
    return {
        "ok": True,
        "flow_name": flow_name,
        "bundle_dir": str(bundle_dir),
        "workflow_referenced_skills": referenced,
        "implemented_skill_ids": implemented_ids,
        "repaired_skill_ids": repaired_ids,
        "preserved_skill_ids": preserved_ids,
        "manual_review_skill_ids": manual_review_ids,
        "written_files": written,
        "unresolved_skill_ids": unresolved,
        "warnings": warnings,
        "repair_results": results,
        "bug_signals": bugs,
        "data": {
            "flow_name": flow_name,
            "bundle_dir": str(bundle_dir),
            "workflow_referenced_skills": referenced,
            "implemented_skill_ids": implemented_ids,
            "repaired_skill_ids": repaired_ids,
            "preserved_skill_ids": preserved_ids,
            "manual_review_skill_ids": manual_review_ids,
            "written_files": written,
            "unresolved_skill_ids": unresolved,
            "warnings": warnings,
            "repair_results": results,
            "bug_signals": bugs,
        },
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow_exchange",
    "label": "Workflow Exchange Local Skill Repair",
    "description": "Read existing generated skill files in a bounded way and repair or preserve them using imported skill specs plus evaluation bug signals.",
    "permissions": PERMISSIONS,
    "metadata": _META,
    "params_schema": {
        "type": "object",
        "properties": {
            "bundle_dir": {"type": "string"},
            "flow_name": {"type": "string"},
            "workflow_json": {},
            "missing_skill_specs": {"type": "array", "items": {}},
            "skill_specs": {"type": "array", "items": {}},
            "bugs": {"type": "array", "items": {"type": "string"}},
            "review_summary": {"type": "string"},
            "comparison": {"type": "object"},
        },
        "required": ["bundle_dir"],
        "additionalProperties": True,
    },
}
