from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class SmokeCase:
    name: str
    prompt: str
    expect_mode: str
    expect_selected_flow: str = ""
    expect_autoflow_selected: str = ""
    expect_run_kind: str = ""
    expect_substrings: List[str] | None = None


CASES: List[SmokeCase] = [
    SmokeCase(
        name="no_flow_general_chat",
        prompt="What is photosynthesis?",
        expect_mode="chat",
        expect_selected_flow="",
        expect_substrings=["photosynthesis"],
    ),
    SmokeCase(
        name="no_flow_text_generation",
        prompt="Draft a short professional follow-up email after an interview.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_substrings=["Subject:", "Thank you"],
    ),
    SmokeCase(
        name="weather_builtin",
        prompt="What is the weather in San Jose today?",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_weather_lookup__",
        expect_substrings=["San Jose", "Open-Meteo"],
    ),
    SmokeCase(
        name="market_data_builtin",
        prompt="Using Yahoo Finance data, compare NVIDIA (NVDA) and AMD using the most current price, 52-week range, market cap, and average volume. Return a compact investor-style comparison table and a short plain-language summary. Do not give personal financial advice.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_market_data__",
        expect_substrings=["Investor Comparison", "NVDA", "AMD", "Plain-Language Summary"],
    ),
    SmokeCase(
        name="scholar_builtin",
        prompt="Use Google Scholar to find recent scholarly sources since 2023 about teen mental health, social media use, and school pressure. Return 5 relevant sources with title, year, link, and a short synthesis of the strongest repeated findings.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_google_scholar_report__",
        expect_substrings=["Google Scholar Sources", "| Title | Year | Link |", "Strongest Repeated Findings"],
    ),
    SmokeCase(
        name="scholar_urban_heat_builtin",
        prompt="Use Google Scholar to find recent scholarly sources since 2024 about urban heat islands and climate inequality. Return 5 relevant sources with title, year, link, and a short synthesis.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_google_scholar_report__",
        expect_substrings=["Google Scholar Sources", "urban", "heat", "climate"],
    ),
    SmokeCase(
        name="scholar_implicit_builtin",
        prompt="Find recent scholarly sources since 2024 about urban heat islands and climate inequality. Return 5 relevant sources with title, year, link, and a short synthesis.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_google_scholar_report__",
        expect_substrings=["Google Scholar Sources", "urban", "heat", "climate"],
    ),
    SmokeCase(
        name="arxiv_builtin",
        prompt="Use arXiv to find recent papers about detecting AI-generated misinformation or synthetic political content. Return 5 papers with title, year, link, and a short methods-oriented synthesis of the main technical approaches.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_arxiv_report__",
        expect_substrings=["arXiv Papers", "Methods-Oriented Synthesis"],
    ),
    SmokeCase(
        name="arxiv_implicit_builtin",
        prompt="Find recent papers since 2023 about detecting AI-generated misinformation or synthetic political content. Return 5 papers with title, year, link, and a short methods-oriented synthesis.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_arxiv_report__",
        expect_substrings=["arXiv Papers", "Methods-Oriented Synthesis"],
    ),
    SmokeCase(
        name="macro_web_research",
        prompt="What are the latest inflation and unemployment updates in the United States today?",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_web_research__",
        expect_substrings=["inflation", "unemployment"],
    ),
    SmokeCase(
        name="current_identity_builtin",
        prompt="Who is the current CEO of NVIDIA?",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_web_research__",
        expect_substrings=["Jensen Huang", "NVIDIA"],
    ),
    SmokeCase(
        name="ai_trends_web_research",
        prompt="What are the latest AI model trends this week?",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_web_research__",
        expect_substrings=["AI", "trend"],
    ),
    SmokeCase(
        name="world_bank_compare_builtin",
        prompt="Using the World Bank, compare the latest available inflation rate, GDP growth, and unemployment context for Indonesia, Vietnam, and Mexico. Return a reviewer-ready markdown table and a short summary of which economy looks most stable right now.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_world_bank_compare__",
        expect_substrings=["World Bank Comparison", "Indonesia", "Vietnam", "Mexico"],
    ),
    SmokeCase(
        name="world_bank_compare_implicit_builtin",
        prompt="Compare the latest available inflation rate, GDP growth, and unemployment context for Indonesia, Vietnam, and Mexico. Return a reviewer-ready markdown table and a short summary of which economy looks most stable right now.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_world_bank_compare__",
        expect_substrings=["World Bank Comparison", "Indonesia", "Vietnam", "Mexico"],
    ),
    SmokeCase(
        name="imf_world_bank_macro_brief_builtin",
        prompt="Using IMF and World Bank context together, prepare a short macro brief comparing current growth and inflation outlook for the United States, Euro Area, and China. Highlight where the two sources appear aligned or where one source is only contextual.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_imf_world_bank_macro_brief__",
        expect_substrings=["Macro Brief", "United States", "Euro Area", "China"],
    ),
    SmokeCase(
        name="imf_world_bank_macro_brief_implicit_builtin",
        prompt="Prepare a short macro brief comparing current growth and inflation outlook for the United States, Euro Area, and China. Highlight where the two sources appear aligned or where one source is only contextual.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_imf_world_bank_macro_brief__",
        expect_substrings=["Macro Brief", "United States", "Euro Area", "China"],
    ),
    SmokeCase(
        name="current_context_authoring_builtin",
        prompt="Make me a PowerPoint structure for AP Government about whether AI-generated content should be regulated, tied to free speech, elections, and public trust.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_current_context_answer__",
        expect_run_kind="direct_authoring_fallback",
        expect_substrings=["Presentation Outline", "Slide 1", "free speech", "elections", "public trust"],
    ),
    SmokeCase(
        name="repo_path_inspect_builtin",
        prompt="What is inside /data/agent_workflow/repo/plugins/gui_helpers/collab_chat?",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_repo_path_inspect__",
        expect_substrings=["Folder", "routes.py", "manifest.json"],
    ),
    SmokeCase(
        name="repo_project_summary_builtin",
        prompt="What is this repo for in /data/agent_workflow/repo? Give me a high-level summary.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_repo_project_summary__",
        expect_substrings=["Main Purpose", "Repo Root", "Key Components"],
    ),
    SmokeCase(
        name="repo_code_explain",
        prompt="What does /data/agent_workflow/repo/plugins/gui_helpers/collab_chat/routes.py do?",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_repo_code_explain__",
        expect_substrings=["routes.py", "What It Does"],
    ),
    SmokeCase(
        name="repo_reference_search",
        prompt="Where is service_direct_model_only referenced in /data/agent_workflow/repo/plugins/gui_helpers/collab_chat?",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_repo_reference_search__",
        expect_substrings=["service_direct_model_only", "routes.py"],
    ),
    SmokeCase(
        name="repo_file_summary",
        prompt="Summarize this file /uploads/autoflow_release_notes_sample.json and tell me what kind of data it contains.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_repo_file_summary__",
        expect_substrings=["top-level keys", "release_date", "highlights"],
    ),
    SmokeCase(
        name="zip_files_builtin",
        prompt="Zip these files and return it: /uploads/autoflow_budget_compare_sample.csv /uploads/autoflow_support_tickets_sample.csv",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_zip_files__",
        expect_substrings=["zip bundle", ".zip", "Archived file count: 2"],
    ),
    SmokeCase(
        name="budget_compare_builtin",
        prompt="Compare this spreadsheet file /uploads/autoflow_budget_compare_sample.csv and flag any department whose February amount changed by more than 10 percent versus January. Return a reviewer-ready markdown table and short summary.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_budget_compare__",
        expect_substrings=["Budget Comparison", "Engineering", "Support"],
    ),
    SmokeCase(
        name="support_triage_builtin",
        prompt="Use /uploads/autoflow_support_tickets_sample.csv to create a same-day triage brief for support tickets and call out which tickets need immediate attention first.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_support_ticket_triage__",
        expect_substrings=["Same-Day Triage Brief", "T-1003", "Immediate attention first"],
    ),
    SmokeCase(
        name="vendor_shortlist_builtin",
        prompt="Analyze /uploads/autoflow_vendor_matrix_sample.csv and create a vendor shortlist recommendation with tradeoffs across security, support, cost, and implementation.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_vendor_shortlist__",
        expect_substrings=["Vendor Shortlist Recommendation", "VendorB", "Tradeoff Table"],
    ),
    SmokeCase(
        name="contract_risk_builtin",
        prompt="Review this file /uploads/autoflow_contract_notes_sample.txt and produce a compact contract risk review with the highest-risk clauses and follow-up questions.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_contract_risk_review__",
        expect_substrings=["Contract Risk Review", "Liability cap", "Follow-up Question"],
    ),
    SmokeCase(
        name="release_email_builtin",
        prompt="Using /uploads/autoflow_release_notes_sample.json, draft a release announcement email for customers that highlights the main benefits and next steps.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_release_announcement_email__",
        expect_substrings=["Subject:", "Main benefits:", "Next steps:"],
    ),
    SmokeCase(
        name="chart_builtin",
        prompt="I want you to take this file /uploads/autoflow_chart_weekly_sample.json and print out its chart.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_file_chart_report__",
        expect_substrings=["Rendered 1 chart(s)", ".html"],
    ),
    SmokeCase(
        name="sprint_plan_builtin",
        prompt="Use /uploads/autoflow_sprint_backlog_sample.csv to prepare a practical next sprint plan with pull-first recommendations and dependency risks.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_sprint_plan__",
        expect_substrings=["Next Sprint Plan", "Pull-First Recommendations", "Dependency-Risk"],
    ),
    SmokeCase(
        name="scheduling_builtin",
        prompt="Use /uploads/autoflow_schedule_conflicts_sample.csv and prepare a scheduling resolution brief with the highest-priority conflicts and who should be contacted first.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_scheduling_resolution__",
        expect_substrings=["Scheduling Resolution Brief", "Dana", "Start with Dana"],
    ),
    SmokeCase(
        name="incident_timeline_builtin",
        prompt="Use /uploads/autoflow_incident_log_sample.csv to create an incident timeline summary and note the customer impact turning points.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_incident_timeline__",
        expect_substrings=["Incident Timeline Summary", "Revenue-impacting outage", "recovery turning point"],
    ),
    SmokeCase(
        name="faq_builtin",
        prompt="Turn /uploads/autoflow_faq_topics_sample.csv into a compact FAQ in plain language for new users.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_faq_compiler__",
        expect_substrings=["FAQ", "Getting started", "Public catalog"],
    ),
    SmokeCase(
        name="weather_practical_builtin",
        prompt="What is the weather in San Jose today and should I bring a jacket tonight?",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_weather_lookup__",
        expect_substrings=["San Jose", "Open-Meteo", "layer"],
    ),
    SmokeCase(
        name="eu_ai_regulation_bullets_builtin",
        prompt="What are the latest AI regulation developments in the European Union right now, and summarize them in 5 bullets.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_web_research__",
        expect_substrings=["- Current EU AI regulation developments", "High-risk", "AI Office"],
    ),
    SmokeCase(
        name="repo_change_guidance_builtin",
        prompt="Look in /data/agent_workflow/repo and tell me what files I would most likely need to change to update the AutoFlow service_chat routing behavior.",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_repo_project_summary__",
        expect_substrings=["Likely Files To Change", "plugins/ai_routes/autoflow/__init__.py", "plugins/gui_helpers/collab_chat/routes.py"],
    ),
    SmokeCase(
        name="research_proposal_current_sources_builtin",
        prompt="Can you draft a 20-page AP Research paper proposal about teen mental health, social media use, and school pressure, including research questions and possible current sources?",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_current_context_answer__",
        expect_run_kind="direct_authoring_fallback",
        expect_substrings=["Research Proposal Framework", "Core Research Question", "Possible Current Sources To Gather"],
    ),
    SmokeCase(
        name="physics_project_current_builtin",
        prompt="Can you suggest an AP Physics project about renewable energy efficiency, like comparing solar panel angles or battery storage ideas, and connect it to energy costs today?",
        expect_mode="chat",
        expect_selected_flow="",
        expect_autoflow_selected="__autoflow_builtin_current_context_answer__",
        expect_run_kind="direct_authoring_fallback",
        expect_substrings=["Project Framework", "panel angle", "energy costs"],
    ),
]


def _post_json(url: str, token: str, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Gui-Enabled-Plugins": "collab_chat,autoflow",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        data = json.loads(body)
        return {"status": resp.status, "data": data}


def _run_case(url: str, token: str, case: SmokeCase, timeout: float) -> Dict[str, Any]:
    payload = {"message": case.prompt, "selected_flow": "__none__"}
    attempts = 3
    last_result: Dict[str, Any] | None = None
    for attempt in range(attempts):
        started = time.perf_counter()
        try:
            row = _post_json(url, token, payload, timeout)
            elapsed_s = round(time.perf_counter() - started, 3)
            data = row["data"]
            result = data.get("result") if isinstance(data.get("result"), dict) else {}
            autoflow = result.get("autoflow") if isinstance(result.get("autoflow"), dict) else {}
            run = result.get("run") if isinstance(result.get("run"), dict) else {}
            response_text = str(data.get("assistant_response") or "")
            failures: List[str] = []
            actual_mode = str(data.get("mode") or "")
            actual_selected_flow = str(data.get("selected_flow") or "")
            actual_autoflow_selected = str(autoflow.get("selected_flow") or autoflow.get("flow_name") or "")
            actual_run_kind = str(run.get("kind") or "")
            if actual_mode != case.expect_mode:
                failures.append(f"mode={actual_mode!r} expected {case.expect_mode!r}")
            if actual_selected_flow != case.expect_selected_flow:
                failures.append(f"selected_flow={actual_selected_flow!r} expected {case.expect_selected_flow!r}")
            if case.expect_autoflow_selected and actual_autoflow_selected != case.expect_autoflow_selected:
                failures.append(f"autoflow_selected={actual_autoflow_selected!r} expected {case.expect_autoflow_selected!r}")
            if case.expect_run_kind and actual_run_kind != case.expect_run_kind:
                failures.append(f"run_kind={actual_run_kind!r} expected {case.expect_run_kind!r}")
            low_response = response_text.lower()
            for token_text in list(case.expect_substrings or []):
                if token_text.lower() not in low_response:
                    failures.append(f"missing substring: {token_text!r}")
            last_result = {
                "name": case.name,
                "ok": not failures,
                "status": row["status"],
                "elapsed_s": elapsed_s,
                "mode": actual_mode,
                "selected_flow": actual_selected_flow,
                "autoflow_selected": actual_autoflow_selected,
                "run_kind": actual_run_kind,
                "failures": failures,
                "assistant_response": response_text[:3000],
            }
            if last_result["ok"] or attempt == attempts - 1:
                return last_result
        except urllib.error.HTTPError as exc:
            elapsed_s = round(time.perf_counter() - started, 3)
            raw = exc.read().decode("utf-8", errors="replace")
            last_result = {
                "elapsed_s": elapsed_s,
                "name": case.name,
                "ok": False,
                "status": exc.code,
                "mode": None,
                "selected_flow": None,
                "autoflow_selected": None,
                "run_kind": None,
                "failures": [f"http_error:{exc.code}"],
                "assistant_response": raw[:3000],
            }
            if attempt == attempts - 1:
                return last_result
        except Exception as exc:
            elapsed_s = round(time.perf_counter() - started, 3)
            last_result = {
                "elapsed_s": elapsed_s,
                "name": case.name,
                "ok": False,
                "status": None,
                "mode": None,
                "selected_flow": None,
                "autoflow_selected": None,
                "run_kind": None,
                "failures": [repr(exc)],
                "assistant_response": "",
            }
            if attempt == attempts - 1:
                return last_result
    return last_result or {
        "name": case.name,
        "ok": False,
        "status": None,
        "mode": None,
        "selected_flow": None,
        "autoflow_selected": None,
        "run_kind": None,
        "failures": ["unknown_failure"],
        "assistant_response": "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run representative AutoFlow/no-flow live smoke checks against a service_chat endpoint.")
    parser.add_argument("--url", required=True, help="Full service_chat endpoint URL.")
    parser.add_argument("--token", required=True, help="Bearer token for the service_chat endpoint.")
    parser.add_argument("--timeout", type=float, default=300.0, help="Per-request timeout in seconds.")
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    parser.add_argument("--case", dest="case_names", action="append", default=[], help="Optional case name filter. May be repeated.")
    args = parser.parse_args()

    selected_cases = CASES
    if args.case_names:
        wanted = {str(name or "").strip() for name in args.case_names if str(name or "").strip()}
        selected_cases = [case for case in CASES if case.name in wanted]
        missing = sorted(wanted - {case.name for case in selected_cases})
        if missing:
            print(json.dumps({"ok": False, "error": "unknown_case", "missing": missing, "available": [case.name for case in CASES]}, ensure_ascii=True, indent=2))
            return 2

    results = [_run_case(args.url, args.token, case, args.timeout) for case in selected_cases]
    durations = [float(row.get("elapsed_s") or 0.0) for row in results if isinstance(row.get("elapsed_s"), (int, float))]
    summary = {
        "url": args.url,
        "case_count": len(results),
        "requested_cases": [case.name for case in selected_cases],
        "avg_elapsed_s": round(sum(durations) / len(durations), 3) if durations else None,
        "max_elapsed_s": round(max(durations), 3) if durations else None,
        "passed": sum(1 for row in results if row.get("ok")),
        "failed": sum(1 for row in results if not row.get("ok")),
        "results": results,
    }
    rendered = json.dumps(summary, ensure_ascii=True, indent=2)
    print(rendered)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(rendered + "\n")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
