from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

try:
    from ._model_workflow_common import (
        BASE_PARAMS_SCHEMA,
        add_diag,
        flush_workflow_debug,
        get_artifact,
        get_run,
        mark_workflow_failed,
        resource_snapshot,
        set_artifact,
        settings_artifact,
        skipped_for_failed_workflow,
    )
except Exception:
    from _model_workflow_common import (
        BASE_PARAMS_SCHEMA,
        add_diag,
        flush_workflow_debug,
        get_artifact,
        get_run,
        mark_workflow_failed,
        resource_snapshot,
        set_artifact,
        settings_artifact,
        skipped_for_failed_workflow,
    )


NAME = "models.wan22_i2v_source_prepare"
PERMISSIONS = ["models.wan22_i2v_source_prepare", "models.*"]


def _int_setting(settings: Dict[str, Any], key: str, default: int) -> int:
    try:
        return int(float(settings.get(key) or default))
    except Exception:
        return int(default)


def _bool_setting(settings: Dict[str, Any], key: str, default: bool) -> bool:
    value = settings.get(key)
    if value is None or value == "":
        return bool(default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _asset_text(assets: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = assets.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _prepare_source_image(source_path: str, out_path: Path, settings: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from PIL import Image, ImageOps  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"Wan I2V source preparation requires pillow: {exc}") from exc

    src = Path(source_path).expanduser()
    if not src.exists():
        raise FileNotFoundError(f"missing Wan I2V source image: {source_path}")

    img = Image.open(src)
    img = ImageOps.exif_transpose(img).convert("RGB")
    original_size = img.size

    shortest_side = _int_setting(settings, "source_image_resize_shortest_side", 0)
    if shortest_side > 0:
        w, h = img.size
        scale = float(shortest_side) / float(max(1, min(w, h)))
        new_w = max(2, int(round((w * scale) / 2.0) * 2))
        new_h = max(2, int(round((h * scale) / 2.0) * 2))
        resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        img = img.resize((new_w, new_h), resample=resample)

    fit_to_output = _bool_setting(settings, "wan_i2v_prepare_source_to_output_size", True)
    target_w = _int_setting(settings, "width", _int_setting(settings, "output_width", 0))
    target_h = _int_setting(settings, "height", _int_setting(settings, "output_height", 0))
    if fit_to_output and target_w > 0 and target_h > 0 and img.size != (target_w, target_h):
        # Comfy's WanImageToVideo ultimately upscales/crops the source tensor to
        # the latent size before VAE encoding.  Doing this while the image is
        # still a PIL image avoids carrying a large source tensor into the VAE
        # node, which was causing 50-60GB RAM spikes before XPU was used.
        target_w = max(16, int(round(target_w / 16.0) * 16))
        target_h = max(16, int(round(target_h / 16.0) * 16))
        resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        img = ImageOps.fit(img, (target_w, target_h), method=resample, centering=(0.5, 0.5))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG", optimize=True)
    prepared_size = img.size
    img.close()

    return {
        "source_image_path": str(src.resolve()),
        "prepared_source_image_path": str(out_path.resolve()),
        "original_width": original_size[0],
        "original_height": original_size[1],
        "prepared_width": prepared_size[0],
        "prepared_height": prepared_size[1],
        "resize_shortest_side": shortest_side,
        "fit_to_output": fit_to_output,
        "target_width": target_w,
        "target_height": target_h,
    }


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "wan22_i2v_source_prepare")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped

    settings = settings_artifact(row, params or {})
    assets = get_artifact(row, "assets", {}) or {}
    diagnostics = row.setdefault("diagnostics", [])

    try:
        before_snapshot = resource_snapshot()
        add_diag(row, node_id, "resource snapshot before Wan I2V source prepare", resource_snapshot=before_snapshot)
        request_source_path = _asset_text(settings if isinstance(settings, dict) else {}, "__request_source_image_path")
        source_path = request_source_path or _asset_text(assets if isinstance(assets, dict) else {}, "source_image_path", "image_path", "start_image_path", "input_image_path")
        add_diag(
            row,
            node_id,
            "Wan I2V source selection",
            request_source_image_path=request_source_path,
            selected_source_image_path=source_path,
            asset_source_image_path=str((assets if isinstance(assets, dict) else {}).get("source_image_path") or ""),
            asset_image_path=str((assets if isinstance(assets, dict) else {}).get("image_path") or ""),
            settings_source_image_path=str((settings if isinstance(settings, dict) else {}).get("source_image_path") or ""),
        )
        if not source_path:
            raise FileNotFoundError("missing Wan I2V source_image_path before source prepare")
        source_path_norm = str(source_path).replace("\\", "/").lower()
        if not request_source_path and (
            "/.codex/generated_images/" in source_path_norm
            or "/data/model_sources/" in source_path_norm
        ):
            raise FileNotFoundError(
                "missing live Wan I2V request source image; refusing to use saved generated/model source image"
            )

        debug_root = Path("tmp") / "model_workflow_debug" / str(row.get("run_id") or "unknown")
        out_path = debug_root / "wan_i2v_prepared_source.png"
        prepared = _prepare_source_image(source_path, out_path, settings if isinstance(settings, dict) else {})

        new_assets = dict(assets) if isinstance(assets, dict) else {}
        new_assets["original_source_image_path"] = prepared["source_image_path"]
        new_assets["prepared_source_image_path"] = prepared["prepared_source_image_path"]
        # The next WanImageToVideo node can consume the prepared file directly.
        new_assets["source_image_path"] = prepared["prepared_source_image_path"]
        set_artifact(row, "assets", new_assets)
        set_artifact(row, "wan_i2v_source_image", {"kind": "wan22_i2v_prepared_source_image", **prepared, "status": "prepared"})
        add_diag(row, node_id, "prepared Wan I2V source image as standalone node", **prepared, resource_snapshot=resource_snapshot())
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {
            "ok": True,
            "run_id": row.get("run_id"),
            "status": "executed",
            "source_image": {"kind": "wan22_i2v_prepared_source_image", **prepared, "status": "prepared"},
            "data": {"status": "executed", "source_image": prepared, "log_file": log_file},
            "warnings": [],
        }
    except Exception as exc:
        mark_workflow_failed(row, node_id, exc, warning="wan22_i2v_source_prepare_failed")
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {
            "ok": False,
            "run_id": row.get("run_id"),
            "status": "failed",
            "error": str(exc),
            "data": {"status": "failed", "error": str(exc), "diagnostics": diagnostics, "log_file": log_file},
            "warnings": ["wan22_i2v_source_prepare_failed"],
        }


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Wan2.2 I2V Source Prepare",
    "description": "Prepare and resize the Wan2.2 I2V source image in its own node before VAE source conditioning.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
