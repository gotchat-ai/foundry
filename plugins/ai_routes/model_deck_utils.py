from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, Callable, List
import asyncio
import inspect
import json
import multiprocessing
import os
import traceback
import time
import urllib.error
import urllib.parse
import urllib.request
from runtime_cuda import empty_accelerator_cache
from plugins.gui_helpers._framework.services import get_plugin_service


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".wmv"}


def _is_workflow_model_loader_settings(info: Dict[str, Any], model_settings: Dict[str, Any]) -> bool:
    fields = dict(info or {})
    fields.update(model_settings or {})
    mode_values = {
        str(fields.get("workflow_loader_mode") or "").strip().lower(),
        str(fields.get("model_workflow_mode") or "").strip().lower(),
        str(fields.get("execution_mode") or "").strip().lower(),
        str(fields.get("backend_mode") or "").strip().lower(),
    }
    return (
        "workflow_model_loader" in mode_values
        or bool(str(fields.get("workflow_model_loader_id") or "").strip())
        or bool(str(fields.get("model_workflow_flow_name") or "").strip())
    )


def _http_json(method: str, url: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str], timeout_s: float) -> Dict[str, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method.upper())
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        if v is not None:
            req.add_header(str(k), str(v))
    try:
        with urllib.request.urlopen(req, timeout=max(1.0, float(timeout_s or 1.0))) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"http {exc.code}: {raw[:500]}") from exc
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {"data": parsed}


def _request_headers_for_agent_flow(settings: Dict[str, Any]) -> Dict[str, str]:
    raw = dict((settings or {}).get("__request_headers") or {})
    out: Dict[str, str] = {}
    for key in ("authorization", "x-auth-token", "x-admin-auth", "cookie"):
        value = raw.get(key) or raw.get(key.title())
        if value:
            out[key] = str(value)
    enabled = raw.get("x-gui-enabled-plugins") or raw.get("X-Gui-Enabled-Plugins") or ""
    parts = [p.strip() for p in str(enabled or "").split(",") if p.strip()]
    for required in ("agent_flow", "model_deck", "collab_chat"):
        if required not in parts:
            parts.append(required)
    out["X-Gui-Enabled-Plugins"] = ",".join(parts)
    return out


def _is_loopback_host(host: str) -> bool:
    parsed = urllib.parse.urlparse(f"//{host}" if "://" not in host else host)
    name = (parsed.hostname or host).strip().lower().strip("[]")
    return name in {"127.0.0.1", "localhost", "0.0.0.0", "::1", "host.docker.internal"}


def _setting_url(settings: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str((settings or {}).get(key) or os.environ.get(key.upper()) or "").strip()
        if value:
            return value
    return ""


def _agent_flow_base_url(settings: Dict[str, Any]) -> str:
    explicit = _setting_url(
        settings,
        "agent_flow_internal_base_url",
        "llmloader2_internal_base_url",
        "gotchat_internal_base_url",
    )
    if explicit:
        return explicit.rstrip("/")

    headers = dict((settings or {}).get("__request_headers") or {})
    host = str(headers.get("host") or headers.get("Host") or "").strip()
    if host and _is_loopback_host(host):
        proto = str(headers.get("x-forwarded-proto") or headers.get("X-Forwarded-Proto") or "http").split(",", 1)[0].strip() or "http"
        if proto not in {"http", "https"}:
            proto = "http"
        return f"{proto}://{host}"

    port = (
        str((settings or {}).get("server_port") or "").strip()
        or str((settings or {}).get("app_port") or "").strip()
        or os.environ.get("LLMLOADER2_PORT")
        or os.environ.get("PORT")
        or "8000"
    )
    return f"http://127.0.0.1:{port}"


def _find_media_result(value: Any, suffixes: Tuple[str, ...]) -> str:
    seen: set[int] = set()

    def walk(obj: Any) -> str:
        oid = id(obj)
        if oid in seen:
            return ""
        seen.add(oid)
        if isinstance(obj, str):
            text = obj.strip()
            low = text.lower().split("?", 1)[0]
            return text if any(low.endswith(s) for s in suffixes) else ""
        if isinstance(obj, dict):
            preferred = (
                "output_path",
                "out_path",
                "video_path",
                "image_path",
                "path",
                "url",
                "video_url",
                "image_url",
                "output",
            )
            for key in preferred:
                if key in obj:
                    found = walk(obj.get(key))
                    if found:
                        return found
            for item in obj.values():
                found = walk(item)
                if found:
                    return found
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                found = walk(item)
                if found:
                    return found
        return ""

    return walk(value)


def _uploads_url_for_path(path_or_url: str) -> str:
    text = str(path_or_url or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme in {"http", "https"} or text.startswith("/uploads/"):
        return text
    return f"/uploads/{os.path.basename(text)}"


def _workflow_flow_name(model_settings: Dict[str, Any]) -> str:
    for key in ("model_workflow_flow_name", "workflow_flow_name", "agent_flow_active_flow", "flow_name"):
        value = str((model_settings or {}).get(key) or "").strip()
        if value:
            return value
    for key in ("video_runtime_params_json", "video_runtime_assets_json", "video_runtime_template_json", "image_runtime_params_json", "image_runtime_assets_json"):
        raw = (model_settings or {}).get(key)
        if isinstance(raw, dict):
            nested = dict(raw)
        else:
            try:
                nested = json.loads(str(raw or ""))
            except Exception:
                nested = {}
        if not isinstance(nested, dict):
            continue
        for nested_key in ("model_workflow_flow_name", "workflow_flow_name", "agent_flow_active_flow", "flow_name", "template_flow_name"):
            value = str(nested.get(nested_key) or "").strip()
            if value:
                return value
    workflow_id = str((model_settings or {}).get("workflow_id") or "").strip()
    loader_id = str((model_settings or {}).get("workflow_model_loader_id") or "").strip()
    family = str((model_settings or {}).get("model_family") or "").strip()
    compat = str((model_settings or {}).get("model_deck_compat_manifest_id") or "").strip()
    if workflow_id == "unsloth_ltx23_gguf" or loader_id == "models.unsloth_ltx23_gguf" or family == "unsloth_ltx23_gguf" or compat == "unsloth_ltx_workflow":
        return "Models / Unsloth LTX 2.3 GGUF"
    return ""


def _settings_identity_compatible(base: Dict[str, Any], overlay: Dict[str, Any]) -> bool:
    if not isinstance(base, dict) or not isinstance(overlay, dict) or not overlay:
        return True
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
        base_key = pair[0]
        overlay_key = pair[-1]
        base_value = str((base or {}).get(base_key) or "").strip().lower()
        overlay_value = str((overlay or {}).get(overlay_key) or "").strip().lower()
        if base_value and overlay_value and base_value != overlay_value:
            return False
    return True


def _prefer_image_to_video_flow(flow_name: str, model_settings: Dict[str, Any], source_image: str) -> str:
    if not str(source_image or "").strip():
        return flow_name
    fields = " ".join(
        str((model_settings or {}).get(key) or "")
        for key in (
            "model_id",
            "model_family",
            "workflow_variant",
            "workflow_id",
            "workflow_model_loader_id",
            "model_deck_compat_manifest_id",
            "model_workflow_flow_name",
            "model_workflow_template_flow_name",
        )
    ).lower()
    current = str(flow_name or "").strip()
    current_low = current.lower()
    if "i2v" in current_low or "image-to-video" in current_low or "image_to_video" in current_low:
        return current
    if "wan2.2" in fields or "wan22" in fields or "wan_2.2" in fields:
        return "Models / Wan2.2 I2V GGUF"
    if "hunyuan" in fields and ("1.5" in fields or "15" in fields):
        return "Models / HunyuanVideo 1.5 I2V GGUF"
    return current


def _load_model_workflow_blueprint_flows(settings: Dict[str, Any], model_settings: Dict[str, Any], flow_name: str) -> Dict[str, Any]:
    app = get_server_app(settings, (settings or {}).get("__model_loader_registry"))
    base = None
    if app is not None:
        base = getattr(app.state, "data_dir", None) or getattr(app.state, "workdir", None)
    if not base:
        base = os.path.join(os.getcwd(), "data")
    root = os.path.join(str(base), "generated", "workflow_blueprints")
    if not os.path.isdir(root):
        return {}
    wanted_names = {
        str(flow_name or "").strip(),
        str((model_settings or {}).get("model_workflow_flow_name") or "").strip(),
    }
    wanted_names = {x for x in wanted_names if x}
    wanted_ids = {
        str((model_settings or {}).get("workflow_id") or "").strip(),
        str((model_settings or {}).get("model_workflow_id") or "").strip(),
        str((model_settings or {}).get("agent_flow_default_workflow_id") or "").strip(),
        str((model_settings or {}).get("workflow_model_loader_id") or "").strip(),
    }
    wanted_ids = {x for x in wanted_ids if x}
    workflow_fields = " ".join(
        str((model_settings or {}).get(key) or "")
        for key in (
            "workflow_id",
            "workflow_model_loader_id",
            "model_workflow_id",
            "agent_flow_default_workflow_id",
            "model_workflow_flow_name",
            "model_workflow_template_flow_name",
            "model_family",
            "model_deck_compat_manifest_id",
        )
    ).lower()
    if "ltx" in workflow_fields or "unsloth_ltx" in workflow_fields:
        wanted_names.add("Models / Unsloth LTX 2.3 GGUF")
        wanted_ids.update({"models.unsloth_ltx23_gguf", "unsloth_ltx23_gguf"})
    default_flow_path = os.path.join(str(base), "projects", "agent_flow", "default.json")
    if os.path.isfile(default_flow_path):
        try:
            with open(default_flow_path, "r", encoding="utf-8") as fh:
                default_doc = json.load(fh)
        except Exception:
            default_doc = {}
        default_flows = default_doc.get("flows") if isinstance(default_doc, dict) else None
        if isinstance(default_flows, dict):
            for wanted_name in wanted_names:
                flow_def = default_flows.get(wanted_name)
                if isinstance(flow_def, dict):
                    return {wanted_name: dict(flow_def)}
            for candidate_name, flow_def in default_flows.items():
                if not isinstance(flow_def, dict):
                    continue
                wf_id = str(flow_def.get("workflow_id") or flow_def.get("id") or "").strip()
                if wf_id and wf_id in wanted_ids:
                    return {str(candidate_name): dict(flow_def)}
    matches: List[Tuple[float, Dict[str, Any]]] = []
    try:
        entries = list(os.scandir(root))
    except Exception:
        return {}
    for entry in entries:
        if not entry.is_dir():
            continue
        manifest_path = os.path.join(entry.path, "agent_flow_manifest.json")
        if not os.path.isfile(manifest_path):
            continue
        try:
            with open(manifest_path, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
        except Exception:
            continue
        workflow_file = str(manifest.get("workflow_file") or "").strip()
        if not workflow_file:
            continue
        flow_path = os.path.join(entry.path, workflow_file)
        if not os.path.isfile(flow_path):
            continue
        try:
            with open(flow_path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception:
            continue
        flows = doc.get("flows") if isinstance(doc, dict) else None
        if not isinstance(flows, dict) or not flows:
            continue
        score = 0.0
        names = {str(manifest.get("root_flow") or "").strip(), *[str(x or "").strip() for x in (manifest.get("flow_names") or [])]}
        names.update(str(k or "").strip() for k in flows.keys())
        names = {x for x in names if x}
        if names & wanted_names:
            score += 10.0
        for flow_def in flows.values():
            if not isinstance(flow_def, dict):
                continue
            wf_id = str(flow_def.get("workflow_id") or flow_def.get("id") or "").strip()
            if wf_id in wanted_ids:
                score += 5.0
        lower_name = entry.name.lower()
        if "ltx" in lower_name and "unsloth" in " ".join(wanted_ids).lower():
            score += 1.0
        if score > 0:
            try:
                score += os.path.getmtime(flow_path) / 10000000000.0
            except Exception:
                pass
            matches.append((score, flows))
    if not matches:
        return {}
    flows = dict(sorted(matches, key=lambda item: item[0], reverse=True)[0][1])
    if not flows:
        return {}
    source_flow = None
    for name in (flow_name, *flows.keys()):
        if str(name or "").strip() in flows and isinstance(flows.get(str(name or "").strip()), dict):
            source_flow = dict(flows[str(name or "").strip()])
            break
    if source_flow is None:
        first = next(iter(flows.values()))
        source_flow = dict(first) if isinstance(first, dict) else {}
    if source_flow:
        for alias in wanted_names:
            flows.setdefault(alias, dict(source_flow))
    return flows


def _run_agent_flow_model_workflow(
    *,
    settings: Dict[str, Any],
    model_settings: Dict[str, Any],
    model_type: str,
    prompt: str,
    params: Dict[str, Any],
    suffixes: Tuple[str, ...],
    timeout_s: int,
    progress_callback: Optional[Any] = None,
    cancel_cb: Optional[Any] = None,
) -> Dict[str, Any]:
    pid = str((settings or {}).get("__pid") or "").strip()
    sid = str((settings or {}).get("__sid") or "").strip()
    if not pid or not sid:
        return {"ok": False, "error": "agent_flow_session_missing"}
    headers = _request_headers_for_agent_flow(settings)
    base_url = _agent_flow_base_url(settings).rstrip("/")
    safe_pid = urllib.parse.quote(pid, safe="")
    safe_sid = urllib.parse.quote(sid, safe="")
    workflow_settings = dict(model_settings or {})
    workflow_settings.update({k: v for k, v in (params or {}).items() if v not in (None, "")})
    if prompt:
        workflow_settings["prompt"] = prompt
        workflow_settings["positive_prompt"] = prompt
        workflow_settings["__request_prompt"] = prompt
        workflow_settings["use_default_when_blank"] = False
        workflow_settings["wan_optional_use_default_when_blank"] = False
    if "model_workflow_use_model_deck_default_assets" not in workflow_settings:
        workflow_settings["model_workflow_use_model_deck_default_assets"] = model_type != "image_gen"
    if "use_model_deck_default_assets" not in workflow_settings:
        workflow_settings["use_model_deck_default_assets"] = model_type != "image_gen"
    workflow_assets: Dict[str, Any] = {}
    media_keys = {
        "input_image_paths",
        "image_paths",
        "source_image_path",
        "first_image_path",
        "input_image_path",
        "init_image_path",
        "reference_image_path",
        "last_image_path",
        "target_image_path",
        "end_image_path",
        "input_video_paths",
        "video_paths",
        "source_video_path",
        "first_video_path",
        "input_video_path",
        "init_video_path",
        "reference_video_path",
        "last_video_path",
        "target_video_path",
        "end_video_path",
        "workflow_media_inputs",
    }
    for key in media_keys:
        value = (params or {}).get(key)
        if value not in (None, "", [], {}):
            workflow_assets[key] = value
    request_source_image = str(
        (params or {}).get("source_image_path")
        or (params or {}).get("input_image_path")
        or (params or {}).get("image_path")
        or ""
    ).strip()
    source_image = request_source_image
    if source_image:
        flow_name = _prefer_image_to_video_flow(_workflow_flow_name(workflow_settings), workflow_settings, source_image)
        workflow_settings["model_workflow_flow_name"] = flow_name
        workflow_settings["model_workflow_template_flow_name"] = flow_name
        workflow_settings["source_image_path"] = source_image
        workflow_settings["input_image_path"] = source_image
        workflow_settings["image_path"] = source_image
        workflow_assets["source_image_path"] = source_image
        workflow_assets["input_image_path"] = source_image
        workflow_assets["image_path"] = source_image
        if request_source_image:
            workflow_settings["__request_source_image_path"] = request_source_image
            workflow_assets["__request_source_image_path"] = request_source_image
        try:
            print(
                "[model_workflow] using source image "
                f"flow={flow_name!r} source_image={source_image!r} request_source={bool(request_source_image)} prompt_len={len(prompt or '')}",
                flush=True,
            )
        except Exception:
            pass
    else:
        flow_name = _workflow_flow_name(workflow_settings)
    if not flow_name:
        return {"ok": False, "error": "workflow_flow_name_missing"}
    if (
        not request_source_image
        and ("i2v" in str(flow_name or "").lower() or "image-to-video" in str(flow_name or "").lower())
        and bool((settings or {}).get("__pid"))
        and bool((settings or {}).get("__sid"))
    ):
        return {
            "ok": False,
            "error": "i2v_source_image_missing: no uploaded/request image reached the video workflow; refusing to use the saved default source image",
        }
    ext = {
        "agent_flow_active_flow": flow_name,
        "agent_flow_active_workflow_id": str(
            model_settings.get("workflow_id")
            or model_settings.get("model_workflow_id")
            or model_settings.get("agent_flow_default_workflow_id")
            or ""
        ).strip(),
        "agent_flow_force_runtime_flow": False,
        "agent_flow_internal_run": True,
        "model_workflow_direct_request": True,
        "model_workflow_request": {
            "model_type": model_type,
            "prompt": prompt,
            "settings": workflow_settings,
            "assets": workflow_assets,
            **dict(params or {}),
        },
    }
    runtime_flows = _load_model_workflow_blueprint_flows(settings, workflow_settings, flow_name)
    if runtime_flows:
        ext["agent_flow_flows"] = runtime_flows
    start = _http_json(
        "POST",
        f"{base_url}/v1/projects/{safe_pid}/sessions/{safe_sid}/agent_flow/run",
        {"text": prompt, "ext": ext},
        headers,
        timeout_s=30,
    )
    if not start.get("ok"):
        return {"ok": False, "error": f"agent_flow_start_failed:{start}"}
    run_id = str(start.get("run_id") or (start.get("state") or {}).get("run_id") or "").strip()
    deadline = time.monotonic() + (int(timeout_s or 0) if int(timeout_s or 0) > 0 else 3600)
    last_progress = 0.0
    state: Dict[str, Any] = dict(start.get("state") or {})
    while True:
        if callable(cancel_cb) and cancel_cb():
            return {"ok": False, "error": "canceled", "workflow_run_id": run_id}
        status_url = f"{base_url}/v1/projects/{safe_pid}/sessions/{safe_sid}/agent_flow/status"
        if run_id:
            status_url += f"?run_id={urllib.parse.quote(run_id, safe='')}"
        status = _http_json("GET", status_url, None, headers, timeout_s=30)
        if isinstance(status.get("state"), dict):
            state = dict(status.get("state") or {})
        if callable(progress_callback) and time.monotonic() - last_progress >= 2.0:
            try:
                progress_callback(int(state.get("step_index") or 0), int(state.get("steps_total") or 0))
            except Exception:
                pass
            last_progress = time.monotonic()
        if not bool(state.get("running")):
            break
        if time.monotonic() > deadline:
            return {"ok": False, "error": "workflow_timeout", "workflow_run_id": run_id}
        time.sleep(1.0)
    found = _find_media_result(state, suffixes)
    if not found:
        final_text = str(state.get("final_result") or state.get("status") or "").strip()
        return {"ok": False, "error": final_text or "workflow_completed_without_media", "workflow_run_id": run_id}
    return {
        "ok": True,
        "out_path": found if not urllib.parse.urlparse(found).scheme and not found.startswith("/uploads/") else "",
        "url": _uploads_url_for_path(found),
        "workflow_run_id": run_id,
        "workflow_flow_name": flow_name,
    }


def _attachment_dict(item: Any) -> Dict[str, Any]:
    if item is None:
        return {}
    if isinstance(item, dict):
        return dict(item)
    try:
        if hasattr(item, "model_dump"):
            return dict(item.model_dump(exclude_none=True))
        if hasattr(item, "dict"):
            return dict(item.dict(exclude_none=True))
    except Exception:
        pass
    try:
        return dict(item)
    except Exception:
        return {}


def _extract_ordered_attachments(req: Any) -> List[Dict[str, Any]]:
    sources: List[Any] = []

    def _add(src: Any) -> None:
        if not src:
            return
        if isinstance(src, dict):
            nested = src.get("items") or src.get("attachments")
            if nested is not None:
                _add(nested)
                return
            sources.append(src)
            return
        if isinstance(src, (list, tuple)):
            sources.extend(src)
            return
        sources.append(src)

    if isinstance(req, dict):
        _add(req.get("attachments"))
        ext = req.get("ext") if isinstance(req.get("ext"), dict) else {}
        _add((ext or {}).get("attachments"))
        _add((ext or {}).get("media_attachments"))
        router_msgs = (ext or {}).get("router_context_messages")
        msgs = req.get("messages")
    else:
        _add(getattr(req, "attachments", None))
        ext = getattr(req, "ext", None)
        if isinstance(ext, dict):
            _add(ext.get("attachments"))
            _add(ext.get("media_attachments"))
            router_msgs = ext.get("router_context_messages")
        else:
            router_msgs = None
        msgs = getattr(req, "messages", None)

    if isinstance(router_msgs, list) and router_msgs:
        msgs = list(router_msgs)

    if isinstance(msgs, list):
        for msg in msgs:
            if not isinstance(msg, dict) or (msg.get("role") or "").lower() != "user":
                continue
            meta = msg.get("meta")
            if isinstance(meta, dict):
                _add(meta.get("attachments"))
            content = msg.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        _add(part.get("attachment") or part.get("file") or part.get("media"))
                        image_url = part.get("image_url")
                        if isinstance(image_url, dict):
                            _add({
                                "url": image_url.get("url") or "",
                                "mime": image_url.get("mime") or image_url.get("content_type") or "image/*",
                                "kind": "image",
                                "name": image_url.get("name") or image_url.get("filename") or "",
                            })
                        elif isinstance(image_url, str) and image_url.strip():
                            _add({"url": image_url.strip(), "mime": "image/*", "kind": "image"})

    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in sources:
        item = _attachment_dict(raw)
        if not item:
            continue
        path = item.get("path") or item.get("local_path") or item.get("file_path") or item.get("abs_path")
        url = item.get("url") or item.get("href") or item.get("download_url")
        name = item.get("name") or item.get("filename") or item.get("file_name") or (os.path.basename(str(path)) if path else "")
        mime = str(item.get("mime") or item.get("content_type") or item.get("type") or "").lower()
        kind = str(item.get("kind") or item.get("media_type") or item.get("category") or "").lower()
        key = str(path or url or name or repr(item))
        if key in seen:
            continue
        seen.add(key)
        out.append({**item, "path": path or "", "url": url or "", "name": name or "", "mime": mime, "kind": kind})
    return out


def _session_recent_media_attachments(req: Any, settings_override: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    settings = dict(settings_override or {})
    if isinstance(req, dict):
        if not settings and isinstance(req.get("settings"), dict):
            settings = dict(req.get("settings") or {})
        ext = req.get("ext") if isinstance(req.get("ext"), dict) else {}
    else:
        if not settings and isinstance(getattr(req, "settings", None), dict):
            settings = dict(getattr(req, "settings", None) or {})
        ext = getattr(req, "ext", None) if isinstance(getattr(req, "ext", None), dict) else {}
    pid = str(settings.get("__pid") or ext.get("pid") or ext.get("project_id") or "").strip()
    sid = str(settings.get("__sid") or ext.get("sid") or ext.get("session_id") or "").strip()
    if not pid or not sid:
        return []
    app = get_server_app(settings, settings.get("__model_loader_registry"))
    db = getattr(getattr(app, "state", None), "collab_db", None) if app is not None else None
    if db is None or not hasattr(db, "list_messages"):
        return []
    try:
        rows = db.list_messages(pid=pid, sid=sid, limit=20, order_desc=True)
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for row in rows or []:
        if str((row or {}).get("role") or "").lower() != "user":
            continue
        meta = row.get("meta") if isinstance(row, dict) else None
        if not isinstance(meta, dict):
            raw_meta = row.get("meta_json") if isinstance(row, dict) else ""
            try:
                meta = json.loads(str(raw_meta or "{}"))
            except Exception:
                meta = {}
        attachments = None
        if isinstance(meta, dict):
            attachments = meta.get("attachments") or meta.get("media_attachments") or meta.get("files")
        if isinstance(attachments, list) and attachments:
            out.extend(_attachment_dict(item) for item in attachments)
            break
    return [item for item in out if item]


def _localize_media_reference(req: Any, ref: str, settings_override: Optional[Dict[str, Any]] = None) -> str:
    text = str(ref or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme in {"http", "https"}:
        if parsed.path.startswith("/uploads/"):
            text = parsed.path
        else:
            return text
    if text.startswith("/uploads/"):
        settings = dict(settings_override or {})
        if isinstance(req, dict):
            if not settings and isinstance(req.get("settings"), dict):
                settings = dict(req.get("settings") or {})
        else:
            if not settings and isinstance(getattr(req, "settings", None), dict):
                settings = dict(getattr(req, "settings", None) or {})
        app = get_server_app(settings, settings.get("__model_loader_registry"))
        data_dir = getattr(getattr(app, "state", None), "data_dir", None) if app is not None else None
        if data_dir:
            return os.path.join(str(data_dir), "uploads", os.path.basename(text))
    return text


def normalize_workflow_media_inputs(req: Any, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Map chat-uploaded media into predictable first/last workflow inputs.

    Convention:
    - one image/video => source/first media
    - two images/videos => first media is source, second media is last/target
    - text prompt remains the route prompt; workflows may omit unused extras
    """
    images: List[str] = []
    videos: List[str] = []

    attachments = _extract_ordered_attachments(req)
    if not attachments:
        attachments = _session_recent_media_attachments(req, settings)

    for item in attachments:
        path = _localize_media_reference(req, str(item.get("path") or item.get("local_path") or item.get("url") or item.get("download_url") or "").strip(), settings)
        if not path:
            continue
        mime = str(item.get("mime") or "").lower()
        kind = str(item.get("kind") or "").lower()
        name = str(item.get("name") or path).lower()
        ext = os.path.splitext(name.split("?", 1)[0])[1].lower()
        is_image = kind == "image" or mime.startswith("image/") or ext in IMAGE_EXTENSIONS
        is_video = kind == "video" or mime.startswith("video/") or ext in VIDEO_EXTENSIONS
        if is_image:
            images.append(path)
        elif is_video:
            videos.append(path)

    out: Dict[str, Any] = {}
    if images:
        out.update({
            "input_image_paths": images,
            "image_paths": images,
            "source_image_path": images[0],
            "first_image_path": images[0],
            "input_image_path": images[0],
            "init_image_path": images[0],
            "reference_image_path": images[0],
        })
        if len(images) > 1:
            out.update({
                "last_image_path": images[1],
                "target_image_path": images[1],
                "end_image_path": images[1],
            })
    if videos:
        out.update({
            "input_video_paths": videos,
            "video_paths": videos,
            "source_video_path": videos[0],
            "first_video_path": videos[0],
            "input_video_path": videos[0],
            "init_video_path": videos[0],
            "reference_video_path": videos[0],
        })
        if len(videos) > 1:
            out.update({
                "last_video_path": videos[1],
                "target_video_path": videos[1],
                "end_video_path": videos[1],
            })
    if images or videos:
        out["workflow_media_inputs"] = {"images": images, "videos": videos}
        try:
            print(
                "[model_workflow] workflow_media_inputs "
                f"images={images[:3]!r} videos={videos[:3]!r}",
                flush=True,
            )
        except Exception:
            pass
    return out


def get_server_app(settings: Dict[str, Any], reg: Any) -> Any:
    app = settings.get("__server_app")
    if app is not None:
        return app
    if reg is not None:
        try:
            gguf_loader = reg.get("model_loader.gguf") if hasattr(reg, "get") else None
        except Exception:
            gguf_loader = None
        if gguf_loader is not None:
            app = getattr(gguf_loader, "_app", None)
            if app is not None:
                return app
    return None


def _model_deck_service(settings: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    app = get_server_app(settings, settings.get("__model_loader_registry", None))
    svc = get_plugin_service(app, "model_deck")
    return svc if isinstance(svc, dict) else None


def resolve_model_deck_default(
    settings: Dict[str, Any],
    model_type: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    reg = settings.get("__model_loader_registry", None)
    app = get_server_app(settings, reg)
    if app is None:
        return None, "server_app_missing"

    deck_svc = _model_deck_service(settings)
    if not isinstance(deck_svc, dict):
        return None, "model_deck_service_missing"

    try:
        load_deck = deck_svc.get("load_deck")
        ensure_defaults = deck_svc.get("ensure_defaults")
        get_type = deck_svc.get("get_type")
        find_model = deck_svc.get("find_model")
        if not callable(load_deck) or not callable(ensure_defaults) or not callable(get_type) or not callable(find_model):
            return None, "model_deck_service_incomplete"
        deck = ensure_defaults(load_deck())
        t = get_type(deck, model_type)
    except Exception as exc:
        return None, f"model_deck_load_failed: {exc}"

    if not isinstance(t, dict):
        return None, f"model_deck_type_missing:{model_type}"

    override_keys = (
        f"{model_type}_model_id",
        f"{model_type}_deck_model_id",
        "model_deck_model_id",
    )
    mid = ""
    for key in override_keys:
        value = str((settings or {}).get(key) or "").strip()
        if value:
            mid = value
            break
    if not mid:
        mid = str(t.get("default_model_id") or "").strip()
    if not mid:
        return None, "model_deck_default_missing"
    m = find_model(t, mid)
    if not m:
        return None, "model_deck_default_not_found"

    return {
        "model_id": mid,
        "loader_id": str(m.get("loader_id") or ""),
        "settings": dict(m.get("settings") or {}),
        "lazy": bool(m.get("lazy", True)),
        "persist": bool(m.get("persist", False)),
    }, None


def resolve_main_text_llm_fallback(settings: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    reg = settings.get("__model_loader_registry", None)
    app = get_server_app(settings, reg)
    if app is None:
        return None, "server_app_missing"
    provider = getattr(getattr(app, "state", None), "main_text_llm_provider", None)
    if not callable(provider):
        return None, "main_text_llm_provider_missing"
    try:
        provider_result = provider() or {}
    except Exception as exc:
        return None, f"main_text_llm_provider_failed: {exc}"
    model_id = str(provider_result.get("model_id") or "").strip()
    loader_id = str(provider_result.get("loader_id") or "").strip()
    if not model_id:
        return None, "main_text_llm_model_missing"
    if loader_id not in ("model_loader.model_deck.text_llm", "model_loader.gguf") and not loader_id.startswith("remote_model."):
        return None, f"main_text_llm_loader_unsupported:{loader_id}"
    return {
        "model_id": model_id,
        "loader_id": loader_id,
        "settings": dict(provider_result.get("settings") or {}),
        "lazy": False,
        "persist": True,
        "use_main_text_llm_fallback": True,
    }, None


class ModelDeckRunner:
    def __init__(
        self,
        *,
        core: Any,
        settings: Dict[str, Any],
        model_type: str,
        slot: str,
        prefer_worker: bool = True,
        worker_mode: str = "per_request",
        worker_timeout: int = 120,
        require_mmproj: bool = False,
    ) -> None:
        self.core = core
        self.settings = settings
        self.model_type = model_type
        self.slot = slot
        self.prefer_worker = bool(prefer_worker)
        self.worker_mode = str(worker_mode or "per_request").strip().lower()
        if self.worker_mode not in ("per_request", "per_call"):
            self.worker_mode = "per_request"
        self.worker_timeout = int(worker_timeout or 120)
        self.require_mmproj = bool(require_mmproj)

        self.error: Optional[str] = None
        self._worker = None
        self._worker_cfg: Optional[Dict[str, Any]] = None
        self._model_ctx: Dict[str, Any] = {}
        self._use_worker = False

        self._init_runtime()

    def plan(self, messages: list[Dict[str, Any]], params: Dict[str, Any], timeout_s: int | None = None) -> Dict[str, Any]:
        if self.error:
            return {"ok": False, "error": self.error}
        cancel_cb = params.get("cancel_cb")
        try:
            if callable(cancel_cb) and cancel_cb():
                return {"ok": False, "error": "canceled"}
        except Exception:
            pass
        if self._use_worker:
            if self.worker_mode == "per_call":
                mgr = getattr(self.core, "worker_manager", None)
                if mgr is None or not self._worker_cfg:
                    return {"ok": False, "error": "worker_unavailable"}
                return mgr.run_vlm_plan(self._worker_cfg, messages, params, timeout_s=timeout_s or self.worker_timeout)
            return self._worker.plan(messages, params, timeout_s=timeout_s or self.worker_timeout)

        model = self._model_ctx.get("model")
        if model is None:
            return {"ok": False, "error": "model_unavailable"}
        max_new_tokens = int(params.get("max_new_tokens") or 512)
        temperature = float(params.get("temperature") or 0.2)
        top_p = float(params.get("top_p") or 0.3)
        top_k = int(params.get("top_k") or 30)
        out = ""
        if hasattr(model, "chat_mm"):
            try:
                if callable(cancel_cb) and cancel_cb():
                    return {"ok": False, "error": "canceled"}
            except Exception:
                pass
            out = model.chat_mm(
                messages=messages,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
            )
        if not out:
            try:
                if callable(cancel_cb) and cancel_cb():
                    return {"ok": False, "error": "canceled"}
            except Exception:
                pass
            out = model.chat(
                messages=messages,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
            )
        return {"ok": True, "raw": out}

    def stream(
        self,
        messages: list[Dict[str, Any]],
        params: Dict[str, Any],
        timeout_s: int | None = None,
        token_cb: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        if self.error:
            return {"ok": False, "error": self.error}
        cancel_cb = params.get("cancel_cb")
        try:
            if callable(cancel_cb) and cancel_cb():
                return {"ok": False, "error": "canceled"}
        except Exception:
            pass
        if self._use_worker:
            if self.worker_mode == "per_call":
                mgr = getattr(self.core, "worker_manager", None)
                if mgr is None or not self._worker_cfg:
                    return {"ok": False, "error": "worker_unavailable"}
                return mgr.run_vlm_stream(
                    self._worker_cfg,
                    messages,
                    params,
                    timeout_s=timeout_s or self.worker_timeout,
                    token_cb=token_cb,
                )
            return self._worker.stream(
                messages,
                params,
                timeout_s=timeout_s or self.worker_timeout,
                token_cb=token_cb,
            )

        model = self._model_ctx.get("model")
        if model is None:
            return {"ok": False, "error": "model_unavailable"}
        max_new_tokens = int(params.get("max_new_tokens") or 512)
        temperature = float(params.get("temperature") or 0.2)
        top_p = float(params.get("top_p") or 0.3)
        token_chunk_size = int(params.get("token_chunk_size") or 8)
        pieces: List[str] = []
        if hasattr(model, "stream_chat"):
            for piece in model.stream_chat(
                messages=messages,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                token_chunk_size=token_chunk_size,
            ):
                try:
                    if callable(cancel_cb) and cancel_cb():
                        return {"ok": False, "error": "canceled", "raw": "".join(pieces)}
                except Exception:
                    pass
                if not piece:
                    continue
                pieces.append(piece)
                if callable(token_cb):
                    try:
                        token_cb(piece)
                    except Exception:
                        pass
            return {"ok": True, "raw": "".join(pieces)}

        out = ""
        if hasattr(model, "chat_mm"):
            try:
                if callable(cancel_cb) and cancel_cb():
                    return {"ok": False, "error": "canceled"}
            except Exception:
                pass
            out = model.chat_mm(
                messages=messages,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=int(params.get("top_k") or 30),
            )
        if not out:
            try:
                if callable(cancel_cb) and cancel_cb():
                    return {"ok": False, "error": "canceled"}
            except Exception:
                pass
            out = model.chat(
                messages=messages,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=int(params.get("top_k") or 30),
            )
        if out and callable(token_cb):
            try:
                token_cb(out)
            except Exception:
                pass
        return {"ok": True, "raw": out}

    def close(self) -> None:
        if self._use_worker and self._worker is not None and self.worker_mode != "per_call":
            try:
                self._worker.close()
            except Exception:
                pass
        if self._model_ctx and not self._model_ctx.get("persist"):
            loader = self._model_ctx.get("loader")
            if loader is not None and hasattr(loader, "unload_for"):
                try:
                    self._awaitable_call(loader.unload_for, self._model_ctx.get("sid"), self._model_ctx.get("slot"))
                except Exception:
                    pass
            if self._should_stop_managed_llama_server_after_unload(loader):
                try:
                    deck_svc = _model_deck_service(self._model_ctx.get("settings") or {})
                    stop_managed = deck_svc.get("stop_managed_llama_server_if_needed") if isinstance(deck_svc, dict) else None
                    if callable(stop_managed):
                        stop_managed(self._model_ctx.get("settings") or {})
                    print(
                        f"[model_deck_runner.close] stopped managed llama-server "
                        f"id={(self._model_ctx.get('settings') or {}).get('llama_server_managed_id')} "
                        f"slot={self._model_ctx.get('slot')}",
                        flush=True,
                    )
                except Exception as exc:
                    print(f"[model_deck_runner.close] managed_stop_failed error={exc}", flush=True)

    def _should_stop_managed_llama_server_after_unload(self, loader: Any) -> bool:
        settings = self._model_ctx.get("settings") or {}
        if str(settings.get("backend_mode") or "").strip().lower() != "llama_server":
            return False
        managed_id = str(settings.get("llama_server_managed_id") or "").strip()
        if not managed_id:
            return False
        if not self._model_ctx.get("managed_llama_server"):
            return False

        try:
            state = getattr(loader, "_state", {}) or {}
        except Exception:
            state = {}
        for _key, st in state.items():
            if not isinstance(st, dict):
                continue
            other_settings = st.get("settings") or {}
            other_managed = str(other_settings.get("llama_server_managed_id") or "").strip()
            if other_managed == managed_id:
                return False
        return True

    def _awaitable_call(self, fn, *args, **kwargs):
        res = fn(*args, **kwargs)
        if inspect.isawaitable(res):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(res)
            fut = asyncio.run_coroutine_threadsafe(res, loop)
            return fut.result()
        return res

    def _init_runtime(self) -> None:
        info, err = resolve_model_deck_default(self.settings, self.model_type)
        if err and str(self.model_type or "").strip() == "text_llm":
            info, err = resolve_main_text_llm_fallback(self.settings)
        if err:
            self.error = err
            return

        loader_id = str(info.get("loader_id") or "model_loader.gguf")
        backend_mode = str(((info.get("settings") or {}).get("backend_mode") or "")).strip().lower()
        worker_mgr = getattr(self.core, "worker_manager", None)
        if (
            self.prefer_worker
            and worker_mgr is not None
            and info.get("lazy")
            and not info.get("persist")
            and backend_mode != "llama_server"
            and loader_id in ("model_loader.gguf", "model_loader.model_deck.vlm")
        ):
            cfg, err = self._build_gguf_worker_cfg(info)
            if err:
                self.error = err
                return
            self._worker_cfg = cfg
            if self.worker_mode == "per_request":
                self._worker = worker_mgr.spawn_vlm_worker(
                    cfg,
                    meta={
                        "model_type": self.model_type,
                        "slot": self.slot,
                        "model_id": info.get("model_id"),
                        "loader_id": loader_id,
                        "lazy": bool(info.get("lazy", True)),
                        "persist": bool(info.get("persist", False)),
                        "source": "model_deck_runner",
                    },
                )
            self._use_worker = True
            return

        self._model_ctx = self._bind_model_from_deck(info, loader_id)
        if self._model_ctx.get("error"):
            self.error = str(self._model_ctx.get("error"))

    def _build_gguf_worker_cfg(self, info: Dict[str, Any]) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        reg = self.settings.get("__model_loader_registry", None)
        app = get_server_app(self.settings, reg)
        if app is None:
            return None, "server_app_missing"

        try:
            from plugins.model_loader.model_deck.local_loaders.gguf_bridge import map_gguf_settings
            deck_settings = dict(info.get("settings") or {})
            app = get_server_app(self.settings, reg)
            if app is not None:
                deck_settings.setdefault("__server_app", app)
            gguf_settings = map_gguf_settings(deck_settings, require_mmproj=self.require_mmproj)
        except Exception as exc:
            return None, f"model_deck_settings_invalid: {exc}"

        try:
            from plugins.model_loader.gguf import plugin as gguf_plugin
            model_path = gguf_plugin._resolve_gguf_path(
                app, gguf_settings.get("model_id"), gguf_settings.get("gguf_filename")
            )
            mmproj_id = gguf_settings.get("mmproj_path")
            mmproj_path = None
            if mmproj_id:
                mmproj_path = gguf_plugin._resolve_gguf_path(app, mmproj_id, None)
        except Exception as exc:
            return None, f"resolve_failed: {exc}"

        model_settings = dict(info.get("settings") or {})
        cfg = {
            "model_path": model_path,
            "mmproj_path": mmproj_path,
            "vision_handler": gguf_settings.get("vision_handler") or "auto",
            "n_ctx": gguf_settings.get("n_ctx") or model_settings.get("n_ctx") or 4096,
            "n_threads": model_settings.get("n_threads"),
            "n_gpu_layers": gguf_settings.get("n_gpu_layers") or 0,
            "chat_format": model_settings.get("chat_format") or None,
        }
        return cfg, None

    def _bind_model_from_deck(self, info: Dict[str, Any], loader_id: str) -> Dict[str, Any]:
        reg = self.settings.get("__model_loader_registry", None)
        app = get_server_app(self.settings, reg)
        use_main_fallback = bool(info.get("use_main_text_llm_fallback"))
        sid = "_default" if use_main_fallback else str(self.settings.get("__sid") or "_default")
        slot = "text_llm_main" if use_main_fallback else self.slot

        use_settings = dict(info.get("settings") or {})
        if loader_id.startswith("remote_model.") or str(use_settings.get("model_location") or "").strip().lower() == "remote":
            if app is None:
                return {"error": "server_app_missing_for_remote_model"}
            provider_id = str(use_settings.get("remote_provider_id") or loader_id.replace("remote_model.", "", 1)).strip()
            services = getattr(getattr(app, "state", None), "plugin_services", None)
            service = (services or {}).get(provider_id) if isinstance(services, dict) else None
            if not isinstance(service, dict) or service.get("kind") != "remote_text_model":
                return {"error": f"remote_text_model_provider_missing:{provider_id or loader_id}"}
            getter = service.get("get_active_model")
            model = getter() if callable(getter) else None
            if model is None:
                return {"error": f"remote_text_model_inactive:{provider_id or loader_id}"}
            return {
                "model": model,
                "loader": None,
                "sid": sid,
                "slot": slot,
                "persist": True,
                "settings": use_settings,
                "backend_mode": "remote",
                "managed_llama_server": False,
            }

        if reg is None:
            return {"error": "model_loader_registry_missing"}

        loader = reg.get(loader_id) if hasattr(reg, "get") else None
        gguf_loader = reg.get("model_loader.gguf") if hasattr(reg, "get") else None
        backend_mode = str((use_settings.get("backend_mode") or "")).strip().lower()
        managed_llama_server = False

        if use_main_fallback:
            loader_id = "model_loader.gguf"
            loader = gguf_loader

        if loader_id in ("model_loader.gguf", "model_loader.model_deck.vlm"):
            loader = gguf_loader
            if loader is None:
                return {"error": "model_loader.gguf missing"}
            try:
                from plugins.model_loader.model_deck.local_loaders.gguf_bridge import map_gguf_settings
                deck_svc = _model_deck_service(self.settings)
                if not isinstance(deck_svc, dict):
                    return {"error": "model_deck_service_missing"}
                app = get_server_app(self.settings, reg)
                if app is not None:
                    use_settings = dict(use_settings)
                    use_settings.setdefault("__server_app", app)
                use_settings = map_gguf_settings(use_settings, require_mmproj=self.require_mmproj)
                backend_mode = str(use_settings.get("backend_mode") or "").strip().lower()
                if backend_mode == "llama_server":
                    source_path = str(use_settings.get("model_id") or "").strip()
                    ensure_model_copy = deck_svc.get("ensure_llama_server_model_copy")
                    resolve_aux = deck_svc.get("resolve_aux_gguf_path")
                    start_managed = deck_svc.get("start_managed_llama_server_if_needed")
                    if not callable(ensure_model_copy) or not callable(resolve_aux) or not callable(start_managed):
                        return {"error": "model_deck_service_incomplete"}
                    _, rel_model_path = ensure_model_copy(source_path)
                    rel_mmproj_path = None
                    mmproj_path = resolve_aux(app, str(use_settings.get("mmproj_path") or "").strip())
                    if mmproj_path:
                        _, rel_mmproj_path = ensure_model_copy(mmproj_path)
                    managed_url = start_managed(
                        use_settings,
                        rel_model_path,
                        mmproj_relpath=rel_mmproj_path,
                    )
                    if managed_url:
                        use_settings["llama_server_url"] = managed_url
                        managed_llama_server = bool(str(use_settings.get("llama_server_managed_id") or "").strip())
                    elif not str(use_settings.get("llama_server_url") or "").strip():
                        return {"error": "llama_server_url_missing_for_vlm"}
            except Exception as exc:
                return {"error": f"model_deck_settings_invalid: {exc}"}
        elif loader is None or not hasattr(loader, "load_for"):
            return {"error": f"model_loader_missing:{loader_id}"}

        if not hasattr(loader, "get_model_for"):
            return {"error": f"model_loader_missing_get_model_for:{loader_id}"}

        model = loader.get_model_for(sid, slot)
        if model is None:
            try:
                load_res = self._awaitable_call(loader.load_for, sid, slot, settings=use_settings)
            except Exception as exc:
                return {"error": f"model_load_failed: {exc}"}
            if not (load_res or {}).get("ok", False):
                return {"error": f"model_load_failed: {load_res}"}
            model = loader.get_model_for(sid, slot)
        if model is None:
            return {"error": "loaded_model_missing"}

        return {
            "model": model,
            "loader": loader,
            "sid": sid,
            "slot": slot,
            "persist": bool(info.get("persist")),
            "settings": use_settings,
            "backend_mode": backend_mode,
            "managed_llama_server": managed_llama_server,
        }


def _save_image_worker(image: Any, fmt: str, output_dir: str) -> str:
    from uuid import uuid4

    ext = "png" if fmt == "png" else "jpg"
    name = f"image_gen_{uuid4().hex}.{ext}"
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, name)
    try:
        if fmt in ("jpg", "jpeg"):
            image = image.convert("RGB")
            image.save(path, format="JPEG", quality=95)
        else:
            image.save(path, format="PNG")
    except Exception:
        image.save(path)
    return path


def _image_gen_worker(conn, loader_id: str, model_settings: Dict[str, Any], params: Dict[str, Any]) -> None:
    try:
        from plugins.model_loader.model_deck.local_loaders.image_gen_gguf import routes as gguf_image_routes
        from plugins.model_loader.model_deck.local_loaders.diffusers import routes as diffusers_routes
        from plugins.model_loader.model_deck.local_loaders import custom_command_runtime

        prompt = str(params.get("prompt") or "")
        negative_prompt = params.get("negative_prompt")
        num_inference_steps = params.get("num_inference_steps")
        guidance_scale = params.get("guidance_scale")
        width = params.get("width")
        height = params.get("height")
        seed = params.get("seed")
        fmt = str(params.get("fmt") or "png").lower()
        output_dir = str(params.get("output_dir") or "").strip()

        out_path = ""
        url = ""

        def _progress(step: int, total: int) -> None:
            try:
                conn.send({"type": "progress", "step": int(step), "total": int(total)})
            except Exception:
                pass

        if str(model_settings.get("image_command_mode") or "standard").strip().lower() == "advanced":
            if not output_dir:
                output_dir = os.path.join(os.getcwd(), "data", "uploads")
            os.makedirs(output_dir, exist_ok=True)
            ext = "jpg" if fmt in ("jpg", "jpeg") else ("webp" if fmt == "webp" else "png")
            out_path = os.path.join(output_dir, f"image_gen_{int(time.time())}_{os.getpid()}.{ext}")
            custom_command_runtime.run_advanced_command(
                settings=model_settings,
                prefix="image",
                runtime_inputs={
                    "prompt": prompt,
                    "negative_prompt": negative_prompt or "",
                    "output_path": out_path,
                    "width": width or "",
                    "height": height or "",
                    "steps": num_inference_steps or "",
                    "num_inference_steps": num_inference_steps or "",
                    "guidance": guidance_scale or "",
                    "guidance_scale": guidance_scale or "",
                    "seed": seed or "",
                    "seed_arg": f"--seed {seed}" if seed not in (None, "") else "",
                },
            )
            if not os.path.isfile(out_path):
                raise RuntimeError(f"advanced image command did not create output: {out_path}")
            url = f"/uploads/{os.path.basename(out_path)}"
        elif loader_id == gguf_image_routes.LOADER_ID:
            out_path = gguf_image_routes.generate_text2image(
                prompt=prompt,
                settings=model_settings,
                negative_prompt=negative_prompt,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                width=width,
                height=height,
                seed=seed,
                progress_callback=_progress,
            )
            url = f"/uploads/{os.path.basename(out_path)}"
        else:
            images = diffusers_routes.generate_text2image(
                prompt=prompt,
                settings=model_settings,
                negative_prompt=negative_prompt,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                width=width,
                height=height,
                seed=seed,
                progress_callback=_progress,
            )
            image = None
            if isinstance(images, (list, tuple)) and images:
                image = images[0]
            elif images is not None:
                image = images
            if image is None:
                raise RuntimeError("no_image_generated")
            if not output_dir:
                output_dir = os.path.join(os.getcwd(), "data", "uploads")
            out_path = _save_image_worker(image, fmt, output_dir)
            url = f"/uploads/{os.path.basename(out_path)}"
            try:
                if hasattr(image, "close"):
                    image.close()
            except Exception:
                pass

        conn.send({"type": "result", "ok": True, "out_path": out_path, "url": url})
    except Exception as exc:
        conn.send({"type": "result", "ok": False, "error": str(exc), "trace": traceback.format_exc()})
    finally:
        try:
            conn.close()
        except Exception:
            pass


class ImageGenRunner:
    def __init__(
        self,
        *,
        core: Any,
        settings: Dict[str, Any],
        model_type: str = "image_gen",
        prefer_worker: bool = True,
        worker_timeout: int = 600,
    ) -> None:
        self.core = core
        self.settings = settings
        self.model_type = model_type
        self.prefer_worker = bool(prefer_worker)
        self.worker_timeout = int(worker_timeout or 600)
        self.error: Optional[str] = None
        self.info: Dict[str, Any] = {}
        self.loader_id: str = ""
        self._use_worker = False

        self._init_runtime()

    def _init_runtime(self) -> None:
        info, err = resolve_model_deck_default(self.settings, self.model_type)
        if err:
            self.error = err
            return
        self.info = info or {}
        self.loader_id = str(self.info.get("loader_id") or "")
        if self.prefer_worker and info.get("lazy") and not info.get("persist"):
            self._use_worker = True

    def close(self) -> None:
        return

    def generate(
        self,
        *,
        prompt: str,
        negative_prompt: Optional[str],
        num_inference_steps: int,
        guidance_scale: float,
        width: int,
        height: int,
        seed: Optional[int],
        fmt: str,
        progress_callback: Optional[Any] = None,
        cancel_cb: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if self.error:
            return {"ok": False, "error": self.error}
        info = self.info or {}

        from plugins.model_loader.model_deck.local_loaders.image_gen_gguf import routes as gguf_image_routes
        from plugins.model_loader.model_deck.local_loaders.diffusers import routes as diffusers_routes

        loader_id = str(info.get("loader_id") or "")
        model_settings = dict(info.get("settings") or {})
        model_settings.update(self.settings.get("image_gen_model_settings") or {})
        try:
            print(
                "[image_gen] merged_model_settings "
                f"loader_id={loader_id!r} "
                f"model_id={str(model_settings.get('model_id') or model_settings.get('model') or '')!r} "
                f"repo_id={str(model_settings.get('repo_id') or '')!r} "
                f"device={str(model_settings.get('device') or '')!r} "
                f"dtype={str(model_settings.get('dtype') or '')!r} "
                f"cpu_offload={model_settings.get('enable_model_cpu_offload')!r} "
                f"seq_offload={model_settings.get('enable_sequential_cpu_offload')!r}",
                flush=True,
            )
        except Exception:
            pass
        if _is_workflow_model_loader_settings(info, model_settings):
            return _run_agent_flow_model_workflow(
                settings=self.settings,
                model_settings=model_settings,
                model_type=self.model_type,
                prompt=prompt,
                params={
                    "negative_prompt": negative_prompt,
                    "num_inference_steps": num_inference_steps,
                    "guidance_scale": guidance_scale,
                    "width": width,
                    "height": height,
                    "seed": seed,
                    "fmt": fmt,
                },
                suffixes=(".png", ".jpg", ".jpeg", ".webp", ".bmp"),
                timeout_s=self.worker_timeout,
                progress_callback=progress_callback,
                cancel_cb=cancel_cb,
            )
        allowed = {gguf_image_routes.LOADER_ID, diffusers_routes.LOADER_ID}
        if loader_id not in allowed:
            return {"ok": False, "error": f"unsupported_loader:{loader_id}"}
        for key in (
            "image_gen_use_prompt_embeds",
            "debug_prompt_embeds",
            "use_prompt_embeds",
            "max_sequence_length",
        ):
            if key in self.settings:
                model_settings[key] = self.settings.get(key)
        if "__server_app" not in model_settings:
            app = get_server_app(self.settings, self.settings.get("__model_loader_registry"))
            if app is not None:
                model_settings["__server_app"] = app
        if "__model_loader_registry" not in model_settings and self.settings.get("__model_loader_registry") is not None:
            model_settings["__model_loader_registry"] = self.settings.get("__model_loader_registry")

        persist_raw = info.get("persist", False)
        if isinstance(persist_raw, str):
            persist = persist_raw.strip().lower() in ("1", "true", "yes", "on")
        else:
            persist = bool(persist_raw)

        if callable(cancel_cb) and cancel_cb():
            return {"ok": False, "error": "canceled"}

        if self._use_worker and not persist:
            worker_settings = self._prepare_worker_settings(loader_id, model_settings)
            return self._run_worker(
                loader_id=loader_id,
                model_settings=worker_settings,
                prompt=prompt,
                negative_prompt=negative_prompt,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                width=width,
                height=height,
                seed=seed,
                fmt=fmt,
                progress_callback=progress_callback,
                cancel_cb=cancel_cb,
            )

        if loader_id == gguf_image_routes.LOADER_ID:
            try:
                def _progress(step: int, total: int) -> None:
                    if callable(cancel_cb) and cancel_cb():
                        raise RuntimeError("canceled")
                    if callable(progress_callback):
                        progress_callback(step, total)

                out_path = gguf_image_routes.generate_text2image(
                    prompt=prompt,
                    settings=model_settings,
                    negative_prompt=negative_prompt,
                    num_inference_steps=num_inference_steps,
                    guidance_scale=guidance_scale,
                    width=width,
                    height=height,
                    seed=seed,
                    progress_callback=_progress if progress_callback or cancel_cb else None,
                )
            finally:
                if not persist:
                    try:
                        gguf_image_routes.unload(None, model_settings)
                    except Exception:
                        pass
                    self._cleanup_memory()
            return {"ok": True, "out_path": out_path, "url": f"/uploads/{os.path.basename(out_path)}"}

        try:
            def _progress(step: int, total: int) -> None:
                if callable(cancel_cb) and cancel_cb():
                    raise RuntimeError("canceled")
                if callable(progress_callback):
                    progress_callback(step, total)

            images = diffusers_routes.generate_text2image(
                prompt=prompt,
                settings=model_settings,
                negative_prompt=negative_prompt,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                width=width,
                height=height,
                seed=seed,
                progress_callback=_progress if progress_callback or cancel_cb else None,
            )
        finally:
            if not persist:
                try:
                    diffusers_routes.unload(None, model_settings)
                except Exception:
                    pass
                self._cleanup_memory()

        image = None
        if isinstance(images, (list, tuple)) and images:
            image = images[0]
        elif images is not None:
            image = images
        if image is None:
            return {"ok": False, "error": "no_image_generated"}

        out_dir = self._uploads_dir(model_settings)
        out_path = _save_image_worker(image, fmt, out_dir)
        try:
            if hasattr(image, "close"):
                image.close()
        except Exception:
            pass
        return {"ok": True, "out_path": out_path, "url": f"/uploads/{os.path.basename(out_path)}"}

    def _uploads_dir(self, model_settings: Dict[str, Any]) -> str:
        app = model_settings.get("__server_app")
        if app is None:
            reg = self.settings.get("__model_loader_registry", None)
            app = get_server_app(self.settings, reg)
        base = None
        if app is not None:
            base = getattr(app.state, "data_dir", None) or getattr(app.state, "workdir", None)
        if not base:
            base = os.path.join(os.getcwd(), "data")
        out = os.path.join(base, "uploads")
        os.makedirs(out, exist_ok=True)
        return out

    def _prepare_worker_settings(self, loader_id: str, model_settings: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(model_settings or {})
        for k in list(out.keys()):
            if str(k).startswith("__"):
                out.pop(k, None)

        out_dir = out.get("output_dir")
        if not out_dir:
            out["output_dir"] = self._uploads_dir(model_settings)

        if loader_id == "model_loader.model_deck.image_gen_gguf":
            try:
                from plugins.model_loader.model_deck.local_loaders.image_gen_gguf import routes as gguf_image_routes
                out["model_path"] = gguf_image_routes._resolve_model_path(out)
            except Exception:
                pass
        else:
            try:
                from plugins.model_loader.model_deck.local_loaders.diffusers import routes as diffusers_routes
                gguf_path = str(out.get("gguf_path") or "").strip()
                if gguf_path:
                    out["gguf_path"] = diffusers_routes._resolve_gguf_path_setting(None, model_settings, gguf_path)
                unet_path = str(out.get("sdxl_unet_path") or "").strip()
                if unet_path or out.get("sdxl_unet_repo") or out.get("sdxl_unet_filename"):
                    resolved = diffusers_routes._resolve_unet_path_setting(None, model_settings, unet_path)
                    if resolved:
                        out["sdxl_unet_path"] = resolved
            except Exception:
                pass
        return out

    def _run_worker(
        self,
        *,
        loader_id: str,
        model_settings: Dict[str, Any],
        prompt: str,
        negative_prompt: Optional[str],
        num_inference_steps: int,
        guidance_scale: float,
        width: int,
        height: int,
        seed: Optional[int],
        fmt: str,
        progress_callback: Optional[Any] = None,
        cancel_cb: Optional[Any] = None,
    ) -> Dict[str, Any]:
        ctx = multiprocessing.get_context("spawn")
        parent, child = ctx.Pipe()
        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "num_inference_steps": num_inference_steps,
            "guidance_scale": guidance_scale,
            "width": width,
            "height": height,
            "seed": seed,
            "fmt": fmt,
            "output_dir": model_settings.get("output_dir") or "",
        }
        proc = ctx.Process(
            target=_image_gen_worker,
            args=(child, loader_id, model_settings, payload),
            daemon=True,
        )
        proc.start()
        start = time.monotonic()
        try:
            last_step = -1
            last_total = None
            last_heartbeat = time.monotonic()
            heartbeat_total = int(num_inference_steps or 0)
            while True:
                if callable(cancel_cb) and cancel_cb():
                    try:
                        if proc.is_alive():
                            proc.terminate()
                    except Exception:
                        pass
                    return {"ok": False, "error": "canceled"}
                if parent.poll(0.1):
                    msg = parent.recv()
                    if isinstance(msg, dict) and msg.get("type") == "progress":
                        if callable(progress_callback):
                            try:
                                step = int(msg.get("step") or 0)
                                total = int(msg.get("total") or 0)
                                if step > last_step or total != last_total:
                                    last_step = step
                                    last_total = total
                                    progress_callback(step, total)
                            except Exception:
                                pass
                        last_heartbeat = time.monotonic()
                        continue
                    if isinstance(msg, dict) and msg.get("type") == "result":
                        msg.pop("type", None)
                        return msg
                    return msg
                if callable(progress_callback) and proc.is_alive() and (time.monotonic() - last_heartbeat) >= 4.0:
                    try:
                        progress_callback(max(last_step, 0), int(last_total or heartbeat_total or 0))
                    except Exception:
                        pass
                    last_heartbeat = time.monotonic()
                if self.worker_timeout > 0 and (time.monotonic() - start > self.worker_timeout):
                    return {"ok": False, "error": "worker_timeout"}
        finally:
            try:
                parent.close()
            except Exception:
                pass
            try:
                proc.join(timeout=2)
            except Exception:
                pass
            try:
                if proc.is_alive():
                    proc.terminate()
            except Exception:
                pass

    def _cleanup_memory(self) -> None:
        try:
            import gc
            gc.collect()
        except Exception:
            pass
        try:
            import torch
            empty_accelerator_cache(torch)
        except Exception:
            pass


def _video_gen_worker(conn, model_settings: Dict[str, Any], params: Dict[str, Any]) -> None:
    try:
        from plugins.model_loader.model_deck.local_loaders.video import routes as video_routes
        from plugins.model_loader.model_deck.local_loaders import custom_command_runtime

        prompt = str(params.get("prompt") or "")
        num_frames = params.get("num_frames")
        num_inference_steps = params.get("num_inference_steps")
        guidance_scale = params.get("guidance_scale")
        width = params.get("width")
        height = params.get("height")
        fps = params.get("fps")
        seed = params.get("seed")
        negative_prompt = params.get("negative_prompt")
        output_dir = str(params.get("output_dir") or "").strip()

        def _progress(step: int, total: int) -> None:
            try:
                conn.send({"type": "progress", "step": int(step), "total": int(total)})
            except Exception:
                pass

        if str(model_settings.get("video_command_mode") or "standard").strip().lower() == "advanced":
            if not output_dir:
                output_dir = os.path.join(os.getcwd(), "data", "uploads")
            os.makedirs(output_dir, exist_ok=True)
            out_path = os.path.join(output_dir, f"video_gen_{int(time.time())}_{os.getpid()}.mp4")
            custom_command_runtime.run_advanced_command(
                settings=model_settings,
                prefix="video",
                runtime_inputs={
                    "prompt": prompt,
                    "negative_prompt": negative_prompt or "",
                    "output_path": out_path,
                    "width": width or "",
                    "height": height or "",
                    "frames": num_frames or "",
                    "num_frames": num_frames or "",
                    "fps": fps or "",
                    "steps": num_inference_steps or "",
                    "num_inference_steps": num_inference_steps or "",
                    "guidance": guidance_scale or "",
                    "guidance_scale": guidance_scale or "",
                    "seed": seed or "",
                    "seed_arg": f"--seed {seed}" if seed not in (None, "") else "",
                },
            )
            if not os.path.isfile(out_path):
                raise RuntimeError(f"advanced video command did not create output: {out_path}")
        else:
            out_path = video_routes.generate_text2video(
                prompt=prompt,
                settings=model_settings,
                num_frames=num_frames,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                width=width,
                height=height,
                fps=fps,
                seed=seed,
                progress_callback=_progress,
                output_dir=output_dir or None,
            )
        url = f"/uploads/{os.path.basename(out_path)}"
        conn.send({"type": "result", "ok": True, "out_path": out_path, "url": url})
    except Exception as exc:
        conn.send({"type": "result", "ok": False, "error": str(exc), "trace": traceback.format_exc()})
    finally:
        try:
            conn.close()
        except Exception:
            pass


class VideoGenRunner:
    def __init__(
        self,
        *,
        core: Any,
        settings: Dict[str, Any],
        model_type: str = "video_gen",
        prefer_worker: bool = True,
        worker_timeout: int = 0,
    ) -> None:
        self.core = core
        self.settings = settings
        self.model_type = model_type
        self.prefer_worker = bool(prefer_worker)
        if worker_timeout is None:
            self.worker_timeout = 0
        else:
            try:
                self.worker_timeout = int(worker_timeout)
            except Exception:
                self.worker_timeout = 0
        if self.worker_timeout < 0:
            self.worker_timeout = 0
        self.error: Optional[str] = None
        self.info: Dict[str, Any] = {}
        self.loader_id: str = ""
        self._use_worker = False

        self._init_runtime()

    def _init_runtime(self) -> None:
        info, err = resolve_model_deck_default(self.settings, self.model_type)
        if err:
            self.error = err
            return
        self.info = info or {}
        self.loader_id = str(self.info.get("loader_id") or "")
        if self.prefer_worker and info.get("lazy") and not info.get("persist"):
            self._use_worker = True

    def close(self) -> None:
        return

    def generate(
        self,
        *,
        prompt: str,
        num_frames: int,
        num_inference_steps: int,
        guidance_scale: float,
        width: int,
        height: int,
        fps: int,
        seed: Optional[int],
        progress_callback: Optional[Any] = None,
        cancel_cb: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if self.error:
            return {"ok": False, "error": self.error}
        info = self.info or {}

        from plugins.model_loader.model_deck.local_loaders.video import routes as video_routes

        loader_id = str(info.get("loader_id") or "")
        if loader_id != video_routes.LOADER_ID:
            return {"ok": False, "error": f"unsupported_loader:{loader_id}"}

        model_settings = dict(info.get("settings") or {})
        model_overrides = self.settings.get("video_gen_model_settings") or {}
        if isinstance(model_overrides, dict) and model_overrides:
            if _settings_identity_compatible(model_settings, model_overrides):
                model_settings.update(model_overrides)
            else:
                media_override_keys = {
                    "input_image_paths",
                    "image_paths",
                    "source_image_path",
                    "first_image_path",
                    "input_image_path",
                    "init_image_path",
                    "reference_image_path",
                    "last_image_path",
                    "target_image_path",
                    "end_image_path",
                    "workflow_media_inputs",
                    "prompt",
                    "positive_prompt",
                    "__request_prompt",
                }
                for key in media_override_keys:
                    value = model_overrides.get(key)
                    if value not in (None, "", [], {}):
                        model_settings[key] = value
                try:
                    print(
                        "[video_gen.workflow] skipped_incompatible_model_settings_overlay "
                        f"selected_flow={str(model_settings.get('model_workflow_flow_name') or '')!r} "
                        f"overlay_flow={str(model_overrides.get('model_workflow_flow_name') or '')!r} "
                        f"selected_compat={str(model_settings.get('model_deck_compat_manifest_id') or '')!r} "
                        f"overlay_compat={str(model_overrides.get('model_deck_compat_manifest_id') or '')!r}",
                        flush=True,
                    )
                except Exception:
                    pass
        if _is_workflow_model_loader_settings(info, model_settings):
            runtime_params = {
                "num_frames": num_frames,
                "num_inference_steps": num_inference_steps,
                "guidance_scale": guidance_scale,
                "width": width,
                "height": height,
                "fps": fps,
                "seed": seed,
            }
            for key in (
                "input_image_paths",
                "image_paths",
                "source_image_path",
                "first_image_path",
                "input_image_path",
                "init_image_path",
                "reference_image_path",
                "last_image_path",
                "target_image_path",
                "end_image_path",
                "input_video_paths",
                "video_paths",
                "source_video_path",
                "first_video_path",
                "input_video_path",
                "init_video_path",
                "reference_video_path",
                "last_video_path",
                "target_video_path",
                "end_video_path",
                "workflow_media_inputs",
            ):
                value = self.settings.get(key)
                if value not in (None, "", [], {}):
                    runtime_params[key] = value
            try:
                print(
                    "[video_gen.workflow] runtime_params "
                    f"source={str(runtime_params.get('source_image_path') or runtime_params.get('input_image_path') or '')!r} "
                    f"images={runtime_params.get('image_paths') or runtime_params.get('input_image_paths') or []!r} "
                    f"prompt_len={len(prompt or '')}",
                    flush=True,
                )
            except Exception:
                pass
            return _run_agent_flow_model_workflow(
                settings=self.settings,
                model_settings=model_settings,
                model_type=self.model_type,
                prompt=prompt,
                params=runtime_params,
                suffixes=(".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".wmv"),
                timeout_s=self.worker_timeout,
                progress_callback=progress_callback,
                cancel_cb=cancel_cb,
            )
        if "__server_app" not in model_settings:
            app = get_server_app(self.settings, self.settings.get("__model_loader_registry"))
            if app is not None:
                model_settings["__server_app"] = app
        if "__model_loader_registry" not in model_settings and self.settings.get("__model_loader_registry") is not None:
            model_settings["__model_loader_registry"] = self.settings.get("__model_loader_registry")

        persist_raw = info.get("persist", False)
        if isinstance(persist_raw, str):
            persist = persist_raw.strip().lower() in ("1", "true", "yes", "on")
        else:
            persist = bool(persist_raw)

        if self._use_worker and not persist:
            worker_settings = self._prepare_worker_settings(model_settings)
            return self._run_worker(
                model_settings=worker_settings,
                prompt=prompt,
                num_frames=num_frames,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                width=width,
                height=height,
                fps=fps,
                seed=seed,
                progress_callback=progress_callback,
                cancel_cb=cancel_cb,
            )

        try:
            def _progress(step: int, total: int) -> None:
                if callable(cancel_cb) and cancel_cb():
                    raise RuntimeError("canceled")
                if callable(progress_callback):
                    progress_callback(step, total)

            out_path = video_routes.generate_text2video(
                prompt=prompt,
                settings=model_settings,
                num_frames=num_frames,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                width=width,
                height=height,
                fps=fps,
                seed=seed,
                progress_callback=_progress if progress_callback or cancel_cb else None,
            )
        except RuntimeError as exc:
            if str(exc).lower().startswith("canceled"):
                return {"ok": False, "error": "canceled"}
            raise
        finally:
            if not persist:
                try:
                    video_routes.unload(None, model_settings)
                except Exception:
                    pass
                self._cleanup_memory()
        return {"ok": True, "out_path": out_path, "url": f"/uploads/{os.path.basename(out_path)}"}

    def _uploads_dir(self, model_settings: Dict[str, Any]) -> str:
        app = model_settings.get("__server_app")
        if app is None:
            reg = self.settings.get("__model_loader_registry", None)
            app = get_server_app(self.settings, reg)
        base = None
        if app is not None:
            base = getattr(app.state, "data_dir", None) or getattr(app.state, "workdir", None)
        if not base:
            base = os.path.join(os.getcwd(), "data")
        out = os.path.join(base, "uploads")
        os.makedirs(out, exist_ok=True)
        return out

    def _prepare_worker_settings(self, model_settings: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(model_settings or {})
        for k in list(out.keys()):
            if str(k).startswith("__"):
                out.pop(k, None)
        out_dir = out.get("output_dir")
        if not out_dir:
            out["output_dir"] = self._uploads_dir(model_settings)
        return out

    def _run_worker(
        self,
        *,
        model_settings: Dict[str, Any],
        prompt: str,
        num_frames: int,
        num_inference_steps: int,
        guidance_scale: float,
        width: int,
        height: int,
        fps: int,
        seed: Optional[int],
        progress_callback: Optional[Any] = None,
        cancel_cb: Optional[Any] = None,
    ) -> Dict[str, Any]:
        ctx = multiprocessing.get_context("spawn")
        parent, child = ctx.Pipe()
        payload = {
            "prompt": prompt,
            "num_frames": num_frames,
            "num_inference_steps": num_inference_steps,
            "guidance_scale": guidance_scale,
            "width": width,
            "height": height,
            "fps": fps,
            "seed": seed,
            "output_dir": model_settings.get("output_dir") or "",
        }
        proc = ctx.Process(
            target=_video_gen_worker,
            args=(child, model_settings, payload),
            daemon=True,
        )
        proc.start()
        start = time.monotonic()
        try:
            last_step = -1
            last_total = None
            while True:
                if callable(cancel_cb) and cancel_cb():
                    try:
                        if proc.is_alive():
                            proc.terminate()
                    except Exception:
                        pass
                    return {"ok": False, "error": "canceled"}
                if parent.poll(0.1):
                    msg = parent.recv()
                    if isinstance(msg, dict) and msg.get("type") == "progress":
                        if callable(progress_callback):
                            try:
                                step = int(msg.get("step") or 0)
                                total = int(msg.get("total") or 0)
                                if step > last_step or total != last_total:
                                    last_step = step
                                    last_total = total
                                    progress_callback(step, total)
                            except Exception:
                                pass
                        continue
                    if isinstance(msg, dict) and msg.get("type") == "result":
                        msg.pop("type", None)
                        return msg
                    return msg
                if self.worker_timeout > 0 and (time.monotonic() - start > self.worker_timeout):
                    return {"ok": False, "error": "worker_timeout"}
        finally:
            try:
                parent.close()
            except Exception:
                pass
            try:
                proc.join(timeout=2)
            except Exception:
                pass
            try:
                if proc.is_alive():
                    proc.terminate()
            except Exception:
                pass

    def _cleanup_memory(self) -> None:
        try:
            import gc
            gc.collect()
        except Exception:
            pass
        try:
            import torch
            empty_accelerator_cache(torch)
        except Exception:
            pass
