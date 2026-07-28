from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

try:
    from plugins.gui_helpers.agent_flow.skills import register_agent_flow_skills
except Exception:
    import importlib.util
    import sys
    _SKILLS_INIT = Path(__file__).resolve().parent.parent / "__init__.py"
    _SKILLS_SPEC = importlib.util.spec_from_file_location(
        "agent_flow_skills_local",
        _SKILLS_INIT,
        submodule_search_locations=[str(_SKILLS_INIT.parent)],
    )
    _SKILLS_MOD = importlib.util.module_from_spec(_SKILLS_SPEC)
    assert _SKILLS_SPEC is not None and _SKILLS_SPEC.loader is not None
    sys.modules[_SKILLS_SPEC.name] = _SKILLS_MOD
    _SKILLS_SPEC.loader.exec_module(_SKILLS_MOD)
    register_agent_flow_skills = _SKILLS_MOD.register_agent_flow_skills
import _workflow_store


def slugify(value: Any, fallback: str = "workflow") -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return text or fallback


_SENSITIVE_TEXT_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)\bpassword\s*[:=]\s*\S+", "<password>"),
    (r"(?i)\b(api[_ -]?key|token|bearer)\s*[:=]\s*\S+", "<api_key>"),
    (r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "<email>"),
    (r"(?i)\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b", "<phone>"),
    (r"(?i)\b[a-z]:\\[^\\\r\n\t]+(?:\\[^\\\r\n\t]+)*", "<local_path>"),
    (r"(?i)\b/app/[^\s\"']+", "<local_path>"),
    (r"(?i)\b(?:https?://)?(?:localhost|127\.0\.0\.1|host\.docker\.internal|[\w.-]+\.(?:local|internal|intra|lan))(?:[:/][^\s\"']*)?", "<private_url>"),
    (r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp|kafka|jdbc):[^\s\"'<>]+", "<connection_string>"),
    (r"(?i)\b[\w .-]+\.(?:html?|txt|csv|tsv|json|ya?ml|xml|md|docx?|pptx?|xlsx?|pdf|py|js|jsx|ts|tsx|css|sql|zip|png|jpe?g|gif|bmp|webp)\b", "<file>"),
]

_PUBLIC_TAG_STOPWORDS = {
    "a", "an", "and", "assistant", "bundle", "build", "built", "create", "created", "data", "file", "files",
    "flow", "for", "from", "general", "help", "import", "local", "need", "new", "plugin", "project", "public",
    "request", "run", "sanitize", "sanitized", "share", "shared", "task", "the", "this", "update", "user", "workflow",
}


def sanitize_sensitive_text(text: Any) -> str:
    out = str(text or "")
    for pattern, placeholder in _SENSITIVE_TEXT_PATTERNS:
        out = re.sub(pattern, placeholder, out, flags=re.IGNORECASE)
    return out.strip()



def _public_term_list(values: Iterable[Any]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values or []:
        text = slugify(value, "")
        if not text or text in seen or text in _PUBLIC_TAG_STOPWORDS:
            continue
        if text.startswith("local_") or text.startswith("temp_") or text.startswith("user_"):
            continue
        seen.add(text)
        out.append(text)
    return out



def derive_public_workflow_metadata(
    *,
    flow_name: Any = "",
    request_text: Any = "",
    summary: Any = "",
    description: Any = "",
    tags: Iterable[Any] | None = None,
    supported_capability_ids: Iterable[Any] | None = None,
    intent_tags: Iterable[Any] | None = None,
    subject_tags: Iterable[Any] | None = None,
) -> Dict[str, Any]:
    sanitized_flow_name = sanitize_sensitive_text(flow_name)
    sanitized_request = sanitize_sensitive_text(request_text)
    sanitized_summary = sanitize_sensitive_text(summary)
    sanitized_description = sanitize_sensitive_text(description)
    base_text = " ".join(
        part for part in [sanitized_flow_name, sanitized_request, sanitized_summary, sanitized_description] if str(part or "").strip()
    ).strip()
    inferred_caps = [
        slugify(item, "") for item in infer_request_capabilities(base_text) if slugify(item, "")
    ]
    capability_ids = _public_term_list(list(supported_capability_ids or []) + inferred_caps)
    intent_ids = _public_term_list(intent_tags or [])
    subject_ids = _public_term_list(subject_tags or [])
    tag_ids = _public_term_list(tags or [])
    if not subject_ids:
        subject_ids = [tag for tag in tag_ids if tag not in capability_ids and tag not in intent_ids][:4]
    if not intent_ids:
        intent_ids = [tag for tag in tag_ids if tag not in subject_ids and tag not in capability_ids][:3]
    combined_tags = _public_term_list(subject_ids + intent_ids + capability_ids)[:24]
    name_parts = (subject_ids[:2] or capability_ids[:1] or ["general"]) + (intent_ids[:1] or ["assist"])
    public_flow_name = slugify("_".join(name_parts + ["workflow"]), "workflow")
    subject_phrase = ", ".join(subject_ids[:2]).replace("_", " ") if subject_ids else "the detected request domain"
    intent_phrase = (intent_ids[0] if intent_ids else "complete").replace("_", " ")
    capability_phrase = ", ".join(capability_ids[:3]).replace("_", " ")
    public_summary = f"Reusable workflow for {intent_phrase} tasks involving {subject_phrase}."
    public_description = public_summary
    if capability_phrase:
        public_description = f"{public_summary} Supports {capability_phrase} capabilities."
    return {
        "flow_name": public_flow_name,
        "summary": public_summary,
        "description": public_description,
        "tags": combined_tags,
        "supported_capability_ids": capability_ids,
        "intent_tags": intent_ids,
        "subject_tags": subject_ids,
        "sanitized_request_text": sanitized_request,
        "sanitized_flow_name": sanitized_flow_name,
        "sanitized_summary": sanitized_summary,
        "sanitized_description": sanitized_description,
    }


def _contains_keyword(text: str, term: str) -> bool:
    source = str(text or "").lower()
    needle = str(term or "").lower().strip()
    if not source or not needle:
        return False
    if re.search(r"[a-z0-9]", needle) and " " not in needle and "-" not in needle:
        return re.search(rf"\b{re.escape(needle)}\b", source) is not None
    return needle in source


def app_paths(ctx: Dict[str, Any]) -> Tuple[Path, Path]:
    app = (ctx or {}).get("app") if isinstance(ctx, dict) else None
    data_dir_raw = getattr(getattr(app, "state", None), "data_dir", None) if app is not None else None
    workdir_raw = getattr(getattr(app, "state", None), "workdir", None) if app is not None else None
    repo_root = Path(__file__).resolve().parents[5]
    fallback_data_dir = (repo_root / "data").resolve()
    fallback_workdir = repo_root.resolve()
    data_dir = Path(str(data_dir_raw or "./data")).resolve()
    workdir = Path(str(workdir_raw or os.getcwd())).resolve()
    if data_dir_raw and not data_dir.exists() and fallback_data_dir.is_dir():
        data_dir = fallback_data_dir
    if workdir_raw and not workdir.exists() and fallback_workdir.is_dir():
        workdir = fallback_workdir
    return data_dir, workdir


def flows_dir(ctx: Dict[str, Any]) -> Path:
    data_dir, _ = app_paths(ctx)
    path = data_dir / "projects" / "agent_flow"
    path.mkdir(parents=True, exist_ok=True)
    return path


def generated_dir(ctx: Dict[str, Any]) -> Path:
    data_dir, _ = app_paths(ctx)
    path = data_dir / "generated" / "workflow_blueprints"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_cross_env_generated_path(ctx: Dict[str, Any], raw_path: str) -> Path:
    text = str(raw_path or "").strip()
    if not text:
        return Path(".").resolve()
    candidate = Path(text).resolve()
    if candidate.exists():
        return candidate
    normalized = text.replace("\\", "/").strip()
    lower_normalized = normalized.lower()
    suffixes: List[str] = []
    for prefix in (
        "/app/data/generated/workflow_blueprints/",
        "/app/generated/workflow_blueprints/",
        "c:/app/data/generated/workflow_blueprints/",
        "c:/app/generated/workflow_blueprints/",
    ):
        if lower_normalized.startswith(prefix.lower()):
            suffixes.append(normalized[len(prefix):])
    for marker in ("/data/generated/workflow_blueprints/", "/generated/workflow_blueprints/"):
        pos = lower_normalized.find(marker.lower())
        if pos >= 0:
            suffixes.append(normalized[pos + len(marker):])
    generated_root = generated_dir(ctx).resolve()
    repo_generated_root = (Path(__file__).resolve().parents[5] / "data" / "generated" / "workflow_blueprints").resolve()
    for rel in suffixes:
        rel_clean = str(rel or "").strip().lstrip("/").replace("\\", "/")
        if not rel_clean:
            continue
        for root in (repo_generated_root, generated_root):
            resolved = (root / rel_clean).resolve()
            if resolved.exists():
                return resolved
    return candidate


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    for enc in ("utf-8", "utf-8-sig", "utf-16"):
        try:
            with path.open("r", encoding=enc) as fh:
                row = json.load(fh)
            return row if isinstance(row, dict) else {}
        except Exception:
            continue
    return {}


def backup_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.bk")


def atomic_write_text(path: Path, content: str, *, make_backup: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = str(content or "")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if make_backup and path.exists():
            shutil.copy2(str(path), str(backup_path(path)))
        os.replace(str(tmp_path), str(path))
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


def atomic_write_json_doc(path: Path, payload: Dict[str, Any], *, ensure_ascii: bool = True, indent: int = 2, make_backup: bool = True) -> None:
    atomic_write_text(
        path,
        json.dumps(payload if isinstance(payload, dict) else {}, ensure_ascii=ensure_ascii, indent=indent) + "\n",
        make_backup=make_backup,
    )


def load_project_flows(ctx: Dict[str, Any], pid: str = "project2") -> Dict[str, Any]:
    return _workflow_store.load_project_flows(ctx, pid)


def load_default_flows(ctx: Dict[str, Any]) -> Dict[str, Any]:
    return _workflow_store.load_default_flows(ctx)


def available_skill_specs(ctx: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    app = (ctx or {}).get("app") if isinstance(ctx, dict) else None
    if app is None:
        return {}
    specs = getattr(app.state, "agent_flow_skill_specs", None)
    if not isinstance(specs, dict) or not specs:
        register_agent_flow_skills(app)
        specs = getattr(app.state, "agent_flow_skill_specs", None)
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(specs, dict):
        for key, value in specs.items():
            if isinstance(value, dict):
                out[str(key)] = dict(value)
    return out


def summarize_flow(name: str, flow: Dict[str, Any]) -> Dict[str, Any]:
    nodes = flow.get("nodes") if isinstance(flow.get("nodes"), dict) else {}
    node_types = set()
    transition_types = set()
    action_skills = set()
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        ps = node.get("plugin_settings") if isinstance(node.get("plugin_settings"), dict) else {}
        node_type = str(ps.get("node_type") or "").strip()
        if node_type:
            node_types.add(node_type)
        for skill in ps.get("action_skills") or []:
            skill_id = str(skill or "").strip()
            if skill_id:
                action_skills.add(skill_id)
        tool_cfg = ps.get("tool_config") if isinstance(ps.get("tool_config"), dict) else {}
        tool_name = str(tool_cfg.get("tool") or "").strip()
        if tool_name:
            action_skills.add(tool_name)
        for transition in node.get("transitions") or []:
            cond = transition.get("condition") if isinstance(transition, dict) else {}
            cond_type = str((cond or {}).get("type") or "").strip()
            if cond_type:
                transition_types.add(cond_type)
    return {
        "name": str(flow.get("name") or name),
        "flow_id": name,
        "description": str(flow.get("description") or "").strip(),
        "start": str(flow.get("start") or "").strip(),
        "node_count": len(nodes),
        "node_ids": sorted(nodes.keys()),
        "node_types": sorted(node_types),
        "transition_types": sorted(transition_types),
        "action_skills": sorted(action_skills),
    }


def _capability_focus_text(text: Any) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    match = re.search(
        r"original user request:\s*(.+?)(?:\n\s*\n|\n(?:likely required capabilities|unmet live-data requirement|web research requirement|sports live-data requirement|nearby existing flow coverage|the generated workflow must)\b|$)",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return raw
    extracted = str(match.group(1) or "").strip()
    return extracted or raw


def infer_request_capabilities(text: Any) -> List[Dict[str, Any]]:
    low = _capability_focus_text(text).lower()
    caps: List[Dict[str, Any]] = []
    workflow_creation_intent = any(
        tok in low
        for tok in (
            "create a workflow",
            "create me a workflow",
            "build a workflow",
            "build me a workflow",
            "design a workflow",
            "generate a workflow",
            "make a workflow",
            "workflow for ",
            "subflow for ",
            "agent flow",
        )
    )

    def _add(cap_id: str, reason: str, required: List[str], optional: List[str] | None = None) -> None:
        caps.append(
            {
                "id": cap_id,
                "reason": reason,
                "required_any": list(required),
                "optional_any": list(optional or []),
            }
        )

    portal_terms = (
        "portal",
        "vendor portal",
        "log in",
        "login",
        "statement",
        "statements",
        "download",
        "downloads",
    )
    reconcile_terms = (
        "reconcile",
        "reconciliation",
        "compare",
        "comparison",
        "discrepancy",
        "discrepancies",
        "mismatch",
        "mismatches",
        "variance",
        "exception",
    )
    workbook_terms = (
        "spreadsheet",
        "workbook",
        "excel",
        ".xlsx",
        ".xls",
        ".csv",
        "ledger",
    )
    if (
        any(tok in low for tok in portal_terms)
        and any(tok in low for tok in reconcile_terms)
        and any(tok in low for tok in workbook_terms)
    ):
        _add(
            "portal_reconciliation",
            "The request requires logging into a portal, acquiring statements, reconciling them against local files, and producing a discrepancy workbook.",
            [
                "custom.portal_statement_reconciliation",
                "custom.vendor_portal_reconciliation",
                "custom.statement_reconciliation",
                "custom.portal_reconciliation_executor",
            ],
        )

    if any(tok in low for tok in ("excel", ".xlsx", ".xls", ".csv", "spreadsheet", "workbook", "sheet ")):
        _add(
            "spreadsheet_io",
            "The request requires reading or updating spreadsheet data.",
            ["custom.spreadsheet_competitor_update", "custom.campaign_performance_report", "custom.spreadsheet_profile_report", "sheet.read_large", "sheet.profile", "sheet.search", "sheet.update", "sheet.export", "sheet."],
            ["result.file", "result.files"],
        )
    if (not workflow_creation_intent) and any(
        tok in low
        for tok in (
            "lesson plan",
            "write a lesson plan",
            "create a lesson plan",
            "draft a lesson plan",
            "write an email",
            "draft an email",
            "write a summary",
            "create a summary",
            "write a memo",
            "draft a memo",
            "write a report",
            "draft a report",
            "create a report",
            "discussion questions",
            "class discussion response",
            "essay",
            "concept statement",
            "artist statement",
            "project series",
            "project ideas",
            "research paper proposal",
            "homework",
            "objectives",
            "materials",
            "macro brief",
            "investor-style",
            "plain-language summary",
            "methods-oriented synthesis",
            "strongest repeated findings",
        )
    ):
        _add(
            "content_authoring",
            "The request is a direct text-authoring task that should produce a textual deliverable.",
            ["result.text"],
        )
    if any(
        tok in low
        for tok in (
            "updated excel",
            "updated csv",
            "download",
            "downloadable",
            "export",
            "save as",
            "save the",
            "save to",
            "write a file",
            "create a file",
            "output file",
            "generate a file",
            "return a file",
            "return the file",
            "return an xlsx",
            "return a csv",
            "return a pdf",
            "produce a workbook",
            "deliver a workbook",
        )
    ):
        _add(
            "file_output",
            "The request expects a generated or downloadable file output.",
            ["result.file", "result.files", "sheet.export"],
        )
    explicit_web_research = any(
        tok in low
        for tok in (
            "online",
            "website",
            "web ",
            "browser",
            "search",
            "google",
            "competitor",
            "internet",
            "news",
            "headline",
            "headlines",
            "top stories",
            "breaking story",
            "breaking stories",
            "trending",
            "trend",
            "trends",
            "youtube",
            "current",
            "latest",
            "today",
            "tonight",
            "live",
            "real data",
            "real-world data",
            "housing prices",
            "inflation",
            "college tuition",
            "affordability",
            "energy costs",
            "migration today",
            "global migration today",
            "current energy costs",
            "world bank",
            "imf",
            "google scholar",
            "scholar",
            "arxiv",
            "scholarly sources",
            "scholarly source",
            "recent papers",
            "papers with title",
            "macro brief",
            "investor-style",
        )
    )
    portal_browser_only = (
        "portal_reconciliation" in {str(row.get("id") or "").strip() for row in caps}
        and not explicit_web_research
    )
    if any(_contains_keyword(low, tok) for tok in ("weather", "forecast", "temperature", "humidity", "wind", "rain chance", "precipitation")):
        _add(
            "weather_lookup",
            "The request requires current weather conditions or same-day forecast lookup.",
            ["external_data.weather_lookup"],
            ["browser_relay.open", "browser_relay.snapshot", "browser_relay.action", "browser_relay.", "searxng", "web.", "browser."],
        )
    if explicit_web_research or ("portal" in low and not portal_browser_only):
        _add(
            "web_research",
            "The request requires external web or browser capability.",
            ["custom.spreadsheet_competitor_update", "custom.market_data_report", "custom.web_research", "web_research_skill", "browser_relay.open", "browser_relay.snapshot", "browser_relay.action", "browser_relay.", "searxng", "web.", "browser."],
            ["system.browser_smoke"],
        )
    market_terms = (
        "stock",
        "stocks",
        "ticker",
        "tickers",
        "market",
        "markets",
        "finance",
        "yahoo finance",
        "portfolio",
        "quote",
        "quotes",
        "market movers",
        "trending ticker",
        "trending tickers",
    )
    if any(_contains_keyword(low, tok) for tok in market_terms):
        _add(
            "market_data",
            "The request requires current market or stock data with structured output.",
            ["market_data_report", "yahoo_finance.lookup", "web.yahoo_finance"],
            ["browser_relay.open", "browser_relay.snapshot", "browser_relay.action", "browser_relay.", "web.", "browser.", "result.file", "result.files", "result.chart"],
        )
    if any(tok in low for tok in ("contract", "agreement", "clause", "attorney", "legal review", "obligation", "exception report")):
        _add(
            "pdf_processing",
            "The request requires extracting and analyzing legal document content from agreements or contracts.",
            ["custom.legal_contract_review", "pdf.find_repo_pdf", "pdf.read_form_fields", "pdf.read_visual_labels", "pdf.render_page_images", "pdf."],
            ["result.file", "result.files", "result.text"],
        )
    if (
        "pdf" in low
        or "ocr" in low
        or "document scan" in low
        or re.search(r"\bform\b", low)
    ):
        _add(
            "pdf_processing",
            "The request requires PDF processing capability.",
            ["pdf.find_repo_pdf", "pdf.read_form_fields", "pdf.read_visual_labels", "pdf.render_page_images", "pdf."],
            ["result.file", "result.files"],
        )
    if any(tok in low for tok in ("chart", "graph", "bar graph", "line graph", "pie chart", "visualize")):
        _add(
            "chart_output",
            "The request requires chart generation.",
            ["custom.chart_output_executor", "custom.file_chart_visualization", "custom.market_data_report", "chart.", "graph."],
            ["result.chart"],
        )
    sports_terms = (
        "sports",
        "scoreboard",
        "live game",
        "live games",
        "current game",
        "current games",
        "game score",
        "games that is currently going on",
        "games currently going on",
        "game going on",
        "games going on",
        "game tonight",
        "games tonight",
        "playing against",
        "basketball",
        "football",
        "baseball",
        "hockey",
        "soccer",
        "nba",
        "nfl",
        "mlb",
        "nhl",
        "wnba",
        "ncaa",
    )
    if any(
        _contains_keyword(low, tok)
        for tok in (
            *sports_terms,
        )
    ):
        _add(
            "sports_live_data",
            "The request requires live or current sports game lookup with structured results.",
            ["custom.sports_live_games_table", "sports.lookup_live_games", "sports."],
        )
    if any(tok in low for tok in ("approval", "approve", "human review", "sign off")):
        _add(
            "approval_gate",
            "The request explicitly requires a human approval step.",
            ["interaction.approval"],
        )
    if any(tok in low for tok in ("zip", "bundle", "archive", "packet")):
        _add(
            "archive_output",
            "The request explicitly mentions a bundle or archive output.",
            ["result.zip"],
            ["result.file", "result.files"],
        )
    if (
        re.search(r"\brepo\b", low)
        or re.search(r"\bcodebase\b", low)
        or re.search(r"\bsource code\b", low)
        or re.search(r"\bchat\.js\b", low)
        or re.search(r"\bbug fix\b", low)
        or re.search(r"\brefactor\b", low)
        or re.search(r"\bpatch(?:ing|ed)?\b", low)
    ):
        _add(
            "repo_editing",
            "The request requires repository analysis or code editing.",
            ["repo.", "code.", "git."],
            ["result.file"],
        )
    return caps


def summarize_capability_gaps(
    flow: Dict[str, Any],
    request_text: Any,
    *,
    extra_skill_ids: List[str] | None = None,
    generated_capabilities: List[str] | None = None,
) -> Dict[str, Any]:
    summary = summarize_flow(str(flow.get("name") or ""), flow if isinstance(flow, dict) else {})
    skill_ids = [str(x or "").strip().lower() for x in (summary.get("action_skills") or []) if str(x or "").strip()]
    skill_ids.extend(str(x or "").strip().lower() for x in (extra_skill_ids or []) if str(x or "").strip())
    skill_blob = " ".join(skill_ids)
    generated_caps = {str(x or "").strip() for x in (generated_capabilities or []) if str(x or "").strip()}
    reqs = infer_request_capabilities(request_text)
    missing: List[Dict[str, Any]] = []
    present: List[str] = []
    for cap in reqs:
        required_any = [str(x or "").strip().lower() for x in (cap.get("required_any") or []) if str(x or "").strip()]
        optional_any = [str(x or "").strip().lower() for x in (cap.get("optional_any") or []) if str(x or "").strip()]
        cap_id = str(cap.get("id") or "").strip()

        def _matches(prefixes: List[str]) -> bool:
            for prefix in prefixes:
                if prefix.endswith("."):
                    if any(skill.startswith(prefix) for skill in skill_ids):
                        return True
                elif prefix in skill_blob:
                    return True
            return False

        if _matches(required_any):
            present.append(cap_id)
            continue
        if optional_any and _matches(optional_any):
            present.append(cap_id)
            continue
        if cap_id in generated_caps:
            present.append(cap_id)
            continue
        missing.append(
            {
                "id": cap_id,
                "reason": str(cap.get("reason") or ""),
                "required_any": required_any,
            }
        )
    return {
        "required": reqs,
        "present": present,
        "missing": missing,
        "summary": summary,
    }


def parse_jsonish(value: Any) -> Tuple[Any, List[str]]:
    warnings: List[str] = []
    if isinstance(value, (dict, list)):
        return value, warnings
    text = str(value or "").strip()
    if not text:
        return None, ["empty_json_input"]
    try:
        return json.loads(text), warnings
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1]), ["json_recovered_from_wrapped_text"]
        except Exception:
            pass
    return None, ["invalid_json"]


def extract_json_member(text: Any, key: str) -> Tuple[Any, List[str]]:
    raw = str(text or "")
    if not raw.strip():
        return None, ["empty_text"]
    m = re.search(rf'"{re.escape(str(key))}"\s*:\s*', raw)
    if not m:
        m = re.search(rf"{re.escape(str(key))}\s*:\s*", raw)
    if not m:
        return None, [f"{key}_not_found"]
    idx = m.end()
    while idx < len(raw) and raw[idx].isspace():
        idx += 1
    if idx >= len(raw):
        return None, [f"{key}_value_missing"]
    opener = raw[idx]
    if opener not in "{[":
        return None, [f"{key}_not_json_container"]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    start = idx
    for pos in range(idx, len(raw)):
        ch = raw[pos]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start : pos + 1]), []
                except Exception:
                    return None, [f"{key}_invalid_json"]
    return None, [f"{key}_unterminated_json"]


def ensure_flow_payload(value: Any, flow_name_hint: str = "") -> Tuple[Dict[str, Any] | None, str, List[str]]:
    data, warnings = parse_jsonish(value)
    if not isinstance(data, dict):
        return None, str(flow_name_hint or "").strip(), warnings
    if "flows" in data and isinstance(data.get("flows"), dict):
        flows = data.get("flows") or {}
        if len(flows) == 1:
            flow_name, flow_def = next(iter(flows.items()))
            if isinstance(flow_def, dict):
                return flow_def, str(flow_name or flow_name_hint or "").strip(), warnings
        hint = str(flow_name_hint or "").strip()
        if hint:
            direct = flows.get(hint)
            if isinstance(direct, dict):
                return direct, hint, warnings + ["multiple_flows_selected_by_hint"]
            for flow_name, flow_def in flows.items():
                if not isinstance(flow_def, dict):
                    continue
                name = str(flow_name or "").strip()
                if hint and (name == hint or hint in name or name in hint):
                    return flow_def, name, warnings + ["multiple_flows_selected_by_hint"]
        for flow_name, flow_def in flows.items():
            if isinstance(flow_def, dict):
                return flow_def, str(flow_name or flow_name_hint or "").strip(), warnings + ["multiple_flows_selected_first"]
        return None, str(flow_name_hint or "").strip(), warnings + ["multiple_flows_not_supported"]
    flow_name = str(flow_name_hint or data.get("name") or data.get("flow_id") or "").strip()
    return data, flow_name, warnings


def extract_referenced_skills(flow: Dict[str, Any]) -> List[str]:
    out = set()
    nodes = flow.get("nodes") if isinstance(flow.get("nodes"), dict) else {}
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        ps = node.get("plugin_settings") if isinstance(node.get("plugin_settings"), dict) else {}
        for skill in ps.get("action_skills") or []:
            skill_id = str(skill or "").strip()
            if skill_id:
                out.add(skill_id)
        tool_cfg = ps.get("tool_config") if isinstance(ps.get("tool_config"), dict) else {}
        tool_name = str(tool_cfg.get("tool") or "").strip()
        if tool_name:
            out.add(tool_name)
    return sorted(out)


def normalize_missing_skill_specs(raw: Any) -> List[Dict[str, Any]]:
    rows = raw if isinstance(raw, list) else []
    out: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        if isinstance(row, str):
            row = {"id": row}
        if not isinstance(row, dict):
            continue
        skill_id = str(row.get("id") or row.get("skill") or row.get("name") or "").strip()
        if not skill_id or skill_id in seen:
            continue
        seen.add(skill_id)
        params_schema = row.get("params_schema") if isinstance(row.get("params_schema"), dict) else {}
        if not params_schema and isinstance(row.get("parameters"), list):
            props = {}
            for p in row.get("parameters") or []:
                if not isinstance(p, dict):
                    continue
                pname = str(p.get("name") or "").strip()
                if not pname:
                    continue
                prop = {"type": str(p.get("type") or "string").strip() or "string"}
                desc = str(p.get("description") or "").strip()
                if desc:
                    prop["description"] = desc
                if "default" in p:
                    prop["default"] = p.get("default")
                props[pname] = prop
            params_schema = {"type": "object", "properties": props, "additionalProperties": True}
        out.append(
            {
                "id": skill_id,
                "label": str(row.get("label") or skill_id).strip(),
                "description": str(row.get("description") or "").strip(),
                "reason": str(row.get("reason") or "").strip(),
                "category": str(row.get("category") or skill_id.split(".", 1)[0] or "custom").strip(),
                "params_schema": params_schema,
                "metadata": dict(row.get("metadata") or {}) if isinstance(row.get("metadata"), dict) else {},
                "implementation_hint": str(row.get("implementation_hint") or "").strip(),
                "request_text": str(row.get("request_text") or "").strip(),
                "repair_focus": str(row.get("repair_focus") or "").strip(),
                "previous_source": str(row.get("previous_source") or "").strip(),
                "previous_path": str(row.get("previous_path") or "").strip(),
                "previous_hash": str(row.get("previous_hash") or "").strip(),
                "bug_signals": [str(x or "").strip() for x in (row.get("bug_signals") if isinstance(row.get("bug_signals"), list) else []) if str(x or "").strip()],
                "failing_requests": [str(x or "").strip() for x in (row.get("failing_requests") if isinstance(row.get("failing_requests"), list) else []) if str(x or "").strip()],
            }
        )
    return out


def to_pretty_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True, indent=2, sort_keys=False)


def as_lines(values: Iterable[str]) -> str:
    return "\n".join(f"- {str(v)}" for v in values if str(v).strip())


def _ctx_ext(ctx: Dict[str, Any]) -> Dict[str, Any]:
    ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
    return ext if isinstance(ext, dict) else {}


def _candidate_reports(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    ext = _ctx_ext(ctx)
    out: List[Dict[str, Any]] = []
    for key in (
        "agent_flow_previous_step_report_with_tools",
        "agent_flow_previous_step_report",
    ):
        row = ext.get(key)
        if isinstance(row, dict):
            out.append(row)
    return out


def _candidate_tool_results(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for report in _candidate_reports(ctx):
        rows = report.get("tool_results") if isinstance(report.get("tool_results"), list) else []
        for row in rows:
            if isinstance(row, dict):
                out.append(row)
    ext = _ctx_ext(ctx)
    for key in (
        "agent_flow_previous_tool_results",
        "member_tool_results",
        "tool_results",
    ):
        rows = ext.get(key)
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    out.append(row)
    return out


def _tool_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    payload = row.get("data") if isinstance(row.get("data"), dict) else {}
    out = dict(payload)
    for key, value in row.items():
        if key in {"ok", "warnings", "error", "data"}:
            continue
        out.setdefault(str(key), value)
    return out


def recover_workflow_target_from_ctx(ctx: Dict[str, Any]) -> Dict[str, Any]:
    ext = _ctx_ext(ctx)
    pid = str(ext.get("pid") or (ctx or {}).get("pid") or "project2").strip() or "project2"
    for row in _candidate_tool_results(ctx):
        skill = str(row.get("skill") or "").strip().lower()
        if skill not in {"workflow.load_target", "workflow.export", "workflow.write_target", "workflow.temp_library"}:
            continue
        payload = _tool_payload(row)
        flow_name = str(payload.get("flow_name") or "").strip()
        workflow_json = payload.get("workflow_json") if isinstance(payload.get("workflow_json"), dict) else {}
        if not flow_name and isinstance(workflow_json, dict):
            flow_name = str(workflow_json.get("name") or "").strip()
        workflow_file = str(payload.get("workflow_file") or "").strip()
        bundle_dir = str(payload.get("bundle_dir") or "").strip()
        temp_skill_dirs = [str(x or "").strip() for x in (payload.get("temp_skill_dirs") or []) if str(x or "").strip()]
        if not temp_skill_dirs and bundle_dir:
            skills_root = Path(bundle_dir) / "skills"
            if skills_root.is_dir():
                temp_skill_dirs = [str(skills_root)]
        if flow_name or workflow_json or workflow_file or bundle_dir:
            return {
                "ok": True,
                "target_type": str(payload.get("target_type") or ("bundle" if bundle_dir else "")).strip(),
                "flow_name": flow_name,
                "workflow_json": workflow_json,
                "workflow_file": workflow_file,
                "bundle_dir": bundle_dir,
                "temp_skill_dirs": temp_skill_dirs,
                "skill_files": [str(x or "").strip() for x in (payload.get("skill_files") or []) if str(x or "").strip()],
                "pid": str(payload.get("pid") or pid).strip() or pid,
                "data": {},
                "warnings": [],
            }
    return {"ok": False, "warnings": ["workflow_target_not_recoverable_from_context"], "data": {"pid": pid}}


def recover_json_member_from_ctx(ctx: Dict[str, Any], key: str) -> Tuple[Any, List[str]]:
    warnings: List[str] = []
    for row in _candidate_tool_results(ctx):
        payload = _tool_payload(row)
        if key in payload:
            return payload.get(key), warnings
    ext = _ctx_ext(ctx)
    for ext_key in ("agent_flow_previous_output_raw", "agent_flow_previous_output_text"):
        raw = str(ext.get(ext_key) or "").strip()
        if not raw:
            continue
        parsed, parse_warnings = parse_jsonish(raw)
        warnings.extend(parse_warnings)
        if isinstance(parsed, dict) and key in parsed:
            return parsed.get(key), warnings
        extracted, extract_warnings = extract_json_member(raw, key)
        warnings.extend(extract_warnings)
        if extracted is not None:
            return extracted, warnings
    return None, warnings + [f"{key}_not_recoverable_from_context"]


def recover_test_requests_from_ctx(ctx: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    seen = set()
    for report in _candidate_reports(ctx):
        did = str(report.get("did") or "").strip()
        parsed, _ = parse_jsonish(did)
        if isinstance(parsed, dict):
            rows = parsed.get("test_requests") if isinstance(parsed.get("test_requests"), list) else []
            for row in rows:
                text = str(row or "").strip()
                if text and text not in seen:
                    seen.add(text)
                    out.append(text)
    for row in _candidate_tool_results(ctx):
        payload = _tool_payload(row)
        rows = payload.get("test_requests") if isinstance(payload.get("test_requests"), list) else []
        for item in rows:
            text = str(item or "").strip()
            if text and text not in seen:
                seen.add(text)
                out.append(text)
    ext = _ctx_ext(ctx)
    for key in ("agent_flow_previous_output_raw", "agent_flow_previous_output_text"):
        raw = str(ext.get(key) or "").strip()
        if not raw:
            continue
        parsed, _ = parse_jsonish(raw)
        if not isinstance(parsed, dict):
            parsed, _ = extract_json_member(raw, "test_requests")
            if isinstance(parsed, list):
                rows = parsed
            else:
                continue
        else:
            rows = parsed.get("test_requests") if isinstance(parsed.get("test_requests"), list) else []
        for item in rows:
            text = str(item or "").strip()
            if text and text not in seen:
                seen.add(text)
                out.append(text)
    return out


def _extract_target_hints_from_text(text: Any) -> Dict[str, str]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    out: Dict[str, str] = {}
    for key in ("bundle_dir", "workflow_file", "flow_name", "workflow_name", "pid", "project"):
        m = re.search(rf"\b{re.escape(key)}\s*[:=]\s*(\"[^\"]+\"|'[^']+'|\S+)", raw, flags=re.IGNORECASE)
        if not m:
            continue
        val = str(m.group(1) or "").strip()
        if len(val) >= 2 and ((val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'"))):
            val = val[1:-1]
        if val:
            out[key.lower()] = val
    return out


def _target_domain_tokens(text: Any) -> set[str]:
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
        for token in re.findall(r"[a-z0-9]+", row):
            if len(token) >= 3:
                tokens.add(token)
    return tokens


def _strict_creator_domain_request(text: Any) -> bool:
    low = str(text or "").lower()
    return "create a workflow for" in low or "build a workflow for" in low or "design a workflow for" in low


def _recover_temp_library_target_by_name(ctx: Dict[str, Any], flow_name: str, pid: str) -> Dict[str, Any]:
    name = str(flow_name or "").strip()
    if not name:
        return {"ok": False, "warnings": ["temp_library_flow_name_missing"], "data": {"pid": pid}}
    wanted = {name.lower(), slugify(name)}
    current_request = str(
        (ctx or {}).get("current_request_text")
        or (ctx or {}).get("request_text")
        or (ctx or {}).get("user_request")
        or (ctx or {}).get("request")
        or (ctx or {}).get("prompt")
        or (ctx or {}).get("text")
        or (ctx or {}).get("original_request")
        or (ctx or {}).get("user_text")
        or ""
    ).strip()
    request_domains = _target_domain_tokens(current_request)
    index_path = generated_dir(ctx) / "temp_library" / "index.json"
    try:
        index_doc = _read_json(index_path)
    except Exception:
        index_doc = {}
    records = index_doc.get("records") if isinstance(index_doc.get("records"), list) else []
    candidates: List[Dict[str, Any]] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        row_name = str(row.get("flow_name") or "").strip()
        row_id = str(row.get("id") or "").strip()
        row_names = {row_name.lower(), slugify(row_name), row_id.lower(), slugify(row_id)}
        if not (wanted & row_names):
            continue
        if request_domains:
            if _strict_creator_domain_request(current_request):
                record_text = " ".join(
                    [
                        row_name,
                        str(row.get("description") or ""),
                    ]
                )
            else:
                record_text = " ".join(
                    [
                        row_name,
                        str(row.get("source_request") or ""),
                        str(row.get("description") or ""),
                        " ".join(row.get("tags") or []),
                    ]
                )
            record_domains = _target_domain_tokens(record_text) or {
                tok for tok in re.findall(r"[a-z0-9]+", record_text.lower()) if len(tok) >= 3
            }
            overlap = request_domains & record_domains
            required = 2 if len(request_domains) >= 2 else 1
            if len(overlap) < required:
                continue
        workflow_file = Path(str(row.get("workflow_file") or "").strip()) if str(row.get("workflow_file") or "").strip() else None
        bundle_dir = Path(str(row.get("bundle_dir") or "").strip()) if str(row.get("bundle_dir") or "").strip() else None
        if not workflow_file or not workflow_file.is_file():
            continue
        if not bundle_dir or not bundle_dir.is_dir():
            bundle_dir = workflow_file.parent
        candidates.append({**row, "workflow_file": str(workflow_file), "bundle_dir": str(bundle_dir)})
    if not candidates:
        return {"ok": False, "warnings": ["temp_library_record_not_found"], "data": {"pid": pid, "flow_name": name}}
    candidates.sort(key=lambda r: float(r.get("updated_at") or r.get("created_at") or 0), reverse=True)
    row = candidates[0]
    workflow_file = Path(str(row.get("workflow_file") or "")).resolve()
    bundle_dir = Path(str(row.get("bundle_dir") or "")).resolve()
    flow_doc, _, warnings = ensure_flow_payload(workflow_file.read_text(encoding="utf-8"), name)
    if flow_doc is None:
        return {"ok": False, "warnings": ["invalid_temp_library_workflow_json", *warnings], "data": {"workflow_file": str(workflow_file)}}
    resolved_name = str(flow_doc.get("name") or row.get("flow_name") or name or workflow_file.stem).strip()
    skills_root = bundle_dir / "skills"
    temp_skill_dirs = [str(skills_root)] if skills_root.is_dir() else []
    skill_files = [str(p) for p in skills_root.rglob("*.py") if p.is_file()] if skills_root.is_dir() else []
    return {
        "ok": True,
        "target_type": "bundle",
        "flow_name": resolved_name,
        "workflow_json": flow_doc,
        "workflow_file": str(workflow_file),
        "bundle_dir": str(bundle_dir),
        "temp_skill_dirs": temp_skill_dirs,
        "skill_files": skill_files,
        "pid": pid,
        "data": {},
        "warnings": ["recovered_from_temp_library_by_flow_name", *warnings],
    }


def _recover_temp_library_target_by_id(ctx: Dict[str, Any], workflow_id: str, pid: str) -> Dict[str, Any]:
    wanted_id = str(workflow_id or "").strip()
    if not wanted_id:
        return {"ok": False, "warnings": ["temp_library_workflow_id_missing"], "data": {"pid": pid}}
    try:
        from temp_library import run as temp_library_run  # type: ignore
    except Exception:
        try:
            from .temp_library import run as temp_library_run  # type: ignore
        except Exception:
            temp_library_run = None
    if temp_library_run is None:
        return {"ok": False, "warnings": ["temp_library_unavailable"], "data": {"pid": pid, "workflow_id": wanted_id}}
    out = temp_library_run(ctx, {"action": "resolve_flow", "workflow_id": wanted_id})
    if not isinstance(out, dict) or not out.get("ok"):
        return {"ok": False, "warnings": list(out.get("warnings") or ["temp_library_record_not_found"]) if isinstance(out, dict) else ["temp_library_record_not_found"], "data": {"pid": pid, "workflow_id": wanted_id}}
    return {
        "ok": True,
        "target_type": "bundle",
        "workflow_id": wanted_id,
        "flow_name": str(out.get("flow_name") or "").strip(),
        "workflow_json": out.get("workflow_json") if isinstance(out.get("workflow_json"), dict) else {},
        "workflow_file": str(out.get("workflow_file") or "").strip(),
        "bundle_dir": str(out.get("bundle_dir") or "").strip(),
        "temp_skill_dirs": list(out.get("temp_skill_dirs") or []),
        "skill_files": list(out.get("skill_files") or []),
        "pid": pid,
        "data": {},
        "warnings": ["recovered_from_temp_library_by_workflow_id", *list(out.get("warnings") or [])],
    }


def load_workflow_target(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    hint_text = (
        str((ctx or {}).get("user_text") or "").strip()
        or str((ctx or {}).get("original_request") or "").strip()
    )
    hints = _extract_target_hints_from_text(hint_text)
    pid = str(params.get("pid") or params.get("project") or hints.get("pid") or hints.get("project") or "project2").strip() or "project2"
    bundle_dir_raw = str(
        params.get("bundle_dir")
        or params.get("last_bundle_dir")
        or hints.get("bundle_dir")
        or hints.get("last_bundle_dir")
        or ""
    ).strip()
    workflow_file_raw = str(
        params.get("workflow_file")
        or params.get("last_workflow_file")
        or params.get("path")
        or hints.get("workflow_file")
        or hints.get("last_workflow_file")
        or ""
    ).strip()
    flow_name = str(
        params.get("flow_name")
        or params.get("last_flow_name")
        or params.get("workflow_name")
        or params.get("name")
        or hints.get("flow_name")
        or hints.get("last_flow_name")
        or hints.get("workflow_name")
        or ""
    ).strip()
    workflow_id = str(
        params.get("workflow_id")
        or params.get("last_workflow_id")
        or hints.get("workflow_id")
        or hints.get("last_workflow_id")
        or ""
    ).strip()

    workflow_json_inline = params.get("workflow_json") if isinstance(params.get("workflow_json"), dict) else None
    temp_skill_dirs_inline = [str(x or "").strip() for x in (params.get("temp_skill_dirs") or []) if str(x or "").strip()] if isinstance(params.get("temp_skill_dirs"), list) else []
    if workflow_json_inline:
        resolved_name = str(workflow_json_inline.get("name") or flow_name or "runtime_flow").strip()
        return {
            "ok": True,
            "target_type": "inline_flow",
            "flow_name": resolved_name,
            "workflow_json": dict(workflow_json_inline),
            "workflow_file": workflow_file_raw,
            "bundle_dir": bundle_dir_raw,
            "temp_skill_dirs": temp_skill_dirs_inline,
            "skill_files": [],
            "pid": pid,
            "data": {},
            "warnings": ["loaded_inline_workflow_json"],
        }

    if bundle_dir_raw:
        bundle_dir = _resolve_cross_env_generated_path(ctx, bundle_dir_raw)
        if not bundle_dir.is_dir():
            recovered = recover_workflow_target_from_ctx(ctx)
            if recovered.get("ok"):
                recovered["warnings"] = ["bundle_dir_not_found_recovered_from_context", *list(recovered.get("warnings") or [])]
                return recovered
            return {"ok": False, "warnings": ["bundle_dir_not_found", *list(recovered.get("warnings") or [])], "data": {"bundle_dir": str(bundle_dir)}}
        if workflow_file_raw:
            workflow_file_raw = str(_resolve_cross_env_generated_path(ctx, workflow_file_raw))
        if not workflow_file_raw:
            json_files = sorted([p for p in bundle_dir.glob("*.json") if p.is_file()])
            if json_files:
                workflow_file_raw = str(json_files[0])
        if not workflow_file_raw:
            return {"ok": False, "warnings": ["bundle_workflow_json_not_found"], "data": {"bundle_dir": str(bundle_dir)}}
        flow_doc, _, warnings = ensure_flow_payload(Path(workflow_file_raw).read_text(encoding="utf-8"), flow_name)
        if flow_doc is None:
            return {"ok": False, "warnings": ["invalid_bundle_workflow_json", *warnings], "data": {"workflow_file": workflow_file_raw}}
        resolved_name = str(flow_doc.get("name") or flow_name or Path(workflow_file_raw).stem).strip()
        skills_root = bundle_dir / "skills"
        temp_skill_dirs = [str(skills_root)] if skills_root.is_dir() else []
        skill_files = []
        if skills_root.is_dir():
            skill_files = [str(p) for p in skills_root.rglob("*.py") if p.is_file()]
        return {
            "ok": True,
            "target_type": "bundle",
            "flow_name": resolved_name,
            "workflow_json": flow_doc,
            "workflow_file": str(Path(workflow_file_raw).resolve()),
            "bundle_dir": str(bundle_dir),
            "temp_skill_dirs": temp_skill_dirs,
            "skill_files": skill_files,
            "pid": pid,
            "data": {},
            "warnings": warnings,
        }

    if workflow_file_raw:
        workflow_file = _resolve_cross_env_generated_path(ctx, workflow_file_raw)
        if workflow_file.is_file():
            flow_doc, _, warnings = ensure_flow_payload(workflow_file.read_text(encoding="utf-8"), flow_name)
            if flow_doc is not None:
                resolved_name = str(flow_doc.get("name") or flow_name or workflow_file.stem).strip()
                bundle_dir = workflow_file.parent
                skills_root = bundle_dir / "skills"
                temp_skill_dirs = [str(skills_root)] if skills_root.is_dir() else []
                skill_files = [str(p) for p in skills_root.rglob("*.py") if p.is_file()] if skills_root.is_dir() else []
                return {
                    "ok": True,
                    "target_type": "bundle",
                    "flow_name": resolved_name,
                    "workflow_json": flow_doc,
                    "workflow_file": str(workflow_file),
                    "bundle_dir": str(bundle_dir),
                    "temp_skill_dirs": temp_skill_dirs,
                    "skill_files": skill_files,
                    "pid": pid,
                    "data": {},
                    "warnings": warnings,
                }
        recovered = recover_workflow_target_from_ctx(ctx)
        if recovered.get("ok"):
            recovered["warnings"] = ["workflow_file_not_found_recovered_from_context", *list(recovered.get("warnings") or [])]
            return recovered

    all_flows = dict(load_default_flows(ctx))
    all_flows.update(load_project_flows(ctx, pid))
    if flow_name and flow_name in all_flows:
        return {
            "ok": True,
            "target_type": "project_flow",
            "flow_name": flow_name,
            "workflow_json": dict(all_flows.get(flow_name) or {}),
            "workflow_file": "",
            "bundle_dir": "",
            "temp_skill_dirs": [],
            "skill_files": [],
            "pid": pid,
            "data": {},
            "warnings": [],
        }
    if workflow_id:
        temp_recovered_by_id = _recover_temp_library_target_by_id(ctx, workflow_id, pid)
        if temp_recovered_by_id.get("ok"):
            return temp_recovered_by_id
    temp_recovered = _recover_temp_library_target_by_name(ctx, flow_name, pid)
    if temp_recovered.get("ok"):
        return temp_recovered
    recovered = recover_workflow_target_from_ctx(ctx)
    if recovered.get("ok"):
        return recovered
    return {"ok": False, "warnings": ["workflow_target_not_found", *list(recovered.get("warnings") or [])], "data": {"pid": pid, "flow_name": flow_name, "bundle_dir": bundle_dir_raw}}




