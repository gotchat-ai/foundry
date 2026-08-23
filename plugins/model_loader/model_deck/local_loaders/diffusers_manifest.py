from __future__ import annotations

import importlib
import inspect
from typing import Any, Callable, Dict, Optional

from fastapi import HTTPException


def resolve_manifest(manifest_mod: Any, *, type_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    try:
        matched = manifest_mod.match_manifest(
            type_id,
            dict(settings or {}),
            str(settings.get("model_deck_compat_manifest_id") or "").strip(),
        )
    except Exception:
        matched = None
    loader: Dict[str, Any] = {}
    if isinstance(matched, dict):
        matched_loader = matched.get("diffusers_loader")
        if isinstance(matched_loader, dict):
            loader = dict(matched_loader)
    pipeline_override = str(settings.get("diffusers_pipeline_class") or "").strip()
    transformer_override = str(settings.get("diffusers_transformer_class") or "").strip()
    manifest_pipeline = str(loader.get("pipeline_class") or "").strip()
    generic_pipeline_overrides = {"DiffusionPipeline", "AutoPipelineForText2Image"}
    if pipeline_override and not (
        loader
        and pipeline_override in generic_pipeline_overrides
        and manifest_pipeline
        and manifest_pipeline not in generic_pipeline_overrides
    ):
        loader["pipeline_class"] = pipeline_override
    if transformer_override:
        loader["transformer_class"] = transformer_override
    if loader:
        return loader
    if not pipeline_override or not transformer_override:
        return {}
    gguf_path = str(settings.get("gguf_path") or "").strip()
    return {
        "pipeline_class": pipeline_override,
        "pipeline_module": "diffusers",
        "pipeline_load_method": "from_pretrained",
        "pipeline_source_setting": "model_id",
        "pipeline_inject_key": "transformer",
        "transformer_class": transformer_override,
        "transformer_module": "diffusers",
        "transformer_load_method": "from_single_file" if gguf_path else "from_pretrained",
        "transformer_source_setting": "gguf_path" if gguf_path else "model_id",
        "transformer_subfolder": "" if gguf_path else "transformer",
    }


def resolve_runtime_profile(manifest_mod: Any, *, type_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    try:
        matched = manifest_mod.match_manifest(
            type_id,
            dict(settings or {}),
            str(settings.get("model_deck_compat_manifest_id") or "").strip(),
        )
    except Exception:
        matched = None
    if not isinstance(matched, dict):
        return {}
    runtime_profile = matched.get("runtime_profile")
    return dict(runtime_profile) if isinstance(runtime_profile, dict) else {}


def import_symbol(module_name: str, class_name: str) -> Any:
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise HTTPException(500, f"failed to import module {module_name}: {exc}") from exc
    try:
        return getattr(module, class_name)
    except AttributeError as exc:
        raise HTTPException(500, f"module {module_name} does not export {class_name}") from exc


def filter_kwargs(fn: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    try:
        sig = inspect.signature(fn)
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            return kwargs
        allowed = {k for k in sig.parameters.keys()}
        return {k: v for k, v in kwargs.items() if k in allowed}
    except Exception:
        return kwargs


def collect_setting_kwargs(spec_rows: Any, settings: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not isinstance(spec_rows, list):
        return out
    for row in spec_rows:
        if not isinstance(row, dict):
            continue
        setting_name = str(row.get("setting") or "").strip()
        kw_name = str(row.get("kw") or setting_name).strip()
        if not setting_name or not kw_name:
            continue
        value = settings.get(setting_name)
        if value in (None, ""):
            continue
        transform = str(row.get("transform") or "").strip().lower()
        if transform == "bool":
            value = bool(value)
        elif transform == "int":
            try:
                value = int(value)
            except Exception:
                continue
        elif transform == "float":
            try:
                value = float(value)
            except Exception:
                continue
        out[kw_name] = value
    return out


def _resolve_torch_dtype_alias(value: Any, *, fallback: Any = None) -> Any:
    text = str(value or "").strip().lower()
    if not text or text == "auto":
        return fallback
    try:
        import torch
    except Exception:
        return fallback
    if text == "fp16":
        return torch.float16
    if text == "bf16":
        return torch.bfloat16
    if text == "fp32":
        return torch.float32
    return fallback


def collect_setting_kwargs_runtime(spec_rows: Any, settings: Dict[str, Any], *, torch_dtype: Any, compute_dtype: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not isinstance(spec_rows, list):
        return out
    for row in spec_rows:
        if not isinstance(row, dict):
            continue
        setting_name = str(row.get("setting") or "").strip()
        kw_name = str(row.get("kw") or setting_name).strip()
        if not setting_name or not kw_name:
            continue
        value = settings.get(setting_name)
        if value in (None, ""):
            continue
        transform = str(row.get("transform") or "").strip().lower()
        if transform == "bool":
            value = bool(value)
        elif transform == "int":
            try:
                value = int(value)
            except Exception:
                continue
        elif transform == "float":
            try:
                value = float(value)
            except Exception:
                continue
        elif transform == "torch_dtype":
            value = _resolve_torch_dtype_alias(value, fallback=torch_dtype)
            if value is None:
                continue
        elif transform == "compute_dtype":
            value = compute_dtype
        out[kw_name] = value
    return out


def _runtime_enabled(component: Dict[str, Any], settings: Dict[str, Any]) -> bool:
    setting_name = str(component.get("enabled_setting") or "").strip()
    if not setting_name:
        return True
    expected = component.get("enabled_equals")
    value = settings.get(setting_name)
    if expected is None:
        return bool(value)
    return str(value) == str(expected)


def _runtime_source(component: Dict[str, Any], settings: Dict[str, Any], resolve_source: Callable[[str], str]) -> str:
    source_key = str(component.get("source_setting") or "").strip()
    source = settings.get(source_key) if source_key else None
    source = str(source or component.get("source_default") or "").strip()
    if not source:
        return ""
    load_method = str(component.get("load_method") or "from_pretrained").strip()
    if load_method == "from_single_file":
        return resolve_source(source)
    return source


def build_pipeline_from_runtime_profile(
    *,
    runtime_profile: Dict[str, Any],
    settings: Dict[str, Any],
    torch_dtype: Any,
    hf_token: str,
    compute_dtype: Any,
    apply_token_kwargs: Callable[[Any, Dict[str, Any], str], Dict[str, Any]],
    resolve_source: Callable[[str], str],
) -> Optional[Any]:
    if str(runtime_profile.get("kind") or "").strip().lower() != "diffusers_components":
        return None
    components = runtime_profile.get("components")
    if not isinstance(components, list) or not components:
        return None
    pipeline_spec = None
    loaded: Dict[str, Any] = {}
    pending = []
    for component in components:
        if not isinstance(component, dict):
            continue
        role = str(component.get("role") or "").strip().lower()
        if role == "pipeline":
            pipeline_spec = component
        else:
            pending.append(component)
    if not isinstance(pipeline_spec, dict):
        return None

    for component in pending:
        if not _runtime_enabled(component, settings):
            continue
        class_name = str(component.get("class") or "").strip()
        module_name = str(component.get("module") or "diffusers").strip() or "diffusers"
        comp_id = str(component.get("id") or component.get("role") or class_name).strip()
        if not class_name or not comp_id:
            continue
        cls = import_symbol(module_name, class_name)
        load_method = str(component.get("load_method") or "from_pretrained").strip()
        loader = getattr(cls, load_method, None)
        if not callable(loader):
            raise HTTPException(500, f"{class_name}.{load_method} is not callable")
        source = _runtime_source(component, settings, resolve_source)
        if not source:
            continue
        kwargs: Dict[str, Any] = {}
        dtype_mode = str(component.get("torch_dtype_mode") or "torch").strip().lower()
        if dtype_mode == "torch":
            kwargs["torch_dtype"] = torch_dtype
        elif dtype_mode == "compute":
            kwargs["torch_dtype"] = compute_dtype
        elif dtype_mode == "none":
            pass
        subfolder = str(settings.get(str(component.get("subfolder_setting") or "").strip()) or component.get("subfolder_default") or "").strip()
        if subfolder and load_method != "from_single_file":
            kwargs["subfolder"] = subfolder
        quant_class_name = str(component.get("quantization_class") or "").strip()
        if quant_class_name:
            quant_module_name = str(component.get("quantization_module") or module_name).strip() or module_name
            quant_class = import_symbol(quant_module_name, quant_class_name)
            kwargs["quantization_config"] = quant_class(compute_dtype=compute_dtype)
        static_kwargs = component.get("static_kwargs")
        if isinstance(static_kwargs, dict):
            kwargs.update(static_kwargs)
        kwargs.update(collect_setting_kwargs_runtime(component.get("kwargs_from_settings"), settings, torch_dtype=torch_dtype, compute_dtype=compute_dtype))
        kwargs = filter_kwargs(loader, kwargs)
        apply_token_kwargs(loader, kwargs, hf_token)
        loaded[comp_id] = loader(source, **kwargs)

    pipeline_class_name = str(pipeline_spec.get("class") or "").strip()
    pipeline_module = str(pipeline_spec.get("module") or "diffusers").strip() or "diffusers"
    if not pipeline_class_name:
        return None
    pipeline_class = import_symbol(pipeline_module, pipeline_class_name)
    pipeline_load_method = str(pipeline_spec.get("load_method") or "from_pretrained").strip()
    pipeline_loader = getattr(pipeline_class, pipeline_load_method, None)
    if not callable(pipeline_loader):
        raise HTTPException(500, f"{pipeline_class_name}.{pipeline_load_method} is not callable")
    pipeline_source = _runtime_source(pipeline_spec, settings, resolve_source)
    if not pipeline_source:
        raise HTTPException(400, f"Missing pipeline source for {pipeline_class_name}")
    pipeline_kwargs: Dict[str, Any] = {"torch_dtype": torch_dtype}
    inject_rows = pipeline_spec.get("inject")
    if isinstance(inject_rows, list):
        for row in inject_rows:
            if not isinstance(row, dict):
                continue
            component_id = str(row.get("component") or "").strip()
            kw_name = str(row.get("kw") or component_id).strip()
            if not component_id or not kw_name or component_id not in loaded:
                continue
            pipeline_kwargs[kw_name] = loaded[component_id]
    else:
        for component in pending:
            if not isinstance(component, dict):
                continue
            component_id = str(component.get("id") or component.get("role") or "").strip()
            kw_name = str(component.get("pipeline_arg") or "").strip()
            if component_id and kw_name and component_id in loaded:
                pipeline_kwargs[kw_name] = loaded[component_id]
    static_pipeline_kwargs = pipeline_spec.get("static_kwargs")
    if isinstance(static_pipeline_kwargs, dict):
        pipeline_kwargs.update(static_pipeline_kwargs)
    pipeline_kwargs.update(collect_setting_kwargs_runtime(pipeline_spec.get("kwargs_from_settings"), settings, torch_dtype=torch_dtype, compute_dtype=compute_dtype))
    pipeline_kwargs = filter_kwargs(pipeline_loader, pipeline_kwargs)
    apply_token_kwargs(pipeline_loader, pipeline_kwargs, hf_token)
    return pipeline_loader(pipeline_source, **pipeline_kwargs)


def build_transformer_and_pipeline(
    *,
    loader_spec: Dict[str, Any],
    settings: Dict[str, Any],
    torch_dtype: Any,
    hf_token: str,
    compute_dtype: Any,
    apply_token_kwargs: Callable[[Any, Dict[str, Any], str], Dict[str, Any]],
    resolve_source: Callable[[str], str],
) -> Optional[Any]:
    transformer_class_name = str(loader_spec.get("transformer_class") or "").strip()
    pipeline_class_name = str(loader_spec.get("pipeline_class") or "").strip()
    if not transformer_class_name or not pipeline_class_name:
        return None

    transformer_module = str(loader_spec.get("transformer_module") or "diffusers").strip() or "diffusers"
    pipeline_module = str(loader_spec.get("pipeline_module") or "diffusers").strip() or "diffusers"
    transformer_class = import_symbol(transformer_module, transformer_class_name)
    pipeline_class = import_symbol(pipeline_module, pipeline_class_name)

    transformer_load_method = str(loader_spec.get("transformer_load_method") or "from_pretrained").strip()
    pipeline_load_method = str(loader_spec.get("pipeline_load_method") or "from_pretrained").strip()
    transformer_loader = getattr(transformer_class, transformer_load_method, None)
    pipeline_loader = getattr(pipeline_class, pipeline_load_method, None)
    if not callable(transformer_loader):
        raise HTTPException(500, f"{transformer_class_name}.{transformer_load_method} is not callable")
    if not callable(pipeline_loader):
        raise HTTPException(500, f"{pipeline_class_name}.{pipeline_load_method} is not callable")

    transformer_source_key = str(loader_spec.get("transformer_source_setting") or "").strip()
    transformer_source = settings.get(transformer_source_key) if transformer_source_key else None
    transformer_source = str(transformer_source or loader_spec.get("transformer_source_default") or "").strip()
    if not transformer_source:
        return None
    if transformer_load_method == "from_single_file":
        transformer_source = resolve_source(transformer_source)

    transformer_kwargs: Dict[str, Any] = {"torch_dtype": torch_dtype}
    subfolder = str(loader_spec.get("transformer_subfolder") or "").strip()
    if subfolder and transformer_load_method != "from_single_file":
        transformer_kwargs["subfolder"] = subfolder
    static_transformer_kwargs = loader_spec.get("transformer_static_kwargs")
    if isinstance(static_transformer_kwargs, dict):
        transformer_kwargs.update(static_transformer_kwargs)
    quant_class_name = str(loader_spec.get("transformer_quantization_class") or "").strip()
    if quant_class_name:
        quant_module_name = str(loader_spec.get("transformer_quantization_module") or transformer_module).strip() or transformer_module
        quant_class = import_symbol(quant_module_name, quant_class_name)
        transformer_kwargs["quantization_config"] = quant_class(compute_dtype=compute_dtype)
    transformer_kwargs.update(collect_setting_kwargs(loader_spec.get("transformer_kwargs_from_settings"), settings))
    transformer_kwargs = filter_kwargs(transformer_loader, transformer_kwargs)
    apply_token_kwargs(transformer_loader, transformer_kwargs, hf_token)
    transformer = transformer_loader(transformer_source, **transformer_kwargs)

    pipeline_source_key = str(loader_spec.get("pipeline_source_setting") or "").strip()
    pipeline_source = settings.get(pipeline_source_key) if pipeline_source_key else None
    pipeline_source = str(pipeline_source or loader_spec.get("pipeline_source_default") or settings.get("model_id") or "").strip()
    if not pipeline_source:
        raise HTTPException(400, f"Missing pipeline source for {pipeline_class_name}")
    pipeline_kwargs: Dict[str, Any] = {"torch_dtype": torch_dtype}
    inject_key = str(loader_spec.get("pipeline_inject_key") or "transformer").strip() or "transformer"
    pipeline_kwargs[inject_key] = transformer
    pipeline_kwargs.update(collect_setting_kwargs(loader_spec.get("pipeline_kwargs_from_settings"), settings))
    pipeline_kwargs = filter_kwargs(pipeline_loader, pipeline_kwargs)
    apply_token_kwargs(pipeline_loader, pipeline_kwargs, hf_token)
    return pipeline_loader(pipeline_source, **pipeline_kwargs)
