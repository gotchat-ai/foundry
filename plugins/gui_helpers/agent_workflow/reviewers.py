from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Dict, List


@dataclass
class ProfileResult:
    profile: str
    ok: bool
    findings: List[str]
    recommendations: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile": self.profile,
            "ok": self.ok,
            "findings": list(self.findings),
            "recommendations": list(self.recommendations),
        }


class BaseProfile:
    profile_id = "base"
    label = "Base Profile"
    phase = "review"
    description = "Base profile contract."

    def review(self, ctx: Dict[str, Any]) -> ProfileResult:
        return ProfileResult(profile=self.profile_id, ok=True, findings=[], recommendations=[])


class JsonProfile(BaseProfile):
    def __init__(self, profile_id: str, config: Dict[str, Any]) -> None:
        self.profile_id = str(profile_id)
        self.label = str(config.get("label") or profile_id)
        self.phase = str(config.get("phase") or "review")
        self.description = str(config.get("description") or "JSON-defined workflow profile.")
        self._rules = list(config.get("rules") or [])

    def review(self, ctx: Dict[str, Any]) -> ProfileResult:
        findings: List[str] = []
        recs: List[str] = []
        text = " ".join(
            [
                str(ctx.get("user_input") or ""),
                json.dumps(ctx.get("plan") or {}, ensure_ascii=False),
                json.dumps(ctx.get("context") or {}, ensure_ascii=False),
                json.dumps(ctx.get("tests") or {}, ensure_ascii=False),
            ]
        ).lower()

        for rule in self._rules:
            if not isinstance(rule, dict):
                continue
            when_all = [str(x).lower() for x in (rule.get("when_all") or []) if str(x).strip()]
            when_any = [str(x).lower() for x in (rule.get("when_any") or []) if str(x).strip()]
            match_all = all(tok in text for tok in when_all) if when_all else True
            match_any = any(tok in text for tok in when_any) if when_any else True
            if match_all and match_any:
                finding = str(rule.get("finding") or "").strip()
                rec = str(rule.get("recommendation") or "").strip()
                if finding:
                    findings.append(finding)
                if rec:
                    recs.append(rec)

        return ProfileResult(profile=self.profile_id, ok=len(findings) == 0, findings=findings, recommendations=recs)

class ProductProfile(BaseProfile):
    profile_id = "product"
    label = "Product Reviewer"
    description = "Checks request-solution fit and user outcome clarity."

    def review(self, ctx: Dict[str, Any]) -> ProfileResult:
        user_input = str(ctx.get("user_input") or "")
        findings = []
        recs = []
        if len(user_input.strip()) < 8:
            findings.append("Request is too short and may under-specify intent.")
            recs.append("Add user goal, constraints, and acceptance criteria.")
        return ProfileResult(profile=self.profile_id, ok=len(findings) == 0, findings=findings, recommendations=recs)


class ArchitectProfile(BaseProfile):
    profile_id = "architect"
    label = "Architecture Reviewer"
    description = "Checks plugin boundaries and coupling risk."

    def review(self, ctx: Dict[str, Any]) -> ProfileResult:
        plan = ctx.get("plan") or {}
        files = list(plan.get("likely_files") or [])
        findings = []
        recs = []
        for f in files:
            low = str(f).lower()
            if low.endswith("chat_js.js") or low.endswith("app.py"):
                findings.append(f"High-risk framework boundary file targeted: {f}")
                recs.append("Prefer plugin-level hook points before framework edits.")
        return ProfileResult(profile=self.profile_id, ok=len(findings) == 0, findings=findings, recommendations=recs)


class StaffEngineerProfile(BaseProfile):
    profile_id = "staff_engineer"
    label = "Staff Engineer Reviewer"
    description = "Checks change scope and execution risk."

    def review(self, ctx: Dict[str, Any]) -> ProfileResult:
        plan = ctx.get("plan") or {}
        steps = list(plan.get("steps") or [])
        findings = []
        recs = []
        if not steps:
            findings.append("Execution plan has no concrete steps.")
            recs.append("Provide explicit step sequence with file-level scope.")
        return ProfileResult(profile=self.profile_id, ok=len(findings) == 0, findings=findings, recommendations=recs)


class CoderProfile(BaseProfile):
    profile_id = "coder"
    label = "Coding Engineer"
    phase = "execute"
    description = "Implements planned code changes with minimal, testable patches."

    def review(self, ctx: Dict[str, Any]) -> ProfileResult:
        plan = ctx.get("plan") or {}
        steps = " ".join(str(s) for s in (plan.get("steps") or [])).lower()
        findings = []
        recs = []
        if "patch" not in steps and "code" not in steps and "implement" not in steps:
            findings.append("Plan does not clearly include an implementation/coding step.")
            recs.append("Add explicit coding step with target files and expected behavior.")
        return ProfileResult(profile=self.profile_id, ok=len(findings) == 0, findings=findings, recommendations=recs)


class SecurityProfile(BaseProfile):
    profile_id = "security"
    label = "Security Reviewer"
    description = "Checks obvious command/data handling risks."

    def review(self, ctx: Dict[str, Any]) -> ProfileResult:
        user_input = str(ctx.get("user_input") or "").lower()
        findings = []
        recs = []
        danger = ("reset --hard", "drop table", "rm -rf", "disable auth")
        if any(x in user_input for x in danger):
            findings.append("Potentially destructive intent detected in request.")
            recs.append("Require explicit approval and guardrails for destructive operations.")
        return ProfileResult(profile=self.profile_id, ok=len(findings) == 0, findings=findings, recommendations=recs)


class QAProfile(BaseProfile):
    profile_id = "qa"
    label = "QA Reviewer"
    description = "Checks test strategy coverage."

    def review(self, ctx: Dict[str, Any]) -> ProfileResult:
        tests = ctx.get("tests") or {}
        findings = []
        recs = []
        if not tests:
            findings.append("No test stage artifacts captured.")
            recs.append("Run smoke/regression checks before release.")
        return ProfileResult(profile=self.profile_id, ok=len(findings) == 0, findings=findings, recommendations=recs)


class ReleaseProfile(BaseProfile):
    profile_id = "release"
    label = "Release Reviewer"
    description = "Checks release readiness signal."

    def review(self, ctx: Dict[str, Any]) -> ProfileResult:
        findings = []
        recs = []
        tests = ctx.get("tests") or {}
        smoke = (tests.get("smoke") or {}) if isinstance(tests, dict) else {}
        if isinstance(smoke, dict) and not smoke.get("ok", True):
            findings.append("Smoke checks failed; release is not ready.")
            recs.append("Fix smoke failures and re-run validation.")
        return ProfileResult(profile=self.profile_id, ok=len(findings) == 0, findings=findings, recommendations=recs)


class DocsProfile(BaseProfile):
    profile_id = "docs"
    label = "Docs Reviewer"
    description = "Checks whether docs updates are planned."

    def review(self, ctx: Dict[str, Any]) -> ProfileResult:
        plan = ctx.get("plan") or {}
        steps = " ".join(str(s) for s in (plan.get("steps") or [])).lower()
        findings = []
        recs = []
        if "doc" not in steps and "changelog" not in steps:
            findings.append("Plan does not mention docs/changelog updates.")
            recs.append("Add docs/changelog update step for shipped changes.")
        return ProfileResult(profile=self.profile_id, ok=len(findings) == 0, findings=findings, recommendations=recs)

class GuiDesignerProfile(BaseProfile):
    profile_id = "gui_designer"
    label = "GUI Designer"
    description = "Checks UI/UX clarity, interaction consistency, and frontend implementation readiness."

    def review(self, ctx: Dict[str, Any]) -> ProfileResult:
        plan = ctx.get("plan") or {}
        steps = " ".join(str(s) for s in (plan.get("steps") or [])).lower()
        findings = []
        recs = []
        ui_terms = ("ui", "ux", "layout", "screen", "component", "frontend", "css", "html")
        if not any(t in steps for t in ui_terms):
            findings.append("Plan does not include explicit UI/UX or frontend design steps.")
            recs.append("Add GUI design tasks and frontend acceptance criteria.")
        return ProfileResult(profile=self.profile_id, ok=len(findings) == 0, findings=findings, recommendations=recs)


class ProfileRegistry:
    def __init__(self) -> None:
        self._profiles: Dict[str, BaseProfile] = {}
        self._teams: Dict[str, List[str]] = {}

    def register_profile(self, profile: BaseProfile) -> None:
        self._profiles[str(profile.profile_id)] = profile

    def register_team(self, name: str, profile_ids: List[str]) -> None:
        self._teams[str(name)] = [str(x) for x in (profile_ids or []) if str(x).strip()]

    def list_profiles(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for pid, p in self._profiles.items():
            out[pid] = {
                "profile_id": p.profile_id,
                "label": p.label,
                "phase": p.phase,
                "description": p.description,
            }
        return out

    def list_teams(self) -> Dict[str, List[str]]:
        return {k: list(v) for k, v in self._teams.items()}

    def resolve_team(self, workflow_family: str, explicit: str | None = None) -> List[str]:
        if explicit and explicit in self._teams:
            return list(self._teams.get(explicit) or [])
        if workflow_family in self._teams:
            return list(self._teams.get(workflow_family) or [])
        return list(self._teams.get("default") or [])

    def run_team(self, profile_ids: List[str], ctx: Dict[str, Any]) -> Dict[str, Any]:
        results = []
        ok = True
        for pid in profile_ids:
            p = self._profiles.get(pid)
            if not p:
                results.append(
                    ProfileResult(
                        profile=pid,
                        ok=False,
                        findings=[f"profile_not_found:{pid}"],
                        recommendations=["Register profile before use."],
                    ).to_dict()
                )
                ok = False
                continue
            r = p.review(ctx)
            results.append(r.to_dict())
            ok = ok and bool(r.ok)
        return {"ok": ok, "results": results}


def build_default_profile_registry() -> ProfileRegistry:
    reg = ProfileRegistry()
    reg.register_profile(ProductProfile())
    reg.register_profile(ArchitectProfile())
    reg.register_profile(StaffEngineerProfile())
    reg.register_profile(CoderProfile())
    reg.register_profile(SecurityProfile())
    reg.register_profile(QAProfile())
    reg.register_profile(ReleaseProfile())
    reg.register_profile(DocsProfile())
    reg.register_profile(GuiDesignerProfile())

    reg.register_team("default", ["coder", "qa"])
    reg.register_team("feature", ["product", "gui_designer", "architect", "coder", "staff_engineer", "qa", "security", "docs", "release"])
    reg.register_team("bugfix", ["coder", "staff_engineer", "security", "qa"])
    reg.register_team("review", ["architect", "staff_engineer", "security"])
    reg.register_team("qa_release", ["qa", "security", "release", "docs"])
    reg.register_team("learning_feedback", ["product", "coder", "staff_engineer", "docs"])
    return reg


def load_profiles_from_json(reg: ProfileRegistry, json_path: str) -> Dict[str, Any]:
    path = os.path.abspath(str(json_path or ""))
    if not path:
        return {"ok": False, "warnings": ["empty_json_path"]}
    if not os.path.isfile(path):
        return {"ok": True, "warnings": [f"profile_json_not_found:{path}"]}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        return {"ok": False, "warnings": [f"profile_json_read_error:{exc}"]}

    profiles = data.get("profiles") if isinstance(data, dict) else None
    teams = data.get("teams") if isinstance(data, dict) else None
    added_profiles = 0
    added_teams = 0

    if isinstance(profiles, dict):
        for pid, cfg in profiles.items():
            if not str(pid).strip() or not isinstance(cfg, dict):
                continue
            reg.register_profile(JsonProfile(str(pid), cfg))
            added_profiles += 1

    if isinstance(teams, dict):
        for tname, members in teams.items():
            if not str(tname).strip() or not isinstance(members, list):
                continue
            reg.register_team(str(tname), [str(x) for x in members])
            added_teams += 1

    return {
        "ok": True,
        "warnings": [],
        "added_profiles": added_profiles,
        "added_teams": added_teams,
        "path": path,
    }


def load_profiles_from_dir(reg: ProfileRegistry, profiles_dir: str) -> Dict[str, Any]:
    pdir = os.path.abspath(str(profiles_dir or ""))
    if not pdir:
        return {"ok": False, "warnings": ["empty_profiles_dir"], "added_profiles": 0, "added_teams": 0, "files": []}
    os.makedirs(pdir, exist_ok=True)

    files = sorted([f for f in os.listdir(pdir) if f.lower().endswith(".json")])
    if not files:
        return {
            "ok": True,
            "warnings": [f"no_profile_json_files:{pdir}"],
            "added_profiles": 0,
            "added_teams": 0,
            "files": [],
            "dir": pdir,
        }

    total_profiles = 0
    total_teams = 0
    warnings: List[str] = []
    loaded_files: List[str] = []
    all_ok = True

    for fn in files:
        path = os.path.join(pdir, fn)
        info = load_profiles_from_json(reg, path)
        loaded_files.append(path)
        total_profiles += int(info.get("added_profiles") or 0)
        total_teams += int(info.get("added_teams") or 0)
        if not bool(info.get("ok", True)):
            all_ok = False
        warnings.extend(list(info.get("warnings") or []))

    return {
        "ok": all_ok,
        "warnings": warnings,
        "added_profiles": total_profiles,
        "added_teams": total_teams,
        "files": loaded_files,
        "dir": pdir,
    }
