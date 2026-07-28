from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from typing import Any, Dict, List

from _wfcommon import extract_referenced_skills, load_workflow_target
from generate_test_requests import run as generic_generate_test_requests


NAME = "workflow.generate_test_requests_capability"
PERMISSIONS = ["workflow.generate_test_requests_capability", "workflow.*"]


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


def _looks_file_backed(text: str) -> bool:
    low = str(text or "").lower()
    if not low:
        return False
    return any(ext in low for ext in (".csv", ".tsv", ".xlsx", ".xls", ".json", ".txt", ".md", ".pdf", ".docx", "/app/", "c:\\"))


def _file_backed_requests(request_text: str) -> List[str]:
    base = request_text.strip()
    if not base:
        return []
    return [
        base,
        f"{base} Use reasonable assumptions for any missing low-risk details and explain them clearly.",
        f"{base} Preserve an audit-friendly summary of what inputs were used, what actions were taken, and what outputs were produced.",
        f"{base} Handle incomplete or messy rows gracefully and still return the best bounded result you can.",
        f"{base} Produce the final answer in a reviewer-ready format with a concise executive summary and a clear table when the data supports it.",
    ]


def _market_requests(request_text: str) -> List[str]:
    base = request_text.strip() or "Create a downloadable market-data report with day and week analysis."
    return [
        f"{base} Return a downloadable market report artifact with summary metrics and chart payload files.",
        "Build a market workflow that retrieves top trending US tickers, compares day versus week momentum, and returns a downloadable report file.",
        "Create a workflow for a portfolio review that ranks trending stocks by volume, day change, and week change, then export the report artifact.",
        "Generate a workflow that gathers top market movers, computes bounded momentum and sell-pressure proxies, and returns a downloadable output file.",
        "Produce a workflow that analyzes trending equities for one-day and one-week performance and exports a chart-ready report artifact.",
    ]


def _campaign_reporting_requests(request_text: str) -> List[str]:
    base = request_text.strip() or "Create a campaign performance reporting workflow."
    return [
        f"{base} Return a downloadable campaign summary artifact with anomaly flags and executive briefing text.",
        "Build a workflow that summarizes channel metrics, flags anomalies, and returns a downloadable campaign report artifact.",
        "Create a campaign reporting workflow that produces an executive briefing file and highlights anomalous channel performance.",
        "Generate a workflow for campaign performance review that returns a downloadable artifact with channel summaries and anomaly notes.",
        "Produce a campaign reporting workflow that emits a file artifact containing channel metrics, anomaly flags, and a concise executive briefing.",
    ]


def _legal_contract_requests(request_text: str) -> List[str]:
    base = request_text.strip() or "Create a workflow for contract clause extraction and legal exception reporting."
    return [
        f"{base} Return a structured clause and exception summary for an uploaded agreement.",
        "Build a workflow that extracts key clauses, risk flags, and attorney-ready exceptions from a contract and returns a readable summary.",
        "Create a legal workflow that reviews an uploaded agreement and reports obligations, risky clauses, and exception notes.",
        "Generate a contract analysis workflow that identifies important clauses and produces an attorney-ready review output.",
        "Produce a workflow for agreement review that extracts legal issues, flags missing clauses, and summarizes next actions.",
    ]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    target = load_workflow_target(ctx, params)
    if not target.get("ok"):
        return target

    flow_name = str(target.get("flow_name") or "").strip()
    flow = target.get("workflow_json") if isinstance(target.get("workflow_json"), dict) else {}
    request_text = _request_text(ctx, params)
    referenced = [str(x or "").strip().lower() for x in extract_referenced_skills(flow)]
    desc = str(flow.get("description") or "").lower()
    blob = " ".join([flow_name.lower(), desc, " ".join(referenced), request_text.lower()])

    if _looks_file_backed(request_text):
        requests = _file_backed_requests(request_text)
        summary = "Generated five file-backed validation requests that preserve the original input paths and output expectations."
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
            "flow_ext": {},
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
                "flow_ext": {},
                "test_plan_summary": summary,
            },
            "warnings": [],
        }

    if "custom.market_data_report" in referenced or any(tok in blob for tok in ("market", "ticker", "stock", "finance", "portfolio", "trending")):
        requests = _market_requests(request_text)
        summary = "Generated five market-data validation requests aligned to the capability-template workflow."
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
            "flow_ext": {},
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
                "flow_ext": {},
                "test_plan_summary": summary,
            },
            "warnings": [],
        }
    if any(tok in blob for tok in ("contract", "agreement", "clause", "attorney", "obligation", "exception")):
        requests = _legal_contract_requests(request_text)
        summary = "Generated five legal-contract validation requests aligned to the document extraction and review workflow."
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
            "flow_ext": {},
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
                "flow_ext": {},
                "test_plan_summary": summary,
            },
            "warnings": [],
        }

    if "custom.campaign_performance_report" in referenced or any(tok in blob for tok in ("campaign", "channel metrics", "anomaly", "briefing")):
        requests = _campaign_reporting_requests(request_text)
        summary = "Generated five campaign-reporting validation requests aligned to the campaign artifact workflow."
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
            "flow_ext": {},
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
                "flow_ext": {},
                "test_plan_summary": summary,
            },
            "warnings": [],
        }

    return generic_generate_test_requests(ctx, params)


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Generate Test Requests Capability",
    "description": "Generate capability-aware sandbox validation requests for a loaded workflow target, falling back to the generic request generator when appropriate.",
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
