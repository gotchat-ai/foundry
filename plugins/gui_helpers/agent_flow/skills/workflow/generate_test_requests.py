from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from pathlib import Path
from typing import Any, Dict, List
import re

from _wfcommon import app_paths, load_workflow_target


NAME = "workflow.generate_test_requests"
PERMISSIONS = ["workflow.generate_test_requests", "workflow.*"]


def _repo_root_candidates(ctx: Dict[str, Any]) -> List[Path]:
    data_dir, _ = app_paths(ctx)
    return [
        data_dir / "agent_workflow" / "repo" / "chatjs",
        data_dir / "agent_workflow" / "repo",
    ]


def _existing_repo_root(ctx: Dict[str, Any]) -> str:
    spreadsheet_names = {
        "Technological-Products-Sample-Data.xlsx",
        "Project-Management-Sample-Data.xlsx",
        "Supermarket-Sales-Sample-Data.xlsx",
        "Healthcare-Insurance-Sample-Data.xlsx",
        "sample_employee_data.csv",
    }
    for cand in _repo_root_candidates(ctx):
        try:
            if cand.is_dir() and any((cand / name).is_file() for name in spreadsheet_names):
                return str(cand.resolve())
        except Exception:
            continue
    for cand in _repo_root_candidates(ctx):
        try:
            if cand.is_dir():
                return str(cand.resolve())
        except Exception:
            continue
    return ""


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ("user_request", "request", "prompt", "text"):
        val = str((params or {}).get(key) or "").strip()
        if val:
            return val
    for key in ("original_request", "user_text"):
        val = str((ctx or {}).get(key) or "").strip()
        if val:
            return val
    return ""


def _sample_spreadsheet_for_request(ctx: Dict[str, Any], request_text: str) -> str:
    low = str(request_text or "").lower()
    repo_root = _existing_repo_root(ctx)
    if not repo_root:
        return ""
    candidates = []
    if any(tok in low for tok in ("product", "competitor", "price", "sales", "retail")):
        candidates.append("Technological-Products-Sample-Data.xlsx")
        candidates.append("Supermarket-Sales-Sample-Data.xlsx")
    if any(tok in low for tok in ("project", "task", "timeline")):
        candidates.append("Project-Management-Sample-Data.xlsx")
    if any(tok in low for tok in ("health", "insurance", "member")):
        candidates.append("Healthcare-Insurance-Sample-Data.xlsx")
    candidates.extend([
        "Technological-Products-Sample-Data.xlsx",
        "Project-Management-Sample-Data.xlsx",
        "Supermarket-Sales-Sample-Data.xlsx",
        "sample_employee_data.csv",
    ])
    seen = set()
    for name in candidates:
        if name in seen:
            continue
        seen.add(name)
        path = Path(repo_root) / name
        try:
            if path.is_file():
                return str(path).replace("\\", "/")
        except Exception:
            continue
    return ""


def _repo_root_from_module() -> Path:
    here = Path(__file__).resolve()
    for parent in [here, *list(here.parents)]:
        if (parent / "autoflow_sequential_tests").is_dir():
            return parent
    return here.parents[5] if len(here.parents) > 5 else here.parent


def _tokenize(text: str) -> List[str]:
    return [tok for tok in re.findall(r"[a-z0-9]+", str(text or "").lower()) if len(tok) >= 4]


def _request_fixture_match(request_text: str) -> Dict[str, str]:
    low_request = str(request_text or "").strip().lower()
    if not low_request:
        return {}
    fixtures_root = _repo_root_from_module() / "autoflow_sequential_tests"
    if not fixtures_root.is_dir():
        return {}
    req_tokens = set(_tokenize(low_request))
    best: Dict[str, str] = {}
    best_score = 0.0
    for req_file in fixtures_root.glob("request_*/request.txt"):
        try:
            fixture_text = req_file.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        fixture_tokens = set(_tokenize(fixture_text))
        if not fixture_tokens:
            continue
        overlap = len(req_tokens & fixture_tokens)
        if overlap <= 0:
            continue
        score = overlap / max(1, len(req_tokens))
        root = req_file.parent
        candidate_files: List[Path] = []
        for sub in ("internal", "inputs", "source", ""):
            base = root / sub if sub else root
            if not base.exists():
                continue
            for pat in ("*.csv", "*.xlsx", "*.xls", "*.json", "*.tsv", "*.txt"):
                candidate_files.extend(sorted(base.glob(pat)))
        if not candidate_files:
            continue
        preferred = None
        for file_row in candidate_files:
            name_low = file_row.name.lower()
            if any(tok in name_low for tok in ("expected", "source", "input", "payments", "ledger", "statement", "invoice", "mapping")):
                preferred = file_row
                break
        sample_file = preferred or candidate_files[0]
        if score > best_score:
            best_score = score
            best = {
                "fixture_root": str(root).replace("\\", "/"),
                "input_path": str(sample_file).replace("\\", "/"),
                "request_text": fixture_text,
                "score": f"{score:.3f}",
            }
    return best if best_score >= 0.35 else {}


def _designer_requests() -> List[str]:
    return [
        "Design a workflow for weekly sales reporting with downloadable workflow json and bundle.",
        "Create a workflow for browser-driven competitor price monitoring with screenshots and weekly csv export, and provide the import json plus any missing skill stubs.",
        "Design a workflow for support incident triage from ticket exports and chat transcripts with downloadable workflow package.",
        "Create a workflow for release readiness across multiple services using docker diagnostics and browser smoke checks with a downloadable bundle.",
        "Design a workflow for contract pdf obligation extraction with reminder csv export and approval gates; provide the workflow json and bundle.",
    ]


def _validator_requests() -> List[str]:
    return [
        "Validate a generated workflow bundle and report whether the workflow JSON is structurally valid.",
        "Run a sandbox validation pass on a workflow target and return corrected workflow JSON if the first pass fails.",
        "Check whether a workflow target emits its downloadable workflow JSON after validation.",
        "Review sandbox pass/fail counts for a workflow target and summarize the concrete bugs and fixes.",
        "Validate a workflow target, apply deterministic repairs if needed, and return the corrected workflow JSON only if the suite passes.",
    ]


def _repo_debugger_requests() -> List[str]:
    return [
        "Inspect the target repo and identify the most likely file involved in a chat.js rendering issue, then summarize the evidence without editing files.",
        "Run a safe runtime-debugging pass and report the most actionable issue with its verified file path.",
        "Check whether the workflow can verify browser-console or app-runtime evidence and summarize the result without broad code changes.",
        "Perform a bounded release-readiness style debug pass and list the concrete verified issues and next fixes.",
        "Review the repo for one likely UI-state or streaming issue, explain the reasoning, and keep the validation focused on diagnosis rather than large edits.",
    ]


def _system_debugger_requests() -> List[str]:
    return [
        "Inspect the target repo and identify the most likely file tied to a chat.js rendering issue; return a concise diagnosis only.",
        "Verify whether the debugger flow can gather safe runtime evidence and summarize the strongest finding without editing files.",
        "Run a bounded debugger pass focused on one likely UI-state or streaming issue and explain the reasoning.",
        "Check whether the workflow can confirm the relevant file path for the issue and summarize the validated evidence only.",
        "Perform a short release-readiness debug review and list the top concrete issue plus the safest next step.",
    ]


def _browser_requests() -> List[str]:
    return [
        "Open a website, inspect the page, and summarize the visible content.",
        "Navigate a multi-step form, describe the required fields, and report blockers.",
        "Capture evidence from a browser workflow and explain what was found.",
        "Open a target site, inspect the DOM/state, and propose the next safe step.",
        "Validate a browser task flow and summarize whether it is ready for automation.",
    ]


def _generic_requests(flow_name: str) -> List[str]:
    base = flow_name or "workflow"
    return [
        f"Run the main happy-path behavior of {base} and summarize the result.",
        f"Exercise a common user request for {base} and report the output.",
        f"Test an edge case for {base} where the input is incomplete and explain the behavior.",
        f"Test a second edge case for {base} where the request is ambiguous and explain the behavior.",
        f"Run one more realistic validation request against {base} and summarize any issues.",
    ]


def _content_authoring_requests(request_text: str) -> List[str]:
    base = str(request_text or "").strip()
    if not base:
        return [
            "Create the requested written deliverable and make sure it is complete and well structured.",
            "Produce the same written deliverable in a concise but still complete form.",
            "Handle the request even if some details are implicit, and state any reasonable assumptions inside the response.",
            "Create the deliverable with clear section headings and directly usable content.",
            "Generate one more polished version of the requested text deliverable and keep it self-contained.",
        ]
    return [
        base,
        f"{base} Keep it concise but complete.",
        f"{base} If a few details are missing, make reasonable assumptions and state them briefly.",
        f"{base} Use clear section headings and classroom-ready wording.",
        f"{base} Produce a polished final version that is ready to use without extra edits.",
    ]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    target = load_workflow_target(ctx, params)
    if not target.get("ok"):
        return target

    flow_name = str(target.get("flow_name") or "").strip()
    flow = target.get("workflow_json") if isinstance(target.get("workflow_json"), dict) else {}
    desc = str(flow.get("description") or "").strip().lower()
    name_l = flow_name.lower()
    request_text = _request_text(ctx, params)
    skill_text = " ".join(str(x or "").strip().lower() for x in (
        ((flow.get("nodes") or {}) if isinstance(flow.get("nodes"), dict) else {}).keys()
    ))
    blob = " ".join([name_l, desc, skill_text, request_text.lower()])

    requests: List[str]
    flow_ext: Dict[str, Any] = {}
    summary = ""

    if "validator_sandbox" in name_l:
        requests = _validator_requests()
        summary = "Generated five workflow-validator requests focused on structural validation, repair, and corrected workflow JSON delivery."
    elif "workflow_designer" in name_l:
        requests = _designer_requests()
        summary = "Generated five workflow-design requests covering common and edge workflow-planning scenarios."
    elif "system_debugger" in name_l or "runtime debugger" in blob or "system debugger" in blob:
        requests = _system_debugger_requests()
        repo_root = _existing_repo_root(ctx)
        if repo_root:
            flow_ext["target_repo_root"] = repo_root
        summary = "Generated five bounded system-debugger validation requests and attached the default sandbox repo root."
    elif any(tok in blob for tok in ["repo", "debug", "git", "code", "chat.js", "chatjs"]):
        requests = _repo_debugger_requests()
        repo_root = _existing_repo_root(ctx)
        if repo_root:
            flow_ext["target_repo_root"] = repo_root
        summary = "Generated five repo-debugging requests and attached the default sandbox repo root."
    elif any(tok in blob for tok in ["browser", "browser_relay", "web_assistant"]):
        requests = _browser_requests()
        summary = "Generated five browser-automation validation requests."
    elif any(tok in blob for tok in ["lesson plan", "discussion questions", "homework", "objectives", "materials", "direct text-authoring workflow"]):
        requests = _content_authoring_requests(request_text)
        summary = "Generated five direct content-authoring validation requests derived from the original user request."
    else:
        requests = _generic_requests(flow_name)
        summary = "Generated five generic workflow validation requests."

    sample_sheet = _sample_spreadsheet_for_request(ctx, request_text)
    fixture_match = _request_fixture_match(request_text)
    if sample_sheet and any(tok in blob for tok in ["excel", "xlsx", "csv", "spreadsheet", "workbook", "sheet", "product", "competitor", "price"]):
        flow_ext["input_path"] = sample_sheet
        flow_ext["file_path"] = sample_sheet
        flow_ext["path"] = sample_sheet
        requests = [
            f"Use the spreadsheet file {sample_sheet} and generate the updated spreadsheet artifact for the requested workflow task.",
            f"Open and analyze {sample_sheet}. If the workflow updates a file, return the output artifact path.",
            f"Using {sample_sheet}, run the main happy-path behavior for this workflow and report any missing capabilities explicitly.",
            f"Test the workflow on {sample_sheet} and explain whether it can complete the requested spreadsheet task end-to-end.",
            f"Using {sample_sheet}, perform one more realistic validation run and summarize the exact artifact or missing capability.",
        ]
        summary = f"Generated five spreadsheet-grounded validation requests using sample file {sample_sheet}."
    elif fixture_match:
        sample_input = str(fixture_match.get("input_path") or "").strip()
        fixture_root = str(fixture_match.get("fixture_root") or "").strip()
        if sample_input:
            flow_ext["input_path"] = sample_input
            flow_ext["file_path"] = sample_input
            flow_ext["path"] = sample_input
            flow_ext["file"] = sample_input
        requests = [
            f"Use the fixture rooted at {fixture_root} and treat {sample_input} as the source file path. Complete the requested workflow task end-to-end and return the real output artifact path.",
            f"Run the workflow against fixture file {sample_input}. If the workflow produces a workbook or export, return the exact artifact path plus a concise audit summary.",
            f"Using the sample file {sample_input}, execute the main happy-path behavior for this workflow and explain any missing capability only if it truly blocks completion.",
            f"Validate the workflow with the fixture at {fixture_root} and summarize whether it can complete the requested task with reviewer-ready output.",
            f"Perform one more realistic run using {sample_input} and return the exact artifact or the single blocking issue.",
        ]
        summary = f"Generated five fixture-grounded validation requests using sample file {sample_input}."

    return {
        "ok": True,
        "flow_name": flow_name,
        "target_type": str(target.get("target_type") or ""),
        "pid": str(target.get("pid") or ""),
        "bundle_dir": str(target.get("bundle_dir") or ""),
        "workflow_file": str(target.get("workflow_file") or ""),
        "workflow_json": flow,
        "temp_skill_dirs": [str(x or "").strip() for x in (target.get("temp_skill_dirs") or []) if str(x or "").strip()],
        "test_requests": requests[:5],
        "flow_ext": flow_ext,
        "test_plan_summary": summary,
        "data": {
            "flow_name": flow_name,
            "target_type": str(target.get("target_type") or ""),
            "pid": str(target.get("pid") or ""),
            "bundle_dir": str(target.get("bundle_dir") or ""),
            "workflow_file": str(target.get("workflow_file") or ""),
            "workflow_json": flow,
            "temp_skill_dirs": [str(x or "").strip() for x in (target.get("temp_skill_dirs") or []) if str(x or "").strip()],
            "test_requests": requests[:5],
            "flow_ext": flow_ext,
            "test_plan_summary": summary,
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Generate Test Requests",
    "description": "Generate at least five realistic sandbox validation requests for a loaded workflow target, plus optional flow_ext hints such as target_repo_root.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "bundle_dir": {"type": "string"},
            "workflow_file": {"type": "string"},
            "flow_name": {"type": "string"},
            "pid": {"type": "string"},
        },
        "additionalProperties": True,
    },
}




