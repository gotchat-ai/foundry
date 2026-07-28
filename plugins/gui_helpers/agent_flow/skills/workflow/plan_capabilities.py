from __future__ import annotations

from pathlib import Path as _Path
import hashlib
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from typing import Any, Dict, List

from _wfcommon import available_skill_specs, infer_request_capabilities, normalize_missing_skill_specs, slugify


NAME = "workflow.plan_capabilities"
PERMISSIONS = ["workflow.plan_capabilities", "workflow.*"]


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ("current_request_text", "user_request", "request", "prompt", "text"):
        val = str((params or {}).get(key) or "").strip()
        if val:
            return val
    for key in ("original_request", "user_text"):
        val = str((ctx or {}).get(key) or "").strip()
        if val:
            return val
    return ""


def _first_matching_skill(specs: Dict[str, Dict[str, Any]], prefixes: List[str]) -> str:
    keys = sorted(str(k or "").strip() for k in specs.keys() if str(k or "").strip())
    for prefix in prefixes:
        low = prefix.lower()
        if low.endswith("."):
            for key in keys:
                if key.lower().startswith(low):
                    return key
        else:
            for key in keys:
                if low in key.lower():
                    return key
    return ""


def _all_matching_skills(specs: Dict[str, Dict[str, Any]], prefixes: List[str], limit: int = 8) -> List[str]:
    out: List[str] = []
    for prefix in prefixes:
        hit = _first_matching_skill(specs, [prefix])
        if hit and hit not in out:
            out.append(hit)
        if len(out) >= limit:
            break
    return out


def _needs_approval(request_text: str, capability_ids: List[str]) -> bool:
    low = str(request_text or "").lower()
    if any(
        tok in low
        for tok in (
            "portal",
            "log in",
            "login",
            "browser",
            "website",
            "current",
            "currently going on",
            "live",
            "download",
            "web",
            "internet",
        )
    ):
        return True
    return bool({"web_research", "sports_live_data", "portal_reconciliation"} & set(capability_ids))


def _output_mode(request_text: str, capability_ids: List[str]) -> str:
    low = str(request_text or "").lower()
    caps = set(capability_ids)
    explicit_file_tokens = (
        "export",
        "download",
        "downloadable",
        "save as",
        "save the",
        "write a file",
        "create a file",
        "output file",
        "workbook",
        "pdf report",
    )
    summary_tokens = (
        "executive summary",
        "summary",
        "summarize",
        "breakdown",
        "table",
        "tabular",
        "markdown table",
        "explain",
        "highlight",
        "flag",
        "report",
    )
    if "archive_output" in caps or any(tok in low for tok in ("zip", "archive", "bundle", "packet")):
        return "zip"
    if "portal_reconciliation" in caps:
        return "file"
    if "sports_live_data" in caps and not any(tok in low for tok in explicit_file_tokens):
        return "table_text"
    if "market_data" in caps and not any(tok in low for tok in explicit_file_tokens):
        return "table_text"
    if "file_output" in caps or any(tok in low for tok in explicit_file_tokens):
        return "file"
    if any(tok in low for tok in ("table", "table view", "markdown table")) and "file_output" not in caps:
        return "table_text"
    if "spreadsheet_io" in caps and any(tok in low for tok in summary_tokens):
        return "table_text"
    if "pdf_processing" in caps and any(tok in low for tok in summary_tokens):
        return "text"
    if "spreadsheet_io" in caps or "pdf_processing" in caps:
        return "file"
    return "text"


def _executor_mode(request_text: str, capability_ids: List[str]) -> str:
    low = str(request_text or "").lower()
    caps = set(capability_ids)
    if "portal_reconciliation" in caps:
        return "portal_reconciliation"
    if "sports_live_data" in caps:
        return "sports_live_table"
    if "weather_lookup" in caps:
        return "weather_lookup"
    if "market_data" in caps:
        return "market_data"
    if "web_research" in caps and any(tok in low for tok in ("weather", "forecast", "temperature", "rain", "humidity", "wind")):
        return "weather_lookup"
    if "pdf_processing" in caps and any(tok in low for tok in ("ocr", "extract", "extracted", "scan", "scanned", "receipt", "convert", "csv", "fields", ".png", ".jpg", ".jpeg", ".webp")):
        return "ocr_extraction"
    if "pdf_processing" in caps and any(tok in low for tok in ("contract", "agreement", "clause", "obligation", "legal")):
        return "document_review"
    if "spreadsheet_io" in caps and "web_research" in caps:
        return "spreadsheet_enrichment"
    if "spreadsheet_io" in caps:
        return "data_analysis"
    if "web_research" in caps and "content_authoring" in caps:
        return "research"
    if "web_research" in caps:
        return "research"
    if "content_authoring" in caps:
        return "authoring"
    return "general"


def _needs_composite_executor(request_text: str, capability_ids: List[str], output_mode: str, executor_mode: str) -> bool:
    low = str(request_text or "").lower()
    caps = set(capability_ids)
    deliverable_tokens = (
        "summary",
        "summarize",
        "brief",
        "memo",
        "register",
        "triage",
        "timeline",
        "recommend",
        "recommendation",
        "shortlist",
        "faq",
        "plan",
        "review",
        "announcement",
        "compare",
        "highlight",
        "flags",
        "questions",
    )
    asks_for_deliverable = any(tok in low for tok in deliverable_tokens)
    file_backed = "/app/" in low and any(ext in low for ext in (".csv", ".tsv", ".xlsx", ".xls", ".json", ".txt", ".md"))
    ocr_transform = any(tok in low for tok in ("ocr", "extract", "extracted", "scan", "scanned", "receipt", "convert", "csv", "fields"))
    if executor_mode == "portal_reconciliation" and "portal_reconciliation" in caps:
        return True
    if executor_mode == "research" and "web_research" in caps:
        return True
    if executor_mode == "market_data" and "market_data" in caps:
        return True
    if executor_mode == "data_analysis" and "spreadsheet_io" in caps and (asks_for_deliverable or file_backed):
        return True
    if executor_mode == "document_review" and "pdf_processing" in caps and asks_for_deliverable:
        return True
    if "pdf_processing" in caps and (ocr_transform or file_backed) and output_mode in {"file", "table_text", "zip"}:
        return True
    if executor_mode == "spreadsheet_enrichment" and {"spreadsheet_io", "web_research"} & caps:
        return True
    return output_mode in {"table_text", "zip"} and asks_for_deliverable


def _merge_missing(base: List[Dict[str, Any]], extra: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for row in [*base, *extra]:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("id") or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        out.append(row)
    return out


def _filter_missing_specs_for_request(
    specs: List[Dict[str, Any]],
    *,
    request_text: str,
    executor_mode: str,
    capability_ids: List[str],
) -> List[Dict[str, Any]]:
    current_caps = {str(x or "").strip() for x in capability_ids if str(x or "").strip()}
    request_low = str(request_text or "").strip().lower()
    filtered: List[Dict[str, Any]] = []
    for row in specs:
        if not isinstance(row, dict):
            continue
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        hint = str(row.get("implementation_hint") or metadata.get("executor_mode") or "").strip()
        if hint and executor_mode and hint != executor_mode:
            continue
        required_caps = {
            str(x or "").strip()
            for x in (metadata.get("required_capabilities") or [])
            if str(x or "").strip()
        }
        if required_caps and current_caps and required_caps.isdisjoint(current_caps):
            continue
        req_excerpt = str(row.get("request_text") or metadata.get("request_excerpt") or "").strip().lower()
        if req_excerpt and request_low:
            excerpt_tokens = {tok for tok in req_excerpt.split() if len(tok) >= 4}
            request_tokens = {tok for tok in request_low.split() if len(tok) >= 4}
            if excerpt_tokens and request_tokens:
                overlap = len(excerpt_tokens & request_tokens)
                if overlap == 0:
                    continue
        filtered.append(row)
    return filtered


def _generated_skill_id(flow_name: str, request_text: str, executor_mode: str) -> str:
    flow_slug = slugify(flow_name or request_text[:72] or "generated_workflow", "generated_workflow")
    seed = f"{flow_slug}|{executor_mode}|{request_text}".encode("utf-8", errors="ignore")
    suffix = hashlib.sha1(seed).hexdigest()[:8]
    return f"custom.{flow_slug}_{suffix}_executor"


def _generated_skill_spec(flow_name: str, request_text: str, unmet_caps: List[Dict[str, Any]], matched_skills: List[str], output_mode: str, executor_mode: str) -> Dict[str, Any]:
    flow_slug = slugify(flow_name or request_text[:72] or "generated_workflow", "generated_workflow")
    cap_ids = [str(row.get("id") or "").strip() for row in unmet_caps if str(row.get("id") or "").strip()]
    if executor_mode == "portal_reconciliation":
        skill_id = _generated_skill_id(flow_name, request_text, executor_mode)
        label = "Portal Reconciliation"
        description = "The request requires logging into a portal, acquiring statements, reconciling them against local files, and producing a discrepancy workbook."
    elif executor_mode == "market_data":
        skill_id = f"custom.{flow_slug}_market_data_report"
        label = "Market Data Report"
        description = "Fetch current market symbols and quotes, compute bounded momentum metrics, and return the requested stock list or report output."
    else:
        skill_id = _generated_skill_id(flow_name, request_text, executor_mode)
        label = f"{flow_slug} executor"
        description = f"Generated workflow executor for: {request_text[:200]}".strip()
    params_properties: Dict[str, Any] = {
        "request_text": {"type": "string"},
        "user_request": {"type": "string"},
        "request": {"type": "string"},
        "text": {"type": "string"},
        "input_path": {"type": "string"},
        "file_path": {"type": "string"},
        "path": {"type": "string"},
    }
    required_params: List[str] = []
    if executor_mode == "sports_live_table":
        params_properties.update(
            {
                "scoreboard_paths": {
                    "type": "array",
                    "description": "Model-selected scoreboard source paths. Each item must include provider sport path, provider league path, and optional display label.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "sport": {"type": "string"},
                            "league": {"type": "string"},
                            "label": {"type": "string"},
                        },
                        "required": ["sport", "league"],
                        "additionalProperties": True,
                    },
                },
                "source_urls": {
                    "type": "array",
                    "description": "Optional direct scoreboard API URLs selected by the model or planner.",
                    "items": {
                        "oneOf": [
                            {"type": "string"},
                            {
                                "type": "object",
                                "properties": {
                                    "url": {"type": "string"},
                                    "label": {"type": "string"},
                                },
                                "required": ["url"],
                                "additionalProperties": True,
                            },
                        ]
                    },
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
            }
        )
    return {
        "id": skill_id,
        "category": "custom",
        "label": label,
        "description": description,
        "reason": "Required because the current installed skills do not fully satisfy the request.",
        "params_schema": {
            "type": "object",
            "properties": params_properties,
            **({"required": required_params} if required_params else {}),
            "additionalProperties": True,
        },
        "metadata": {
            "executor_mode": executor_mode,
            "output_mode": output_mode,
            "required_capabilities": cap_ids,
            "matched_skills": list(matched_skills),
            "request_excerpt": request_text[:240],
            "input_contract": (
                "For sports_live_table, the model/planner must pass scoreboard_paths or source_urls. "
                "The executor resolves human sport/league labels to provider paths at runtime instead of relying on hardcoded topic lists. "
                "For broad categories, the planner should provide multiple concrete provider path candidates or direct source URLs, not placeholder catch-all names."
                if executor_mode == "sports_live_table"
                else ""
            ),
        },
        "implementation_hint": executor_mode,
    }


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    request_text = _request_text(ctx, params)
    flow_name = str(params.get("flow_name") or "").strip() or slugify(request_text[:72] or "generated_workflow", "generated_workflow")
    available = available_skill_specs(ctx)
    capability_rows = [row for row in infer_request_capabilities(request_text) if isinstance(row, dict)]
    capability_ids = [str(row.get("id") or "").strip() for row in capability_rows if str(row.get("id") or "").strip()]
    matched_capabilities: List[Dict[str, Any]] = []
    unmet_capabilities: List[Dict[str, Any]] = []
    matched_skill_ids: List[str] = []

    for row in capability_rows:
        prefixes = [str(x or "").strip() for x in (row.get("required_any") or []) if str(x or "").strip()]
        fallback_prefixes = [str(x or "").strip() for x in (row.get("optional_any") or []) if str(x or "").strip()]
        found = _all_matching_skills(available, prefixes or fallback_prefixes, limit=6)
        row_out = {
            "id": str(row.get("id") or "").strip(),
            "reason": str(row.get("reason") or "").strip(),
            "matched_skills": list(found),
        }
        if found:
            matched_capabilities.append(row_out)
            for skill_id in found:
                if skill_id not in matched_skill_ids:
                    matched_skill_ids.append(skill_id)
        else:
            unmet_capabilities.append(row_out)

    output_mode = _output_mode(request_text, capability_ids)
    executor_mode = _executor_mode(request_text, capability_ids)
    approval_required = _needs_approval(request_text, capability_ids)

    composite_executor_required = _needs_composite_executor(request_text, capability_ids, output_mode, executor_mode)
    incoming_missing = _filter_missing_specs_for_request(
        normalize_missing_skill_specs(params.get("missing_skill_specs")),
        request_text=request_text,
        executor_mode=executor_mode,
        capability_ids=capability_ids,
    )
    generated_missing: List[Dict[str, Any]] = []
    if unmet_capabilities or composite_executor_required:
        generated_missing.append(
            _generated_skill_spec(
                flow_name=flow_name,
                request_text=request_text,
                unmet_caps=unmet_capabilities,
                matched_skills=matched_skill_ids,
                output_mode=output_mode,
                executor_mode=executor_mode,
            )
        )
    missing_skill_specs = _merge_missing(incoming_missing, generated_missing)

    summary = (
        f"Planned capabilities for '{flow_name}'. "
        f"Matched {len(matched_capabilities)} capability group(s), unmet {len(unmet_capabilities)} capability group(s), "
        f"output_mode={output_mode}, executor_mode={executor_mode}, composite_executor_required={str(composite_executor_required).lower()}."
    )

    return {
        "ok": True,
        "flow_name": flow_name,
        "request_text": request_text,
        "capabilities": capability_rows,
        "matched_capabilities": matched_capabilities,
        "unmet_capabilities": unmet_capabilities,
        "matched_skill_ids": matched_skill_ids,
        "missing_skill_specs": missing_skill_specs,
        "approval_required": approval_required,
        "output_mode": output_mode,
        "executor_mode": executor_mode,
        "summary": summary,
        "data": {
            "flow_name": flow_name,
            "request_text": request_text,
            "capabilities": capability_rows,
            "matched_capabilities": matched_capabilities,
            "unmet_capabilities": unmet_capabilities,
            "matched_skill_ids": matched_skill_ids,
            "missing_skill_specs": missing_skill_specs,
            "approval_required": approval_required,
            "output_mode": output_mode,
            "executor_mode": executor_mode,
            "summary": summary,
            "composite_executor_required": composite_executor_required,
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Plan Capabilities",
    "description": "Plan matched and unmet workflow capabilities, emit missing_skill_specs for unmet capability groups, and recommend a generic scaffold profile.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "prompt": {"type": "string"},
            "text": {"type": "string"},
            "flow_name": {"type": "string"},
            "missing_skill_specs": {"type": "array", "items": {}},
        },
        "additionalProperties": True,
    },
}
