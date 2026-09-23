from __future__ import annotations

from typing import Any, Dict

try:
    from ._comfyui_gguf_bridge import load_state_dict_handle, probe as probe_comfyui_gguf
    from ._ltx_native_graph_runtime import build_transformer_resource
    from ._model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_artifact, get_run, lifecycle, mark_workflow_failed, model_workflow_state, public_jsonable, resolve_setting_reference, set_artifact, settings_artifact, skipped_for_failed_workflow
except Exception:
    from _comfyui_gguf_bridge import load_state_dict_handle, probe as probe_comfyui_gguf
    from _ltx_native_graph_runtime import build_transformer_resource
    from _model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_artifact, get_run, lifecycle, mark_workflow_failed, model_workflow_state, public_jsonable, resolve_setting_reference, set_artifact, settings_artifact, skipped_for_failed_workflow


NAME = "models.gguf_transformer_loader"
PERMISSIONS = ["models.gguf_transformer_loader", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "gguf_transformer_loader")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    assets = get_artifact(row, "assets", {})
    gguf_path = str((params or {}).get("gguf_path") or assets.get("gguf_path") or "").strip()
    loader = str((params or {}).get("loader") or "comfyui_gguf").strip()
    policy = lifecycle(params or {}, default="lazy_persist")
    settings = settings_artifact(row, params or {})
    device = str(resolve_setting_reference(params or {}, settings if isinstance(settings, dict) else {}, "device", default="auto") or "auto").strip()
    backend = str((settings if isinstance(settings, dict) else {}).get("workflow_execution_backend") or "").strip().lower()
    if backend in {"native_graph", "native_comfyui_gguf", "ltx_native_graph", "model_graph"}:
        diagnostics = row.setdefault("diagnostics", [])
        try:
            add_diag(row, node_id, "native LTX transformer load starting", workflow_device=str((settings if isinstance(settings, dict) else {}).get("device") or ""), gguf_path=gguf_path)
            flush_workflow_debug(ctx or {}, row, label=f"{node_id}_before")
            resource = build_transformer_resource(assets if isinstance(assets, dict) else {}, settings if isinstance(settings, dict) else {}, diagnostics)
            resource_key = f"{row.get('run_id')}:video_transformer"
            resources = model_workflow_state(ctx or {}).setdefault("resources", {})
            resources[resource_key] = resource
            handle = {
                "kind": "gguf_transformer",
                "loader": "ltx_native_graph",
                "gguf_path": gguf_path,
                "device": str(resource.get("device") or device),
                "dtype": str(resource.get("dtype") or ""),
                "lifecycle": policy,
                "quantized_runtime": True,
                "resource_key": resource_key,
                "loaded_tensor_count": 0,
                "has_audio": bool(resource.get("has_audio")),
                "offload": str(resource.get("offload") or "none"),
                "status": "loaded",
            }
            set_artifact(row, "video_transformer", handle)
            add_diag(row, node_id, "loaded native LTX GGUF transformer builder", device=handle["device"], offload=handle["offload"], has_audio=handle["has_audio"])
            log_file = flush_workflow_debug(ctx or {}, row, label=f"{node_id}_after")
            return {"ok": True, "run_id": row.get("run_id"), "status": "loaded", "video_transformer": handle, "data": {"status": "loaded", "video_transformer": handle, "log_file": log_file}, "warnings": []}
        except Exception as exc:
            mark_workflow_failed(row, node_id, exc, warning="native_transformer_load_failed")
            add_diag(row, node_id, "native LTX GGUF transformer load failed", error=str(exc))
            log_file = flush_workflow_debug(ctx or {}, row, label=f"{node_id}_failed")
            return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": str(exc), "data": {"status": "failed", "error": str(exc), "diagnostics": diagnostics, "log_file": log_file}, "warnings": ["native_transformer_load_failed"]}
    vendor_root = str((settings if isinstance(settings, dict) else {}).get("comfyui_gguf_vendor_root") or r"C:/Users/Tee/projects/llmloader2/vendor/ComfyUI-GGUF")
    comfyui_root = str((settings if isinstance(settings, dict) else {}).get("comfyui_runtime_root") or "")
    bridge = probe_comfyui_gguf(vendor_root, comfyui_root=comfyui_root) if loader == "comfyui_gguf" else {"available": False, "reason": "not_comfyui_gguf_loader"}
    resource_key = ""
    loaded_tensor_count = 0
    if bridge.get("available") and policy == "preload_persist" and gguf_path:
        loaded = load_state_dict_handle(gguf_path, vendor_root=vendor_root, comfyui_root=comfyui_root, is_text_model=False)
        if loaded.get("ok"):
            resource_key = f"{row.get('run_id')}:video_transformer_state_dict"
            resources = model_workflow_state(ctx or {}).setdefault("resources", {})
            resources[resource_key] = {
                "kind": "comfyui_gguf_state_dict",
                "state_dict": loaded.get("state_dict"),
                "extra": loaded.get("extra"),
                "gguf_path": gguf_path,
                "loader": loader,
            }
            loaded_tensor_count = int(loaded.get("tensor_count") or 0)
    handle = {
        "kind": "gguf_transformer",
        "loader": loader,
        "gguf_path": gguf_path,
        "device": device,
        "lifecycle": policy,
        "quantized_runtime": bool(bridge.get("available")),
        "resource_key": resource_key,
        "loaded_tensor_count": loaded_tensor_count,
        "comfyui_gguf": {
            "state_dict_loader": "loader.gguf_sd_loader",
            "ops": "ops.GGMLOps",
            "tensor_wrapper": "ops.GGMLTensor",
            "patcher": "nodes.GGUFModelPatcher",
            "bridge": public_jsonable(bridge),
        },
        "status": "preloaded" if resource_key else "declared",
    }
    set_artifact(row, "video_transformer", handle)
    add_diag(
        row,
        node_id,
        "declared GGUF transformer load",
        loader=loader,
        device=device,
        lifecycle=policy,
        quantized_runtime=bool(bridge.get("available")),
        bridge_reason=str(bridge.get("reason") or ""),
        loaded_tensor_count=loaded_tensor_count or None,
    )
    warnings = [] if gguf_path else ["missing_gguf_path"]
    if loader == "comfyui_gguf" and not bridge.get("available"):
        warnings.append(f"comfyui_gguf_bridge_unavailable:{bridge.get('reason')}")
    return {"ok": bool(gguf_path), "run_id": row.get("run_id"), "status": handle["status"], "video_transformer": handle, "data": {"status": handle["status"], "video_transformer": handle}, "warnings": warnings}


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: GGUF Transformer Loader",
    "description": "Load or declare a quant-aware GGUF transformer node using ComfyUI-GGUF style tensors.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
