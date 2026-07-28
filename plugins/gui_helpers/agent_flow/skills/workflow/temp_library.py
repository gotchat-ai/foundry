from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

import json
import re
import shutil
import time
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Tuple

from _wfcommon import derive_public_workflow_metadata, ensure_flow_payload, generated_dir, slugify, infer_request_capabilities
import _workflow_store


NAME = "workflow.temp_library"
PERMISSIONS = ["workflow.temp_library", "workflow.*"]

_MATCH_STOPWORDS = {
    "able",
    "analysis",
    "analyses",
    "and",
    "build",
    "builder",
    "bundle",
    "bundles",
    "check",
    "checks",
    "create",
    "created",
    "creating",
    "data",
    "design",
    "designer",
    "download",
    "downloadable",
    "each",
    "executive",
    "export",
    "file",
    "files",
    "flow",
    "flows",
    "from",
    "generate",
    "generated",
    "generating",
    "json",
    "library",
    "output",
    "outputs",
    "please",
    "report",
    "request",
    "requests",
    "sandbox",
    "summary",
    "temp",
    "that",
    "the",
    "their",
    "them",
    "these",
    "this",
    "user",
    "validated",
    "validation",
    "with",
    "workflow",
    "workflows",
}

_FILE_FOCUS_STOPWORDS = _MATCH_STOPWORDS | {
    "analysis",
    "brief",
    "csv",
    "data",
    "doc",
    "docx",
    "file",
    "guide",
    "guidance",
    "input",
    "json",
    "md",
    "output",
    "pdf",
    "report",
    "request",
    "results",
    "review",
    "sample",
    "summary",
    "text",
    "tsv",
    "txt",
    "workbook",
    "xlsx",
    "xls",
}


def _temp_root(ctx: Dict[str, Any]) -> Path:
    root = generated_dir(ctx) / "temp_library"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _current_generator_signature() -> str:
    parts: List[str] = []
    for name in (
        "implement_skills.py",
        "plan_capabilities.py",
        "scaffold_generalized.py",
        "scaffold_capability.py",
    ):
        try:
            parts.append((_HERE / name).read_text(encoding="utf-8"))
        except Exception:
            continue
    if not parts:
        return ""
    return hashlib.sha256("\n<<SIG_SPLIT>>\n".join(parts).encode("utf-8")).hexdigest()[:16]


def _index_path(ctx: Dict[str, Any]) -> Path:
    return _temp_root(ctx) / "index.json"


def _read_index(ctx: Dict[str, Any]) -> Dict[str, Any]:
    rows = _workflow_store.list_temp_library_records(ctx)
    out: List[Dict[str, Any]] = []
    for row in rows:
        compat = dict(row)
        compat.pop("workflow_id", None)
        compat.pop("scope", None)
        compat.pop("pid", None)
        compat.pop("flow_json", None)
        compat["id"] = str(row.get("workflow_id") or row.get("id") or "").strip()
        out.append(compat)
    return {"records": out}


def _write_index(ctx: Dict[str, Any], payload: Dict[str, Any]) -> None:
    records = payload.get("records") if isinstance(payload.get("records"), list) else []
    next_rows: List[Dict[str, Any]] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        merged = dict(row)
        workflow_id = str(merged.get("workflow_id") or merged.get("id") or "").strip()
        if workflow_id:
            merged["workflow_id"] = workflow_id
            merged["id"] = workflow_id
        next_rows.append(merged)
    _workflow_store.replace_temp_library_records(ctx, next_rows)


def _existing_record_ids(ctx: Dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for row in _list_records(ctx):
        rid = str((row or {}).get("id") or "").strip()
        if rid:
            out.add(rid)
    return out


def _unique_record_id(ctx: Dict[str, Any], base_id: str) -> str:
    root = _temp_root(ctx)
    token = slugify(base_id, "temp_workflow")
    used = _existing_record_ids(ctx)
    if token not in used and not (root / token).exists():
        return token
    stamp = str(int(time.time()))
    candidate = f"{token}_{stamp}"
    counter = 2
    while candidate in used or (root / candidate).exists():
        candidate = f"{token}_{stamp}_{counter}"
        counter += 1
    return candidate


def _tokenize(text: Any) -> List[str]:
    raw = str(text or "").lower()
    out: List[str] = []
    cur = []
    for ch in raw:
        if ch.isalnum():
            cur.append(ch)
            continue
        if len(cur) >= 3:
            out.append("".join(cur))
        cur = []
    if len(cur) >= 3:
        out.append("".join(cur))
    return sorted({tok for tok in out if tok not in _MATCH_STOPWORDS})


def _sport_tokens(text: Any) -> set[str]:
    low = str(text or "").lower()
    out: set[str] = set()
    groups = {
        "basketball": ("basketball", "nba", "wnba"),
        "baseball": ("baseball", "mlb"),
        "football": ("football", "nfl"),
        "hockey": ("hockey", "nhl"),
        "soccer": ("soccer", "mls", "epl", "fifa"),
    }
    for label, hints in groups.items():
        if any(hint in low for hint in hints):
            out.add(label)
    return out


def _capability_ids(text: Any) -> List[str]:
    out: List[str] = []
    seen = set()
    for row in infer_request_capabilities(text):
        if not isinstance(row, dict):
            continue
        cap_id = str(row.get("id") or "").strip()
        if not cap_id or cap_id in seen:
            continue
        seen.add(cap_id)
        out.append(cap_id)
    return out


def _intent_tags(text: Any) -> List[str]:
    out: List[str] = []
    seen = set()
    for cap_id in _capability_ids(text):
        if cap_id not in seen:
            seen.add(cap_id)
            out.append(cap_id)
    low = str(text or "").lower()
    for label, hints in (
        ("lookup", ("look up", "lookup", "find", "search", "check")),
        ("compare", ("compare", "reconcile", "difference", "variance", "mismatch")),
        ("summarize", ("summarize", "summary", "brief", "overview", "digest")),
        ("download", ("download", "export", "save", "retrieve")),
        ("author", ("write", "draft", "compose", "create", "generate")),
        ("validate", ("validate", "verify", "check", "review", "audit")),
    ):
        if any(hint in low for hint in hints) and label not in seen:
            seen.add(label)
            out.append(label)
    return out[:16]


def _subject_tags(text: Any) -> List[str]:
    low = str(text or "").lower()
    out: List[str] = []
    seen = set()
    for token in sorted(_domain_tokens(text) | _sport_tokens(text)):
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    for label, hints in (
        ("youtube", ("youtube",)),
        ("google_trends", ("google trends", "search trends", "trending on google", "most searched")),
        ("news", ("news", "headline", "headlines", "top stories", "breaking stories")),
        ("sports", ("sports", "scoreboard", "game tonight", "games tonight", "playing against")),
        ("portal", ("portal", "vendor portal")),
        ("statement", ("statement", "statements")),
        ("spreadsheet", ("spreadsheet", "excel", "workbook", ".xlsx", ".xls", ".csv")),
        ("contract", ("contract", "agreement", "clause")),
        ("pdf", ("pdf", "ocr", "scan")),
        ("stocks", ("stock", "stocks", "market data", "ticker")),
    ):
        if any(hint in low for hint in hints) and label not in seen:
            seen.add(label)
            out.append(label)
    return out[:20]


def _normalize_text_list(value: Any) -> List[str]:
    rows = value if isinstance(value, list) else []
    out: List[str] = []
    seen = set()
    for row in rows:
        text = str(row or "").strip()
        low = text.lower()
        if not text or low in seen:
            continue
        seen.add(low)
        out.append(text)
    return out


def _fix_notes(params: Dict[str, Any], previous: Dict[str, Any] | None = None) -> List[str]:
    out: List[str] = []
    seen = set()

    def _add(text: Any) -> None:
        item = str(text or "").strip()
        low = item.lower()
        if not item or low in seen:
            return
        seen.add(low)
        out.append(item)

    for item in _normalize_text_list((params or {}).get("fixes")):
        _add(item)
    fix_summary = str((params or {}).get("fix_summary") or "").strip()
    if fix_summary:
        _add(fix_summary)
    for item in _normalize_text_list((params or {}).get("bugs"))[:8]:
        _add(f"Addressed: {item}")
    prev = previous if isinstance(previous, dict) else {}
    prev_fail = int(prev.get("fail_count") or 0)
    next_pass = bool((params or {}).get("all_passed")) or bool((params or {}).get("validated"))
    next_fail = int((params or {}).get("fail_count") or 0)
    if prev_fail > 0 and next_pass and next_fail == 0:
        _add("Validation failures were repaired and the workflow now passes.")
    return out[:12]


def _fix_note_params(params: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(params or {})
    if isinstance(patch, dict):
        for key in ("fixes", "fix_summary", "bugs", "all_passed", "validated", "fail_count"):
            if key not in merged and key in patch:
                merged[key] = patch.get(key)
    return merged


def _semantic_patch(row: Dict[str, Any]) -> Dict[str, Any]:
    base_text = " ".join(
        [
            str((row or {}).get("flow_name") or ""),
            str((row or {}).get("source_request") or ""),
            str((row or {}).get("summary") or ""),
            str((row or {}).get("description") or ""),
            " ".join((row or {}).get("tags") or []),
        ]
    )
    public_meta = derive_public_workflow_metadata(
        flow_name=(row or {}).get("flow_name"),
        request_text=(row or {}).get("source_request"),
        summary=(row or {}).get("summary"),
        description=(row or {}).get("description"),
        tags=[],
        supported_capability_ids=(row or {}).get("supported_capability_ids") or [],
        intent_tags=(row or {}).get("intent_tags") or [],
        subject_tags=(row or {}).get("subject_tags") or [],
    )
    return {
        "flow_name": str(public_meta.get("flow_name") or (row or {}).get("flow_name") or "").strip(),
        "summary": str(public_meta.get("summary") or (row or {}).get("summary") or "").strip(),
        "description": str(public_meta.get("description") or (row or {}).get("description") or "").strip(),
        "tags": list(public_meta.get("tags") or []),
        "supported_capability_ids": list(public_meta.get("supported_capability_ids") or _capability_ids(str((row or {}).get("source_request") or base_text))),
        "intent_tags": list(public_meta.get("intent_tags") or _intent_tags(base_text)),
        "subject_tags": list(public_meta.get("subject_tags") or _subject_tags(base_text)),
    }


def _score_match(request_tokens: List[str], record: Dict[str, Any]) -> float:
    record_text = " ".join(
        [
            str(record.get("flow_name") or ""),
            str(record.get("source_request") or ""),
            str(record.get("summary") or ""),
            str(record.get("description") or ""),
            " ".join(record.get("tags") or []),
        ]
    )
    record_tokens = set(_tokenize(record_text))
    if not request_tokens or not record_tokens:
        return 0.0
    request_sports = _sport_tokens(" ".join(request_tokens))
    record_sports = _sport_tokens(record_text)
    if request_sports and record_sports and not (request_sports & record_sports):
        return 0.0
    request_text = " ".join(request_tokens)
    request_caps = set(_capability_ids(request_text))
    record_caps = {
        str(x or "").strip()
        for x in (
            record.get("supported_capability_ids")
            if isinstance(record.get("supported_capability_ids"), list)
            else []
        )
        if str(x or "").strip()
    } or set(_capability_ids(record_text))
    if request_caps and record_caps and not (request_caps & record_caps):
        return 0.0
    overlap_tokens = set(request_tokens) & record_tokens
    overlap = len(overlap_tokens)
    if overlap <= 0:
        return 0.0
    if len(set(request_tokens)) >= 4 and overlap < 2:
        return 0.0
    lexical_score = overlap / max(3.0, float(len(set(request_tokens))))
    request_subjects = set(_subject_tags(request_text))
    record_subject_values = record.get("subject_tags") if isinstance(record.get("subject_tags"), list) else []
    record_subjects = {
        str(x or "").strip()
        for x in record_subject_values
        if str(x or "").strip()
    } or set(_subject_tags(record_text))
    request_intents = set(_intent_tags(request_text))
    record_intent_values = record.get("intent_tags") if isinstance(record.get("intent_tags"), list) else []
    record_intents = {
        str(x or "").strip()
        for x in record_intent_values
        if str(x or "").strip()
    } or set(_intent_tags(record_text))
    subject_score = 0.0
    if request_subjects and record_subjects:
        subject_score = len(request_subjects & record_subjects) / max(1.0, float(len(request_subjects)))
    intent_score = 0.0
    if request_intents and record_intents:
        intent_score = len(request_intents & record_intents) / max(1.0, float(len(request_intents)))
    capability_score = 0.0
    if request_caps and record_caps:
        capability_score = len(request_caps & record_caps) / max(1.0, float(len(request_caps)))
    score = (lexical_score * 0.5) + (subject_score * 0.25) + (intent_score * 0.15) + (capability_score * 0.10)
    return round(score, 6)


def _domain_tokens(text: Any) -> set[str]:
    raw = str(text or "").lower()
    rows: List[str] = []
    for pat in (
        r"\bworkflow\s+for\s+(.+?)\s+that\b",
        r"\bworkflow\s+for\s+(.+?)\s+that\s+handles\b",
        r"\bworkflow\s+for\s+(.+?)\s+with\b",
        r"\bfor\s+(.+?)\s+that\b",
        r"\bfor\s+(.+?)\s+that\s+handles\b",
    ):
        for match in re.finditer(pat, raw):
            rows.append(str(match.group(1) or ""))
    tokens: set[str] = set()
    for row in rows:
        for token in _tokenize(row):
            if token not in _MATCH_STOPWORDS:
                tokens.add(token)
    return tokens


def _request_file_focus_groups(text: Any) -> List[set[str]]:
    raw = str(text or "")
    groups: List[set[str]] = []
    patterns = (
        r"([A-Za-z]:[/\\][^\n\r\t\"']+\.(?:csv|tsv|xlsx|xls|json|txt|md|pdf|docx))",
        r"(/[^ \n\r\t\"']+\.(?:csv|tsv|xlsx|xls|json|txt|md|pdf|docx))",
    )
    for pat in patterns:
        for match in re.finditer(pat, raw, flags=re.IGNORECASE):
            path_text = str(match.group(1) or "").strip()
            if not path_text:
                continue
            stem = Path(path_text).stem
            group: set[str] = set()
            for token in _tokenize(stem):
                if token not in _FILE_FOCUS_STOPWORDS:
                    group.add(token)
            if group:
                groups.append(group)
    return groups


def _domain_overlap_ok(request_domains: set[str], record_domains: set[str]) -> bool:
    if not request_domains:
        return True
    overlap = request_domains & record_domains
    if not overlap:
        return False
    required = 2 if len(request_domains) >= 2 else 1
    return len(overlap) >= required


def _strict_creator_domain_request(text: str) -> bool:
    low = str(text or "").lower()
    return "create a workflow for" in low or "build a workflow for" in low or "design a workflow for" in low


def _record_domain_text(row: Dict[str, Any], request_text: str) -> str:
    if _strict_creator_domain_request(request_text):
        return " ".join(
            [
                str((row or {}).get("flow_name") or ""),
                str((row or {}).get("description") or ""),
                str((row or {}).get("summary") or ""),
                " ".join((row or {}).get("subject_tags") or []),
                " ".join((row or {}).get("intent_tags") or []),
            ]
        )
    return " ".join(
        [
            str((row or {}).get("flow_name") or ""),
            str((row or {}).get("source_request") or ""),
            str((row or {}).get("description") or ""),
            " ".join((row or {}).get("tags") or []),
            " ".join((row or {}).get("subject_tags") or []),
            " ".join((row or {}).get("intent_tags") or []),
            " ".join((row or {}).get("supported_capability_ids") or []),
        ]
    )


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    return str(
        (params or {}).get("current_request_text")
        or (params or {}).get("request_text")
        or (params or {}).get("user_request")
        or (params or {}).get("request")
        or (params or {}).get("prompt")
        or (params or {}).get("text")
        or (ctx or {}).get("original_request")
        or (ctx or {}).get("user_text")
        or ""
    ).strip()


def _current_run_id(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
    ext = ext if isinstance(ext, dict) else {}
    return str(
        (params or {}).get("run_id")
        or ext.get("run_id")
        or ext.get("agent_flow_run_id")
        or ""
    ).strip()


def _prior_suite_passed(ctx: Dict[str, Any]) -> bool:
    ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
    ext = ext if isinstance(ext, dict) else {}
    for key in ("agent_flow_previous_step_report_with_tools", "agent_flow_previous_step_report"):
        report = ext.get(key)
        if not isinstance(report, dict):
            continue
        rows = report.get("tool_results") if isinstance(report.get("tool_results"), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            skill = str(row.get("skill") or "").strip().lower()
            if skill != "workflow.review_suite":
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            if bool(data.get("all_passed")) or bool(row.get("all_passed")):
                return True
    return False


def _recover_validation_signals(ctx: Dict[str, Any]) -> Dict[str, Any]:
    ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
    ext = ext if isinstance(ext, dict) else {}
    out: Dict[str, Any] = {}
    for key in ("agent_flow_previous_step_report_with_tools", "agent_flow_previous_step_report"):
        report = ext.get(key)
        if not isinstance(report, dict):
            continue
        tool_rows = report.get("tool_results") if isinstance(report.get("tool_results"), list) else []
        for row in reversed(tool_rows):
            if not isinstance(row, dict):
                continue
            skill = str(row.get("skill") or "").strip().lower()
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            if skill in {"workflow.run_suite", "workflow.run_suite_capability", "workflow.review_suite"}:
                for name in ("all_passed", "pass_count", "fail_count", "validation_profile", "warnings", "bugs", "fixes"):
                    if name not in out:
                        value = data.get(name) if name in data else row.get(name)
                        if value not in (None, "", [], {}):
                            out[name] = value
        if out:
            break
    return out


def _load_flow_metadata(workflow_file: Path) -> Tuple[str, str]:
    if not workflow_file.is_file():
        return "", ""
    try:
        raw = workflow_file.read_text(encoding="utf-8")
    except Exception:
        return "", ""
    flow, flow_name, _ = ensure_flow_payload(raw, workflow_file.stem)
    if not isinstance(flow, dict):
        return flow_name, ""
    return str(flow_name or flow.get("name") or "").strip(), str(flow.get("description") or "").strip()


def _list_records(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = _workflow_store.list_temp_library_records(ctx)
    out: List[Dict[str, Any]] = []
    for row in rows:
        compat = dict(row)
        compat.pop("workflow_id", None)
        compat.pop("scope", None)
        compat.pop("pid", None)
        compat.pop("flow_json", None)
        compat["id"] = str(row.get("workflow_id") or row.get("id") or "").strip()
        out.append(compat)
    return out


def _match(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_text = _request_text(ctx, params)
    request_tokens = _tokenize(request_text)
    request_domain_tokens = _domain_tokens(request_text)
    request_file_groups = _request_file_focus_groups(request_text)
    threshold = float((params or {}).get("min_score") or 0.30)
    reusable_only = bool((params or {}).get("reusable_only"))
    current_signature = _current_generator_signature()
    ranked: List[Dict[str, Any]] = []
    for row in _list_records(ctx):
        row_signature = str(row.get("generator_signature") or "").strip()
        if current_signature and row_signature != current_signature:
            continue
        if reusable_only and not _record_reusable(row):
            continue
        record_text = " ".join(
            [
                str(row.get("flow_name") or ""),
                str(row.get("source_request") or ""),
                str(row.get("summary") or ""),
                str(row.get("description") or ""),
                " ".join(row.get("tags") or []),
            ]
        )
        record_tokens = set(_tokenize(record_text))
        if request_domain_tokens:
            record_text = _record_domain_text(row, request_text)
            record_tokens = set(_tokenize(record_text))
            if not _domain_overlap_ok(request_domain_tokens, record_tokens):
                continue
        if request_file_groups:
            group_match = False
            for group in request_file_groups:
                if group and group.issubset(record_tokens):
                    group_match = True
                    break
            if not group_match:
                continue
        score = _score_match(request_tokens, row)
        if score <= 0:
            continue
        row2 = dict(row)
        row2["score"] = round(score, 4)
        ranked.append(row2)
    ranked.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    best = ranked[0] if ranked and float(ranked[0].get("score") or 0.0) >= threshold else {}
    return {
        "ok": True,
        "request": request_text,
        "match_found": bool(best),
        "best_match": best,
        "matches": ranked[:8],
        "data": {
            "request": request_text,
            "match_found": bool(best),
            "best_match": best,
            "matches": ranked[:8],
            "bundle_dir": str(best.get("bundle_dir") or ""),
            "workflow_file": str(best.get("workflow_file") or ""),
            "flow_name": str(best.get("flow_name") or ""),
        },
        "warnings": [],
    }


def _get_record(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    record_id = str((params or {}).get("id") or (params or {}).get("record_id") or "").strip()
    if not record_id:
        return {"ok": False, "data": {}, "warnings": ["record_id_missing"]}
    for row in _list_records(ctx):
        if str(row.get("id") or "").strip() == record_id:
            return {"ok": True, "record": row, "data": {"record": row}, "warnings": []}
    return {"ok": False, "data": {"record_id": record_id}, "warnings": ["record_not_found"]}


def _resolve_flow(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    workflow_id = str((params or {}).get("workflow_id") or (params or {}).get("id") or "").strip()
    wanted = str((params or {}).get("flow_name") or (params or {}).get("name") or "").strip()
    if not wanted and not workflow_id:
        return {"ok": False, "data": {}, "warnings": ["flow_name_missing"]}
    keys = {wanted.lower(), slugify(wanted)}
    candidates: List[Dict[str, Any]] = []
    for row in _list_records(ctx):
        row_name = str(row.get("flow_name") or "").strip()
        row_id = str(row.get("id") or "").strip()
        if workflow_id and row_id == workflow_id:
            candidates.append(dict(row))
            continue
        row_keys = {row_name.lower(), slugify(row_name), row_id.lower(), slugify(row_id)}
        if not (keys & row_keys):
            continue
        candidates.append(dict(row))
    if not candidates:
        return {"ok": False, "data": {"flow_name": wanted, "workflow_id": workflow_id}, "warnings": ["temp_library_flow_not_found"]}
    candidates.sort(key=lambda x: int(x.get("updated_ts") or 0), reverse=True)
    row = candidates[0]
    workflow_file = Path(str(row.get("workflow_file") or "").strip())
    bundle_dir = Path(str(row.get("bundle_dir") or "").strip())
    if not workflow_file.is_file():
        return {"ok": False, "data": {"flow_name": wanted}, "warnings": ["workflow_file_not_found"]}
    try:
        flow_doc, flow_name, warnings = ensure_flow_payload(workflow_file.read_text(encoding="utf-8"), row.get("flow_name") or wanted)
    except Exception:
        flow_doc, flow_name, warnings = None, "", ["invalid_temp_library_workflow_json"]
    if not isinstance(flow_doc, dict):
        return {"ok": False, "data": {"flow_name": wanted}, "warnings": warnings or ["invalid_temp_library_workflow_json"]}
    skills_root = bundle_dir / "skills"
    temp_skill_dirs = [str(skills_root)] if skills_root.is_dir() else []
    skill_files = [str(p.resolve()) for p in skills_root.rglob("*.py") if p.is_file()] if skills_root.is_dir() else []
    return {
        "ok": True,
        "record": row,
        "flow_name": str(flow_name or flow_doc.get("name") or row.get("flow_name") or wanted).strip(),
        "workflow_json": flow_doc,
        "workflow_file": str(workflow_file.resolve()),
        "bundle_dir": str(bundle_dir.resolve()) if bundle_dir.exists() else str(bundle_dir),
        "temp_skill_dirs": temp_skill_dirs,
        "skill_files": skill_files,
        "data": {
            "record": row,
            "flow_name": str(flow_name or flow_doc.get("name") or row.get("flow_name") or wanted).strip(),
            "workflow_json": flow_doc,
            "workflow_file": str(workflow_file.resolve()),
            "bundle_dir": str(bundle_dir.resolve()) if bundle_dir.exists() else str(bundle_dir),
            "temp_skill_dirs": temp_skill_dirs,
            "skill_files": skill_files,
        },
        "warnings": warnings,
    }


def _delete_record(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    record_id = str((params or {}).get("id") or (params or {}).get("record_id") or "").strip()
    if not record_id:
        return {"ok": False, "data": {}, "warnings": ["record_id_missing"]}
    payload = _read_index(ctx)
    records = payload.get("records") if isinstance(payload.get("records"), list) else []
    next_records: List[Dict[str, Any]] = []
    removed: Dict[str, Any] = {}
    for row in records:
        if not isinstance(row, dict):
            continue
        if str(row.get("id") or "").strip() == record_id and not removed:
            removed = dict(row)
            continue
        next_records.append(dict(row))
    if not removed:
        return {"ok": False, "data": {"record_id": record_id}, "warnings": ["record_not_found"]}
    bundle_dir = Path(str(removed.get("bundle_dir") or "").strip()) if str(removed.get("bundle_dir") or "").strip() else None
    try:
        if bundle_dir and bundle_dir.exists():
            shutil.rmtree(bundle_dir)
    except Exception:
        pass
    payload["records"] = next_records
    _write_index(ctx, payload)
    return {
        "ok": True,
        "deleted": True,
        "record": removed,
        "data": {"deleted": True, "record": removed},
        "warnings": [],
    }


def _backfill_semantic_metadata(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    payload = _read_index(ctx)
    records = payload.get("records") if isinstance(payload.get("records"), list) else []
    next_records: List[Dict[str, Any]] = []
    updated_count = 0
    for row in records:
        if not isinstance(row, dict):
            continue
        row2 = dict(row)
        patch = _semantic_patch(row2)
        changed = False
        for key, value in patch.items():
            next_value = list(value) if isinstance(value, list) else value
            if row2.get(key) != next_value:
                row2[key] = next_value
                changed = True
        if changed:
            row2["updated_ts"] = int(time.time())
            updated_count += 1
        next_records.append(row2)
    payload["records"] = sorted(next_records, key=lambda x: int(x.get("updated_ts") or 0), reverse=True)
    _write_index(ctx, payload)
    return {
        "ok": True,
        "updated_count": updated_count,
        "record_count": len(next_records),
        "data": {"updated_count": updated_count, "record_count": len(next_records)},
        "warnings": [],
    }


def _update_record(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    record_id = str((params or {}).get("id") or (params or {}).get("record_id") or "").strip()
    patch = (params or {}).get("patch")
    if not record_id:
        return {"ok": False, "data": {}, "warnings": ["record_id_missing"]}
    if not isinstance(patch, dict):
        patch = {}
    payload = _read_index(ctx)
    records = payload.get("records") if isinstance(payload.get("records"), list) else []
    updated: Dict[str, Any] = {}
    previous: Dict[str, Any] = {}
    next_records: List[Dict[str, Any]] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        row2 = dict(row)
        if str(row2.get("id") or "").strip() == record_id:
            previous = dict(row2)
            row2.update(patch)
            row2.update(_semantic_patch(row2))
            fix_notes = _fix_notes(_fix_note_params(params, patch), previous)
            if fix_notes:
                row2["fix_notes"] = fix_notes
            row2["updated_ts"] = int(time.time())
            updated = dict(row2)
        next_records.append(row2)
    if not updated:
        return {"ok": False, "data": {"record_id": record_id}, "warnings": ["record_not_found"]}
    payload["records"] = sorted(next_records, key=lambda x: int(x.get("updated_ts") or 0), reverse=True)
    _write_index(ctx, payload)
    try:
        from plugins.gui_helpers.workflow_training.capture import maybe_capture_record
        maybe_capture_record(ctx, updated, trigger="temp_library_update", previous=previous)
    except Exception:
        pass
    try:
        status_label = (
            "working"
            if bool(updated.get("all_passed")) or bool(updated.get("validated"))
            else ("doesnt_work" if int(updated.get("fail_count") or 0) > 0 else "needs_improvements")
        )
        _workflow_store.record_workflow_update(
            ctx,
            {
                "workflow_id": str(updated.get("workflow_id") or updated.get("id") or "").strip(),
                "flow_name": str(updated.get("flow_name") or "").strip(),
                "pid": "__temp_library__",
                "scope": "temp_library",
                "request_text": str(updated.get("last_request") or updated.get("source_request") or "").strip(),
                "update_reason": "temp_library_update",
                "update_target": "workflow_record",
                "status_label": status_label,
                "pass_count": int(updated.get("pass_count") or 0),
                "fail_count": int(updated.get("fail_count") or 0),
                "validation_profile": str(updated.get("validation_profile") or "").strip(),
                "summary": str(updated.get("summary") or "").strip(),
                "bugs": _normalize_text_list(updated.get("fix_notes")) or [],
                "metadata": {
                    "previous_id": str(previous.get("workflow_id") or previous.get("id") or "").strip(),
                    "fix_notes": _normalize_text_list(updated.get("fix_notes")),
                },
            },
        )
    except Exception:
        pass
    return {"ok": True, "record": updated, "data": {"record": updated}, "warnings": []}


def _touch_record_alias(ctx: Dict[str, Any], row: Dict[str, Any], request_text: str) -> Dict[str, Any]:
    record_id = str((row or {}).get("id") or "").strip()
    if not record_id:
        return dict(row or {})
    next_aliases: List[str] = []
    seen = set()
    for item in (row or {}).get("request_aliases") or []:
        text = str(item or "").strip()
        low = text.lower()
        if not text or low in seen:
            continue
        seen.add(low)
        next_aliases.append(text)
    request_text = str(request_text or "").strip()
    if request_text and request_text.lower() not in seen:
        next_aliases.append(request_text)
    updated = _update_record(ctx, {"record_id": record_id, "patch": {"request_aliases": next_aliases, "last_request": request_text}})
    record = updated.get("record") if isinstance(updated.get("record"), dict) else {}
    return record if record else dict(row or {})


def _record_domain_compatible(row: Dict[str, Any], request_text: str) -> bool:
    request_domains = _domain_tokens(request_text)
    if not request_domains:
        return True
    record_text = _record_domain_text(row, request_text)
    record_domains = _domain_tokens(record_text) or set(_tokenize(record_text))
    return _domain_overlap_ok(request_domains, record_domains)


def _record_reusable(row: Dict[str, Any]) -> bool:
    if not bool((row or {}).get("validated")):
        return False
    if not bool((row or {}).get("all_passed")):
        return False
    profile = str((row or {}).get("validation_profile") or "").strip().lower()
    if profile == "lightweight":
        return False
    return True


def _register(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    bundle_dir_raw = str((params or {}).get("bundle_dir") or "").strip()
    workflow_file_raw = str((params or {}).get("workflow_file") or "").strip()
    flow_name_hint = str((params or {}).get("flow_name") or "").strip()
    allow_reuse = bool((params or {}).get("allow_reuse", True))
    request_text = _request_text(ctx, params)
    run_id = _current_run_id(ctx, params)
    recovered_validation = _recover_validation_signals(ctx)
    existing_bundle_dir = ""
    existing_workflow_file = ""
    if bundle_dir_raw:
        try:
            existing_bundle_dir = str(Path(bundle_dir_raw).resolve())
        except Exception:
            existing_bundle_dir = str(bundle_dir_raw).strip()
    if workflow_file_raw:
        try:
            existing_workflow_file = str(Path(workflow_file_raw).resolve())
        except Exception:
            existing_workflow_file = str(workflow_file_raw).strip()
    if existing_bundle_dir or existing_workflow_file:
        for row in _list_records(ctx):
            row_bundle = str(row.get("bundle_dir") or "").strip()
            row_workflow = str(row.get("workflow_file") or "").strip()
            same_bundle = bool(existing_bundle_dir and row_bundle == existing_bundle_dir)
            same_workflow = bool(existing_workflow_file and row_workflow == existing_workflow_file)
            if not (same_bundle or same_workflow):
                continue
            row = _touch_record_alias(ctx, row, request_text)
            return {
                "ok": True,
                "registered": True,
                "reused_existing": True,
                "record": row,
                "bundle_dir": str(row.get("bundle_dir") or ""),
                "workflow_file": str(row.get("workflow_file") or ""),
                "flow_name": str(row.get("flow_name") or ""),
                "data": {
                    "registered": True,
                    "reused_existing": True,
                    "record": row,
                    "bundle_dir": str(row.get("bundle_dir") or ""),
                    "workflow_file": str(row.get("workflow_file") or ""),
                    "flow_name": str(row.get("flow_name") or ""),
                },
                "warnings": [],
            }
    if allow_reuse and run_id:
        for row in _list_records(ctx):
            same_run = str(row.get("registration_run_id") or "").strip() == run_id
            same_flow = str(row.get("flow_name") or "").strip() == flow_name_hint if flow_name_hint else False
            same_request = str(row.get("source_request") or "").strip() == request_text if request_text else False
            if same_run and (same_flow or same_request):
                row = _touch_record_alias(ctx, row, request_text)
                return {
                    "ok": True,
                    "registered": True,
                    "reused_existing": True,
                    "record": row,
                    "bundle_dir": str(row.get("bundle_dir") or ""),
                    "workflow_file": str(row.get("workflow_file") or ""),
                    "flow_name": str(row.get("flow_name") or ""),
                    "data": {
                        "registered": True,
                        "reused_existing": True,
                        "record": row,
                        "bundle_dir": str(row.get("bundle_dir") or ""),
                        "workflow_file": str(row.get("workflow_file") or ""),
                        "flow_name": str(row.get("flow_name") or ""),
                    },
                    "warnings": [],
                }
    if allow_reuse and not bundle_dir_raw and flow_name_hint:
        for row in _list_records(ctx):
            if str(row.get("flow_name") or "").strip() == flow_name_hint and _record_reusable(row):
                if not _record_domain_compatible(row, request_text):
                    continue
                row = _touch_record_alias(ctx, row, request_text)
                return {
                    "ok": True,
                    "registered": True,
                    "reused_existing": True,
                    "record": row,
                    "bundle_dir": str(row.get("bundle_dir") or ""),
                    "workflow_file": str(row.get("workflow_file") or ""),
                    "flow_name": str(row.get("flow_name") or ""),
                    "data": {
                        "registered": True,
                        "reused_existing": True,
                        "record": row,
                        "bundle_dir": str(row.get("bundle_dir") or ""),
                        "workflow_file": str(row.get("workflow_file") or ""),
                        "flow_name": str(row.get("flow_name") or ""),
                    },
                    "warnings": [],
                }
    if allow_reuse and not bundle_dir_raw:
        matched = _match(ctx, {"user_request": request_text, "min_score": 0.42, "reusable_only": True})
        best = matched.get("best_match") if isinstance(matched.get("best_match"), dict) else {}
        if best and _record_reusable(best) and _record_domain_compatible(best, request_text):
            best = _touch_record_alias(ctx, best, request_text)
            return {
                "ok": True,
                "registered": True,
                "reused_existing": True,
                "record": best,
                "bundle_dir": str(best.get("bundle_dir") or ""),
                "workflow_file": str(best.get("workflow_file") or ""),
                "flow_name": str(best.get("flow_name") or ""),
                "data": {
                    "registered": True,
                    "reused_existing": True,
                    "record": best,
                    "bundle_dir": str(best.get("bundle_dir") or ""),
                    "workflow_file": str(best.get("workflow_file") or ""),
                    "flow_name": str(best.get("flow_name") or ""),
                },
                "warnings": [],
            }
    if not bundle_dir_raw and _prior_suite_passed(ctx):
        return {
            "ok": True,
            "registered": True,
            "reused_existing": True,
            "skipped": True,
            "data": {
                "registered": True,
                "reused_existing": True,
                "skipped": True,
            },
            "warnings": [],
        }
    if not bundle_dir_raw:
        return {
            "ok": True,
            "registered": False,
            "skipped": True,
            "data": {
                "registered": False,
                "skipped": True,
            },
            "warnings": [],
        }
    src_bundle = Path(bundle_dir_raw).resolve()
    if not src_bundle.is_dir():
        return {"ok": False, "data": {}, "warnings": ["bundle_dir_not_found"]}
    src_workflow = Path(workflow_file_raw).resolve() if workflow_file_raw else None
    if src_workflow is None or not src_workflow.is_file():
        json_files = sorted([p for p in src_bundle.glob("*.json") if p.is_file()])
        src_workflow = json_files[0] if json_files else None
    if src_workflow is None or not src_workflow.is_file():
        return {"ok": False, "data": {}, "warnings": ["workflow_file_not_found"]}

    flow_name_meta, description = _load_flow_metadata(src_workflow)
    source_request = request_text
    raw_flow_name = str((params or {}).get("flow_name") or flow_name_meta or src_workflow.stem).strip()
    raw_summary = str((params or {}).get("summary") or (params or {}).get("coverage_summary") or (params or {}).get("architect_summary") or "").strip()
    public_meta = derive_public_workflow_metadata(
        flow_name=raw_flow_name,
        request_text=source_request,
        summary=raw_summary,
        description=description,
        tags=[],
        supported_capability_ids=_capability_ids(source_request),
        intent_tags=_intent_tags(" ".join([raw_flow_name, source_request, raw_summary, description])),
        subject_tags=_subject_tags(" ".join([raw_flow_name, source_request, raw_summary, description])),
    )
    flow_name = str(public_meta.get("flow_name") or raw_flow_name).strip()
    summary = str(public_meta.get("summary") or raw_summary).strip()
    description = str(public_meta.get("description") or description).strip()
    tags = list(public_meta.get("tags") or _tokenize(" ".join([flow_name, source_request, summary, description]))[:40])
    supported_capability_ids = list(public_meta.get("supported_capability_ids") or _capability_ids(source_request))
    intent_tags = list(public_meta.get("intent_tags") or _intent_tags(" ".join([flow_name, source_request, summary, description])))
    subject_tags = list(public_meta.get("subject_tags") or _subject_tags(" ".join([flow_name, source_request, summary, description])))
    fix_params = dict(params or {})
    if "bugs" not in fix_params and recovered_validation.get("bugs") not in (None, "", [], {}):
        fix_params["bugs"] = recovered_validation.get("bugs")
    if "fixes" not in fix_params and recovered_validation.get("fixes") not in (None, "", [], {}):
        fix_params["fixes"] = recovered_validation.get("fixes")
    if "bugs" not in fix_params and recovered_validation.get("warnings") not in (None, "", [], {}):
        fix_params["bugs"] = recovered_validation.get("warnings")
    fix_notes = _fix_notes(fix_params)

    dest_root = _temp_root(ctx)
    record_id = _unique_record_id(ctx, slugify(flow_name, "temp_workflow"))
    dest_bundle = dest_root / record_id
    shutil.copytree(src_bundle, dest_bundle)

    desired_name = f"{slugify(flow_name, src_workflow.stem)}.json"
    copied_workflow = dest_bundle / src_workflow.name
    dest_workflow = dest_bundle / desired_name
    if copied_workflow.is_file() and copied_workflow != dest_workflow:
        try:
            copied_workflow.replace(dest_workflow)
        except Exception:
            shutil.copy2(copied_workflow, dest_workflow)
    if not dest_workflow.is_file():
        alt = sorted([p for p in dest_bundle.glob("*.json") if p.is_file()])
        if alt:
            dest_workflow = alt[0]

    payload = _read_index(ctx)
    records = payload.get("records") if isinstance(payload.get("records"), list) else []
    fresh_records: List[Dict[str, Any]] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        fresh_records.append(row)
    now_ts = int(time.time())
    validation_profile = str(
        (params or {}).get("validation_profile")
        or recovered_validation.get("validation_profile")
        or ""
    ).strip().lower()
    all_passed = bool(
        (params or {}).get("all_passed")
        if "all_passed" in (params or {})
        else recovered_validation.get("all_passed")
    )
    pass_count = int(
        (params or {}).get("pass_count")
        if (params or {}).get("pass_count") not in (None, "")
        else recovered_validation.get("pass_count") or 0
    )
    fail_count = int(
        (params or {}).get("fail_count")
        if (params or {}).get("fail_count") not in (None, "")
        else recovered_validation.get("fail_count") or 0
    )
    validated = bool((params or {}).get("validated", all_passed))
    if "validated" not in (params or {}) and "all_passed" in (params or {}):
        validated = bool((params or {}).get("all_passed"))
    record = {
        "id": record_id,
        "flow_name": flow_name,
        "bundle_dir": str(dest_bundle),
        "workflow_file": str(dest_workflow),
        "generator_signature": _current_generator_signature(),
        "registration_run_id": run_id,
        "source_request": source_request,
        "summary": summary,
        "description": description,
        "tags": tags,
        "supported_capability_ids": supported_capability_ids,
        "intent_tags": intent_tags,
        "subject_tags": subject_tags,
        "fix_notes": fix_notes,
        "validated": validated,
        "all_passed": all_passed,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "validation_profile": validation_profile,
        "updated_ts": now_ts,
    }
    fresh_records.append(record)
    payload["records"] = sorted(fresh_records, key=lambda x: int(x.get("updated_ts") or 0), reverse=True)
    _write_index(ctx, payload)
    try:
        from plugins.gui_helpers.workflow_training.capture import maybe_capture_record
        maybe_capture_record(ctx, record, trigger="temp_library_register")
    except Exception:
        pass
    try:
        status_label = "working" if bool(record.get("all_passed")) else ("doesnt_work" if int(record.get("fail_count") or 0) > 0 else "needs_improvements")
        _workflow_store.record_workflow_update(
            ctx,
            {
                "workflow_id": str(record.get("workflow_id") or record.get("id") or "").strip(),
                "flow_name": str(record.get("flow_name") or "").strip(),
                "pid": "__temp_library__",
                "scope": "temp_library",
                "request_text": str(record.get("last_request") or record.get("source_request") or "").strip(),
                "update_reason": "temp_library_register",
                "update_target": "workflow_record",
                "status_label": status_label,
                "pass_count": int(record.get("pass_count") or 0),
                "fail_count": int(record.get("fail_count") or 0),
                "validation_profile": str(record.get("validation_profile") or "").strip(),
                "summary": str(record.get("summary") or "").strip(),
                "bugs": list(fix_notes),
                "metadata": {
                    "bundle_dir": str(record.get("bundle_dir") or "").strip(),
                    "workflow_file": str(record.get("workflow_file") or "").strip(),
                    "fix_notes": list(fix_notes),
                },
            },
        )
    except Exception:
        pass
    return {
        "ok": True,
        "registered": True,
        "record": record,
        "bundle_dir": str(dest_bundle),
        "workflow_file": str(dest_workflow),
        "flow_name": flow_name,
        "data": {
            "registered": True,
            "record": record,
            "bundle_dir": str(dest_bundle),
            "workflow_file": str(dest_workflow),
            "flow_name": flow_name,
        },
        "warnings": [],
    }


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    action = str(params.get("action") or "match").strip().lower()
    if action == "list":
        rows = _list_records(ctx)
        return {"ok": True, "records": rows, "count": len(rows), "data": {"records": rows, "count": len(rows)}, "warnings": []}
    if action == "get":
        return _get_record(ctx, params)
    if action == "resolve_flow":
        return _resolve_flow(ctx, params)
    if action == "delete":
        return _delete_record(ctx, params)
    if action == "backfill_semantic_metadata":
        return _backfill_semantic_metadata(ctx, params)
    if action == "update":
        return _update_record(ctx, params)
    if action == "register":
        return _register(ctx, params)
    if action == "match":
        return _match(ctx, params)
    return {"ok": False, "data": {}, "warnings": [f"unsupported_action:{action}"]}


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Temp Library",
    "description": "Match against or register generated workflow bundles in a reusable temporary sandbox library.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "pid": {"type": "string"},
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "bundle_dir": {"type": "string"},
            "workflow_file": {"type": "string"},
            "flow_name": {"type": "string"},
            "summary": {"type": "string"},
            "min_score": {"type": "number"},
            "id": {"type": "string"},
            "record_id": {"type": "string"},
        },
        "additionalProperties": True,
    },
}




