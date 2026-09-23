from __future__ import annotations

import traceback
from typing import Any, Dict

try:
    from ._ltx_native_graph_runtime import encode_prompt_resource
    from ._model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_artifact, get_run, lifecycle, mark_workflow_failed, model_workflow_state, resolve_setting_reference, settings_artifact, set_artifact
except Exception:
    from _ltx_native_graph_runtime import encode_prompt_resource
    from _model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_artifact, get_run, lifecycle, mark_workflow_failed, model_workflow_state, resolve_setting_reference, settings_artifact, set_artifact


NAME = "models.ltx_prompt_encoder"
PERMISSIONS = ["models.ltx_prompt_encoder", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "ltx_prompt_encoder")
    assets = get_artifact(row, "assets", {})
    settings = settings_artifact(row, params or {})
    prompt = str((params or {}).get("prompt") or "").strip()
    text_device = str(
        (params or {}).get("text_device")
        or resolve_setting_reference(params or {}, settings, "device", default="cpu")
        or "cpu"
    ).strip().lower() or "cpu"
    policy = lifecycle(params or {})
    backend = str(settings.get("workflow_execution_backend") or "").strip().lower()
    if backend in {"native_graph", "native_comfyui_gguf", "ltx_native_graph", "model_graph"}:
        diagnostics = row.setdefault("diagnostics", [])
        resources = model_workflow_state(ctx or {}).setdefault("resources", {})
        transformer_key = str((get_artifact(row, "video_transformer", {}) or {}).get("resource_key") or "").strip()
        transformer_resource = resources.get(transformer_key) if transformer_key else None
        add_diag(
            row,
            node_id,
            "native LTX prompt encoding device request",
            gemma_setting=str(settings.get("gemma_text_encoding_device") or ""),
            workflow_device=str(settings.get("device") or ""),
            param_text_device=str((params or {}).get("text_device") or ""),
        )
        flush_workflow_debug(ctx or {}, row, label=f"{node_id}_before")
        def progress(label: str) -> None:
            add_diag(row, node_id, f"native LTX prompt encoding progress: {label}")
            flush_workflow_debug(ctx or {}, row, label=f"{node_id}_{label}")

        try:
            prompt_resource = encode_prompt_resource(assets, settings, params or {}, transformer_resource, diagnostics, progress=progress)
            resource_key = f"{row.get('run_id')}:prompt_context"
            resources[resource_key] = prompt_resource
            encoded_prompt = str(prompt_resource.get("prompt") or prompt or "").strip()
            context = {
                "kind": "ltx_prompt_context",
                "prompt": encoded_prompt,
                "clean_prompt": encoded_prompt,
                "raw_prompt": prompt,
                "negative_prompt": str((params or {}).get("negative_prompt") or ""),
                "text_encoder_safetensors_path": assets.get("text_encoder_safetensors_path"),
                "text_encoder_tokenizer_gguf_path": assets.get("text_encoder_tokenizer_gguf_path"),
                "text_encoder_gguf_path": assets.get("text_encoder_gguf_path"),
                "text_encoder_mmproj_path": assets.get("text_encoder_mmproj_path"),
                "embeddings_connectors_path": assets.get("embeddings_connectors_path"),
                "device": str(prompt_resource.get("text_device") or text_device),
                "runtime_device": str(prompt_resource.get("device") or ""),
                "lifecycle": policy,
                "resource_key": resource_key,
                "status": "executed",
            }
            set_artifact(row, "prompt_context", context)
            add_diag(row, node_id, "executed native LTX prompt encoding", device=context["device"], runtime_device=context["runtime_device"])
            log_file = flush_workflow_debug(ctx or {}, row, label=f"{node_id}_after")
            return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "prompt_context": context, "data": {"status": "executed", "prompt_context": context, "log_file": log_file}, "warnings": []}
        except Exception as exc:
            mark_workflow_failed(row, node_id, exc, warning="native_prompt_encode_failed")
            add_diag(row, node_id, "native LTX prompt encoding failed", error=str(exc), traceback=traceback.format_exc(limit=30))
            log_file = flush_workflow_debug(ctx or {}, row, label=f"{node_id}_failed")
            return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": str(exc), "data": {"status": "failed", "error": str(exc), "diagnostics": diagnostics, "log_file": log_file}, "warnings": ["native_prompt_encode_failed"]}
    context = {
        "kind": "ltx_prompt_context",
        "prompt": prompt,
        "negative_prompt": str((params or {}).get("negative_prompt") or ""),
        "text_encoder_safetensors_path": assets.get("text_encoder_safetensors_path"),
        "text_encoder_tokenizer_gguf_path": assets.get("text_encoder_tokenizer_gguf_path"),
        "text_encoder_gguf_path": assets.get("text_encoder_gguf_path"),
        "text_encoder_mmproj_path": assets.get("text_encoder_mmproj_path"),
        "embeddings_connectors_path": assets.get("embeddings_connectors_path"),
        "device": text_device,
        "lifecycle": policy,
        "status": "declared",
    }
    set_artifact(row, "prompt_context", context)
    add_diag(row, node_id, "declared LTX prompt encoding step", device=text_device, lifecycle=policy)
    log_file = flush_workflow_debug(ctx or {}, row, label=f"{node_id}_declared")
    return {"ok": True, "run_id": row.get("run_id"), "status": "declared", "prompt_context": context, "data": {"status": "declared", "prompt_context": context, "log_file": log_file}, "warnings": []}


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: LTX Prompt Encoder",
    "description": "Declare or execute the Gemma/MMProj prompt encoding stage for LTX workflows.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
