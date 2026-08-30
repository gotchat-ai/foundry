from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict


EVENT_PREFIX = "__MODEL_WORKFLOW_WORKER__"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _ensure_import_paths() -> Path:
    root = _repo_root()
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    tools = root / "tools"
    if tools.exists():
        tools_s = str(tools)
        if tools_s not in sys.path:
            sys.path.insert(0, tools_s)
    return root


def _emit(event: Dict[str, Any]) -> None:
    try:
        sys.stdout.write(EVENT_PREFIX + json.dumps(event, ensure_ascii=False, default=str) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return repr(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in list(value.items()):
            k = str(key)
            # Live model handles must stay inside the worker process; callers
            # only need ids, paths, settings, and diagnostics.
            if k.startswith("_live") or k in {"model", "module", "pipeline", "transformer", "vae", "text_encoder"}:
                out[k] = f"<worker-owned:{type(item).__name__}>"
                continue
            out[k] = _json_safe(item, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item, depth=depth + 1) for item in list(value)]
    try:
        import torch  # type: ignore

        if isinstance(value, torch.Tensor):
            return {
                "__tensor__": True,
                "shape": list(value.shape),
                "dtype": str(value.dtype),
                "device": str(value.device),
            }
        if isinstance(value, torch.nn.Module):
            return f"<worker-owned-module:{value.__class__.__name__}>"
    except Exception:
        pass
    return repr(value)


def _cleanup_worker_state(app: Any, run_id: str, *, keep_cache: bool = False) -> Dict[str, Any]:
    report: Dict[str, Any] = {"released": [], "errors": []}
    try:
        from plugins.gui_helpers.agent_flow.skills.models._model_lifecycle import comfy_global_cleanup
        from plugins.gui_helpers.agent_flow.skills.models._model_workflow_common import (
            accelerator_cleanup,
            process_memory_trim,
            release_workflow_object,
            unload_runtime_modules,
        )
    except Exception:
        from plugins.gui_helpers.agent_flow.skills.models._model_workflow_common import (  # type: ignore
            accelerator_cleanup,
            process_memory_trim,
            release_workflow_object,
            unload_runtime_modules,
        )

        def comfy_global_cleanup(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:  # type: ignore
            return {}

    try:
        state = getattr(getattr(app, "state", None), "model_workflow_state", None)
        if isinstance(state, dict):
            runs = state.get("runs")
            resources = state.get("resources")
            if isinstance(runs, dict):
                runs.pop(run_id, None)
            if isinstance(resources, dict):
                prefix = f"{run_id}:"
                for key in list(resources.keys()):
                    if not str(key).startswith(prefix):
                        continue
                    if keep_cache and ":cache:" in str(key):
                        continue
                    try:
                        release_workflow_object(resources.get(key))
                    except Exception as exc:
                        report["errors"].append(f"{key}: {exc}")
                    resources.pop(key, None)
                    report["released"].append(str(key))
    except Exception as exc:
        report["errors"].append(f"state_cleanup:{exc}")
    try:
        comfy_global_cleanup(unload_models=True, soft_empty=True)
    except Exception as exc:
        report["errors"].append(f"comfy_cleanup:{exc}")
    try:
        accelerator_cleanup()
    except Exception as exc:
        report["errors"].append(f"accelerator_cleanup:{exc}")
    try:
        report["unloaded_runtime_modules"] = unload_runtime_modules(
            prefixes=("ltx_core", "ltx_pipelines", "comfy", "comfy_extras")
        )
    except Exception as exc:
        report["errors"].append(f"unload_runtime_modules:{exc}")
    try:
        report["process_memory_trim"] = process_memory_trim()
    except Exception as exc:
        report["errors"].append(f"process_memory_trim:{exc}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", default="")
    args = parser.parse_args()
    root = _ensure_import_paths()
    workspace = Path(args.workspace_root or root).resolve()

    state = SimpleNamespace(
        workspace_root=str(workspace),
        workdir=str(workspace),
        data_dir=str(workspace / "data"),
        model_workflow_state={"runs": {}, "resources": {}},
        ai_jobs_cancelled={},
        model_loader_registry=None,
        settings={},
    )
    app = SimpleNamespace(state=state)

    try:
        from plugins.gui_helpers.agent_flow.skills import build_agent_flow_tool_registry

        built = build_agent_flow_tool_registry(app, extra_skill_dirs=None)
        registry = built.get("registry")
        setattr(state, "agent_workflow_tools", registry)
        setattr(state, "agent_flow_skill_specs", dict(built.get("skill_specs") or {}))
        setattr(state, "agent_flow_skill_categories", dict(built.get("categories") or {}))
        setattr(state, "agent_flow_model_adapters", dict(built.get("model_adapters") or {}))
        setattr(state, "agent_flow_skill_load_warnings", list(built.get("warnings") or []))
    except Exception as exc:
        _emit({"event": "ready", "ok": False, "error": str(exc), "traceback": traceback.format_exc()})
        return 2

    _emit({"event": "ready", "ok": True, "pid": os.getpid(), "workspace_root": str(workspace)})

    for raw in sys.stdin:
        try:
            msg = json.loads(raw)
        except Exception as exc:
            _emit({"event": "error", "error": f"invalid_json:{exc}"})
            continue
        cmd = str(msg.get("cmd") or "").strip().lower()
        call_id = str(msg.get("call_id") or "")
        run_id = str(msg.get("run_id") or "").strip()
        if cmd == "shutdown":
            keep_cache = bool(msg.get("keep_cache"))
            _emit({"event": "cleanup", "call_id": call_id, "run_id": run_id, "data": _cleanup_worker_state(app, run_id, keep_cache=keep_cache)})
            _emit({"event": "shutdown", "call_id": call_id, "ok": True})
            return 0
        if cmd == "cancel":
            if run_id:
                state.ai_jobs_cancelled[run_id] = True
            _emit({"event": "cancelled", "call_id": call_id, "run_id": run_id, "ok": True})
            continue
        if cmd != "call":
            _emit({"event": "error", "call_id": call_id, "error": f"unknown_cmd:{cmd}"})
            continue
        tool_name = str(msg.get("tool_name") or "").strip()
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        ctx_in = msg.get("ctx") if isinstance(msg.get("ctx"), dict) else {}
        settings = ctx_in.get("settings") if isinstance(ctx_in.get("settings"), dict) else {}
        setattr(state, "settings", dict(settings))

        def _progress(message: str, **extra: Any) -> None:
            _emit(
                {
                    "event": "progress",
                    "call_id": call_id,
                    "run_id": run_id,
                    "tool": tool_name,
                    "message": str(message or ""),
                    "extra": _json_safe(extra),
                }
            )

        ctx = dict(ctx_in)
        ctx["app"] = app
        ctx["progress"] = _progress
        ctx.setdefault("settings", dict(settings))
        ctx["settings"]["__agent_flow_progress_callback"] = _progress
        try:
            if not registry:
                raise RuntimeError("worker registry unavailable")
            result = registry.call_tool(tool_name, ctx, params)
            _emit({"event": "result", "call_id": call_id, "run_id": run_id, "ok": True, "result": _json_safe(result)})
        except Exception as exc:
            _emit(
                {
                    "event": "result",
                    "call_id": call_id,
                    "run_id": run_id,
                    "ok": False,
                    "result": {
                        "ok": False,
                        "warnings": ["model_workflow_worker_exception", type(exc).__name__],
                        "data": {"error": str(exc), "tool": tool_name, "traceback": traceback.format_exc()},
                    },
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
