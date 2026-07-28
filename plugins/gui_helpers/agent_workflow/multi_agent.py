from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import threading
from typing import Any, Callable, Dict, List

from .reviewers import ProfileRegistry


@dataclass
class WorkerSpec:
    worker_id: str
    profile_id: str
    responsibility: str = ""


def default_worker_team(profile_ids: List[str]) -> List[WorkerSpec]:
    out: List[WorkerSpec] = []
    for i, pid in enumerate(profile_ids):
        out.append(WorkerSpec(worker_id=f"w{i+1}", profile_id=str(pid), responsibility=f"{pid}_review"))
    return out


class SharedState:
    def __init__(self, base: Dict[str, Any]) -> None:
        self._lock = threading.RLock()
        self._state: Dict[str, Any] = dict(base or {})

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def merge(self, patch: Dict[str, Any]) -> None:
        with self._lock:
            for k, v in (patch or {}).items():
                self._state[k] = v

    def value(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state)


class MultiAgentCoordinator:
    def __init__(
        self,
        *,
        profile_registry: ProfileRegistry,
        tool_call: Callable[[str, Dict[str, Any], Dict[str, Any]], Dict[str, Any]] | None = None,
    ) -> None:
        self._profiles = profile_registry
        self._tool_call = tool_call

    def run(
        self,
        *,
        workers: List[WorkerSpec],
        shared_seed: Dict[str, Any],
        pid: str,
        sid: str,
        max_workers: int = 4,
    ) -> Dict[str, Any]:
        shared = SharedState(shared_seed)
        proposals: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max(1, int(max_workers))) as pool:
            fut_map = {
                pool.submit(self._worker_run, w, shared, pid, sid): w
                for w in (workers or [])
            }
            for fut in as_completed(fut_map):
                w = fut_map[fut]
                try:
                    proposals.append(fut.result())
                except Exception as exc:
                    proposals.append(
                        {
                            "worker_id": w.worker_id,
                            "profile_id": w.profile_id,
                            "ok": False,
                            "error": str(exc),
                            "findings": [f"worker_exception:{exc}"],
                            "recommendations": [],
                        }
                    )
        rec = self._reconcile(proposals)
        return {
            "ok": bool(rec.get("ok", False)),
            "workers": [w.__dict__ for w in workers],
            "proposals": proposals,
            "reconciliation": rec,
            "shared_state": shared.value(),
        }

    def _worker_run(self, w: WorkerSpec, shared: SharedState, pid: str, sid: str) -> Dict[str, Any]:
        snap = shared.snapshot()
        review = self._profiles.run_team([w.profile_id], snap)
        item = ((review.get("results") or [{}])[0]) if isinstance(review, dict) else {}
        proposal: Dict[str, Any] = {
            "worker_id": w.worker_id,
            "profile_id": w.profile_id,
            "responsibility": w.responsibility,
            "ok": bool(item.get("ok", False)),
            "findings": list(item.get("findings") or []),
            "recommendations": list(item.get("recommendations") or []),
        }
        # Specialist worker behavior hooks
        if w.profile_id in {"qa", "release"} and callable(self._tool_call):
            t = self._tool_call("tests.run_project", {"pid": pid, "sid": sid}, {"framework": "auto"})
            proposal["test_probe"] = t
        if w.profile_id in {"staff_engineer", "architect"} and callable(self._tool_call):
            gen = self._tool_call(
                "code.generate_patch_candidates",
                {"pid": pid, "sid": sid},
                {
                    "plan": snap.get("plan") or {},
                    "context": snap.get("context") or {},
                    "failures": [],
                    "route_id": str(((snap.get("options") or {}).get("coding_route_id") or "code_patch_candidate")),
                    "use_agent_flow_engine": bool((snap.get("options") or {}).get("use_agent_flow_engine")),
                },
            )
            proposal["patch_probe"] = gen
        return proposal

    def _reconcile(self, proposals: List[Dict[str, Any]]) -> Dict[str, Any]:
        findings: List[str] = []
        recommendations: List[str] = []
        patch_candidates: List[Any] = []
        critical_fail = False
        for p in proposals:
            pid = str(p.get("profile_id") or "")
            ok = bool(p.get("ok", False))
            for f in p.get("findings") or []:
                findings.append(f"{pid}:{f}")
            for r in p.get("recommendations") or []:
                recommendations.append(f"{pid}:{r}")
            if pid in {"security", "architect"} and not ok:
                critical_fail = True
            probe = p.get("patch_probe") or {}
            cands = ((probe.get("data") or {}).get("patch_candidates") or []) if isinstance(probe, dict) else []
            for c in cands:
                patch_candidates.append(c)
        # de-dup recommendations/findings
        dedup_findings = list(dict.fromkeys(findings))
        dedup_recs = list(dict.fromkeys(recommendations))
        return {
            "ok": (not critical_fail),
            "critical_fail": critical_fail,
            "findings": dedup_findings,
            "recommendations": dedup_recs,
            "patch_candidates": patch_candidates[:8],
        }

