from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict

try:
    from ._ltx_native_graph_runtime import encode_video as native_graph_encode_video
    from ._model_workflow_common import (
        BASE_PARAMS_SCHEMA,
        accelerator_cleanup,
        add_diag,
        get_artifact,
        get_run,
        model_workflow_state,
        output_upload_path,
        flush_workflow_debug,
        release_workflow_object,
        resolve_python_bin,
        settings_artifact,
        set_artifact,
        skipped_for_failed_workflow,
        workflow_debug_dir,
    )
except Exception:
    from _ltx_native_graph_runtime import encode_video as native_graph_encode_video
    from _model_workflow_common import (
        BASE_PARAMS_SCHEMA,
        accelerator_cleanup,
        add_diag,
        get_artifact,
        get_run,
        model_workflow_state,
        output_upload_path,
        flush_workflow_debug,
        release_workflow_object,
        resolve_python_bin,
        settings_artifact,
        set_artifact,
        skipped_for_failed_workflow,
        workflow_debug_dir,
    )


NAME = "models.video_encode"
PERMISSIONS = ["models.video_encode", "models.*"]


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _append_optional(cmd: list[str], flag: str, value: Any) -> None:
    if value in (None, "", [], {}):
        return
    cmd.extend([flag, str(value)])


def _tail_text(path: Path, max_chars: int = 12000) -> str:
    try:
        if not path.exists():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace")
        return text[-max_chars:]
    except Exception:
        return ""


def _progress_callback(ctx: Dict[str, Any], settings: Dict[str, Any]):
    cb = (ctx or {}).get("progress")
    if not callable(cb):
        cb = (settings or {}).get("__agent_flow_progress_callback")
    return cb if callable(cb) else None


def _execute_ltx_checkpoint_runner(ctx: Dict[str, Any], row: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    assets = get_artifact(row, "assets", {})
    settings = settings_artifact(row, params)
    prompt_context = get_artifact(row, "prompt_context", {})
    prompt = str(_first((params or {}).get("prompt"), prompt_context.get("prompt"), (ctx or {}).get("user_text"), (ctx or {}).get("original_request")) or "").strip()
    if not prompt:
        raise RuntimeError("prompt is required for workflow video execution")
    output_path = Path(str((params or {}).get("output_path") or output_upload_path(ctx))).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    runner_path = str(_first(settings.get("workflow_runner_path"), assets.get("workflow_runner_path"), r"C:/Users/Tee/projects/llmloader2/tools/run_unsloth_ltx_workflow.py") or "").strip()
    if not runner_path:
        raise RuntimeError("workflow_runner_path is required")
    if not Path(runner_path).exists():
        raise RuntimeError(f"workflow_runner_path does not exist: {runner_path}")
    python_bin = resolve_python_bin({**settings, "python_bin": _first(settings.get("python_bin"), assets.get("python_bin"))})
    width = _coerce_int(_first((params or {}).get("width"), settings.get("width")), 848)
    height = _coerce_int(_first((params or {}).get("height"), settings.get("height")), 480)
    frames = _coerce_int(_first((params or {}).get("frames"), settings.get("frames")), 31)
    fps = _coerce_int(_first((params or {}).get("fps"), settings.get("fps")), 30)
    steps = _coerce_int(_first((params or {}).get("steps"), settings.get("steps")), 8)
    guidance_scale = _coerce_float(_first((params or {}).get("guidance_scale"), settings.get("guidance_scale")), 1.0)
    seed_value = _first((params or {}).get("seed"), settings.get("seed"))
    seed = _coerce_int(seed_value, -1) if seed_value not in (None, "") else -1
    cmd = [
        python_bin,
        runner_path,
        "--prompt", prompt,
        "--output", str(output_path),
        "--gguf", str(assets.get("gguf_path") or settings.get("gguf_path") or ""),
        "--embeddings-connectors", str(assets.get("embeddings_connectors_path") or settings.get("embeddings_connectors_path") or ""),
        "--video-vae", str(assets.get("video_vae_path") or settings.get("video_vae_path") or ""),
        "--audio-vae", str(assets.get("audio_vae_path") or settings.get("audio_vae_path") or ""),
        "--text-encoder", str(assets.get("text_encoder_gguf_path") or settings.get("text_encoder_gguf_path") or ""),
        "--mmproj", str(assets.get("text_encoder_mmproj_path") or settings.get("text_encoder_mmproj_path") or ""),
        "--width", str(width),
        "--height", str(height),
        "--frames", str(frames),
        "--fps", str(fps),
        "--steps", str(steps),
        "--guidance-scale", str(guidance_scale),
    ]
    _append_optional(cmd, "--model-id", settings.get("model_id"))
    _append_optional(cmd, "--negative-prompt", _first((params or {}).get("negative_prompt"), prompt_context.get("negative_prompt"), settings.get("negative_prompt")))
    _append_optional(cmd, "--device", settings.get("device"))
    _append_optional(cmd, "--dtype", settings.get("dtype"))
    _append_optional(cmd, "--gemma-text-encoding-device", settings.get("gemma_text_encoding_device"))
    _append_optional(cmd, "--native-transformer-offload", settings.get("native_transformer_offload"))
    _append_optional(cmd, "--native-transformer-gpu-slots", settings.get("native_transformer_gpu_slots"))
    _append_optional(cmd, "--native-debug-skip-stage2", settings.get("native_debug_skip_stage2"))
    _append_optional(cmd, "--ltx-video-only", settings.get("ltx_video_only"))
    skip_lora = str(
        _first((params or {}).get("skip_lora"), settings.get("skip_lora"), settings.get("native_skip_lora"))
        or ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    if skip_lora:
        add_diag(row, "video_encode", "checkpoint runner fallback skipping LoRA because skip_lora/native_skip_lora is enabled")
    else:
        _append_optional(cmd, "--distilled-lora", assets.get("distilled_lora_path") or settings.get("distilled_lora_path"))
    _append_optional(cmd, "--spatial-upscaler", assets.get("spatial_upscaler_path") or settings.get("spatial_upscaler_path"))
    if seed >= 0:
        cmd.extend(["--seed", str(seed)])
    missing_flags = [cmd[i - 1] for i, value in enumerate(cmd) if i > 0 and cmd[i - 1].startswith("--") and value == ""]
    if missing_flags:
        raise RuntimeError(f"missing required workflow runner values: {', '.join(missing_flags)}")
    debug_dir = workflow_debug_dir(ctx, row)
    run_log = debug_dir / f"agent_flow_video_encode_{int(time.time())}.json"
    stdout_log = debug_dir / f"agent_flow_video_encode_{int(time.time())}.stdout.log"
    stderr_log = debug_dir / f"agent_flow_video_encode_{int(time.time())}.stderr.log"
    add_diag(row, "video_encode", "dispatching workflow checkpoint runner", output_path=str(output_path), python_bin=python_bin, log_file=str(run_log))
    progress = _progress_callback(ctx, settings)
    if progress:
        try:
            progress(f"starting isolated video worker -> {output_path.name}", log_file=str(run_log))
        except Exception:
            pass
    started = time.time()
    timeout_s = _coerce_int(settings.get("workflow_node_timeout_s"), 60 * 60 * 3)
    payload: Dict[str, Any] = {
        "ok": False,
        "returncode": None,
        "cmd": cmd,
        "output_path": str(output_path),
        "elapsed_s": 0,
        "status": "starting",
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
    }
    run_log.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with stdout_log.open("w", encoding="utf-8", errors="replace") as out_fh, stderr_log.open("w", encoding="utf-8", errors="replace") as err_fh:
        proc = subprocess.Popen(
            cmd,
            cwd=str(Path(runner_path).resolve().parent.parent),
            text=True,
            stdout=out_fh,
            stderr=err_fh,
        )
        last_emit = 0.0
        while proc.poll() is None:
            elapsed = time.time() - started
            if elapsed > timeout_s:
                try:
                    proc.terminate()
                    proc.wait(timeout=10)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                raise RuntimeError(f"workflow video runner timed out after {timeout_s}s | log={run_log}")
            try:
                cancelled = getattr((ctx or {}).get("app"), "state", None)
                cancelled_map = getattr(cancelled, "ai_jobs_cancelled", None)
                if isinstance(cancelled_map, dict) and cancelled_map.get(str(row.get("run_id") or "")):
                    proc.terminate()
                    raise RuntimeError("workflow video runner canceled")
            except RuntimeError:
                raise
            except Exception:
                pass
            now = time.time()
            if now - last_emit >= 2.0:
                last_emit = now
                payload.update(
                    {
                        "status": "running",
                        "elapsed_s": round(elapsed, 3),
                        "stdout_tail": _tail_text(stdout_log, 6000),
                        "stderr_tail": _tail_text(stderr_log, 6000),
                    }
                )
                try:
                    run_log.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
                if progress:
                    try:
                        progress(f"isolated video worker running... {int(elapsed)}s", log_file=str(run_log))
                    except Exception:
                        pass
            time.sleep(0.35)
        returncode = proc.returncode
    payload = {
        "ok": returncode == 0,
        "returncode": returncode,
        "cmd": cmd,
        "output_path": str(output_path),
        "elapsed_s": round(time.time() - started, 3),
        "status": "finished" if returncode == 0 else "failed",
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
        "stdout_tail": _tail_text(stdout_log),
        "stderr_tail": _tail_text(stderr_log),
    }
    run_log.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    if progress:
        try:
            progress(
                ("isolated video worker finished" if payload["ok"] else f"isolated video worker failed returncode={returncode}"),
                log_file=str(run_log),
                output_path=str(output_path) if output_path.exists() else "",
            )
        except Exception:
            pass
    if returncode != 0:
        raise RuntimeError(f"workflow video runner failed | returncode={returncode} | log={run_log}")
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise RuntimeError(f"workflow video runner completed but output is missing or empty: {output_path}")
    return {"output_path": str(output_path), "log_file": str(run_log), "elapsed_s": payload["elapsed_s"]}


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "video_encode")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    settings = settings_artifact(row, params or {})
    execution_backend = str((params or {}).get("execution_backend") or settings.get("workflow_execution_backend") or "native_graph").strip()
    loader_mode = str(settings.get("workflow_loader_mode") or "").strip().lower()
    if loader_mode == "workflow_model_loader" and execution_backend.lower() in {"", "auto"}:
        execution_backend = "native_graph"
    warnings = []
    executed = None
    if execution_backend in {"native_graph", "native_comfyui_gguf", "ltx_native_graph", "model_graph"}:
        diagnostics = row.setdefault("diagnostics", [])
        resources = model_workflow_state(ctx or {}).setdefault("resources", {})
        decoded_handle = get_artifact(row, "decoded_video", {}) or {}
        decoded_resource = resources.get(str(decoded_handle.get("resource_key") or ""))
        if not decoded_resource:
            err = "missing native decoded video resource"
            add_diag(row, node_id, "native graph video encode failed", error=err)
            return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "warnings": ["missing_decoded_video_resource"], "error": err, "data": {"status": "failed", "error": err, "diagnostics": diagnostics}}
        try:
            output_path = Path(str((params or {}).get("output_path") or output_upload_path(ctx))).resolve()
            out = native_graph_encode_video(decoded_resource, str(output_path), diagnostics)
            decoded_key = str(decoded_handle.get("resource_key") or "").strip()
            released_decoded = 0
            if decoded_key and decoded_key in resources:
                released_decoded = release_workflow_object(resources.get(decoded_key))
                resources.pop(decoded_key, None)
            else:
                released_decoded = release_workflow_object(decoded_resource)
            accelerator_cleanup()
            add_diag(row, node_id, "released decoded video resource after MP4 encode", resource_key=decoded_key, nested_released=released_decoded)
            executed = {"output_path": out, "log_file": "", "elapsed_s": 0}
        except Exception as exc:
            add_diag(row, node_id, "native graph video encode failed", error=str(exc))
            return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "warnings": ["native_video_encode_failed"], "error": str(exc), "data": {"status": "failed", "error": str(exc), "diagnostics": diagnostics}}
    elif execution_backend in {"ltx_checkpoint_runner", "checkpoint_runner", "auto"}:
        if loader_mode == "workflow_model_loader":
            add_diag(
                row,
                node_id,
                "using checkpoint runner fallback for workflow_model_loader",
                execution_backend=execution_backend,
            )
        try:
            executed = _execute_ltx_checkpoint_runner(ctx or {}, row, params or {})
        except Exception as exc:
            add_diag(row, node_id, "workflow video execution failed", error=str(exc))
            return {
                "ok": False,
                "run_id": row.get("run_id"),
                "warnings": ["workflow_video_execution_failed"],
                "error": str(exc),
                "data": {"error": str(exc), "diagnostics": row.get("diagnostics") or []},
            }
    else:
        warnings.append(f"unsupported_execution_backend:{execution_backend}")
    output = {
        "kind": "output_video",
        "decoded_video": get_artifact(row, "decoded_video", {}),
        "fps": int((params or {}).get("fps") or 30),
        "codec": str((params or {}).get("codec") or "libx264"),
        "output_path": str((executed or {}).get("output_path") or (params or {}).get("output_path") or ""),
        "log_file": str((executed or {}).get("log_file") or ""),
        "execution_backend": execution_backend,
        "status": "executed" if executed else "declared",
    }
    set_artifact(row, "output_video", output)
    add_diag(row, node_id, "encoded video stage", codec=output["codec"], status=output["status"], output_path=output["output_path"])
    log_file = flush_workflow_debug(ctx or {}, row, label=f"{node_id}_after")
    if not output["log_file"]:
        output["log_file"] = log_file
    files = [output["output_path"]] if str(output.get("output_path") or "").strip() else []
    return {
        "ok": bool(executed) or not warnings,
        "run_id": row.get("run_id"),
        "status": output["status"],
        "result_mode": "files" if files else "",
        "files": files,
        "output_path": output["output_path"],
        "output_video": output,
        "data": {
            "status": output["status"],
            "result_mode": "files" if files else "",
            "files": files,
            "output_video": output,
            "output_path": output["output_path"],
            "log_file": output["log_file"],
            "diagnostics": row.get("diagnostics") or [],
        },
        "warnings": warnings,
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Encode Video",
    "description": "Encode decoded video frames/chunks into a browser-playable file.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
