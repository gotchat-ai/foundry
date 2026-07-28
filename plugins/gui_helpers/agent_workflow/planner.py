from __future__ import annotations

from typing import Any, Dict, List


def classify_family(user_input: str, explicit_family: str | None, mode: str, learning_hints: List[Dict[str, Any]] | None = None) -> str:
    if explicit_family:
        return explicit_family
    t = (user_input or "").lower()
    hints = learning_hints or []
    for h in hints:
        wf = str(h.get("workflow_family") or "").strip()
        if wf:
            return wf
    if mode in ("review_only",):
        return "review"
    if "bug" in t or "fix" in t or "error" in t:
        return "bugfix"
    if "release" in t or "deploy" in t:
        return "qa_release"
    if "feedback" in t or "correction" in t or "learn" in t:
        return "learning_feedback"
    return "feature"


def build_plan(
    *,
    user_input: str,
    family: str,
    mode: str,
    targets: Dict[str, Any],
    constraints: Dict[str, Any],
    learning_hints: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    files = []
    raw_files = targets.get("files") if isinstance(targets, dict) else None
    if isinstance(raw_files, list):
        files = [str(x) for x in raw_files if str(x).strip()]
    for h in (learning_hints or []):
        for f in (h.get("preferred_files") or []):
            sf = str(f).strip()
            if sf and sf not in files:
                files.append(sf)

    steps: List[str] = [
        "Map request to plugin boundaries and affected modules.",
        "Inspect relevant files and dependencies before patching.",
        "Prepare minimal scoped change that preserves framework hooks.",
        "Apply scoped patch operations safely.",
        "Run project test adapters and parse failures.",
        "Debug/fix from structured failures and iterate until pass or max attempts.",
        "Update docs/changelog notes for shipped behavior changes.",
    ]
    if mode == "suggest_patch":
        steps.extend(
            [
                "Draft patch proposal with exact file targets.",
                "Run reviewer checks and identify test coverage gaps.",
            ]
        )

    return {
        "family": family,
        "mode": mode,
        "input": user_input,
        "likely_files": files,
        "constraints": dict(constraints or {}),
        "steps": steps,
        "risks": [
            "Cross-plugin coupling if boundaries are ignored.",
            "Behavior drift if framework hooks are bypassed.",
        ],
        "missing_context": [] if files else ["No explicit file targets provided."],
        "learning_hints": learning_hints or [],
    }
