from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, Generator, List, Tuple

from .adapters import gather_context, suggest_patch
from .context import build_context
from .planner import build_plan, classify_family
from .schemas import WorkflowResult, WorkflowRunRequest, WorkflowStatus, WorkflowTraceEntry
from .workflows import workflow_stages
from .reviewers import ProfileRegistry
from .multi_agent import MultiAgentCoordinator, default_worker_team


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowExecutor:
    def __init__(
        self,
        *,
        set_status: Callable[[WorkflowStatus], None],
        append_trace: Callable[[str, WorkflowTraceEntry], None],
        tool_call: Callable[[str, Dict[str, Any], Dict[str, Any]], Dict[str, Any]] | None = None,
        profile_registry: ProfileRegistry | None = None,
    ) -> None:
        self._set_status = set_status
        self._append_trace = append_trace
        self._tool_call = tool_call
        self._profile_registry = profile_registry

    def run(self, *, workflow_id: str, req: WorkflowRunRequest) -> WorkflowResult:
        family, outputs, warnings, errors, paused = self._execute_pipeline(
            workflow_id=workflow_id, req=req, allow_pause=True, skip_approval=False
        )
        if paused:
            warnings.append("Workflow paused for approval.")
        self._apply_completion_gate(outputs, warnings, errors)
        return WorkflowResult(
            workflow_id=workflow_id,
            ok=(len(errors) == 0 and not paused),
            workflow_family=family,
            mode=req.mode,
            summary=(
                "Workflow paused and awaiting approval."
                if paused
                else f"Workflow executed with {len(outputs)} output artifact(s)."
            ),
            outputs=outputs,
            warnings=warnings,
            errors=errors,
            trace_id=workflow_id,
        )

    def resume_after_approval(self, *, workflow_id: str, req: WorkflowRunRequest) -> WorkflowResult:
        family, outputs, warnings, errors, paused = self._execute_pipeline(
            workflow_id=workflow_id, req=req, allow_pause=False, skip_approval=True
        )
        if paused:
            errors.append("Unexpected pause while resuming approved workflow.")
        self._apply_completion_gate(outputs, warnings, errors)
        return WorkflowResult(
            workflow_id=workflow_id,
            ok=(len(errors) == 0 and not paused),
            workflow_family=family,
            mode=req.mode,
            summary="Workflow resumed after approval.",
            outputs=outputs,
            warnings=warnings,
            errors=errors,
            trace_id=workflow_id,
        )

    def run_stream(
        self, *, workflow_id: str, req: WorkflowRunRequest
    ) -> Generator[Tuple[str, Dict[str, Any]], None, WorkflowResult]:
        started = _utc_now()
        hint_rows = []
        if callable(self._tool_call):
            hr = self._tool_call("learning.get_hints", {"pid": req.pid, "sid": req.sid}, {"query": req.input})
            if isinstance(hr, dict):
                hint_rows = list(((hr.get("data") or {}).get("hints") or []))
        family = classify_family(req.input, req.workflow_family, req.mode, learning_hints=hint_rows)
        stages = workflow_stages(family, req.mode)
        total = float(max(len(stages), 1))

        self._set_status(
            WorkflowStatus(
                workflow_id=workflow_id,
                state="running",
                current_stage=stages[0] if stages else None,
                current_node=None,
                started_at=started,
                updated_at=started,
                progress=0.0,
            )
        )
        yield ("workflow_start", {"workflow_id": workflow_id, "family": family})

        ctx = build_context(
            workflow_id=workflow_id,
            pid=req.pid,
            sid=req.sid,
            user_input=req.input,
            workflow_family=family,
            mode=req.mode,
            constraints=req.constraints,
            options=req.options,
        )
        if hint_rows:
            ctx.memory_state["learning_hints"] = hint_rows
        warnings: List[str] = []
        errors: List[str] = []

        paused = False
        for i, stage in enumerate(stages):
            warn_before = len(warnings)
            err_before = len(errors)
            self._append_trace(
                workflow_id,
                WorkflowTraceEntry(stage=stage, event_type="stage_start", message=f"Stage started: {stage}", data={}),
            )
            yield ("stage_start", {"stage": stage})
            yield ("stage_progress", {"stage": stage, "message": self._stage_message(stage)})

            stage_result = self._run_stage(
                stage, ctx, req, warnings, errors, allow_pause=True, skip_approval=False
            )
            progress = (i + 1.0) / total
            next_state = "running"
            if stage_result.get("pause"):
                next_state = "paused"
                paused = True
            self._set_status(
                WorkflowStatus(
                    workflow_id=workflow_id,
                    state=next_state,
                    current_stage=stage,
                    current_node=None,
                    started_at=started,
                    updated_at=_utc_now(),
                    progress=progress,
                )
            )
            self._append_trace(
                workflow_id,
                WorkflowTraceEntry(
                    stage=stage,
                    event_type="stage_result",
                    message=f"Stage completed: {stage}",
                    data={"ok": True, "progress": progress, "paused": paused},
                ),
            )
            yield (
                "stage_result",
                {
                    "stage": stage,
                    "progress": progress,
                    "paused": paused,
                    "warnings_count": len(warnings),
                    "errors_count": len(errors),
                    "outputs_count": len(ctx.outputs),
                    "iteration": (ctx.graph_state.get("iteration") if stage == "iterate" else None),
                    "review": (ctx.graph_state.get("review") if stage == "review" else None),
                },
            )
            # Emit richer stage details for transcript observability.
            detail: Dict[str, Any] = {"stage": stage}
            if stage == "plan":
                detail["plan"] = ctx.graph_state.get("plan") or {}
            elif stage == "iterate":
                it = ctx.graph_state.get("iteration") or {}
                attempts = list(it.get("attempts") or [])
                last = attempts[-1] if attempts else {}
                detail["iteration"] = {
                    "attempt_index": int(last.get("attempt") or len(attempts) or 0),
                    "max_attempts": int(it.get("max_attempts") or 0),
                    "all_ok": bool(it.get("all_ok")),
                    "changed_files": list((((last.get("apply") or {}).get("data") or {}).get("changed_files") or [])),
                    "apply_errors": list((((last.get("apply") or {}).get("data") or {}).get("errors") or [])),
                    "test_runs": list((((last.get("test") or {}).get("data") or {}).get("runs") or [])),
                    "test_warnings": list(((last.get("test") or {}).get("warnings") or [])),
                    "debug_suggestions": list((((last.get("debug") or {}).get("data") or {}).get("suggestions") or [])),
                }
            elif stage == "review":
                detail["review"] = ctx.graph_state.get("review") or {}
            elif stage == "output":
                detail["outputs"] = list(ctx.outputs or [])
            detail["new_warnings"] = list(warnings[warn_before:])
            detail["new_errors"] = list(errors[err_before:])
            yield ("stage_detail", detail)
            if stage_result.get("pause"):
                payload = {
                    "workflow_id": workflow_id,
                    "node_id": "approval_1",
                    "stage": stage,
                    "actions": ["approve", "reject", "revise", "cancel"],
                }
                yield ("approval_required", payload)
                return WorkflowResult(
                    workflow_id=workflow_id,
                    ok=False,
                    workflow_family=family,
                    mode=req.mode,
                    summary="Workflow paused and awaiting approval.",
                    outputs=list(ctx.outputs),
                    warnings=warnings + ["Awaiting approval."],
                    errors=errors,
                    trace_id=workflow_id,
                )

        done = _utc_now()
        final_status = "completed" if not errors else "failed"
        self._set_status(
            WorkflowStatus(
                workflow_id=workflow_id,
                state=final_status,
                current_stage="output",
                current_node=None,
                started_at=started,
                updated_at=done,
                progress=1.0,
            )
        )
        result = WorkflowResult(
            workflow_id=workflow_id,
            ok=len(errors) == 0,
            workflow_family=family,
            mode=req.mode,
            summary=f"Workflow {final_status}.",
            outputs=list(ctx.outputs),
            warnings=warnings,
            errors=errors,
            trace_id=workflow_id,
        )
        self._apply_completion_gate(result.outputs, result.warnings, result.errors)
        yield ("workflow_result", result.model_dump())
        yield ("workflow_complete", {"workflow_id": workflow_id, "ok": result.ok})
        return result

    def _execute_pipeline(
        self, *, workflow_id: str, req: WorkflowRunRequest, allow_pause: bool, skip_approval: bool
    ) -> Tuple[str, List[Any], List[str], List[str], bool]:
        started = _utc_now()
        hint_rows = []
        if callable(self._tool_call):
            hr = self._tool_call("learning.get_hints", {"pid": req.pid, "sid": req.sid}, {"query": req.input})
            if isinstance(hr, dict):
                hint_rows = list(((hr.get("data") or {}).get("hints") or []))
        family = classify_family(req.input, req.workflow_family, req.mode, learning_hints=hint_rows)
        stages = workflow_stages(family, req.mode)
        total = float(max(len(stages), 1))
        warnings: List[str] = []
        errors: List[str] = []

        ctx = build_context(
            workflow_id=workflow_id,
            pid=req.pid,
            sid=req.sid,
            user_input=req.input,
            workflow_family=family,
            mode=req.mode,
            constraints=req.constraints,
            options=req.options,
        )
        if hint_rows:
            ctx.memory_state["learning_hints"] = hint_rows

        paused = False
        for i, stage in enumerate(stages):
            self._set_status(
                WorkflowStatus(
                    workflow_id=workflow_id,
                    state="running",
                    current_stage=stage,
                    current_node=None,
                    started_at=started,
                    updated_at=_utc_now(),
                    progress=i / total,
                )
            )
            self._append_trace(
                workflow_id,
                WorkflowTraceEntry(stage=stage, event_type="stage_start", message=f"Stage started: {stage}", data={}),
            )
            stage_result = self._run_stage(stage, ctx, req, warnings, errors, allow_pause=allow_pause, skip_approval=skip_approval)
            self._append_trace(
                workflow_id,
                WorkflowTraceEntry(
                    stage=stage,
                    event_type="stage_result",
                    message=f"Stage completed: {stage}",
                    data={"ok": True, "paused": bool(stage_result.get("pause"))},
                ),
            )
            if stage_result.get("pause"):
                paused = True
                self._set_status(
                    WorkflowStatus(
                        workflow_id=workflow_id,
                        state="paused",
                        current_stage=stage,
                        current_node="approval_1",
                        started_at=started,
                        updated_at=_utc_now(),
                        progress=(i + 1.0) / total,
                    )
                )
                break

        if not paused:
            final_state = "completed" if not errors else "failed"
            self._set_status(
                WorkflowStatus(
                    workflow_id=workflow_id,
                    state=final_state,
                    current_stage="output",
                    current_node=None,
                    started_at=started,
                    updated_at=_utc_now(),
                    progress=1.0,
                )
            )
        return family, list(ctx.outputs), warnings, errors, paused

    def _run_stage(
        self,
        stage: str,
        ctx: Any,
        req: WorkflowRunRequest,
        warnings: List[str],
        errors: List[str],
        *,
        allow_pause: bool,
        skip_approval: bool,
    ) -> Dict[str, Any]:
        if stage == "classify":
            hints = list(ctx.memory_state.get("learning_hints") or [])
            ctx.workflow_family = classify_family(req.input, req.workflow_family, req.mode, learning_hints=hints)
            return {"pause": False}
        if stage == "gather_context":
            ctx.graph_state["context"] = gather_context(
                pid=req.pid,
                sid=req.sid,
                user_input=req.input,
                targets=req.targets,
                options=req.options,
                tool_call=self._tool_call,
            )
            return {"pause": False}
        if stage == "plan":
            ctx.graph_state["plan"] = build_plan(
                user_input=req.input,
                family=ctx.workflow_family,
                mode=req.mode,
                targets=req.targets,
                constraints=req.constraints,
                learning_hints=list(ctx.memory_state.get("learning_hints") or []),
            )
            return {"pause": False}
        if stage == "execute":
            plan = ctx.graph_state.get("plan") or {}
            context = ctx.graph_state.get("context") or {}
            ctx.graph_state["patch"] = suggest_patch(plan=plan, context=context)
            return {"pause": False}
        if stage == "iterate":
            return self._run_iteration_loop(ctx, req, warnings, errors)
        if stage == "review":
            team_name = str(((req.options or {}).get("profile_team") or "")).strip() or None
            if self._profile_registry is None:
                ctx.graph_state["review"] = {
                    "team": [],
                    "ok": True,
                    "results": [],
                    "warnings": ["profile_registry_unavailable"],
                }
                return {"pause": False}
            team = self._profile_registry.resolve_team(ctx.workflow_family, explicit=team_name)
            run_ctx = {
                "user_input": req.input,
                "pid": req.pid,
                "sid": req.sid,
                "workflow_family": ctx.workflow_family,
                "plan": ctx.graph_state.get("plan") or {},
                "context": ctx.graph_state.get("context") or {},
                "tests": ctx.graph_state.get("tests") or {},
                "options": dict(req.options or {}),
            }
            if bool((req.options or {}).get("multi_agent_enabled")):
                coord = MultiAgentCoordinator(profile_registry=self._profile_registry, tool_call=self._tool_call)
                raw_workers = (req.options or {}).get("multi_agent_workers")
                if isinstance(raw_workers, list) and raw_workers:
                    workers = []
                    for i, rw in enumerate(raw_workers):
                        if not isinstance(rw, dict):
                            continue
                        pid2 = str(rw.get("profile_id") or "").strip()
                        if not pid2:
                            continue
                        wid2 = str(rw.get("worker_id") or "").strip() or f"w{i+1}"
                        resp2 = str(rw.get("responsibility") or "").strip()
                        from .multi_agent import WorkerSpec

                        workers.append(WorkerSpec(worker_id=wid2, profile_id=pid2, responsibility=resp2))
                    if not workers:
                        workers = default_worker_team(team)
                else:
                    workers = default_worker_team(team)
                maxw = int((req.options or {}).get("multi_agent_max_workers") or max(2, len(workers)))
                conc = coord.run(
                    workers=workers,
                    shared_seed=run_ctx,
                    pid=req.pid,
                    sid=req.sid,
                    max_workers=maxw,
                )
                result = {
                    "ok": bool((conc.get("reconciliation") or {}).get("ok", False)),
                    "results": [
                        {
                            "profile": "multi_agent_reconciler",
                            "ok": bool((conc.get("reconciliation") or {}).get("ok", False)),
                            "findings": list(((conc.get("reconciliation") or {}).get("findings") or [])),
                            "recommendations": list(((conc.get("reconciliation") or {}).get("recommendations") or [])),
                        }
                    ],
                    "concurrency": conc,
                }
                # feed reconciled candidate proposals into iteration path
                rec_cands = list(((conc.get("reconciliation") or {}).get("patch_candidates") or []))
                if rec_cands:
                    ctx.graph_state["multi_agent_patch_candidates"] = rec_cands
            else:
                result = self._profile_registry.run_team(team, run_ctx)
            ctx.graph_state["review"] = {"team": team, **result}
            if not result.get("ok"):
                warnings.append("One or more profile reviewers reported findings.")
            return {"pause": False}
        if stage == "test":
            files = []
            try:
                files = list(((ctx.graph_state.get("context") or {}).get("targets") or {}).get("files") or [])
            except Exception:
                files = []
            smoke = (
                self._tool_call("tests.smoke", {"pid": req.pid, "sid": req.sid}, {"files": files})
                if callable(self._tool_call)
                else {"ok": False, "data": {"executed": False}, "warnings": ["tool_registry_unavailable"]}
            )
            ctx.graph_state["tests"] = {"suggested": ["smoke", "regression"], "executed": True, "smoke": smoke}
            if not smoke.get("ok"):
                warnings.append("Smoke checks reported issues.")
            return {"pause": False}
        if stage == "approval":
            approval_required = bool((req.options or {}).get("require_approval", False))
            iter_state = ctx.graph_state.get("iteration") or {}
            # Only require approval when iterative coding/test loop already succeeded.
            if isinstance(iter_state, dict) and not bool(iter_state.get("all_ok", False)):
                warnings.append("Skipping approval because iteration did not reach passing state.")
                return {"pause": False}
            if not approval_required:
                ctx.approvals["approval_1"] = {"state": "auto_approved", "actions": ["approve", "reject", "revise", "cancel"]}
                return {"pause": False}
            if skip_approval:
                ctx.approvals["approval_1"] = {"state": "approved", "actions": ["approve", "reject", "revise", "cancel"]}
                return {"pause": False}
            if not allow_pause:
                ctx.approvals["approval_1"] = {"state": "auto_approved", "actions": ["approve", "reject", "revise", "cancel"]}
                return {"pause": False}
            ctx.approvals["approval_1"] = {"state": "pending", "actions": ["approve", "reject", "revise", "cancel"]}
            return {"pause": True, "node_id": "approval_1"}
        if stage == "learn":
            auto_feedback = (req.options or {}).get("feedback")
            if isinstance(auto_feedback, dict) and callable(self._tool_call):
                payload = dict(auto_feedback)
                payload.setdefault("workflow_id", ctx.workflow_id)
                payload.setdefault("workflow_family", ctx.workflow_family)
                out = self._tool_call("learning.capture_feedback", {"pid": req.pid, "sid": req.sid}, payload)
                ctx.memory_state["feedback_capture"] = out
                if isinstance(out, dict) and not out.get("ok"):
                    warnings.append("Learning feedback capture returned warnings.")
            return {"pause": False}
        if stage == "output":
            out = {"type": "workflow_plan", "data": ctx.graph_state.get("plan") or {}}
            ctx.outputs.append(out)
            ctx.outputs.append({"type": "review", "data": ctx.graph_state.get("review") or {}})
            if req.mode == "suggest_patch":
                ctx.outputs.append({"type": "patch_suggestion", "data": ctx.graph_state.get("patch") or {}})
            if req.mode in ("suggest_patch", "apply_patch"):
                ctx.outputs.append({"type": "iteration", "data": ctx.graph_state.get("iteration") or {}})
            return {"pause": False}
        errors.append(f"Unknown stage: {stage}")
        return {"pause": False}

    def _stage_message(self, stage: str) -> str:
        labels = {
            "classify": "Classifying workflow family",
            "gather_context": "Collecting request and target context",
            "plan": "Building execution plan",
            "execute": "Preparing patch suggestion",
            "iterate": "Running patch/test/debug iterations",
            "review": "Running reviewer checks",
            "test": "Generating test recommendations",
            "learn": "Capturing learning feedback",
            "output": "Formatting outputs",
        }
        return labels.get(stage, f"Running stage: {stage}")

    def _run_iteration_loop(self, ctx: Any, req: WorkflowRunRequest, warnings: List[str], errors: List[str]) -> Dict[str, Any]:
        if req.mode not in ("suggest_patch", "apply_patch"):
            return {"pause": False}
        opts = dict(req.options or {})
        max_attempts = int(opts.get("max_attempts") or 3)
        target_repo_root = str(opts.get("target_repo_root") or ".").strip() or "."
        candidates = list(opts.get("patch_candidates") or [])
        if not candidates and isinstance(opts.get("patch_ops"), list):
            candidates = [opts.get("patch_ops")]
        if not candidates:
            candidates = list(ctx.graph_state.get("multi_agent_patch_candidates") or [])
        auto_fix_rules = list(opts.get("auto_fix_rules") or [])
        if not candidates and callable(self._tool_call):
            gen = self._tool_call(
                "code.generate_patch_candidates",
                {"pid": req.pid, "sid": req.sid},
                {
                    "user_input": req.input,
                    "plan": ctx.graph_state.get("plan") or {},
                    "context": ctx.graph_state.get("context") or {},
                    "failures": [],
                    "route_id": str(opts.get("coding_route_id") or "code_patch_candidate"),
                    "use_agent_flow_engine": bool(opts.get("use_agent_flow_engine")),
                },
            )
            gen_cands = list(((gen.get("data") or {}).get("patch_candidates") or [])) if isinstance(gen, dict) else []
            if gen_cands:
                candidates.extend(gen_cands)
            else:
                gw = list((gen.get("warnings") or [])) if isinstance(gen, dict) else []
                if gw:
                    warnings.append(f"Auto coding adapter warnings: {gw}")
                gd = (gen.get("data") or {}) if isinstance(gen, dict) else {}
                if isinstance(gd, dict):
                    md = gd.get("model_diag")
                    if md:
                        warnings.append(f"Auto coding adapter model: {md}")
                    rh = str(gd.get("raw_text") or "")[:400]
                    if rh:
                        warnings.append(f"Auto coding adapter raw_text_head: {rh}")
                warnings.append("Auto coding adapter could not generate patch candidates.")
        attempts = []
        all_ok = False
        files_hint = list(((req.targets or {}).get("files") or []))

        for idx in range(max_attempts):
            cand = candidates[idx] if idx < len(candidates) else []
            apply_res = {"ok": True, "data": {"changed_files": [], "errors": []}, "warnings": []}
            if cand:
                apply_res = (
                    self._tool_call("code.apply_patch", {"pid": req.pid, "sid": req.sid}, {"ops": cand})
                    if callable(self._tool_call)
                    else {"ok": False, "data": {}, "warnings": ["tool_registry_unavailable"]}
                )
            changed_files = list(((apply_res.get("data") or {}).get("changed_files") or [])) if isinstance(apply_res, dict) else []
            test_res = (
                self._tool_call(
                    "tests.run_project",
                    {"pid": req.pid, "sid": req.sid},
                    {"framework": "auto", "project_dir": target_repo_root, "changed_files": changed_files},
                )
                if callable(self._tool_call)
                else {"ok": False, "data": {"runs": []}, "warnings": ["tool_registry_unavailable"]}
            )
            runs = list(((test_res.get("data") or {}).get("runs") or [])) if isinstance(test_res, dict) else []
            failed_chunks = []
            for r in runs:
                if not r.get("ok"):
                    parsed = (r.get("parsed") or {})
                    fails = parsed.get("failures") or []
                    if isinstance(fails, list):
                        failed_chunks.extend(fails[:30])
            debug_res = (
                self._tool_call(
                    "debug.fix_from_errors",
                    {"pid": req.pid, "sid": req.sid},
                    {"failures": failed_chunks, "files_hint": files_hint},
                )
                if callable(self._tool_call)
                else {"ok": True, "data": {"suggestions": []}, "warnings": []}
            )
            attempt_ok = bool(apply_res.get("ok")) and bool(test_res.get("ok"))
            attempts.append(
                {
                    "attempt": idx + 1,
                    "apply": apply_res,
                    "test": test_res,
                    "debug": debug_res,
                    "ok": attempt_ok,
                }
            )
            # Keep latest test artifact visible to downstream review profiles.
            ctx.graph_state["tests"] = {
                "executed": True,
                "framework": "auto",
                "latest": test_res,
                "attempt": idx + 1,
            }
            if attempt_ok:
                all_ok = True
                break
            # auto-generate next candidate from fix rules based on failure text
            if idx + 1 >= len(candidates) and auto_fix_rules and failed_chunks:
                flat_err = json_dumps_safe(failed_chunks).lower()
                gen_ops = []
                for rule in auto_fix_rules:
                    if not isinstance(rule, dict):
                        continue
                    pat = str(rule.get("match") or "").lower().strip()
                    ops = rule.get("ops")
                    if pat and pat in flat_err and isinstance(ops, list):
                        gen_ops.extend(ops)
                if gen_ops:
                    candidates.append(gen_ops)
            if idx + 1 >= len(candidates) and failed_chunks and callable(self._tool_call):
                regen = self._tool_call(
                    "code.generate_patch_candidates",
                    {"pid": req.pid, "sid": req.sid},
                    {
                        "user_input": req.input,
                        "plan": ctx.graph_state.get("plan") or {},
                        "context": ctx.graph_state.get("context") or {},
                        "failures": failed_chunks,
                        "route_id": str(opts.get("coding_route_id") or "code_patch_candidate"),
                        "use_agent_flow_engine": bool(opts.get("use_agent_flow_engine")),
                    },
                )
                regen_cands = list(((regen.get("data") or {}).get("patch_candidates") or [])) if isinstance(regen, dict) else []
                if regen_cands:
                    candidates.extend(regen_cands)
                else:
                    rw = list((regen.get("warnings") or [])) if isinstance(regen, dict) else []
                    if rw:
                        warnings.append(f"Auto coding adapter retry warnings: {rw}")
                    rd = (regen.get("data") or {}) if isinstance(regen, dict) else {}
                    if isinstance(rd, dict):
                        md = rd.get("model_diag")
                        if md:
                            warnings.append(f"Auto coding adapter retry model: {md}")
                        rh = str(rd.get("raw_text") or "")[:400]
                        if rh:
                            warnings.append(f"Auto coding adapter retry raw_text_head: {rh}")
            # If no parsed failures were captured, still attempt candidate regeneration
            # using execution state so the loop does not dead-end on empty/no-op patches.
            if idx + 1 >= len(candidates) and not failed_chunks and callable(self._tool_call):
                apply_errs = list(((apply_res.get("data") or {}).get("errors") or [])) if isinstance(apply_res, dict) else []
                test_warns = list((test_res.get("warnings") or [])) if isinstance(test_res, dict) else []
                synth_failures: List[str] = []
                if apply_errs:
                    synth_failures.extend([f"apply_error:{x}" for x in apply_errs[:20]])
                if test_warns:
                    synth_failures.extend([f"test_warning:{x}" for x in test_warns[:20]])
                if not changed_files:
                    synth_failures.append("no_files_changed")
                if not synth_failures:
                    synth_failures.append("attempt_failed_without_parsed_failures")
                regen2 = self._tool_call(
                    "code.generate_patch_candidates",
                    {"pid": req.pid, "sid": req.sid},
                    {
                        "user_input": req.input,
                        "plan": ctx.graph_state.get("plan") or {},
                        "context": ctx.graph_state.get("context") or {},
                        "failures": synth_failures,
                        "route_id": str(opts.get("coding_route_id") or "code_patch_candidate"),
                        "use_agent_flow_engine": bool(opts.get("use_agent_flow_engine")),
                    },
                )
                regen2_cands = list(((regen2.get("data") or {}).get("patch_candidates") or [])) if isinstance(regen2, dict) else []
                if regen2_cands:
                    candidates.extend(regen2_cands)
                else:
                    rw2 = list((regen2.get("warnings") or [])) if isinstance(regen2, dict) else []
                    if rw2:
                        warnings.append(f"Auto coding adapter retry(no-failure-parse) warnings: {rw2}")
            if not cand and idx >= len(candidates) - 1:
                warnings.append("No further patch candidates available for auto-fix loop.")
                break

        if not all_ok:
            errors.append("Iteration loop did not reach passing tests within max_attempts.")
        ctx.graph_state["iteration"] = {"max_attempts": max_attempts, "attempts": attempts, "all_ok": all_ok}
        return {"pause": False}

    def _apply_completion_gate(self, outputs: List[Any], warnings: List[str], errors: List[str]) -> None:
        # completion gate: required tests pass + no critical reviewer failures
        iteration_ok = False
        critical_ok = True
        critical_findings = []
        has_iteration = False
        for out in outputs or []:
            if isinstance(out, dict) and out.get("type") == "iteration":
                has_iteration = True
                iteration_ok = bool(((out.get("data") or {}).get("all_ok")))
        # infer reviewer criticals from review output
        review_results = []
        for out in outputs or []:
            if isinstance(out, dict) and out.get("type") == "review":
                review_results = list(((out.get("data") or {}).get("results") or []))
                break
        critical_profiles = {"security", "architect"}
        for rr in review_results:
            pid = str(rr.get("profile") or "")
            ok = bool(rr.get("ok"))
            if pid in critical_profiles and not ok:
                critical_ok = False
                for f in rr.get("findings") or []:
                    critical_findings.append(f"{pid}:{f}")
        # fallback from warnings parsing
        for w in list(warnings):
            low = str(w).lower()
            if "security" in low or "architect" in low or "critical" in low:
                critical_ok = False
                critical_findings.append(w)
        if not has_iteration:
            return
        gate = {"tests_passed": iteration_ok, "critical_review_passed": critical_ok, "working_code": iteration_ok and critical_ok}
        outputs.append({"type": "completion_gate", "data": gate})
        if not gate["working_code"]:
            if critical_findings:
                warnings.append(f"Critical review findings: {critical_findings[:6]}")
            errors.append("Completion gate not met: working code criteria failed.")


def json_dumps_safe(v: Any) -> str:
    try:
        import json

        return json.dumps(v, ensure_ascii=False)
    except Exception:
        return str(v)
