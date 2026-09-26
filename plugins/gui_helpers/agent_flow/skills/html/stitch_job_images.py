from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

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


NAME = "html.stitch_job_images"
PERMISSIONS = ["html.stitch_job_images", "html.*"]


_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)


def _template(value: Any, ctx: Dict[str, Any], params: Dict[str, Any]) -> Any:
    if not isinstance(value, str):
        return value
    ext = ctx.get("ext") if isinstance(ctx.get("ext"), dict) else {}
    run_id = str(
        params.get("run_id")
        or params.get("agent_flow_run_id")
        or params.get("workflow_run_id")
        or ctx.get("run_id")
        or ctx.get("agent_flow_run_id")
        or ext.get("run_id")
        or ext.get("agent_flow_run_id")
        or ""
    ).strip()
    return value.replace("{run_id}", run_id)


def _job_snapshot(app: Any, job_ids: List[str]) -> List[Dict[str, Any]]:
    wanted = {str(x or "").strip() for x in job_ids if str(x or "").strip()}
    if not wanted:
        return []
    try:
        reg = getattr(getattr(app, "state", None), "ai_jobs", None)
        rows = reg.snapshot() if reg is not None and hasattr(reg, "snapshot") else []
    except Exception:
        rows = []
    out: List[Dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("job_id") or "").strip() in wanted:
            out.append(dict(row))
    return out


def _image_ref(job: Dict[str, Any]) -> str:
    result = job.get("router_result") if isinstance(job.get("router_result"), dict) else {}
    for source in (result, job):
        if not isinstance(source, dict):
            continue
        for key in ("image_url", "image_path", "url", "path", "output_path"):
            value = str(source.get(key) or "").strip()
            if value:
                return value
    artifact = str(job.get("artifact_text") or "")
    match = re.search(r"(/uploads/[^\s)]+?\.(?:png|jpg|jpeg|webp|gif|bmp))", artifact, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"([A-Za-z]:[\\/][^\n\r]+?\.(?:png|jpg|jpeg|webp|gif|bmp))", artifact, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _set_attr(tag: str, name: str, value: Any) -> str:
    tag = re.sub(r"\s+/\s+(?=[A-Za-z_:][-A-Za-z0-9_:.]*\s*=)", " ", tag)
    text = str(value if value is not None else "").strip()
    if not text:
        return tag
    escaped = text.replace("&", "&amp;").replace('"', "&quot;")
    pattern = re.compile(rf"\s{name}\s*=\s*(['\"]).*?\1", re.IGNORECASE)
    if pattern.search(tag):
        return pattern.sub(f' {name}="{escaped}"', tag, count=1)
    if tag.rstrip().endswith("/>"):
        return tag.rstrip()[:-2].rstrip() + f' {name}="{escaped}" />'
    return tag[:-1].rstrip() + f' {name}="{escaped}">'


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = dict(ctx or {})
    params = dict(params or {})
    app = ctx.get("app")
    html_raw = str(params.get("html_path") or params.get("path") or "").strip()
    if not html_raw:
        return {"ok": False, "data": {}, "warnings": ["html_path_required"]}
    try:
        html_path = resolve_path(ctx, params, html_raw)
    except Exception as exc:
        return {"ok": False, "data": {}, "warnings": [str(exc)]}
    if not html_path.is_file():
        return {"ok": False, "data": {"html_path": str(html_path)}, "warnings": ["html_file_missing"]}

    raw_slots = params.get("slots")
    slots = [dict(row) for row in raw_slots if isinstance(row, dict)] if isinstance(raw_slots, list) else []
    if not slots:
        slots = [dict(row) for row in (params.get("images") or []) if isinstance(row, dict)] if isinstance(params.get("images"), list) else []
    if not slots:
        return {"ok": False, "data": {"html_path": str(html_path)}, "warnings": ["slots_required"]}

    job_ids = [str(_template(slot.get("job_id"), ctx, params) or "").strip() for slot in slots]
    jobs = {str(row.get("job_id") or "").strip(): row for row in _job_snapshot(app, job_ids)}
    html = html_path.read_text(encoding="utf-8", errors="replace")
    matches = list(_IMG_RE.finditer(html))
    if len(matches) < len(slots):
        return {
            "ok": False,
            "data": {"html_path": str(html_path), "img_count": len(matches), "slot_count": len(slots)},
            "warnings": ["not_enough_img_tags"],
        }

    replacements: List[Dict[str, Any]] = []
    missing: List[str] = []
    pieces: List[str] = []
    cursor = 0
    for idx, slot in enumerate(slots):
        match = matches[idx]
        job_id = str(_template(slot.get("job_id"), ctx, params) or "").strip()
        job = jobs.get(job_id) or {}
        src = _image_ref(job)
        if not src:
            missing.append(job_id or f"slot_{idx}")
            src = str(slot.get("fallback_src") or "").strip()
        tag = match.group(0)
        if src:
            tag = _set_attr(tag, "src", src)
        for attr in ("alt", "width", "height", "loading", "decoding"):
            if slot.get(attr) not in (None, ""):
                tag = _set_attr(tag, attr, slot.get(attr))
        pieces.append(html[cursor:match.start()])
        pieces.append(tag)
        cursor = match.end()
        replacements.append({"job_id": job_id, "src": src, "tag_index": idx})
    pieces.append(html[cursor:])
    new_html = "".join(pieces)
    changed = new_html != html
    if changed:
        html_path.write_text(new_html, encoding="utf-8")

    return {
        "ok": not missing,
        "path": str(html_path),
        "changed": changed,
        "data": {
            "html_path": str(html_path),
            "replacements": replacements,
            "missing": missing,
            "changed": changed,
        },
        "warnings": [f"missing_image_job:{item}" for item in missing],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "html",
    "label": "HTML: Stitch Job Images",
    "description": "Patch HTML image tags using image artifacts from completed spawned AI job records.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "html_path": {"type": "string"},
            "slots": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "cwd": {"type": "string"},
            "base_dir": {"type": "string"},
        },
        "required": ["html_path", "slots"],
        "additionalProperties": True,
    },
}
