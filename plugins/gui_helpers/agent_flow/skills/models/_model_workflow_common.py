from __future__ import annotations

import json
import os
import re
import sys
import time
import gc
import types
import builtins
from pathlib import Path
from typing import Any, Dict, List


MODEL_WORKFLOW_RUN_OVERRIDE_KEYS = {
    "steps",
    "high_noise_steps",
    "low_noise_steps",
    "guidance_scale",
    "high_noise_cfg",
    "low_noise_cfg",
    "sampler_name",
    "scheduler",
    "wan_i2v_denoise_strength",
    "i2v_denoise_strength",
    "i2v_strength",
    "wan_i2v_high_noise_start_step",
    "wan_i2v_low_noise_start_step",
    "wan_i2v_source_encode_mode",
    "wan_i2v_source_conditioning_cache_mode",
    "wan_i2v_source_hold_frames",
    "wan_i2v_source_conditioning_frames",
    "wan_i2v_source_tail_mode",
    "wan_i2v_source_tail_min_strength",
    "wan_i2v_source_tail_decay_power",
    "wan_i2v_vae_encode_device",
    "wan_i2v_source_vae_encode_device",
    "wan_vae_decode_device",
    "wan_vae_decode_mode",
    "wan_vae_halo_core_latent_frames",
    "wan_vae_halo_core_overlap_latent_frames",
    "wan_vae_halo_latent_frames",
    "wan_vae_halo_max_window_latent_frames",
    "wan_vae_halo_spatial_tiled",
    "wan_vae_halo_tile_size",
    "wan_vae_halo_tile_overlap",
    "wan_apply_stage_lora",
    "wan_stage_lora_strength",
    "high_noise_lora_strength",
    "low_noise_lora_strength",
    "negative_prompt",
    "prompt",
    "__request_source_image_path",
    "source_image_path",
    "image_path",
    "input_image_path",
    "start_image_path",
    "reference_image_path",
    "first_image_path",
    "last_image_path",
    "end_image_path",
    "target_image_path",
    "reference_image_1_path",
    "reference_image_2_path",
    "ref_image_1_path",
    "ref_image_2_path",
    "input_image_paths",
    "image_paths",
    "workflow_media_inputs",
}


def _run_override_values(raw: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for key in MODEL_WORKFLOW_RUN_OVERRIDE_KEYS:
        value = raw.get(key)
        if value in (None, "", [], {}):
            continue
        out[key] = value
    return out


def _norm_identity_value(value: Any) -> str:
    return str(value or "").strip().lower()


def _model_deck_defaults_match_current_workflow(current: Dict[str, Any], deck_settings: Dict[str, Any]) -> bool:
    """Return whether video deck defaults are safe to overlay onto this run.

    The Model Deck video default is a fallback/hydration source for generic
    model workflows. It must not overwrite a run that already selected a
    different model workflow; otherwise a Wan flow can inherit MiniMax assets
    and fail at decode with mismatched latent/VAE channels.
    """
    if not isinstance(current, dict) or not isinstance(deck_settings, dict) or not deck_settings:
        return False
    identity_pairs = (
        ("model_deck_compat_manifest_id",),
        ("tested_profile_id", "model_deck_compat_manifest_id"),
        ("model_workflow_flow_name",),
        ("model_workflow_template_flow_name", "model_workflow_flow_name"),
        ("model_family",),
        ("workflow_variant",),
        ("model_id",),
    )
    for pair in identity_pairs:
        current_key = pair[0]
        deck_key = pair[-1]
        current_value = _norm_identity_value(current.get(current_key))
        deck_value = _norm_identity_value(deck_settings.get(deck_key))
        if current_value and deck_value and current_value != deck_value:
            return False
    return True


def now_ms() -> int:
    return int(time.time() * 1000)


def workspace_root(ctx: Dict[str, Any]) -> Path:
    app = (ctx or {}).get("app")
    root = getattr(getattr(app, "state", None), "workspace_root", None)
    if root:
        return Path(str(root)).resolve()
    return Path(__file__).resolve().parents[5]


def model_deck_models_dir(ctx: Dict[str, Any] | None = None, settings: Dict[str, Any] | None = None) -> Path:
    """Return the portable root for Model Deck model assets.

    Tested workflow/profile JSON should not bake in Windows-only drive paths.
    Use ``${MODEL_DECK_MODELS_DIR}/...`` in templates and let this resolver
    expand it per machine. Users can still keep explicit absolute paths in
    their own deck settings when they want to.
    """
    ctx = ctx or {}
    settings = settings or {}
    for raw in (
        settings.get("model_deck_models_dir"),
        settings.get("models_dir"),
        os.environ.get("MODEL_DECK_MODELS_DIR"),
    ):
        text = str(raw or "").strip()
        if text:
            return Path(os.path.expandvars(os.path.expanduser(text))).resolve()
    if os.name == "nt":
        shared_windows_models = Path("D:/models")
        if shared_windows_models.is_dir():
            return shared_windows_models.resolve()
    return (workspace_root(ctx) / "data" / "models").resolve()


def workflow_data_dir(ctx: Dict[str, Any] | None = None) -> Path:
    return (workspace_root(ctx or {}) / "data").resolve()


def expand_portable_path(value: Any, ctx: Dict[str, Any] | None = None, settings: Dict[str, Any] | None = None) -> str:
    """Expand portable workflow path tokens while leaving ordinary text intact."""
    text = str(value or "").strip()
    if not text:
        return ""
    ctx = ctx or {}
    settings = settings or {}
    root = str(workspace_root(ctx)).replace("\\", "/")
    models = str(model_deck_models_dir(ctx, settings)).replace("\\", "/")
    data = str(workflow_data_dir(ctx)).replace("\\", "/")
    replacements = {
        "${MODEL_DECK_MODELS_DIR}": models,
        "$MODEL_DECK_MODELS_DIR": models,
        "${LLMLOADER2_ROOT}": root,
        "$LLMLOADER2_ROOT": root,
        "${APP_ROOT}": root,
        "$APP_ROOT": root,
        "${WORKSPACE_ROOT}": root,
        "$WORKSPACE_ROOT": root,
        "${MODEL_DECK_DATA_DIR}": data,
        "$MODEL_DECK_DATA_DIR": data,
    }
    for token, replacement in replacements.items():
        text = text.replace(token, replacement)
    if text.startswith("modeldeck://models/"):
        text = str(model_deck_models_dir(ctx, settings) / text[len("modeldeck://models/") :])
    elif text.startswith("modeldeck://data/"):
        text = str(workflow_data_dir(ctx) / text[len("modeldeck://data/") :])
    return os.path.expandvars(os.path.expanduser(text))


def model_workflow_state(ctx: Dict[str, Any]) -> Dict[str, Any]:
    app = (ctx or {}).get("app")
    state = getattr(app, "state", None)
    if state is None:
        return {}
    current = getattr(state, "model_workflow_state", None)
    if not isinstance(current, dict):
        current = {"runs": {}, "resources": {}}
        setattr(state, "model_workflow_state", current)
    current.setdefault("runs", {})
    current.setdefault("resources", {})
    return current


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _ensure_tools_path() -> None:
    tools = _repo_root() / "tools"
    text = str(tools)
    if text not in sys.path:
        sys.path.insert(0, text)


def release_workflow_object(value: Any, seen: set[int] | None = None) -> int:
    """Best-effort recursive release for live model workflow resources."""
    if seen is None:
        seen = set()
    if value is None:
        return 0
    # Never recurse into Python runtime modules. Earlier cleanup tried to walk
    # module globals to free nested model objects, but third-party modules often
    # keep references to ``builtins`` and asyncio internals under normal names.
    # Mutating those dictionaries can corrupt the live server process
    # (for example, turning builtins.hasattr into None).
    if value is builtins or value is sys or isinstance(value, types.ModuleType):
        return 0
    ident = id(value)
    if ident in seen:
        return 0
    seen.add(ident)
    released = 0
    try:
        _ensure_tools_path()
        from ltx_native_gguf_bridge import release_module_gguf_tensors

        released += int(release_module_gguf_tensors(value) or 0)
    except Exception:
        pass
    try:
        import torch

        if isinstance(value, torch.Tensor):
            return released + 1
        if isinstance(value, torch.nn.Module):
            # This object is an explicit workflow-owned model/module resource.
            # Empty to meta instead of CPU so terminal cleanup does not inflate
            # host RAM while trying to free accelerator memory.
            try:
                value.to_empty(device="meta")
                released += 1
            except Exception:
                pass
            return released
    except Exception:
        pass
    if isinstance(value, dict):
        is_module_globals = "__builtins__" in value or "__name__" in value or "__loader__" in value
        for key, item in list(value.items()):
            key_text = str(key or "")
            if key_text == "__builtins__" or (is_module_globals and key_text.startswith("__")):
                continue
            released += release_workflow_object(item, seen)
            if is_module_globals:
                try:
                    value[key] = None
                except Exception:
                    pass
        if not is_module_globals:
            value.clear()
        return released + 1
    if isinstance(value, list):
        for item in list(value):
            released += release_workflow_object(item, seen)
        value.clear()
        return released + 1
    if isinstance(value, tuple):
        for item in value:
            released += release_workflow_object(item, seen)
        return released
    for method_name in ("close", "cleanup", "unload", "release"):
        try:
            method = getattr(value, method_name, None)
        except Exception:
            continue
        if not callable(method):
            continue
        try:
            method()
            released += 1
            break
        except TypeError:
            continue
        except Exception:
            continue
    # Do not introspect arbitrary object attributes here. It is tempting to walk
    # fields such as ``model`` or ``module`` to chase down every tensor, but in a
    # long-running web server those objects can include import machinery,
    # asyncio handles, loggers, and module globals. Clearing those references can
    # corrupt the interpreter. Owned workflow containers should pass dict/list
    # resources explicitly; process-per-job workers should rely on process exit.
    return released


def process_memory_trim() -> Dict[str, Any]:
    """Ask the host OS/native allocator to return free heap pages.

    This is intentionally best-effort.  It does not kill the server or unload
    user-visible state; it only trims pages that are already free after Python
    refs, model tensors, and accelerator caches have been released.
    """

    report: Dict[str, Any] = {"attempted": False, "method": "", "ok": False, "actions": [], "error": ""}
    try:
        if os.name == "nt":
            import ctypes  # type: ignore

            report["attempted"] = True
            report["method"] = "windows_heap_trim"
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            handle = kernel32.GetCurrentProcess()
            actions = report.setdefault("actions", [])
            for dll_name in ("ucrtbase", "msvcrt"):
                try:
                    crt = ctypes.CDLL(dll_name)
                    heapmin = getattr(crt, "_heapmin", None)
                    if callable(heapmin):
                        rc = int(heapmin())
                        actions.append({"name": f"{dll_name}._heapmin", "ok": rc == 0, "rc": rc})
                        break
                except Exception as exc:
                    actions.append({"name": f"{dll_name}._heapmin", "ok": False, "error": str(exc)})
            try:
                kernel32.GetProcessHeap.restype = ctypes.c_void_p
                heap = kernel32.GetProcessHeap()
                if heap:
                    kernel32.HeapCompact.argtypes = [ctypes.c_void_p, ctypes.c_uint]
                    kernel32.HeapCompact.restype = ctypes.c_size_t
                    compacted = int(kernel32.HeapCompact(ctypes.c_void_p(heap), 0) or 0)
                    actions.append({"name": "kernel32.HeapCompact", "ok": True, "bytes": compacted})
            except Exception as exc:
                actions.append({"name": "kernel32.HeapCompact", "ok": False, "error": str(exc)})
            ok = bool(psapi.EmptyWorkingSet(ctypes.c_void_p(handle)))
            actions.append({"name": "psapi.EmptyWorkingSet", "ok": ok, "winerr": 0 if ok else ctypes.get_last_error()})
            report["ok"] = any(bool(item.get("ok")) for item in actions if isinstance(item, dict))
            return report
        if sys.platform.startswith("linux"):
            import ctypes  # type: ignore

            report["attempted"] = True
            report["method"] = "libc.malloc_trim(0)"
            libc = ctypes.CDLL("libc.so.6")
            report["ok"] = bool(libc.malloc_trim(0))
            return report
    except Exception as exc:
        report["error"] = str(exc)
    return report


def accelerator_cleanup() -> None:
    """Release Python refs and ask accelerator/native allocators to return cached blocks."""
    try:
        gc.collect()
    except Exception:
        pass
    try:
        import torch

        if hasattr(torch, "xpu") and torch.xpu.is_available():
            try:
                torch.xpu.synchronize()
            except Exception:
                pass
            try:
                torch.xpu.empty_cache()
            except Exception:
                pass
        try:
            if hasattr(torch._C, "_host_emptyCache"):
                torch._C._host_emptyCache()
        except Exception:
            pass
        if hasattr(torch, "cuda") and torch.cuda.is_available():
            try:
                torch.cuda.synchronize()
            except Exception:
                pass
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass
    except Exception:
        pass
    try:
        gc.collect()
    except Exception:
        pass
    try:
        process_memory_trim()
    except Exception:
        pass


def memory_snapshot(label: str = "") -> Dict[str, Any]:
    """Compact CPU/GPU memory snapshot for model workflow diagnostics."""
    out: Dict[str, Any] = {"label": str(label or "")}
    try:
        import psutil  # type: ignore

        proc = psutil.Process(os.getpid())
        mem = proc.memory_info()
        out["process_rss_mb"] = round(float(getattr(mem, "rss", 0) or 0) / 1024 / 1024, 1)
        out["process_vms_mb"] = round(float(getattr(mem, "vms", 0) or 0) / 1024 / 1024, 1)
        vm = psutil.virtual_memory()
        out["system_used_mb"] = round(float(getattr(vm, "used", 0) or 0) / 1024 / 1024, 1)
        out["system_available_mb"] = round(float(getattr(vm, "available", 0) or 0) / 1024 / 1024, 1)
    except Exception as exc:
        out["process_memory_error"] = str(exc)
    try:
        import torch  # type: ignore

        if hasattr(torch, "xpu") and torch.xpu.is_available():
            try:
                out["xpu_allocated_mb"] = round(float(torch.xpu.memory_allocated()) / 1024 / 1024, 1)
            except Exception as exc:
                out["xpu_allocated_error"] = str(exc)
            try:
                out["xpu_reserved_mb"] = round(float(torch.xpu.memory_reserved()) / 1024 / 1024, 1)
            except Exception as exc:
                out["xpu_reserved_error"] = str(exc)
        if hasattr(torch, "cuda") and torch.cuda.is_available():
            try:
                out["cuda_allocated_mb"] = round(float(torch.cuda.memory_allocated()) / 1024 / 1024, 1)
                out["cuda_reserved_mb"] = round(float(torch.cuda.memory_reserved()) / 1024 / 1024, 1)
            except Exception as exc:
                out["cuda_memory_error"] = str(exc)
    except Exception as exc:
        out["torch_memory_error"] = str(exc)
    return out


def live_accelerator_tensor_summary(*, limit: int = 12) -> Dict[str, Any]:
    """Return a compact process-wide summary of live accelerator tensors.

    This is diagnostic only.  We intentionally do not mutate arbitrary tensors
    discovered through gc because the server can host other models in the same
    process.  The summary tells us whether post-run VRAM is true live tensor
    residency or only an allocator/runtime reservation.
    """
    out: Dict[str, Any] = {"live_tensor_count": 0, "live_tensor_mb": 0.0, "largest": []}
    try:
        import torch
    except Exception as exc:
        out["error"] = str(exc)
        return out
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    try:
        objects = gc.get_objects()
    except Exception as exc:
        out["error"] = str(exc)
        return out
    for obj in objects:
        try:
            if not isinstance(obj, torch.Tensor):
                continue
        except Exception:
            continue
        ident = id(obj)
        if ident in seen:
            continue
        seen.add(ident)
        try:
            device_text = str(getattr(obj, "device", "") or "")
        except Exception:
            continue
        if not device_text.startswith(("xpu", "cuda", "mps")):
            continue
        try:
            numel = int(obj.numel())
            elem_size = int(obj.element_size())
            size_mb = (numel * elem_size) / 1024 / 1024
            shape = tuple(int(x) for x in tuple(obj.shape))
            dtype = str(obj.dtype)
        except Exception:
            numel = 0
            elem_size = 0
            size_mb = 0.0
            shape = ()
            dtype = ""
        rows.append(
            {
                "mb": round(size_mb, 1),
                "device": device_text,
                "dtype": dtype,
                "shape": shape,
                "requires_grad": bool(getattr(obj, "requires_grad", False)),
            }
        )
    rows.sort(key=lambda item: float(item.get("mb") or 0.0), reverse=True)
    out["live_tensor_count"] = len(rows)
    out["live_tensor_mb"] = round(sum(float(item.get("mb") or 0.0) for item in rows), 1)
    out["largest"] = rows[: max(0, int(limit))]
    return out


def unload_runtime_modules(prefixes: tuple[str, ...] = ("ltx_core", "ltx_pipelines")) -> int:
    """Unload workflow-only runtime modules so module globals cannot pin tensors."""
    removed = 0
    for name in list(sys.modules.keys()):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes):
            try:
                sys.modules.pop(name, None)
                removed += 1
            except Exception:
                pass
    return removed


def run_id(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    explicit = str((params or {}).get("run_id") or "").strip()
    if explicit:
        return explicit
    ext = (ctx or {}).get("ext") if isinstance((ctx or {}).get("ext"), dict) else {}
    for key in ("model_workflow_run_id", "agent_flow_run_id", "run_id"):
        value = str(ext.get(key) or "").strip()
        if value:
            return value
    return f"model_workflow_{now_ms()}"


def get_run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    rid = run_id(ctx, params)
    state = model_workflow_state(ctx)
    runs = state.setdefault("runs", {})
    row = runs.get(rid)
    if not isinstance(row, dict):
        row = {"run_id": rid, "artifacts": {}, "diagnostics": [], "created_ms": now_ms(), "updated_ms": now_ms()}
        runs[rid] = row
    row.setdefault("artifacts", {})
    row.setdefault("diagnostics", [])
    seed = None
    if isinstance(params, dict) and isinstance(params.get("model_workflow_seed_artifacts"), dict):
        seed = params.get("model_workflow_seed_artifacts")
    elif isinstance(ctx, dict) and isinstance(ctx.get("model_workflow_seed_artifacts"), dict):
        seed = ctx.get("model_workflow_seed_artifacts")
    if isinstance(seed, dict) and not row.get("_seed_artifacts_loaded"):
        artifacts = row.setdefault("artifacts", {})
        if not isinstance(artifacts, dict):
            artifacts = {}
            row["artifacts"] = artifacts
        for key, value in seed.items():
            if str(key) in {"settings", "assets"} and isinstance(value, dict):
                existing = artifacts.get(str(key))
                if not isinstance(existing, dict):
                    existing = {}
                artifacts[str(key)] = {**existing, **dict(value)}
            elif value not in (None, "", [], {}):
                artifacts[str(key)] = value
        row["_seed_artifacts_loaded"] = True
        try:
            row.setdefault("diagnostics", []).append({
                "ts_ms": now_ms(),
                "node": "get_run",
                "message": "loaded model workflow seed artifacts",
                "seed_keys": sorted(str(k) for k in seed.keys()),
                "settings_source_image_path": str((artifacts.get("settings") if isinstance(artifacts.get("settings"), dict) else {}).get("__request_source_image_path") or ""),
                "assets_source_image_path": str((artifacts.get("assets") if isinstance(artifacts.get("assets"), dict) else {}).get("__request_source_image_path") or ""),
            })
        except Exception:
            pass
    row["updated_ms"] = now_ms()
    return row


def add_diag(run: Dict[str, Any], node_id: str, message: str, **extra: Any) -> None:
    diag = run.setdefault("diagnostics", [])
    item = {"ts_ms": now_ms(), "node": str(node_id or ""), "message": str(message or "")}
    for key, value in extra.items():
        if value is not None:
            item[key] = value
    diag.append(item)
    if len(diag) > 500:
        del diag[:-500]


def resource_snapshot() -> Dict[str, Any]:
    out: Dict[str, Any] = {"pid": os.getpid(), "ts_ms": now_ms()}
    try:
        import psutil

        proc = psutil.Process(os.getpid())
        mem = proc.memory_info()
        vm = psutil.virtual_memory()
        out.update(
            {
                "process_rss_mb": round(mem.rss / 1024 / 1024, 1),
                "process_private_mb": round(getattr(mem, "private", 0) / 1024 / 1024, 1) if getattr(mem, "private", 0) else None,
                "process_vms_mb": round(mem.vms / 1024 / 1024, 1),
                "process_cpu_pct": round(proc.cpu_percent(interval=None), 1),
                "system_used_mb": round((vm.total - vm.available) / 1024 / 1024, 1),
                "system_available_mb": round(vm.available / 1024 / 1024, 1),
                "system_used_pct": round(float(vm.percent), 1),
            }
        )
    except Exception as exc:
        out["system_probe_error"] = str(exc)
    try:
        import torch

        if hasattr(torch, "xpu") and torch.xpu.is_available():
            xpu = torch.xpu
            dev = torch.device("xpu:0")
            out["xpu_available"] = True
            if hasattr(xpu, "memory_allocated"):
                out["xpu_allocated_mb"] = round(xpu.memory_allocated(dev) / 1024 / 1024, 1)
            if hasattr(xpu, "memory_reserved"):
                out["xpu_reserved_mb"] = round(xpu.memory_reserved(dev) / 1024 / 1024, 1)
            if hasattr(xpu, "mem_get_info"):
                try:
                    free_b, total_b = xpu.mem_get_info(dev)
                except TypeError:
                    free_b, total_b = xpu.mem_get_info()
                out["xpu_free_mb"] = round(int(free_b) / 1024 / 1024, 1)
                out["xpu_total_mb"] = round(int(total_b) / 1024 / 1024, 1)
        if hasattr(torch, "cuda") and torch.cuda.is_available():
            dev = torch.device("cuda:0")
            out["cuda_available"] = True
            out["cuda_allocated_mb"] = round(torch.cuda.memory_allocated(dev) / 1024 / 1024, 1)
            out["cuda_reserved_mb"] = round(torch.cuda.memory_reserved(dev) / 1024 / 1024, 1)
    except Exception as exc:
        out["accelerator_probe_error"] = str(exc)
    return {k: v for k, v in out.items() if v is not None}


def set_artifact(run: Dict[str, Any], key: str, value: Any) -> None:
    run.setdefault("artifacts", {})[str(key)] = value
    run["updated_ms"] = now_ms()


def get_artifact(run: Dict[str, Any], key: str, default: Any = None) -> Any:
    return (run.get("artifacts") if isinstance(run.get("artifacts"), dict) else {}).get(str(key), default)


def mark_workflow_failed(run: Dict[str, Any], node_id: str, error: Any, *, warning: str = "model_workflow_failed") -> Dict[str, Any]:
    failure = {
        "node": str(node_id or ""),
        "error": str(error or "model workflow failed"),
        "warning": str(warning or "model_workflow_failed"),
        "ts_ms": now_ms(),
    }
    set_artifact(run, "workflow_failed", failure)
    return failure


def workflow_failed(run: Dict[str, Any]) -> Dict[str, Any] | None:
    failure = get_artifact(run, "workflow_failed", None)
    return failure if isinstance(failure, dict) and failure.get("error") else None


def skipped_for_failed_workflow(run: Dict[str, Any], node_id: str, ctx: Dict[str, Any] | None = None) -> Dict[str, Any] | None:
    failure = workflow_failed(run)
    if not failure:
        return None
    add_diag(
        run,
        node_id,
        "skipping node because an upstream model workflow node failed",
        failed_node=str(failure.get("node") or ""),
        upstream_error=str(failure.get("error") or ""),
    )
    log_file = ""
    if ctx is not None:
        log_file = flush_workflow_debug(ctx or {}, run, label=f"{node_id}_skipped")
    return {
        "ok": False,
        "run_id": run.get("run_id"),
        "status": "skipped",
        "error": f"upstream model workflow failure at {failure.get('node')}: {failure.get('error')}",
        "data": {"status": "skipped", "upstream_failure": failure, "log_file": log_file},
        "warnings": [str(failure.get("warning") or "model_workflow_failed")],
    }


def dict_param(params: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = (params or {}).get(key)
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def list_param(params: Dict[str, Any], key: str) -> List[str]:
    value = (params or {}).get(key)
    if isinstance(value, list):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


MODEL_WORKFLOW_MEDIA_OVERRIDE_KEYS = (
    "__request_source_image_path",
    "source_image_path",
    "image_path",
    "input_image_path",
    "init_image_path",
    "start_image_path",
    "reference_image_path",
    "first_image_path",
    "last_image_path",
    "target_image_path",
    "end_image_path",
    "reference_image_1_path",
    "reference_image_2_path",
    "ref_image_1_path",
    "ref_image_2_path",
    "input_image_paths",
    "image_paths",
    "workflow_media_inputs",
)


MODEL_WORKFLOW_IDENTITY_KEYS = (
    "agent_flow_default_workflow_id",
    "model_workflow_attached_flows",
    "model_workflow_id",
)


def _workflow_family_probe(settings: Dict[str, Any]) -> str:
    return " ".join(
        str(settings.get(key) or "").replace("_", " ").replace("-", " ").lower()
        for key in (
            "model_id",
            "model_family",
            "workflow_variant",
            "model_deck_compat_manifest_id",
            "tested_profile_id",
            "model_workflow_flow_name",
            "model_workflow_template_flow_name",
        )
    )


def strip_stale_workflow_identity(settings: Dict[str, Any]) -> None:
    if not isinstance(settings, dict):
        return
    selected_flow_name = str(settings.get("model_workflow_flow_name") or "").strip()
    if not selected_flow_name.lower().startswith("models /"):
        return
    attached_rows = settings.get("model_workflow_attached_flows")
    if isinstance(attached_rows, list):
        probe_id = _workflow_family_probe(settings).replace(" ", "_")
        kept_rows = [
            dict(row) for row in attached_rows
            if isinstance(row, dict) and str(row.get("name") or "").strip() == selected_flow_name
        ]
        for row in kept_rows:
            row_id = str(row.get("workflow_id") or "").strip().lower()
            if row_id.startswith("models.") and row_id not in probe_id:
                row.pop("workflow_id", None)
        if kept_rows:
            settings["model_workflow_attached_flows"] = kept_rows
        else:
            settings.pop("model_workflow_attached_flows", None)
    probe_id = _workflow_family_probe(settings).replace(" ", "_")
    for key in ("model_workflow_id", "agent_flow_default_workflow_id"):
        value = str(settings.get(key) or "").strip().lower()
        if value.startswith("models.") and value not in probe_id:
            settings.pop(key, None)


def normalize_minimax_h3_settings(settings: Dict[str, Any]) -> None:
    if not isinstance(settings, dict):
        return
    probe = _workflow_family_probe(settings)
    if "minimax" not in probe and "ref2va" not in probe and "fl2va" not in probe:
        return
    if str(settings.get("native_lazy_quantized_packed_device") or "").strip().lower() in {"", "auto", "gpu"}:
        settings["native_lazy_quantized_packed_device"] = "cpu"


def workflow_accepts_request_images(settings: Dict[str, Any]) -> bool:
    if not isinstance(settings, dict):
        return True
    probe_parts = [
        settings.get("workflow_variant"),
        settings.get("hunyuan_conditioning_mode"),
        settings.get("wan_conditioning_mode"),
        settings.get("minimax_conditioning_mode"),
        settings.get("model_family"),
        settings.get("model_workflow_flow_name"),
        settings.get("model_workflow_template_flow_name"),
        settings.get("workflow_media_mode"),
    ]
    probe = " ".join(str(part or "").replace("_", " ").replace("-", " ").lower() for part in probe_parts)
    if any(token in probe for token in (" i2v", "i2v ", "image to video", "ref2v", "ref2va", "fl2va", "first last")):
        return True
    if any(token in probe for token in (" t2v", "t2v ", "text to video")):
        return False
    return True


def workflow_request_image_limit(settings: Dict[str, Any]) -> int:
    if not isinstance(settings, dict):
        return 1
    probe_parts = [
        settings.get("workflow_variant"),
        settings.get("hunyuan_conditioning_mode"),
        settings.get("wan_conditioning_mode"),
        settings.get("minimax_conditioning_mode"),
        settings.get("model_family"),
        settings.get("model_workflow_flow_name"),
        settings.get("model_workflow_template_flow_name"),
        settings.get("workflow_media_mode"),
    ]
    probe = " ".join(str(part or "").replace("_", " ").replace("-", " ").lower() for part in probe_parts)
    if "minimax" in probe or "ref2va" in probe or "fl2va" in probe or "first last" in probe:
        return 2
    if "hunyuan" in probe or "wan" in probe or " i2v" in probe or "i2v " in probe or "image to video" in probe:
        return 1
    return 1


def clear_request_media_overrides(settings: Dict[str, Any]) -> None:
    if not isinstance(settings, dict):
        return
    for key in MODEL_WORKFLOW_MEDIA_OVERRIDE_KEYS:
        settings.pop(key, None)


def clamp_request_media_overrides(settings: Dict[str, Any]) -> None:
    if not isinstance(settings, dict):
        return
    if workflow_request_image_limit(settings) > 1:
        return
    first_image = str(
        settings.get("__request_source_image_path")
        or settings.get("first_image_path")
        or settings.get("reference_image_1_path")
        or settings.get("ref_image_1_path")
        or settings.get("source_image_path")
        or settings.get("image_path")
        or ""
    ).strip()
    for key in ("last_image_path", "end_image_path", "target_image_path", "reference_image_2_path", "ref_image_2_path"):
        settings.pop(key, None)
    for key in ("image_paths", "input_image_paths"):
        value = settings.get(key)
        if isinstance(value, list):
            settings[key] = value[:1]
    media_inputs = settings.get("workflow_media_inputs")
    if isinstance(media_inputs, dict):
        images = media_inputs.get("images")
        if isinstance(images, list):
            media_inputs["images"] = images[:1]
        for key in ("last_image_path", "end_image_path", "target_image_path", "reference_image_2_path", "ref_image_2_path"):
            media_inputs.pop(key, None)
        if first_image:
            media_inputs["first_image_path"] = first_image
            media_inputs["source_image_path"] = first_image


def resolve_asset_values(params: Dict[str, Any]) -> Dict[str, Any]:
    assets = dict_param(params, "assets")
    settings = dict_param(params, "settings")
    ctx = dict_param(params, "ctx")
    explicit_run_overrides = _run_override_values(settings)
    explicit_source_image_override = next(
        (
            str(settings.get(key) or "").strip()
            for key in (
                "__request_source_image_path",
                "first_image_path",
                "reference_image_1_path",
                "ref_image_1_path",
                "source_image_path",
            )
            if str(settings.get(key) or "").strip()
        ),
        "",
    )
    explicit_last_image_override = next(
        (
            str(settings.get(key) or "").strip()
            for key in (
                "last_image_path",
                "reference_image_2_path",
                "ref_image_2_path",
                "end_image_path",
                "target_image_path",
            )
            if str(settings.get(key) or "").strip()
        ),
        "",
    )
    explicit_request_prompt = str(settings.get("__request_prompt") or "").strip()
    media_type = str(
        settings.get("model_type")
        or settings.get("workflow_media_type")
        or settings.get("diffusers_media_type")
        or ""
    ).strip().lower()
    is_image_workflow = media_type in {"image", "image_gen"} or str(settings.get("model_family") or "").strip().lower().endswith("_diffusers_repo")
    deck_settings, deck_model_id = ({}, "") if is_image_workflow else _current_model_deck_video_default_settings()
    deck_default_flag = settings.get("model_workflow_use_model_deck_default_assets")
    if deck_default_flag is None:
        deck_default_flag = settings.get("use_model_deck_default_assets")
    use_deck_defaults = str("true" if deck_default_flag is None else deck_default_flag).strip().lower() not in {"0", "false", "no", "off"}
    deck_defaults_match = _model_deck_defaults_match_current_workflow(settings, deck_settings)
    if deck_settings and use_deck_defaults and not deck_defaults_match:
        try:
            print(
                "[model_workflow.assets] skipped_model_deck_default_overlay "
                f"current_flow={str(settings.get('model_workflow_flow_name') or '')!r} "
                f"deck_flow={str(deck_settings.get('model_workflow_flow_name') or '')!r} "
                f"current_compat={str(settings.get('model_deck_compat_manifest_id') or settings.get('tested_profile_id') or '')!r} "
                f"deck_compat={str(deck_settings.get('model_deck_compat_manifest_id') or deck_settings.get('tested_profile_id') or '')!r}",
                flush=True,
            )
        except Exception:
            pass
    if deck_settings and use_deck_defaults and deck_defaults_match:
        settings = {**settings, **deck_settings}
        strip_stale_workflow_identity(settings)
        if deck_model_id:
            settings["__model_deck_default_model_id"] = deck_model_id
        if explicit_run_overrides:
            settings.update(explicit_run_overrides)
        if explicit_request_prompt:
            settings["prompt"] = explicit_request_prompt
            settings["positive_prompt"] = explicit_request_prompt
            settings["__request_prompt"] = explicit_request_prompt
            settings["default_prompt"] = ""
            settings["wan_optional_default_prompt"] = ""
            settings["use_default_when_blank"] = False
            settings["wan_optional_use_default_when_blank"] = False
        if explicit_source_image_override:
            # I2V runs can provide a one-off source image from the request.
            # Model Deck defaults remain useful for assets/weights, but a saved
            # default source image must not override the explicit run input.
            settings["source_image_path"] = explicit_source_image_override
            settings["image_path"] = explicit_source_image_override
            settings["input_image_path"] = explicit_source_image_override
            settings["start_image_path"] = explicit_source_image_override
            settings["reference_image_path"] = explicit_source_image_override
            settings["first_image_path"] = explicit_source_image_override
            settings["reference_image_1_path"] = explicit_source_image_override
            settings["ref_image_1_path"] = explicit_source_image_override
            settings["__request_source_image_path"] = explicit_source_image_override
        if explicit_last_image_override:
            settings["last_image_path"] = explicit_last_image_override
            settings["end_image_path"] = explicit_last_image_override
            settings["target_image_path"] = explicit_last_image_override
            settings["reference_image_2_path"] = explicit_last_image_override
            settings["ref_image_2_path"] = explicit_last_image_override
    if not workflow_accepts_request_images(settings):
        clear_request_media_overrides(settings)
        explicit_source_image_override = ""
        explicit_last_image_override = ""
    else:
        clamp_request_media_overrides(settings)
        if workflow_request_image_limit(settings) <= 1:
            explicit_last_image_override = ""
    normalize_minimax_h3_settings(settings)
    try:
        print(
            "[model_workflow.assets] resolve_start "
            f"explicit_source={explicit_source_image_override!r} "
            f"explicit_last={explicit_last_image_override!r} "
            f"settings_source={str(settings.get('source_image_path') or '')!r} "
            f"settings_last={str(settings.get('reference_image_2_path') or settings.get('last_image_path') or '')!r} "
            f"runtime_assets_has={bool(str(settings.get('video_runtime_assets_json') or '').strip())} "
            f"assets_source={str(assets.get('source_image_path') or '')!r}",
            flush=True,
        )
    except Exception:
        pass
    runtime_assets = {}
    raw_runtime_assets = settings.get("video_runtime_assets_json")
    if isinstance(raw_runtime_assets, str) and raw_runtime_assets.strip():
        try:
            parsed_runtime_assets = json.loads(raw_runtime_assets)
            if isinstance(parsed_runtime_assets, dict):
                runtime_assets = parsed_runtime_assets
        except Exception:
            runtime_assets = {}
    asset_keys = list_param(params, "asset_keys")
    if not asset_keys:
        asset_keys = sorted({*assets.keys(), *runtime_assets.keys(), *settings.keys()})
    elif explicit_source_image_override or explicit_last_image_override:
        for key in (
            "__request_source_image_path",
            "source_image_path",
            "image_path",
            "start_image_path",
            "input_image_path",
            "init_image_path",
            "reference_image_path",
            "first_image_path",
            "last_image_path",
            "end_image_path",
            "target_image_path",
            "reference_image_1_path",
            "reference_image_2_path",
            "ref_image_1_path",
            "ref_image_2_path",
            "input_image_paths",
            "image_paths",
            "workflow_media_inputs",
        ):
            if key in settings and key not in asset_keys:
                asset_keys.append(key)
    out: Dict[str, Any] = {}
    for key in asset_keys:
        # First-class Model Deck fields are the source of truth for a selected
        # model. Nested runtime JSON and reusable flow defaults are fallback
        # templates; they may be stale after cloning or editing a model.
        value = settings.get(key)
        if value in (None, ""):
            value = runtime_assets.get(key)
        if value in (None, ""):
            value = assets.get(key)
        if value in (None, ""):
            continue
        text = expand_portable_path(value, ctx, settings)
        out[key] = text
        if key.endswith("_path") or key in {"gguf_path", "model_path"}:
            try:
                p = Path(text).expanduser()
                out[f"{key}__exists"] = p.exists()
                out[f"{key}__abs"] = str(p.resolve()) if p.exists() else os.path.abspath(text)
            except Exception:
                out[f"{key}__exists"] = False
    try:
        print(
            "[model_workflow.assets] resolve_done "
            f"source={str(out.get('source_image_path') or '')!r} "
            f"request_source={str(out.get('__request_source_image_path') or '')!r} "
            f"image={str(out.get('image_path') or '')!r} "
            f"first={str(out.get('reference_image_1_path') or out.get('first_image_path') or '')!r} "
            f"last={str(out.get('reference_image_2_path') or out.get('last_image_path') or '')!r}",
            flush=True,
        )
    except Exception:
        pass
    return out


def _path_exists_text(value: Any) -> bool:
    text = expand_portable_path(value)
    if not text:
        return False
    try:
        return Path(text).expanduser().exists()
    except Exception:
        return False


def _mark_asset_path(out: Dict[str, Any], key: str, value: str) -> None:
    text = expand_portable_path(value)
    if not text:
        return
    out[key] = text
    if key.endswith("_path") or key in {"gguf_path", "model_path"}:
        try:
            p = Path(text).expanduser()
            out[f"{key}__exists"] = p.exists()
            out[f"{key}__abs"] = str(p.resolve()) if p.exists() else os.path.abspath(text)
        except Exception:
            out[f"{key}__exists"] = False


def normalize_ltx23_asset_variant(assets: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
    """Keep Unsloth LTX 2.3 GGUF assets internally consistent.

    The UI can retain stale asset paths after the user switches files/profile.
    A particularly bad case is workflow_variant=distilled with the dev GGUF,
    dev connectors, and dev VAEs. That combination can run far enough to sample,
    but it produces NaN latents/garbage frames. Prefer a matching sibling file
    set from the same HF snapshot when it is present.
    """
    if not isinstance(assets, dict):
        assets = {}
    if not isinstance(settings, dict):
        settings = {}
    text = " ".join(
        str(settings.get(key) or assets.get(key) or "")
        for key in (
            "model_id",
            "model_family",
            "workflow_variant",
            "hf_source_repo_id",
            "hf_source_filename",
            "gguf_path",
        )
    ).lower()
    if "unsloth_ltx23_gguf" not in text and "ltx-2.3" not in text and "ltx-2.3-gguf" not in text:
        return assets

    out = dict(assets)
    variant = str(settings.get("workflow_variant") or "").strip().lower()
    gguf_text = str(out.get("gguf_path") or settings.get("gguf_path") or "").strip()
    if not gguf_text:
        gguf_text = str(settings.get("hf_source_filename") or "").strip()
    explicit_gguf_text = " ".join(
        str(value or "")
        for value in (
            out.get("gguf_path"),
            settings.get("gguf_path"),
            settings.get("hf_source_filename"),
        )
    ).lower()
    # The LTX 2.3 "dev base + distilled LoRA" workflow is easy to misclassify
    # because several companion files legitimately contain "distilled" in the
    # filename. The base GGUF filename is the authoritative variant signal; do
    # not let stale workflow_variant JSON or LoRA/upscaler names rewrite a dev
    # GGUF back to the distilled base.
    if "dev" in explicit_gguf_text and "distill" not in Path(str(gguf_text or explicit_gguf_text)).name.lower():
        variant = "dev"
        settings["workflow_variant"] = "dev"
    elif "distill" in explicit_gguf_text:
        variant = "distilled"
        settings["workflow_variant"] = "distilled"

    candidates: list[Path] = []
    if gguf_text:
        try:
            p = Path(gguf_text).expanduser()
            if p.exists():
                candidates.append(p)
            for parent in [p, *p.parents]:
                if parent.name == "snapshots":
                    break
                if (parent / "distilled-1.1").exists() or (parent / "text_encoders").exists() or (parent / "vae").exists():
                    candidates.append(parent)
        except Exception:
            pass
    for value in (
        out.get("embeddings_connectors_path"),
        out.get("video_vae_path"),
        out.get("audio_vae_path"),
        out.get("distilled_lora_path"),
        out.get("spatial_upscaler_path"),
        settings.get("distilled_lora_path"),
        settings.get("spatial_upscaler_path"),
    ):
        try:
            p = Path(str(value or "")).expanduser()
            if p.exists():
                candidates.extend([p.parent, p.parent.parent])
        except Exception:
            pass

    snapshot_roots: list[Path] = []
    for candidate in candidates:
        try:
            base = candidate if candidate.is_dir() else candidate.parent
            for parent in [base, *base.parents]:
                has_unsloth_assets = (parent / "text_encoders").exists() and (parent / "vae").exists()
                has_ltx_companion_assets = any(parent.glob("*distilled-lora*.safetensors")) or any(
                    parent.glob("*upscaler*.safetensors")
                )
                if has_unsloth_assets or has_ltx_companion_assets:
                    snapshot_roots.append(parent)
                    break
        except Exception:
            continue
    seen_roots: set[str] = set()
    snapshot_roots = [root for root in snapshot_roots if not (str(root) in seen_roots or seen_roots.add(str(root)))]

    def choose(patterns: list[str]) -> str:
        for root in snapshot_roots:
            for pattern in patterns:
                matches = sorted(root.glob(pattern))
                for match in matches:
                    if match.is_file():
                        return str(match)
        return ""

    if variant == "distilled":
        replacements = {
            "gguf_path": choose(["distilled-1.1/*distilled*.gguf", "**/*distilled*.gguf"]),
            "embeddings_connectors_path": choose(["text_encoders/*distilled*_embeddings_connectors.safetensors", "**/*distilled*_embeddings_connectors.safetensors"]),
            "video_vae_path": choose(["vae/*distilled*video_vae.safetensors", "**/*distilled*video_vae.safetensors"]),
            "audio_vae_path": choose(["vae/*distilled*audio_vae.safetensors", "**/*distilled*audio_vae.safetensors"]),
            "distilled_lora_path": choose([
                "*distilled-lora*1.1*.safetensors",
                "**/*distilled-lora*1.1*.safetensors",
                "*distilled-lora*.safetensors",
                "**/*distilled-lora*.safetensors",
            ]),
            "spatial_upscaler_path": choose([
                "*spatial-upscaler*x2*1.1*.safetensors",
                "**/*spatial-upscaler*x2*1.1*.safetensors",
                "*spatial-upscaler*.safetensors",
                "**/*spatial-upscaler*.safetensors",
            ]),
        }
    else:
        replacements = {
            "gguf_path": choose(["*dev*.gguf", "**/*dev*.gguf"]),
            "embeddings_connectors_path": choose(["text_encoders/*dev*_embeddings_connectors.safetensors", "**/*dev*_embeddings_connectors.safetensors"]),
            "video_vae_path": choose(["vae/*dev*video_vae.safetensors", "**/*dev*video_vae.safetensors"]),
            "audio_vae_path": choose(["vae/*dev*audio_vae.safetensors", "**/*dev*audio_vae.safetensors"]),
        }

    changed: list[str] = []
    for key, value in replacements.items():
        if key in {"distilled_lora_path", "spatial_upscaler_path"}:
            explicit = str(settings.get(key) or out.get(key) or "").strip()
            if explicit and _path_exists_text(explicit):
                _mark_asset_path(out, key, explicit)
                settings[key] = explicit
                continue
        if value and _path_exists_text(value) and str(out.get(key) or "") != value:
            _mark_asset_path(out, key, value)
            settings[key] = value
            changed.append(key)
    if changed:
        out["__variant_normalized"] = ",".join(changed)
        out["__variant"] = variant or ("distilled" if "distill" in explicit_gguf_text else "dev")
    return out


def lifecycle(params: Dict[str, Any], default: str = "lazy_unload") -> str:
    value = str((params or {}).get("lifecycle") or (params or {}).get("lifecycle_policy") or default).strip().lower()
    return value if value in {"lazy_unload", "lazy_persist", "preload_persist", "persist", "terminal"} else default


def settings_artifact(run: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    raw = dict_param(params, "settings")
    if raw:
        out.update(raw)
    stored = get_artifact(run, "settings", {})
    stored_request_source_image = ""
    stored_first_image = ""
    stored_last_image = ""
    stored_request_prompt = ""
    if isinstance(stored, dict):
        stored_first_image = str(stored.get("first_image_path") or stored.get("reference_image_1_path") or stored.get("ref_image_1_path") or "").strip()
        stored_last_image = str(stored.get("last_image_path") or stored.get("reference_image_2_path") or stored.get("ref_image_2_path") or stored.get("end_image_path") or "").strip()
        stored_request_source_image = str(stored.get("__request_source_image_path") or stored_first_image or "").strip()
        stored_request_prompt = str(stored.get("__request_prompt") or "").strip()
        out = {**stored, **out}
    if not stored_request_source_image:
        out.pop("__request_source_image_path", None)
    if not stored_request_prompt:
        out.pop("__request_prompt", None)
    try:
        print(
            "[model_workflow.settings] merge_start "
            f"run_id={str((run or {}).get('run_id') or '')!r} "
            f"raw_source={str(raw.get('__request_source_image_path') or raw.get('source_image_path') or '')!r} "
            f"stored_source={stored_request_source_image!r} "
            f"stored_first={stored_first_image!r} "
            f"stored_last={stored_last_image!r} "
            f"raw_prompt_len={len(str(raw.get('__request_prompt') or raw.get('prompt') or ''))} "
            f"stored_prompt_len={len(stored_request_prompt)}",
            flush=True,
        )
    except Exception:
        pass
    if stored_request_source_image:
        # Saved workflow node params can contain old one-off request fields from
        # a previous template/debug run. The run artifact is the live chat
        # request, so it must win over node params for request-only values.
        for key in (
            "__request_source_image_path",
            "source_image_path",
            "image_path",
            "input_image_path",
            "start_image_path",
            "reference_image_path",
            "first_image_path",
            "reference_image_1_path",
            "ref_image_1_path",
        ):
            out[key] = stored_request_source_image
    if stored_last_image:
        for key in (
            "last_image_path",
            "end_image_path",
            "target_image_path",
            "reference_image_2_path",
            "ref_image_2_path",
        ):
            out[key] = stored_last_image
    if stored_request_prompt:
        out["__request_prompt"] = stored_request_prompt
        out["prompt"] = stored_request_prompt
        out["positive_prompt"] = stored_request_prompt
        out["default_prompt"] = ""
        out["wan_optional_default_prompt"] = ""
        out["regression_test_note"] = ""
        out["use_default_when_blank"] = False
        out["wan_optional_use_default_when_blank"] = False
    explicit_run_overrides = _run_override_values(out)
    explicit_source_image_override = str(
        out.get("__request_source_image_path")
        or out.get("first_image_path")
        or out.get("reference_image_1_path")
        or out.get("ref_image_1_path")
        or ""
    ).strip()
    explicit_last_image_override = str(
        out.get("last_image_path")
        or out.get("reference_image_2_path")
        or out.get("ref_image_2_path")
        or out.get("end_image_path")
        or ""
    ).strip()
    explicit_request_prompt = str(out.get("__request_prompt") or "").strip()
    deck_settings, deck_model_id = _current_model_deck_video_default_settings()
    deck_default_flag = out.get("model_workflow_use_model_deck_default_assets")
    if deck_default_flag is None:
        deck_default_flag = out.get("use_model_deck_default_assets")
    use_deck_defaults = str("true" if deck_default_flag is None else deck_default_flag).strip().lower() not in {"0", "false", "no", "off"}
    deck_defaults_match = _model_deck_defaults_match_current_workflow(out, deck_settings)
    if deck_settings and use_deck_defaults and not deck_defaults_match:
        try:
            print(
                "[model_workflow.settings] skipped_model_deck_default_overlay "
                f"run_id={str((run or {}).get('run_id') or '')!r} "
                f"current_flow={str(out.get('model_workflow_flow_name') or '')!r} "
                f"deck_flow={str(deck_settings.get('model_workflow_flow_name') or '')!r} "
                f"current_compat={str(out.get('model_deck_compat_manifest_id') or out.get('tested_profile_id') or '')!r} "
                f"deck_compat={str(deck_settings.get('model_deck_compat_manifest_id') or deck_settings.get('tested_profile_id') or '')!r}",
                flush=True,
            )
        except Exception:
            pass
    if deck_settings and use_deck_defaults and deck_defaults_match:
        out = {**out, **deck_settings}
        strip_stale_workflow_identity(out)
        if deck_model_id:
            out["__model_deck_default_model_id"] = deck_model_id
        if explicit_run_overrides:
            out.update(explicit_run_overrides)
        if explicit_request_prompt:
            out["prompt"] = explicit_request_prompt
            out["positive_prompt"] = explicit_request_prompt
            out["__request_prompt"] = explicit_request_prompt
            out["default_prompt"] = ""
            out["wan_optional_default_prompt"] = ""
            out["use_default_when_blank"] = False
            out["wan_optional_use_default_when_blank"] = False
        if explicit_source_image_override:
            # Keep per-run I2V source image overrides authoritative over saved
            # Model Deck defaults. Otherwise service_chat/Agent Flow requests
            # can silently render an older source image selected in the edit UI.
            out["source_image_path"] = explicit_source_image_override
            out["image_path"] = explicit_source_image_override
            out["input_image_path"] = explicit_source_image_override
            out["start_image_path"] = explicit_source_image_override
            out["reference_image_path"] = explicit_source_image_override
            out["first_image_path"] = explicit_source_image_override
            out["reference_image_1_path"] = explicit_source_image_override
            out["ref_image_1_path"] = explicit_source_image_override
            out["__request_source_image_path"] = explicit_source_image_override
        if explicit_last_image_override:
            out["last_image_path"] = explicit_last_image_override
            out["end_image_path"] = explicit_last_image_override
            out["target_image_path"] = explicit_last_image_override
            out["reference_image_2_path"] = explicit_last_image_override
            out["ref_image_2_path"] = explicit_last_image_override
        # First-class Model Deck asset fields are authoritative over stale
        # nested preset/runtime JSON. A common edit flow is: user selects a new
        # LoRA/upscaler path in Model Deck, but an older saved workflow still
        # contains skip_lora/native_debug_skip_stage2=true in
        # video_runtime_params_json. If the user did not explicitly set the
        # top-level skip flags on the model, do not let those stale JSON booleans
        # disable the selected assets.
        lora_selected = _path_exists_text(deck_settings.get("distilled_lora_path"))
        if lora_selected:
            if "skip_lora" not in deck_settings:
                out["skip_lora"] = False
            if "native_skip_lora" not in deck_settings:
                out["native_skip_lora"] = False
        upscaler_selected = _path_exists_text(deck_settings.get("spatial_upscaler_path"))
        if upscaler_selected and "native_debug_skip_stage2" not in deck_settings:
            out["native_debug_skip_stage2"] = False
    allow_checkpoint_fallback = str(
        out.get("native_allow_checkpoint_runner_fallback")
        or out.get("native_checkpoint_runner_parity")
        or ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    if allow_checkpoint_fallback:
        for blob_key in ("video_runtime_template_json", "video_runtime_assets_json", "video_runtime_params_json"):
            raw_blob = out.get(blob_key)
            if not isinstance(raw_blob, str) or not raw_blob.strip().startswith("{"):
                continue
            try:
                blob = json.loads(raw_blob)
            except Exception:
                continue
            blob_backend = str(blob.get("workflow_execution_backend") or "").strip().lower()
            if blob_backend in {"ltx_checkpoint_runner", "checkpoint_runner"}:
                out["workflow_execution_backend"] = blob_backend
                break
    normalize_workflow_settings(out)
    try:
        diagnostics = run.setdefault("diagnostics", [])
        if isinstance(diagnostics, list):
            diagnostics.append({
                "node": "settings_artifact",
                "message": "model workflow settings merge",
                "run_id": str((run or {}).get("run_id") or ""),
                "raw_source_image_path": str(raw.get("__request_source_image_path") or raw.get("source_image_path") or ""),
                "stored_source_image_path": stored_request_source_image,
                "stored_first_image_path": stored_first_image,
                "stored_last_image_path": stored_last_image,
                "final_request_source_image_path": str(out.get("__request_source_image_path") or ""),
                "final_source_image_path": str(out.get("source_image_path") or ""),
                "final_first_image_path": str(out.get("reference_image_1_path") or out.get("first_image_path") or ""),
                "final_last_image_path": str(out.get("reference_image_2_path") or out.get("last_image_path") or ""),
                "raw_prompt_len": len(str(raw.get("__request_prompt") or raw.get("prompt") or "")),
                "stored_prompt_len": len(stored_request_prompt),
                "final_prompt_len": len(str(out.get("__request_prompt") or out.get("prompt") or "")),
                "final_default_prompt_len": len(str(out.get("default_prompt") or "")),
            })
    except Exception:
        pass
    try:
        print(
            "[model_workflow.settings] merge_done "
            f"run_id={str((run or {}).get('run_id') or '')!r} "
            f"request_source={str(out.get('__request_source_image_path') or '')!r} "
            f"source={str(out.get('source_image_path') or '')!r} "
            f"first={str(out.get('reference_image_1_path') or out.get('first_image_path') or '')!r} "
            f"last={str(out.get('reference_image_2_path') or out.get('last_image_path') or '')!r} "
            f"prompt_len={len(str(out.get('__request_prompt') or out.get('prompt') or ''))} "
            f"default_prompt_len={len(str(out.get('default_prompt') or ''))}",
            flush=True,
        )
    except Exception:
        pass
    if out:
        set_artifact(run, "settings", out)
    return out


def _current_model_deck_video_default_settings() -> tuple[Dict[str, Any], str]:
    """Return the saved Model Deck video_gen default model settings.

    Agent Flow model-workflow nodes intentionally carry a generic template so a
    workflow can be reused between models. The live Model Deck default must win
    over stale embedded flow copies; otherwise a cloned model can appear
    selected in the UI while the workflow still runs old asset paths.
    """
    try:
        deck_path = Path(__file__).resolve().parents[5] / "data" / "model_deck" / "deck.json"
        deck = json.loads(deck_path.read_text(encoding="utf-8"))
        video = (deck.get("types") or deck.get("model_types") or {}).get("video_gen")
        if not isinstance(video, dict):
            return {}, ""
        default_id = str(video.get("default_model_id") or "").strip()
        if not default_id:
            return {}, ""
        for model in video.get("models") or []:
            if not isinstance(model, dict):
                continue
            if str(model.get("model_id") or "").strip() != default_id:
                continue
            settings = dict(model.get("settings") or {})
            for key in MODEL_WORKFLOW_IDENTITY_KEYS:
                settings.pop(key, None)
            # Preserve top-level convenience mirrors used by the edit form.
            for key in (
                "device",
                "gpu_selection_mode",
                "main_gpu",
                "gemma_text_encoding_device",
                "workflow_loader_mode",
                "workflow_execution_backend",
                "native_transformer_offload",
                "native_gguf_execution_mode",
                "native_lazy_quantized_packed_device",
                "native_transformer_gpu_slots",
                "ltx_video_only",
                "native_skip_lora",
                "skip_lora",
                "native_normalize_stage1_latent",
                "native_stage1_latent_target_std",
                "ltx_stage1_sampler",
                "ltx_stage1_sigmas",
                "ltx_stage1_cfg",
                "ltx_stage2_sampler",
                "ltx_stage2_sigmas",
                "ltx_stage2_cfg",
                "ltx_crop_guides_enabled",
                "ltx_chunk_feedforward_chunks",
                "ltx_chunk_feedforward_dim_threshold",
                "ltx_distilled_lora_strength",
                "ltx_detailer_lora_path",
                "ltx_detailer_lora_strength",
                "ltx_vae_decode_tiling_mode",
                "ltx_vae_decode_tile_size",
                "ltx_vae_decode_overlap",
                "ltx_vae_decode_temporal_size",
                "ltx_vae_decode_temporal_overlap",
                "allow_eager_gemma_gpu",
                "enable_model_cpu_offload",
                "enable_sequential_cpu_offload",
            ):
                if model.get(key) not in (None, "", [], {}):
                    settings[key] = model.get(key)
            return settings, default_id
    except Exception:
        return {}, ""
    return {}, ""


def normalize_workflow_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize stale Model Deck workflow values before any node branches on them.

    Older saved LTX flows used workflow_model_loader + ltx_checkpoint_runner. That
    combination makes nodes 2-6 declare work and lets step 7 run the monolithic
    checkpoint subprocess. For workflow model loader, the backend must be the
    staged native graph so every node executes its own stage and passes handles
    forward.
    """
    if not isinstance(settings, dict):
        return {}
    mode = str(settings.get("workflow_loader_mode") or "").strip().lower()
    backend = str(settings.get("workflow_execution_backend") or "").strip().lower()
    if mode in {"", "checkpoint_runner"}:
        settings["workflow_loader_mode"] = "workflow_model_loader"
        mode = "workflow_model_loader"
    allow_checkpoint_fallback = str(
        settings.get("native_allow_checkpoint_runner_fallback")
        or settings.get("native_checkpoint_runner_parity")
        or ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    if mode == "workflow_model_loader" and backend in {"", "auto"}:
        settings["workflow_execution_backend"] = "native_graph"
    strip_stale_workflow_identity(settings)
    _normalize_ltx23_gpu_settings(settings)
    normalize_minimax_h3_settings(settings)
    normalize_ltx23_asset_variant(settings, settings)
    accepts_request_images = workflow_accepts_request_images(settings)
    if not accepts_request_images:
        clear_request_media_overrides(settings)
    else:
        clamp_request_media_overrides(settings)
    request_source_image = str(
        settings.get("__request_source_image_path")
        or settings.get("first_image_path")
        or settings.get("reference_image_1_path")
        or settings.get("ref_image_1_path")
        or ""
    ).strip()
    request_last_image = str(
        settings.get("last_image_path")
        or settings.get("reference_image_2_path")
        or settings.get("ref_image_2_path")
        or settings.get("end_image_path")
        or ""
    ).strip()
    request_prompt = str(settings.get("__request_prompt") or "").strip()
    if request_source_image:
        settings["__request_source_image_path"] = request_source_image
        settings["source_image_path"] = request_source_image
        settings["image_path"] = request_source_image
        settings["input_image_path"] = request_source_image
        settings["start_image_path"] = request_source_image
        settings["reference_image_path"] = request_source_image
        settings["first_image_path"] = request_source_image
        settings["reference_image_1_path"] = request_source_image
        settings["ref_image_1_path"] = request_source_image
    if request_last_image:
        settings["last_image_path"] = request_last_image
        settings["end_image_path"] = request_last_image
        settings["target_image_path"] = request_last_image
        settings["reference_image_2_path"] = request_last_image
        settings["ref_image_2_path"] = request_last_image
    if request_source_image or request_last_image:
        image_paths = [path for path in (request_source_image, request_last_image) if path]
        if image_paths:
            settings["image_paths"] = image_paths
            settings["input_image_paths"] = image_paths
            media_inputs = {"images": image_paths}
            if request_source_image:
                media_inputs["source_image_path"] = request_source_image
                media_inputs["first_image_path"] = request_source_image
            if request_last_image:
                media_inputs["last_image_path"] = request_last_image
            settings["workflow_media_inputs"] = media_inputs
    elif request_prompt:
        clear_request_media_overrides(settings)
    if request_prompt:
        settings["prompt"] = request_prompt
        settings["positive_prompt"] = request_prompt
        settings["default_prompt"] = ""
        settings["wan_optional_default_prompt"] = ""
        settings["regression_test_note"] = ""
        settings["use_default_when_blank"] = False
        settings["wan_optional_use_default_when_blank"] = False

    def _apply_request_overrides_to_runtime_blob(blob_key: str) -> None:
        raw_runtime = settings.get(blob_key)
        if not isinstance(raw_runtime, str) or not raw_runtime.strip():
            return
        try:
            runtime_params = json.loads(raw_runtime)
        except Exception:
            return
        if isinstance(runtime_params, dict):
            runtime_mode = str(runtime_params.get("workflow_loader_mode") or "").strip().lower()
            runtime_backend = str(runtime_params.get("workflow_execution_backend") or "").strip().lower()
            if runtime_mode in {"", "checkpoint_runner"}:
                runtime_params["workflow_loader_mode"] = "workflow_model_loader"
                runtime_mode = "workflow_model_loader"
            runtime_allow_checkpoint_fallback = str(
                runtime_params.get("native_allow_checkpoint_runner_fallback")
                or runtime_params.get("native_checkpoint_runner_parity")
                or allow_checkpoint_fallback
                or ""
            ).strip().lower() in {"1", "true", "yes", "on"}
            if runtime_mode == "workflow_model_loader" and runtime_backend in {"", "auto"}:
                runtime_params["workflow_execution_backend"] = "native_graph"
            elif (
                runtime_mode == "workflow_model_loader"
                and runtime_backend in {"ltx_checkpoint_runner", "checkpoint_runner"}
                and not runtime_allow_checkpoint_fallback
            ):
                runtime_params["workflow_execution_backend"] = "native_graph"
            _normalize_ltx23_gpu_settings(runtime_params)
            strip_stale_workflow_identity(runtime_params)
            normalize_minimax_h3_settings(runtime_params)
            if not accepts_request_images:
                for key in MODEL_WORKFLOW_MEDIA_OVERRIDE_KEYS:
                    runtime_params.pop(key, None)
            else:
                if request_source_image:
                    for key in (
                        "__request_source_image_path",
                        "source_image_path",
                        "image_path",
                        "input_image_path",
                        "start_image_path",
                        "reference_image_path",
                        "first_image_path",
                        "reference_image_1_path",
                        "ref_image_1_path",
                    ):
                        runtime_params[key] = request_source_image
                effective_last_image = request_last_image if workflow_request_image_limit(runtime_params) > 1 else ""
                if effective_last_image:
                    for key in (
                        "last_image_path",
                        "end_image_path",
                        "target_image_path",
                        "reference_image_2_path",
                        "ref_image_2_path",
                    ):
                        runtime_params[key] = effective_last_image
                if request_source_image or effective_last_image:
                    image_paths = [path for path in (request_source_image, effective_last_image) if path]
                    if image_paths:
                        runtime_params["image_paths"] = image_paths
                        runtime_params["input_image_paths"] = image_paths
                        media_inputs = {"images": image_paths}
                        if request_source_image:
                            media_inputs["source_image_path"] = request_source_image
                            media_inputs["first_image_path"] = request_source_image
                        if effective_last_image:
                            media_inputs["last_image_path"] = effective_last_image
                        runtime_params["workflow_media_inputs"] = media_inputs
                elif request_prompt:
                    for key in MODEL_WORKFLOW_MEDIA_OVERRIDE_KEYS:
                        runtime_params.pop(key, None)
                clamp_request_media_overrides(runtime_params)
            if request_prompt:
                runtime_params["__request_prompt"] = request_prompt
                runtime_params["prompt"] = request_prompt
                runtime_params["positive_prompt"] = request_prompt
                runtime_params["default_prompt"] = ""
                runtime_params["wan_optional_default_prompt"] = ""
                runtime_params["regression_test_note"] = ""
                runtime_params["use_default_when_blank"] = False
                runtime_params["wan_optional_use_default_when_blank"] = False
            settings[blob_key] = json.dumps(runtime_params, indent=2)

    for runtime_blob_key in ("video_runtime_params_json", "video_runtime_assets_json", "video_runtime_template_json"):
        _apply_request_overrides_to_runtime_blob(runtime_blob_key)
    return settings


def _normalize_ltx23_gpu_settings(settings: Dict[str, Any]) -> None:
    if not isinstance(settings, dict):
        return
    text = " ".join(
        str(settings.get(key) or "")
        for key in ("model_id", "model_family", "workflow_variant", "hf_source_repo_id", "hf_source_filename")
    ).lower()
    if "unsloth_ltx23_gguf" not in text and "ltx-2.3" not in text and "ltx-2.3-gguf" not in text:
        return
    # This tested workflow is meant to run the main video runtime on Intel XPU
    # when the saved UI state has gone stale. CPU here causes exactly the
    # behavior the user is seeing: Gemma and the LTX transformer materialize in
    # system RAM, then sampling fails or crawls.
    if str(settings.get("device") or "").strip().lower() in {"", "auto", "cpu"}:
        settings["device"] = "xpu"
    if str(settings.get("gpu_selection_mode") or "").strip().lower() in {"", "auto"}:
        settings["gpu_selection_mode"] = "single"
    if settings.get("main_gpu") in (None, ""):
        settings["main_gpu"] = 0
    if str(settings.get("gemma_text_encoding_device") or "").strip().lower() in {"", "auto"}:
        settings["gemma_text_encoding_device"] = "gpu"
    if str(settings.get("native_prompt_encoder_backend") or "").strip().lower() in {"", "auto"}:
        text_encoder_path = str(settings.get("text_encoder_safetensors_path") or "").strip().lower()
        projection_path = str(
            settings.get("text_encoder_projection_path")
            or settings.get("text_encoder_mmproj_path")
            or settings.get("embeddings_connectors_path")
            or ""
        ).strip()
        if text_encoder_path.endswith((".safetensors", ".sft")) and projection_path:
            settings["native_prompt_encoder_backend"] = "comfy_ltxav_safetensors"
    # Do not force GGUF models onto LTX block streaming here. The Unsloth LTX
    # AVTransformer GGUF needs ComfyUI-GGUF-style lazy quantized modules by
    # default; LTX block streaming expands dense per-block slots and can consume
    # the whole GPU/host memory even with one GPU slot. If a saved model/profile
    # explicitly chooses disk/cpu streaming, preserve that choice, but let the
    # runtime decide whether it is safe for the selected GGUF architecture.
    if str(settings.get("native_transformer_offload") or "").strip().lower() in {"", "auto"}:
        settings["native_transformer_offload"] = "none"
    if str(settings.get("native_gguf_execution_mode") or "").strip().lower() in {"", "auto"}:
        settings["native_gguf_execution_mode"] = "lazy_quantized"
    # The full AVTransformer branch is available, but it is very slow and
    # memory-heavy on a single Intel XPU. MP4 generation should default to
    # video-only and expose full AV as an explicit troubleshooting/quality
    # choice instead of silently consuming CPU RAM.
    ltx_video_only_value = settings.get("ltx_video_only")
    if str(ltx_video_only_value).strip().lower() in {"", "none", "auto"}:
        settings["ltx_video_only"] = "true"


def resolve_setting_reference(params: Dict[str, Any], settings: Dict[str, Any], param_key: str, default: Any = "") -> Any:
    direct = (params or {}).get(param_key)
    if direct not in (None, "", [], {}):
        return direct
    ref_key = str((params or {}).get(f"{param_key}_setting") or "").strip()
    if not ref_key and param_key == "device":
        ref_key = str((params or {}).get("device_setting") or "").strip()
    if ref_key:
        if isinstance(settings, dict) and settings.get(ref_key) not in (None, "", [], {}):
            return settings.get(ref_key)
        return default
    return default


def workflow_debug_dir(ctx: Dict[str, Any], run: Dict[str, Any]) -> Path:
    app = (ctx or {}).get("app")
    base = None
    state = getattr(app, "state", None)
    if state is not None:
        base = getattr(state, "workdir", None) or getattr(state, "data_dir", None)
    root = Path(str(base)).resolve() if base else workspace_root(ctx)
    raw_run_id = str(run.get("run_id") or f"run_{now_ms()}")
    safe_run_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_run_id).strip("._ ") or f"run_{now_ms()}"
    path = root / "tmp" / "model_workflow_debug" / safe_run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def flush_workflow_debug(ctx: Dict[str, Any], run: Dict[str, Any], *, label: str = "") -> str:
    debug_dir = workflow_debug_dir(ctx, run)
    payload = {
        "ok": True,
        "run_id": str(run.get("run_id") or ""),
        "label": str(label or ""),
        "updated_ms": now_ms(),
        "resource_snapshot": resource_snapshot(),
        "diagnostics": public_jsonable(run.get("diagnostics") or []),
        "artifacts": public_jsonable(run.get("artifacts") or {}),
    }
    latest = debug_dir / "latest.json"
    latest.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    stamped = debug_dir / f"run_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.json"
    stamped.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(latest)


def output_upload_path(ctx: Dict[str, Any], prefix: str = "video_gen", suffix: str = ".mp4") -> Path:
    app = (ctx or {}).get("app")
    base = None
    state = getattr(app, "state", None)
    if state is not None:
        base = getattr(state, "data_dir", None) or getattr(state, "workdir", None)
    root = Path(str(base)).resolve() if base else workspace_root(ctx) / "data"
    out_dir = root / "uploads"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{prefix}_{int(time.time())}{suffix}"


def resolve_python_bin(settings: Dict[str, Any]) -> str:
    # Keep this intentionally boring. The user explicitly asked us not to auto-discover
    # and rewrite python.exe paths after the venv launcher regression.
    return str((settings or {}).get("python_bin") or "python").strip() or "python"


def public_jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except Exception:
        if isinstance(value, dict):
            return {str(k): public_jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [public_jsonable(v) for v in value]
        return repr(value)


BASE_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string"},
        "node_id": {"type": "string"},
        "assets": {"type": "object"},
        "settings": {"type": "object"},
        "lifecycle": {"type": "string", "enum": ["lazy_unload", "lazy_persist", "preload_persist", "persist", "terminal"]},
        "wan_i2v_denoise_strength": {
            "type": ["number", "string"],
            "title": "Wan I2V denoise strength",
            "description": "Image-to-video source preservation control. 1.0 is full current denoise; lower values preserve the input image more and reduce texture drift.",
            "default": 0.90,
            "minimum": 0.05,
            "maximum": 1.0,
        },
        "wan_i2v_quality_profile_mode": {
            "type": "string",
            "title": "Wan I2V quality/memory auto profile",
            "description": "Calculate recommended source-halo and high/low sampler settings from clip length and detected VRAM. Off only uses the saved values. Recommend only logs the suggested values. Apply blank fills empty fields. Override replaces saved fields with the recommendation for this run.",
            "enum": ["off", "recommend_only", "apply_blank", "override"],
            "default": "off",
        },
        "wan_i2v_quality_auto_profile": {
            "type": ["boolean", "string"],
            "title": "Wan I2V auto profile legacy toggle",
            "description": "Legacy shortcut. When enabled and quality profile mode is off/blank, behaves like apply_blank.",
            "default": False,
        },
        "wan_i2v_high_noise_start_step": {
            "type": ["integer", "string"],
            "title": "Wan I2V high-noise start step",
            "description": "Optional advanced override. Leave blank to derive from denoise strength; higher values skip more early noise.",
            "default": 1,
        },
        "wan_i2v_low_noise_start_step": {
            "type": ["integer", "string"],
            "title": "Wan I2V low-noise start step",
            "description": "Optional advanced override for the low-noise pass. Leave blank for the normal high/low boundary.",
        },
        "wan_i2v_vae_encode_device": {
            "type": "string",
            "title": "Wan I2V source-image VAE encode device",
            "description": "Device used to encode the source image into Wan I2V conditioning. Auto follows the final VAE decode device, so GPU/chunked/full final decode also uses GPU source encode.",
            "enum": ["auto", "cpu", "gpu", "xpu"],
            "default": "auto",
        },
        "wan_i2v_vae_encode_dtype": {
            "type": "string",
            "title": "Wan I2V source-image VAE encode dtype",
            "enum": ["bfloat16", "float16", "float32"],
            "default": "bfloat16",
        },
        "wan_i2v_source_encode_mode": {
            "type": "string",
            "title": "Wan I2V source encode memory mode",
            "description": "How the source image is converted into Wan I2V concat conditioning. source_motion_burst keeps a short source anchor and releases the remaining concat latent so motion can start earlier. source_latent_hold encodes the source/hold frames once and repeats the source latent as a stable long anchor, which reduces moon/highlight/detail pumping. comfy_exact mirrors Comfy's WanImageToVideo and VAE-encodes a full video-length neutral tail. comfy_temporal_halo encodes the same tail in latent-time windows with halo overlap. masked_start_only encodes only the real source/hold frames and pads the masked tail.",
            "enum": ["source_motion_burst", "source_latent_hold", "masked_start_only", "comfy_temporal_halo", "comfy_exact"],
            "default": "source_motion_burst",
        },
        "wan_i2v_source_hold_frames": {
            "type": ["integer", "string"],
            "title": "Wan I2V source hold frames",
            "description": "How many initial video frames are directly seeded from the source image before the tail region begins. 1 keeps the first frame only; use 2+ for slower/stiffer movement.",
            "default": 1,
            "minimum": 1,
        },
        "wan_i2v_source_conditioning_frames": {
            "type": ["integer", "string"],
            "title": "Wan I2V source anchor frames",
            "description": "How many initial video frames keep source-image conditioning active. 2 is the current small-animation default: slower than a one-frame release but less frozen than long anchors.",
            "default": 2,
            "minimum": 1,
        },
        "wan_i2v_source_tail_mode": {
            "type": "string",
            "title": "Wan I2V source tail mode",
            "description": "Only used by temporal-halo source encode. neutral matches Comfy's stock WanImageToVideo tail. blend_source_to_neutral gradually weakens the source reference toward neutral to reduce long-clip grey collapse while still allowing motion.",
            "enum": ["neutral", "blend_source_to_neutral"],
            "default": "neutral",
        },
        "wan_i2v_source_tail_min_strength": {
            "type": ["number", "string"],
            "title": "Wan I2V source tail minimum strength",
            "description": "Only used when source tail mode is blend_source_to_neutral. Lower values allow more motion but can risk grey/blank drift on long clips; higher values preserve the source more strongly but can look frozen.",
            "default": 0.35,
            "minimum": 0,
            "maximum": 1,
        },
        "wan_i2v_source_tail_decay_power": {
            "type": ["number", "string"],
            "title": "Wan I2V source tail decay power",
            "description": "Only used by blend_source_to_neutral tail mode. Higher values decay the source influence faster, allowing earlier motion.",
            "default": 3.0,
            "minimum": 0.25,
            "maximum": 8,
        },
        "sampler_name": {
            "type": "string",
            "title": "Sampler",
            "description": "Comfy sampler used by supported model workflow nodes.",
            "enum": ["euler", "euler_ancestral", "heun", "dpm_2", "dpm_2_ancestral", "lms", "dpm_fast", "dpm_adaptive", "dpmpp_2s_ancestral", "dpmpp_sde", "dpmpp_2m", "dpmpp_2m_sde", "dpmpp_3m_sde", "ddim", "uni_pc", "lcm"],
            "default": "euler",
        },
        "scheduler": {
            "type": "string",
            "title": "Scheduler",
            "description": "Comfy scheduler used by supported sampler nodes.",
            "enum": ["simple", "normal", "karras", "exponential", "sgm_uniform", "ddim_uniform", "beta", "linear_quadratic", "kl_optimal"],
            "default": "simple",
        },
        "steps": {
            "type": ["integer", "string"],
            "title": "Sampler steps",
            "default": 12,
            "minimum": 1,
        },
        "high_noise_steps": {
            "type": ["integer", "string"],
            "title": "Wan high-noise steps",
            "default": 6,
            "minimum": 0,
        },
        "low_noise_steps": {
            "type": ["integer", "string"],
            "title": "Wan low-noise steps",
            "default": 6,
            "minimum": 1,
        },
        "guidance_scale": {
            "type": ["number", "string"],
            "title": "Guidance / CFG",
            "default": 2.0,
            "minimum": 0,
        },
        "high_noise_cfg": {
            "type": ["number", "string"],
            "title": "Wan high-noise CFG",
            "default": 2.0,
            "minimum": 0,
        },
        "low_noise_cfg": {
            "type": ["number", "string"],
            "title": "Wan low-noise CFG",
            "default": 1.25,
            "minimum": 0,
        },
        "wan_i2v_source_halo_core_latent_frames": {
            "type": ["integer", "string"],
            "title": "Source encode temporal halo: core latent frames",
            "description": "Only used when Wan I2V source encode memory mode is comfy_temporal_halo. Number of latent timesteps kept from each source-conditioning chunk. Larger values use fewer chunks and may be faster, but use more RAM/VRAM.",
            "default": 2,
            "minimum": 1,
        },
        "wan_i2v_source_halo_latent_frames": {
            "type": ["integer", "string"],
            "title": "Source encode temporal halo: overlap latent frames",
            "description": "Only used when Wan I2V source encode memory mode is comfy_temporal_halo. Extra latent timesteps of context added on both sides before cropping back to the core chunk.",
            "default": 1,
            "minimum": 0,
        },
        "wan_i2v_source_halo_max_window_latent_frames": {
            "type": ["integer", "string"],
            "title": "Source encode temporal halo: max window latent frames",
            "description": "Only used when Wan I2V source encode memory mode is comfy_temporal_halo. Maximum expanded latent window encoded at once. Lower saves memory; higher is closer to Comfy exact and can reduce color drift.",
            "default": 3,
            "minimum": 1,
        },
        "wan_i2v_source_encode_cleanup_each_stage": {
            "type": ["boolean", "string"],
            "title": "Wan I2V source encode cleanup after stage",
            "description": "Release temporary tensors and accelerator cache immediately after source VAE encode. Keep this on unless debugging.",
            "default": True,
        },
        "wan_i2v_resource_guard": {
            "type": ["boolean", "string"],
            "title": "Wan I2V source encode resource guard",
            "description": "Check system RAM and GPU/XPU memory before the I2V source-image VAE encode step. This prevents starting the heavy source-conditioning step when the machine is already near its limit.",
            "default": True,
        },
        "wan_i2v_resource_guard_action": {
            "type": "string",
            "title": "Wan I2V source encode guard action",
            "description": "What to do when a threshold is exceeded before source encode starts. fallback_cpu moves GPU source encode to CPU; fail stops early.",
            "enum": ["fallback_cpu", "fail", "warn"],
            "default": "fallback_cpu",
        },
        "wan_i2v_cpu_max_percent": {
            "type": ["number", "string"],
            "title": "Wan I2V CPU RAM max %",
            "description": "Do not start the I2V source encode when system RAM use is at or above this percentage. Keep this below 90 if you want the desktop responsive.",
            "default": 85,
            "minimum": 1,
            "maximum": 100,
        },
        "wan_i2v_gpu_max_percent": {
            "type": ["number", "string"],
            "title": "Wan I2V GPU VRAM max %",
            "description": "Do not start GPU/XPU source encode when accelerator memory use is at or above this percentage.",
            "default": 85,
            "minimum": 1,
            "maximum": 100,
        },
        "wan_i2v_min_cpu_available_mb": {
            "type": ["integer", "string"],
            "title": "Wan I2V minimum free system RAM MB",
            "description": "Optional free-RAM floor before source encode starts. 8192 keeps about 8GB free for the OS and browser.",
            "default": 8192,
            "minimum": 0,
        },
        "wan_i2v_min_gpu_free_mb": {
            "type": ["integer", "string"],
            "title": "Wan I2V minimum free GPU/XPU MB",
            "description": "Optional free-VRAM floor before GPU source encode starts.",
            "default": 4096,
            "minimum": 0,
        },
        "prompt_encoder_cache_mode": {
            "type": "string",
            "title": "Prompt encoder cache mode",
            "description": "Generic model workflow prompt-encoder lifecycle. Off unloads after prompt encoding. CPU keeps the encoder reusable in CPU/offload state while clearing VRAM. VRAM keeps it hot on the main device for fastest repeat prompts.",
            "enum": ["off", "cpu", "vram"],
            "default": "off",
        },
        "wan_prompt_encoder_persist": {
            "type": ["boolean", "string"],
            "title": "Wan prompt encoder keep loaded between runs (legacy)",
            "description": "Legacy boolean. Prefer Wan prompt encoder cache mode: off, cpu, or vram. True maps to vram when the explicit cache mode is empty.",
            "default": False,
        },
        "wan_prompt_encoder_cache_mode": {
            "type": "string",
            "title": "Wan prompt encoder cache mode",
            "description": "Controls what happens to the Wan UMT5/CLIP GGUF prompt encoder after prompt encoding. Off unloads it. CPU keeps a reusable offloaded cache while clearing accelerator memory. VRAM keeps it hot on the main device for the fastest repeat prompts but reserves about 7GB VRAM.",
            "enum": ["off", "cpu", "vram"],
            "default": "off",
        },
        "wan_vae_decode_mode": {
            "type": "string",
            "title": "Wan final VAE decode mode",
            "description": "Final Wan video VAE decode strategy. CPU safe is cleanest but slow/high-RAM. GPU chunked is faster but can show temporal seams. GPU temporal halo keeps extra context around each chunk and spatially tiles it to reduce seams.",
            "enum": ["cpu_safe", "gpu_chunked_safe", "gpu_temporal_halo", "gpu_full_preferred", "gpu_full"],
            "default": "gpu_temporal_halo",
        },
        "wan_vae_decode_device": {
            "type": "string",
            "title": "Wan final VAE decode device",
            "description": "Device used for the final video VAE decode. Use GPU with temporal halo for speed, CPU safe for comparison/reference quality.",
            "enum": ["cpu", "gpu", "xpu"],
            "default": "gpu",
        },
        "wan_vae_halo_core_latent_frames": {
            "type": ["integer", "string"],
            "title": "Wan VAE halo core latent frames",
            "description": "How many latent timesteps are kept from each temporal-halo decode window. 2 preserves Wan's temporal expansion while staying smaller than full decode.",
            "default": 2,
            "minimum": 2,
        },
        "wan_vae_halo_auto_profile": {
            "type": ["boolean", "string"],
            "title": "Wan VAE halo auto profile",
            "description": "When enabled, choose temporal-halo VAE chunk/window/tile settings from detected GPU VRAM unless the user explicitly fills those fields.",
            "default": False,
        },
        "wan_vae_halo_core_overlap_latent_frames": {
            "type": ["integer", "string"],
            "title": "Wan VAE halo core overlap",
            "description": "Core-window latent overlap. Keep this at 1 so consecutive core chunks stitch without missing expanded frames.",
            "default": 1,
            "minimum": 1,
        },
        "wan_vae_halo_latent_frames": {
            "type": ["integer", "string"],
            "title": "Wan VAE temporal halo latent frames",
            "description": "Extra latent timesteps decoded before/after each core chunk, then cropped away. This gives kept frames temporal context and reduces lighting/grid seams.",
            "default": 1,
            "minimum": 0,
        },
        "wan_vae_halo_max_window_latent_frames": {
            "type": ["integer", "string"],
            "title": "Wan VAE halo max window",
            "description": "Largest expanded latent window allowed on GPU. 4 is quality-first; lower it to 3 if XPU runs out of resources.",
            "default": 4,
            "minimum": 2,
        },
        "wan_vae_halo_spatial_tiled": {
            "type": ["boolean", "string"],
            "title": "Wan VAE halo spatial tiling",
            "description": "Spatially tile each temporal-halo window on GPU while preserving the temporal window. This is different from temporal tiling and is meant to reduce VRAM without adding time seams.",
            "default": True,
        },
        "wan_vae_halo_tile_size": {
            "type": ["integer", "string"],
            "title": "Wan VAE halo tile size",
            "default": 256,
            "minimum": 64,
        },
        "wan_vae_halo_tile_overlap": {
            "type": ["integer", "string"],
            "title": "Wan VAE halo tile overlap",
            "default": 64,
            "minimum": 0,
        },
        "wan_vae_halo_cpu_fallback": {
            "type": ["boolean", "string"],
            "title": "Wan VAE halo CPU fallback",
            "description": "If the GPU temporal-halo VAE decode runs out of resources, automatically finish the decode on CPU/full mode instead of failing the workflow.",
            "default": True,
        },
        "wan_luminance_stabilize": {
            "type": ["boolean", "string"],
            "title": "Wan output luminance stabilization",
            "description": "Normalize small frame-to-frame exposure drift after VAE decode and before MP4 encoding. Useful when temporal-halo decode removes grid collapse but frames still alternate or ramp light/dark.",
            "default": False,
        },
        "wan_luminance_strength": {
            "type": ["number", "string"],
            "title": "Wan luminance stabilization strength",
            "description": "How strongly each frame is pulled toward the target luminance. 0 disables correction, 1 fully applies the clamped correction.",
            "default": 0.85,
            "minimum": 0,
            "maximum": 1,
        },
        "wan_luminance_min_gain": {
            "type": ["number", "string"],
            "title": "Wan luminance minimum gain",
            "description": "Lower clamp for per-frame exposure correction.",
            "default": 0.90,
            "minimum": 0.5,
            "maximum": 1,
        },
        "wan_luminance_max_gain": {
            "type": ["number", "string"],
            "title": "Wan luminance maximum gain",
            "description": "Upper clamp for per-frame exposure correction.",
            "default": 1.12,
            "minimum": 1,
            "maximum": 2,
        },
        "wan_luminance_stabilize_threshold": {
            "type": ["number", "string"],
            "title": "Wan luminance stabilization threshold",
            "description": "Skip stabilization if measured frame brightness range is already below this 0-255 threshold.",
            "default": 1.0,
            "minimum": 0,
        },
        "wan_video_temporal_denoise": {
            "type": ["boolean", "string"],
            "title": "Wan post-VAE temporal denoise",
            "description": "Apply a lightweight motion-aware temporal denoise after VAE decode and before MP4 encoding. This can reduce moving grain without changing the sampler.",
            "default": False,
        },
        "wan_video_temporal_denoise_strength": {
            "type": ["number", "string"],
            "title": "Wan temporal denoise strength",
            "description": "Blend strength for post-VAE temporal denoise. Start around 0.18-0.28; higher values can smear motion.",
            "default": 0.22,
            "minimum": 0,
            "maximum": 0.75,
        },
        "wan_video_temporal_denoise_radius": {
            "type": ["integer", "string"],
            "title": "Wan temporal denoise radius",
            "description": "Number of neighboring frames on each side. 1 is safest; 2 is stronger but can ghost.",
            "default": 1,
            "minimum": 1,
            "maximum": 2,
        },
        "wan_video_temporal_denoise_motion_gate": {
            "type": ["number", "string"],
            "title": "Wan temporal denoise motion gate",
            "description": "Per-pixel motion threshold. Lower preserves moving details; higher denoises more aggressively.",
            "default": 0.075,
            "minimum": 0.005,
            "maximum": 0.5,
        },
        "wan_i2v_source_hold_frames": {
            "type": ["integer", "string"],
            "title": "Wan I2V source hold frames",
            "description": "Repeat the source image for the first N conditioning frames before WanImageToVideo. Higher values preserve subject identity longer but reduce motion freedom.",
            "default": 1,
            "minimum": 1,
        },
        "wan_output_frame_resample": {
            "type": ["boolean", "string"],
            "title": "Wan output frame resample",
            "description": "When false, keep the exact decoded frame count instead of nearest-neighbor expanding to output_frames.",
            "default": True,
        },
        "wan_apply_stage_lora": {
            "type": ["boolean", "string"],
            "title": "Wan apply stage LoRA",
            "description": "Apply the matching HighNoise/LowNoise LoRA immediately after each Wan GGUF stage loads, matching the ComfyUI Power Lora Loader placement.",
            "default": True,
        },
        "wan_stage_lora_stock_loader": {
            "type": ["boolean", "string"],
            "title": "Wan stage LoRA stock loader",
            "description": "Use ComfyUI's stock load_lora_for_models path for stage LoRAs. Disable only if a profile provides a custom LoRA node handler.",
            "default": True,
        },
        "wan_stage_lora_strength": {
            "type": ["number", "string"],
            "title": "Wan stage LoRA strength",
            "description": "Default strength for both HighNoise and LowNoise stage LoRAs when role-specific strengths are blank.",
            "default": 1.0,
        },
        "high_noise_lora_strength": {
            "type": ["number", "string"],
            "title": "Wan HighNoise LoRA strength",
            "default": 1.0,
        },
        "low_noise_lora_strength": {
            "type": ["number", "string"],
            "title": "Wan LowNoise LoRA strength",
            "default": 1.0,
        },
        "wan_stage_lora_mismatch_fallback": {
            "type": ["boolean", "string"],
            "title": "Wan skip mismatched stage LoRA",
            "description": "If enabled, a LoRA load failure is logged and the run continues without that LoRA. Keep disabled for real quality tests so mismatched assets fail loudly.",
            "default": False,
        },
    },
    "additionalProperties": True,
}
