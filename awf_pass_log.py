from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List


PASS_LOG_FIELDS = [
    "request_id",
    "request_dir",
    "request_file",
    "source_file",
    "result_file",
    "record_id",
    "flow_name",
    "workflow_file",
    "bundle_dir",
    "validation_profile",
    "selected_flow_source",
    "judge_score",
    "judge_reason",
    "notes",
    "created_ts",
]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _guess_request_id(*values: Any) -> str:
    parts = [_clean(v) for v in values if _clean(v)]
    for value in parts:
        for token in value.replace("/", "\\").split("\\"):
            token = token.strip()
            if token.startswith("request_"):
                return token
    return ""


def _guess_request_dir(*values: Any) -> str:
    parts = [_clean(v) for v in values if _clean(v)]
    for value in parts:
        normalized = value.replace("/", "\\")
        marker = "autoflow_"
        idx = normalized.find(marker)
        if idx < 0:
            continue
        tail = normalized[idx:]
        chunks = [chunk for chunk in tail.split("\\") if chunk]
        if len(chunks) >= 2 and chunks[0].startswith("autoflow_") and chunks[1].startswith("request_"):
            return "\\".join(chunks[:2])
    request_id = _guess_request_id(*values)
    if request_id:
        for value in parts:
            normalized = value.replace("/", "\\")
            if request_id in normalized and "autoflow_" in normalized:
                prefix = normalized.split(request_id, 1)[0].rstrip("\\")
                bits = [bit for bit in prefix.split("\\") if bit.startswith("autoflow_")]
                if bits:
                    return bits[-1] + "\\" + request_id
    return ""


def _looks_like_request_dir(value: str) -> bool:
    normalized = _clean(value).replace("/", "\\")
    if not normalized:
        return False
    chunks = [chunk for chunk in normalized.split("\\") if chunk]
    return len(chunks) >= 2 and chunks[-2].startswith("autoflow_") and chunks[-1].startswith("request_")


def normalize_pass_log_row(row: Dict[str, Any]) -> Dict[str, str]:
    request_id = _clean(row.get("request_id"))
    request_dir = _clean(row.get("request_dir"))
    request_file = _clean(row.get("request_file"))
    source_file = _clean(row.get("source_file"))
    result_file = _clean(row.get("result_file") or row.get("file"))
    record_id = _clean(row.get("record_id"))
    flow_name = _clean(row.get("flow_name"))
    workflow_file = _clean(row.get("workflow_file"))
    bundle_dir = _clean(row.get("bundle_dir"))
    validation_profile = _clean(row.get("validation_profile"))
    selected_flow_source = _clean(row.get("selected_flow_source"))
    judge_score = _clean(row.get("judge_score"))
    judge_reason = _clean(row.get("judge_reason"))
    notes = _clean(row.get("notes"))
    created_ts = _clean(row.get("created_ts"))

    if not request_id:
        request_id = _guess_request_id(request_dir, request_file, source_file, result_file, notes)
    if not _looks_like_request_dir(request_dir):
        request_dir = _guess_request_dir(request_dir, request_file, source_file, result_file, notes)
    if not request_file.lower().endswith("request.txt") and request_dir:
        request_file = request_dir.replace("\\", "/") + "/request.txt"
    if not source_file and request_dir:
        source_file = request_dir
    if not workflow_file and bundle_dir and flow_name:
        workflow_file = bundle_dir.rstrip("/\\") + "/" + flow_name + ".json"
    if not notes and validation_profile and validation_profile not in {
        "saved_result_import",
        "harness_rerun_import",
        "judge_pass_attempt1",
        "direct_run_request_once_judged_pass",
        "live_backend_select_run_judge_pass",
    }:
        notes = validation_profile
    if not created_ts:
        created_ts = str(int(time.time()))

    normalized = {
        "request_id": request_id,
        "request_dir": request_dir,
        "request_file": request_file,
        "source_file": source_file,
        "result_file": result_file,
        "record_id": record_id,
        "flow_name": flow_name,
        "workflow_file": workflow_file,
        "bundle_dir": bundle_dir,
        "validation_profile": validation_profile,
        "selected_flow_source": selected_flow_source,
        "judge_score": judge_score,
        "judge_reason": judge_reason,
        "notes": notes,
        "created_ts": created_ts,
    }
    return {field: _clean(normalized.get(field)) for field in PASS_LOG_FIELDS}


def load_pass_log_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = []
        for raw in reader:
            if not isinstance(raw, dict):
                continue
            rows.append(normalize_pass_log_row(raw))
        return rows


def write_pass_log_rows(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=PASS_LOG_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(normalize_pass_log_row(dict(row)))


def append_pass_log_row(path: Path, row: Dict[str, Any]) -> None:
    rows = load_pass_log_rows(path)
    normalized = normalize_pass_log_row(row)
    dedupe_key = (
        normalized.get("request_id", ""),
        normalized.get("record_id", ""),
        normalized.get("workflow_file", ""),
        normalized.get("validation_profile", ""),
    )
    for existing in rows:
        existing_key = (
            existing.get("request_id", ""),
            existing.get("record_id", ""),
            existing.get("workflow_file", ""),
            existing.get("validation_profile", ""),
        )
        if existing_key == dedupe_key:
            return
    rows.append(normalized)
    write_pass_log_rows(path, rows)
