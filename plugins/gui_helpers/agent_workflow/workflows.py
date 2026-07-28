from __future__ import annotations

from typing import Dict, List


WORKFLOW_FAMILIES = ("feature", "bugfix", "review", "qa_release", "learning_feedback")


def stage_registry() -> Dict[str, str]:
    return {
        "classify": "classify",
        "gather_context": "gather_context",
        "plan": "plan",
        "execute": "execute",
        "iterate": "iterate",
        "debug_fix": "debug_fix",
        "review": "review",
        "test": "test",
        "approval": "approval",
        "learn": "learn",
        "output": "output",
    }


def workflow_stages(family: str, mode: str) -> List[str]:
    base = ["classify", "gather_context", "plan", "iterate", "review", "learn", "output"]
    if mode == "suggest_patch":
        return ["classify", "gather_context", "plan", "iterate", "review", "learn", "output"]
    if mode == "apply_patch":
        return ["classify", "gather_context", "plan", "iterate", "review", "approval", "learn", "output"]
    if mode in ("review_only", "qa_only", "release_only"):
        return ["classify", "gather_context", "review", "test", "learn", "output"]
    return base
