from __future__ import annotations

import os
import py_compile
import json
import subprocess
import re
import inspect
from types import SimpleNamespace
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List

from .registry import WorkflowToolRegistry
from .repo_file_preview import read_repo_file_preview
from ..agent_flow.skills.repo.find_file import run as repo_find_file_skill_run


def _workspace_root(app) -> str:
    wd = getattr(app.state, "workdir", None)
    if isinstance(wd, str) and wd.strip():
        return os.path.abspath(wd)
    return os.path.abspath(".")


def _framework_data_dir(app) -> str:
    data_dir = getattr(getattr(app, "state", None), "data_dir", None)
    if isinstance(data_dir, str) and data_dir.strip():
        return os.path.abspath(data_dir)
    return os.path.join(_workspace_root(app), "data")


def _agent_workflow_data_dir(app) -> str:
    path = os.path.join(_framework_data_dir(app), "agent_workflow")
    os.makedirs(path, exist_ok=True)
    return path


def register_default_tools(app, registry: WorkflowToolRegistry) -> None:
    root = _workspace_root(app)
    learning_dir = _agent_workflow_data_dir(app)
    learning_path = os.path.join(learning_dir, "learning_feedback.json")

    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _call_maybe_async(fn: Any, *args: Any, **kwargs: Any) -> Any:
        out = fn(*args, **kwargs)
        if inspect.isawaitable(out):
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                # Run in a dedicated loop to avoid nested-loop failures.
                new_loop = asyncio.new_event_loop()
                try:
                    return new_loop.run_until_complete(out)
                finally:
                    new_loop.close()
            return asyncio.run(out)
        return out

    def _runtime_base_settings() -> Dict[str, Any]:
        try:
            state_settings = getattr(app.state, "settings", None)
            if callable(state_settings):
                loaded = state_settings()
                if isinstance(loaded, dict):
                    out = dict(loaded)
                    nested_rps = loaded.get("router_plugin_settings") if isinstance(loaded.get("router_plugin_settings"), dict) else {}
                    if isinstance(nested_rps, dict):
                        for _plugin_id, _plugin_cfg in nested_rps.items():
                            if not isinstance(_plugin_cfg, dict):
                                continue
                            for _k, _v in _plugin_cfg.items():
                                out[_k] = _v
                    return out
            elif isinstance(state_settings, dict):
                out = dict(state_settings)
                nested_rps = state_settings.get("router_plugin_settings") if isinstance(state_settings.get("router_plugin_settings"), dict) else {}
                if isinstance(nested_rps, dict):
                    for _plugin_id, _plugin_cfg in nested_rps.items():
                        if not isinstance(_plugin_cfg, dict):
                            continue
                        for _k, _v in _plugin_cfg.items():
                            out[_k] = _v
                return out
        except Exception:
            pass
        return {}

    def _ensure_main_text_model_loaded(preferred_sid: str | None = None, diag: Dict[str, Any] | None = None) -> Any:
        if isinstance(diag, dict):
            diag.setdefault("model_resolver", {})
            diag["model_resolver"]["preferred_sid"] = str(preferred_sid or "").strip() or "_default"
        reg = getattr(app.state, "model_loader_registry", None)
        provider_fn = getattr(app.state, "main_text_llm_provider", None)
        if not hasattr(reg, "get"):
            if isinstance(diag, dict):
                diag["model_resolver"]["registry_missing"] = True
            return None
        gguf = reg.get("model_loader.gguf")
        if gguf is None:
            if isinstance(diag, dict):
                diag["model_resolver"]["gguf_loader_missing"] = True
            return None

        sid_pref = str(preferred_sid or "").strip() or "_default"
        # First, attach to an already-loaded main text model slot.
        for sid_try in [sid_pref, "_default"]:
            try:
                loaded = gguf.get_model_for(sid_try, "text_llm_main")
            except Exception:
                loaded = None
            if loaded is not None:
                if isinstance(diag, dict):
                    diag["model_resolver"]["from_slot"] = f"{sid_try}:text_llm_main"
                return loaded

        # Last-resort: any loaded GGUF slot.
        try:
            st = getattr(gguf, "_models", None)
            if isinstance(st, dict):
                for _k, m in st.items():
                    if m is not None:
                        if isinstance(diag, dict):
                            diag["model_resolver"]["from_any_loaded_slot"] = str(_k)
                        return m
        except Exception:
            pass

        if not callable(provider_fn):
            if isinstance(diag, dict):
                diag["model_resolver"]["provider_missing"] = True
            return None
        try:
            provider = provider_fn() or {}
        except Exception:
            if isinstance(diag, dict):
                diag["model_resolver"]["provider_error"] = True
            return None
        if isinstance(diag, dict):
            diag["model_resolver"]["provider_loader_id"] = str(provider.get("loader_id") or "")
            diag["model_resolver"]["provider_model_id"] = str(provider.get("model_id") or "")
        loader_id = str(provider.get("loader_id") or "").strip()
        model_id = str(provider.get("model_id") or "").strip()
        if not model_id:
            if isinstance(diag, dict):
                diag["model_resolver"]["provider_model_missing"] = True
            return None
        if loader_id not in {"model_loader.gguf", "model_loader.model_deck.text_llm"}:
            if isinstance(diag, dict):
                diag["model_resolver"]["provider_loader_unsupported"] = loader_id
            return None
        slot = "text_llm_main"
        try:
            loaded = gguf.get_model_for(sid_pref, slot)
        except Exception:
            loaded = None
        if loaded is not None:
            return loaded
        try:
            loaded = gguf.get_model_for("_default", slot)
        except Exception:
            loaded = None
        if loaded is not None:
            return loaded
        settings = dict(provider.get("settings") or {})
        settings.setdefault("model_id", model_id)
        try:
            res = _call_maybe_async(gguf.load_for, sid_pref, slot, settings=settings)
        except Exception as exc:
            if isinstance(diag, dict):
                diag["model_resolver"]["load_for_exception"] = str(exc)
            return None
        if isinstance(diag, dict):
            diag["model_resolver"]["load_for_result"] = res
        if not isinstance(res, dict) or not res.get("ok"):
            return None
        try:
            loaded2 = gguf.get_model_for(sid_pref, slot) or gguf.get_model_for("_default", slot)
            if loaded2 is not None and isinstance(diag, dict):
                diag["model_resolver"]["loaded_after_load_for"] = True
            return loaded2
        except Exception:
            return None

    def _resolve_chat_model(preferred_sid: str | None = None, diag: Dict[str, Any] | None = None) -> Any:
        mf = getattr(app.state, "model", None)
        model_obj = None
        try:
            model_obj = mf() if callable(mf) else mf
        except Exception:
            model_obj = None
        if model_obj is not None and isinstance(diag, dict):
            diag.setdefault("model_resolver", {})
            diag["model_resolver"]["from_app_state_model"] = True
        # Fallback to loaded session model if direct accessor is unavailable.
        if model_obj is None:
            try:
                sid = str(preferred_sid or "").strip() or "_default"
                mm = getattr(app.state, "model_manager", None)
                if mm is not None and hasattr(mm, "get_for"):
                    model_obj = mm.get_for(sid)
                    if model_obj is not None and isinstance(diag, dict):
                        diag.setdefault("model_resolver", {})
                        diag["model_resolver"]["from_model_manager_sid"] = sid
            except Exception:
                model_obj = None
        if model_obj is None:
            model_obj = _ensure_main_text_model_loaded(preferred_sid, diag)
        return model_obj

    def _load_learning() -> List[Dict[str, Any]]:
        store = getattr(app.state, "agent_workflow_learning", None)
        if isinstance(store, list):
            return list(store)
        if not os.path.isfile(learning_path):
            app.state.agent_workflow_learning = []
            return []
        try:
            with open(learning_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                app.state.agent_workflow_learning = data
                return list(data)
        except Exception:
            pass
        app.state.agent_workflow_learning = []
        return []

    def _save_learning(rows: List[Dict[str, Any]]) -> None:
        app.state.agent_workflow_learning = list(rows)
        with open(learning_path, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=True, indent=2)

    def _resolve_target_repo_scan_base(raw_target_repo_root: str) -> str:
        raw = str(raw_target_repo_root or "").strip().replace("\\", "/")
        if not raw:
            return root
        if os.path.isabs(raw):
            abs_raw = os.path.abspath(raw)
            if os.path.isdir(abs_raw):
                return abs_raw
        else:
            rel_raw = os.path.abspath(os.path.join(root, raw.strip("/").replace("/", os.sep)))
            if os.path.isdir(rel_raw):
                return rel_raw

        low = raw.lower().strip("/")
        markers = [
            "data/agent_workflow/repo",
            "llmloader2/data/agent_workflow/repo",
        ]
        if any(marker in low for marker in markers):
            candidates = [
                os.path.join(root, "data", "agent_workflow", "repo"),
                os.path.join(_framework_data_dir(app), "agent_workflow", "repo"),
            ]
            for candidate in candidates:
                if os.path.isdir(candidate):
                    return os.path.abspath(candidate)
        return os.path.abspath(raw if os.path.isabs(raw) else os.path.join(root, raw.strip("/").replace("/", os.sep)))

    def _well_known_agent_workflow_repo_dir() -> str:
        candidates = [
            os.path.join(_framework_data_dir(app), "agent_workflow", "repo"),
            os.path.join(root, "llmloader2", "data", "agent_workflow", "repo"),
            os.path.join(root, "data", "agent_workflow", "repo"),
        ]
        for candidate in candidates:
            if os.path.isdir(candidate):
                return os.path.abspath(candidate)
        return ""

    def _resolve_scan_base_with_fallback(
        *,
        ctx: Dict[str, Any],
        params: Dict[str, Any],
        raw_target_repo_root: str = "",
        raw_path: str = "",
        raw_base_prefix: str = "",
    ) -> str:
        settings = ctx.get("settings") if isinstance(ctx, dict) and isinstance(ctx.get("settings"), dict) else {}
        router_plugin_settings = (
            settings.get("router_plugin_settings")
            if isinstance(settings, dict) and isinstance(settings.get("router_plugin_settings"), dict)
            else {}
        )
        agent_workflow_settings = (
            router_plugin_settings.get("agent_workflow")
            if isinstance(router_plugin_settings.get("agent_workflow"), dict)
            else {}
        )
        candidates: List[str] = []
        for raw in (
            raw_target_repo_root,
            params.get("agent_workflow_target_repo_root"),
            params.get("target_repo_root"),
            ctx.get("agent_workflow_target_repo_root") if isinstance(ctx, dict) else None,
            ctx.get("target_repo_root") if isinstance(ctx, dict) else None,
            settings.get("agent_workflow_target_repo_root") if isinstance(settings, dict) else None,
            settings.get("target_repo_root") if isinstance(settings, dict) else None,
            settings.get("selected_repo_root") if isinstance(settings, dict) else None,
            agent_workflow_settings.get("target_repo_root") if isinstance(agent_workflow_settings, dict) else None,
            raw_base_prefix,
            raw_path,
        ):
            sval = str(raw or "").strip().replace("\\", "/")
            if sval and sval not in candidates:
                candidates.append(sval)
        for candidate in candidates:
            resolved = _resolve_target_repo_scan_base(candidate)
            if os.path.isdir(resolved):
                return resolved
        known_repo = _well_known_agent_workflow_repo_dir()
        if known_repo:
            rel_path = _normalize_repo_user_path(raw_path or raw_base_prefix or "")
            if rel_path and not os.path.isabs(rel_path):
                abs_candidate = os.path.abspath(os.path.join(known_repo, rel_path.replace("/", os.sep)))
                if os.path.exists(abs_candidate):
                    return known_repo
            if candidates:
                return known_repo
        scan_base_hint = str(raw_target_repo_root or raw_base_prefix or raw_path or "").strip()
        return _resolve_target_repo_scan_base(scan_base_hint)

    def _tool_error_payload(code: str, message: str, data: Dict[str, Any] | None = None) -> Dict[str, Any]:
        payload = dict(data or {})
        payload["error_code"] = str(code or "").strip() or "UNKNOWN_ERROR"
        return {
            "ok": False,
            "error_code": payload["error_code"],
            "data": payload,
            "warnings": [str(message or "").strip()] if str(message or "").strip() else [],
        }

    def repo_tree(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        max_files = int(params.get("max_files") or 200)
        raw_base_prefix = str(
            params.get("base_prefix")
            or params.get("path")
            or params.get("target")
            or ""
        ).strip().replace("\\", "/")
        raw_target_repo_root = str(params.get("target_repo_root") or "").strip().replace("\\", "/")
        scan_base = _resolve_scan_base_with_fallback(
            ctx=ctx,
            params=params,
            raw_target_repo_root=raw_target_repo_root,
            raw_base_prefix=raw_base_prefix,
        )
        if not os.path.isdir(scan_base):
            return {"ok": False, "data": {"root": root, "scan_root": scan_base, "files": [], "truncated": False}, "warnings": ["target_repo_root_not_found"]}

        scan_root = scan_base
        base_prefix = raw_base_prefix.strip("/")
        if base_prefix and base_prefix not in {".", "./"}:
            normalized_prefix = _normalize_repo_user_path(raw_base_prefix)
            if os.path.isabs(normalized_prefix):
                candidate = os.path.abspath(normalized_prefix)
                allowed_root = os.path.abspath(root)
            else:
                candidate = os.path.abspath(os.path.join(scan_base, normalized_prefix.replace("/", os.sep)))
                allowed_root = scan_base
            if not (candidate == allowed_root or candidate.startswith(allowed_root + os.sep)):
                return {"ok": False, "data": {}, "warnings": [f"base_prefix_outside_workspace:{base_prefix}"]}
            if not os.path.isdir(candidate):
                return {"ok": True, "data": {"root": scan_base, "files": [], "truncated": False, "scan_root": candidate}, "warnings": [f"base_prefix_missing:{base_prefix}"]}
            scan_root = candidate
        out: List[str] = []
        for base, dirs, files in os.walk(scan_root):
            dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", ".venv", "node_modules"}]
            for fn in files:
                rel = os.path.relpath(os.path.join(base, fn), root)
                out.append(rel.replace("\\", "/"))
                if len(out) >= max_files:
                    return {"ok": True, "data": {"root": root, "files": out, "truncated": True, "scan_root": scan_root}, "warnings": []}
        return {"ok": True, "data": {"root": root, "files": out, "truncated": False, "scan_root": scan_root}, "warnings": []}

    def repo_context(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        max_files = int(params.get("max_files") or 600)
        raw_base_prefix = str(
            params.get("base_prefix")
            or params.get("path")
            or params.get("target")
            or ""
        ).strip().replace("\\", "/")
        raw_target_repo_root = str(params.get("target_repo_root") or "").strip().replace("\\", "/")
        scan_base = _resolve_scan_base_with_fallback(
            ctx=ctx,
            params=params,
            raw_target_repo_root=raw_target_repo_root,
            raw_base_prefix=raw_base_prefix,
        )
        if not os.path.isdir(scan_base):
            return {
                "ok": False,
                "data": {"root": root, "file_count_scanned": 0, "top_extensions": [], "truncated": False, "scan_root": scan_base},
                "warnings": ["target_repo_root_not_found"],
            }
        scan_root = scan_base
        base_prefix = raw_base_prefix.strip("/")
        if base_prefix and base_prefix not in {".", "./"}:
            normalized_prefix = _normalize_repo_user_path(raw_base_prefix)
            if os.path.isabs(normalized_prefix):
                candidate = os.path.abspath(normalized_prefix)
                allowed_root = os.path.abspath(root)
            else:
                candidate = os.path.abspath(os.path.join(scan_base, normalized_prefix.replace("/", os.sep)))
                allowed_root = scan_base
            if not (candidate == allowed_root or candidate.startswith(allowed_root + os.sep)):
                return {"ok": False, "data": {}, "warnings": [f"base_prefix_outside_workspace:{base_prefix}"]}
            if not os.path.isdir(candidate):
                return {
                    "ok": True,
                    "data": {"root": root, "file_count_scanned": 0, "top_extensions": [], "truncated": False, "scan_root": candidate},
                    "warnings": [f"base_prefix_missing:{base_prefix}"],
                }
            scan_root = candidate
        total = 0
        ext = Counter()
        for base, dirs, files in os.walk(scan_root):
            dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", ".venv", "node_modules"}]
            for fn in files:
                total += 1
                ext_name = os.path.splitext(fn)[1].lower() or "<none>"
                ext[ext_name] += 1
                if total >= max_files:
                    return {
                        "ok": True,
                        "data": {
                            "root": root,
                            "file_count_scanned": total,
                            "top_extensions": ext.most_common(12),
                            "truncated": True,
                            "scan_root": scan_root,
                        },
                        "warnings": [],
                    }
        return {
            "ok": True,
            "data": {
                "root": root,
                "file_count_scanned": total,
                "top_extensions": ext.most_common(12),
                "truncated": False,
                "scan_root": scan_root,
            },
            "warnings": [],
        }

    def repo_find_file(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        res = repo_find_file_skill_run({"app": app, **(ctx or {})}, dict(params or {}))
        if not isinstance(res, dict):
            return _tool_error_payload("TOOL_RUNTIME_ERROR", "repo_find_file_invalid_response")
        warnings = list(res.get("warnings") or []) if isinstance(res.get("warnings"), list) else []
        if not bool(res.get("ok")):
            error_code = "TOOL_RUNTIME_ERROR"
            if any(str(w).startswith("filename_required") for w in warnings):
                error_code = "FILENAME_REQUIRED"
            elif any(str(w).startswith("path_outside_repo") for w in warnings):
                error_code = "PATH_OUTSIDE_SCOPE"
            elif any(str(w).startswith("path_not_found") for w in warnings):
                error_code = "SEARCH_ROOT_NOT_FOUND"
            data = dict(res.get("data") or {}) if isinstance(res.get("data"), dict) else {}
            data["error_code"] = error_code
            res["data"] = data
            res["error_code"] = error_code
        return res

    def _uploads_root_path() -> str:
        settings = _runtime_base_settings()
        explicit = str(settings.get("uploads_dir") or "").strip()
        if explicit:
            return os.path.abspath(explicit)
        data_dir = getattr(getattr(app, "state", None), "data_dir", None)
        candidates = []
        if isinstance(data_dir, str) and data_dir.strip():
            candidates.append(os.path.join(os.path.abspath(data_dir), "uploads"))
        candidates.extend([
            os.path.join(root, "llmloader2", "data", "uploads"),
            os.path.join(root, "data", "uploads"),
            os.path.join(root, "llmloader2", "uploads"),
            os.path.join(root, "uploads"),
        ])
        for cand in candidates:
            if os.path.isdir(cand):
                return os.path.abspath(cand)
        return os.path.abspath(candidates[0])

    def _resolve_virtual_upload_path(raw_path: str) -> str:
        raw = str(raw_path or "").strip().replace("\\", "/")
        if not raw.startswith("/uploads/"):
            return raw_path
        name = raw.split("/uploads/", 1)[-1].lstrip("/")
        if not name:
            return raw_path
        uploads_root = _uploads_root_path()
        return os.path.join(uploads_root, name.replace("/", os.sep))

    def repo_read(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        raw_path = str(params.get("path") or params.get("target") or "").strip().replace("\\", "/")
        raw_path = str(_resolve_virtual_upload_path(raw_path) or raw_path).strip().replace("\\", "/")
        if not raw_path:
            return _tool_error_payload("PATH_REQUIRED", "path_required")
        rel = _normalize_repo_user_path(raw_path)
        max_chars = int(params.get("max_chars") or 4000)
        max_chars = max(200, min(40000, max_chars))
        start_char = int(params.get("start_char") or 0)
        start_char = max(0, start_char)
        raw_target_repo_root = str(params.get("target_repo_root") or "").strip().replace("\\", "/")
        scan_base = _resolve_scan_base_with_fallback(
            ctx=ctx,
            params=params,
            raw_target_repo_root=raw_target_repo_root,
            raw_path=raw_path,
        )
        if not os.path.isdir(scan_base):
            return _tool_error_payload("TARGET_REPO_ROOT_NOT_FOUND", "target_repo_root_not_found", {"scan_root": scan_base})
        allowed_root = scan_base
        if os.path.isabs(rel):
            abs_path = os.path.abspath(rel)
            allowed_root = os.path.abspath(root)
        else:
            abs_path = os.path.abspath(os.path.join(scan_base, rel.replace("/", os.sep)))
        if not (abs_path == allowed_root or abs_path.startswith(allowed_root + os.sep)):
            return _tool_error_payload("PATH_OUTSIDE_SCOPE", f"path_outside_workspace:{rel}", {"path": rel, "scan_root": scan_base})
        if not os.path.isfile(abs_path):
            return _tool_error_payload("FILE_NOT_FOUND", f"missing_file:{rel}", {"path": rel, "scan_root": scan_base})
        try:
            preview = read_repo_file_preview(abs_path, max_chars=max_chars + start_char)
            full_txt = str(preview.get("text") or "")
        except Exception as exc:
            return _tool_error_payload("READ_ERROR", f"read_error:{exc}", {"path": rel, "scan_root": scan_base})
        total_chars = len(full_txt)
        if start_char > total_chars:
            start_char = total_chars
        txt = full_txt[start_char : start_char + max_chars]
        truncated = (start_char + len(txt)) < total_chars
        return {
            "ok": True,
            "data": {
                "path": rel,
                "scan_root": scan_base,
                "content": txt,
                "truncated": truncated,
                "max_chars": max_chars,
                "start_char": start_char,
                "total_chars": total_chars,
            },
            "warnings": [],
        }

    def repo_read_range(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from ..agent_flow.skills.repo.read_range import run as repo_read_range_run
        except Exception as exc:
            return _tool_error_payload("TOOL_IMPORT_FAILED", f"repo_read_range_import_failed:{exc}")
        res = repo_read_range_run({"app": app, **(ctx or {})}, dict(params or {}))
        if not isinstance(res, dict):
            return _tool_error_payload("TOOL_RUNTIME_ERROR", "repo_read_range_invalid_response")
        warnings = list(res.get("warnings") or []) if isinstance(res.get("warnings"), list) else []
        if not bool(res.get("ok")):
            data = dict(res.get("data") or {}) if isinstance(res.get("data"), dict) else {}
            if any(str(w).startswith("missing_path") for w in warnings):
                data["error_code"] = "PATH_REQUIRED"
            elif any(str(w).startswith("path_outside_repo") for w in warnings):
                data["error_code"] = "PATH_OUTSIDE_SCOPE"
            elif any(str(w).startswith("file_not_found") for w in warnings):
                data["error_code"] = "FILE_NOT_FOUND"
            else:
                data["error_code"] = "TOOL_RUNTIME_ERROR"
            res["data"] = data
            res["error_code"] = data["error_code"]
        return res

    def repo_search(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from ..agent_flow.skills.repo.search import run as repo_search_run
        except Exception as exc:
            return _tool_error_payload("TOOL_IMPORT_FAILED", f"repo_search_import_failed:{exc}")
        res = repo_search_run({"app": app, **(ctx or {})}, dict(params or {}))
        if not isinstance(res, dict):
            return _tool_error_payload("TOOL_RUNTIME_ERROR", "repo_search_invalid_response")
        warnings = list(res.get("warnings") or []) if isinstance(res.get("warnings"), list) else []
        if not bool(res.get("ok")):
            data = dict(res.get("data") or {}) if isinstance(res.get("data"), dict) else {}
            if any(str(w).startswith("query_required") for w in warnings):
                data["error_code"] = "QUERY_REQUIRED"
            elif any(str(w).startswith("path_outside_repo") for w in warnings):
                data["error_code"] = "PATH_OUTSIDE_SCOPE"
            elif any(str(w).startswith("path_not_found") for w in warnings):
                data["error_code"] = "SEARCH_ROOT_NOT_FOUND"
            else:
                data["error_code"] = "TOOL_RUNTIME_ERROR"
            res["data"] = data
            res["error_code"] = data["error_code"]
        return res

    def repo_ingest(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        target_repo_root = str(params.get("target_repo_root") or "").strip().replace("\\", "/").strip("/")
        raw_paths = params.get("paths")
        use_paths = [str(x or "").strip().replace("\\", "/") for x in raw_paths] if isinstance(raw_paths, list) else []
        single = str(params.get("path") or params.get("target") or "").strip().replace("\\", "/")
        if single:
            use_paths.append(single)
        use_paths = [p for p in use_paths if p]
        if not use_paths:
            return {"ok": False, "data": {}, "warnings": ["path_required"]}
        user_rag = getattr(app.state, "user_rag", None)
        if user_rag is None:
            return {"ok": False, "data": {}, "warnings": ["user_rag_disabled"]}
        model_obj = _ensure_main_text_model_loaded(str(ctx.get("sid") or "").strip() or "_default", {})
        tokenizer = None
        try:
            tok = getattr(model_obj, "tokenizer", None)
            if tok is not None and callable(getattr(tok, "encode", None)):
                tokenizer = tok
        except Exception:
            tokenizer = None
        if tokenizer is None:
            class FallbackTokenizer:
                def encode(self, text: str):
                    s = str(text or "")
                    parts = [p for p in s.replace("\r", " ").replace("\n", " ").split(" ") if p]
                    return list(range(len(parts)))
            tokenizer = FallbackTokenizer()
        try:
            import repo_ingest as repo_ingest_mod
        except Exception as exc:
            return {"ok": False, "data": {}, "warnings": [f"repo_ingest_import_failed:{exc}"]}
        ingested: List[Dict[str, Any]] = []
        warnings: List[str] = []
        for rel_in in use_paths[:20]:
            rel = rel_in.strip("/")
            if target_repo_root and not rel.startswith(target_repo_root + "/") and rel != target_repo_root:
                rel = f"{target_repo_root}/{rel}".strip("/")
            abs_target = os.path.abspath(os.path.join(root, rel.replace("/", os.sep)))
            if not abs_target.startswith(root):
                warnings.append(f"path_outside_workspace:{rel_in}")
                continue
            if os.path.isdir(abs_target):
                abs_dir = abs_target
                include_globs = None
                rel_scope = rel.replace("\\", "/")
            elif os.path.isfile(abs_target):
                abs_dir = os.path.dirname(abs_target)
                include_globs = [os.path.basename(abs_target)]
                rel_scope = rel.replace("\\", "/")
            else:
                warnings.append(f"missing_path:{rel_in}")
                continue
            try:
                stats = repo_ingest_mod.ingest_dir_to_user_rag_cold(
                    user_rag,
                    str(ctx.get("sid") or ""),
                    str(params.get("repo_id") or "current"),
                    abs_dir,
                    tokenizer,
                    max_file_bytes=int(params.get("max_file_bytes") or 220000),
                    include_lang=params.get("include_lang"),
                    exclude_globs=params.get("exclude_globs"),
                    chunk_lines=int(params.get("chunk_lines") or 220),
                    version=params.get("version"),
                    include_globs=include_globs,
                )
                ingested.append({"path": rel_scope, "dir": abs_dir, "stats": stats})
            except Exception as exc:
                warnings.append(f"repo_ingest_failed:{rel_scope}:{exc}")
        return {
            "ok": bool(ingested) and not warnings,
            "data": {
                "ingested": ingested,
                "requested_paths": use_paths,
            },
            "warnings": warnings,
        }

    def rag_search(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        query = str(params.get("query") or "").strip()
        if not query:
            return {"ok": True, "data": {"query": "", "matches": []}, "warnings": ["empty_query"]}
        base_prefix = str(
            params.get("base_prefix")
            or params.get("path")
            or params.get("target")
            or ""
        ).strip().replace("\\", "/").strip("/")
        target_repo_root = str(params.get("target_repo_root") or "").strip().replace("\\", "/").strip("/")
        if target_repo_root and base_prefix:
            if not base_prefix.startswith(target_repo_root + "/") and base_prefix != target_repo_root:
                base_prefix = f"{target_repo_root}/{base_prefix}".strip("/")
        elif target_repo_root:
            base_prefix = target_repo_root
        scan_root = root
        if base_prefix:
            candidate = os.path.abspath(os.path.join(root, base_prefix.replace("/", os.sep)))
            if not candidate.startswith(root):
                return {"ok": False, "data": {}, "warnings": [f"base_prefix_outside_workspace:{base_prefix}"]}
            if not os.path.isdir(candidate):
                return {
                    "ok": True,
                    "data": {"query": query, "matches": [], "scan_root": candidate},
                    "warnings": [f"base_prefix_missing:{base_prefix}"],
                }
            scan_root = candidate
        terms = [t for t in query.lower().split() if t]
        matches: List[Dict[str, Any]] = []
        for base, dirs, files in os.walk(scan_root):
            dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", ".venv", "node_modules"}]
            for fn in files:
                path = os.path.join(base, fn)
                if not fn.lower().endswith((".py", ".js", ".ts", ".md", ".json")):
                    continue
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                        txt = fh.read(16000).lower()
                except Exception:
                    continue
                score = sum(1 for t in terms if t in txt)
                if score > 0:
                    matches.append({"file": os.path.relpath(path, root).replace("\\", "/"), "score": score})
                if len(matches) >= 30:
                    break
            if len(matches) >= 30:
                break
        matches.sort(key=lambda x: int(x.get("score") or 0), reverse=True)
        return {"ok": True, "data": {"query": query, "matches": matches[:15], "scan_root": scan_root}, "warnings": []}

    def tests_smoke(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        files = params.get("files")
        if not isinstance(files, list) or not files:
            return {
                "ok": True,
                "data": {"executed": False, "passed": True, "checked_files": [], "errors": []},
                "warnings": ["no_files_provided_for_smoke_compile"],
            }
        checked: List[str] = []
        errs: List[str] = []
        for item in files:
            rel = str(item or "").strip().replace("/", os.sep)
            if not rel.lower().endswith(".py"):
                continue
            path = os.path.abspath(os.path.join(root, rel))
            if not path.startswith(root):
                errs.append(f"outside_workspace:{item}")
                continue
            if not os.path.isfile(path):
                errs.append(f"missing_file:{item}")
                continue
            try:
                py_compile.compile(path, doraise=True)
                checked.append(item)
            except Exception as exc:
                errs.append(f"{item}:{exc}")
        return {
            "ok": len(errs) == 0,
            "data": {"executed": True, "passed": len(errs) == 0, "checked_files": checked, "errors": errs},
            "warnings": [],
        }

    def _normalize_rel_path(rel: str) -> str:
        rel_clean = str(rel or "").strip().replace("/", os.sep).replace("\\", os.sep)
        root_base = os.path.basename(root.rstrip("\\/")).lower()
        prefix = f"llmloader2{os.sep}"
        if root_base == "llmloader2" and rel_clean.lower().startswith(prefix):
            rel_clean = rel_clean[len(prefix) :]
        return rel_clean

    def _session_scoped_rel_path(rel: str, ctx: Dict[str, Any]) -> str:
        rel_clean = _normalize_rel_path(rel)
        sid = str((ctx or {}).get("sid") or "").strip() or "default"
        sid_safe = re.sub(r"[^A-Za-z0-9_.-]", "_", sid)
        # Already session-scoped for this sid: do not scope again.
        already_scoped = os.path.join("data", "agent_workflow", "sessions", sid_safe) + os.sep
        if rel_clean.lower().startswith(already_scoped.lower()):
            return rel_clean
        p1 = f"llmloader2{os.sep}data{os.sep}agent_workflow{os.sep}"
        p2 = f"data{os.sep}agent_workflow{os.sep}"
        low = rel_clean.lower()
        if low.startswith(p1):
            tail = rel_clean[len(p1) :]
            return os.path.join("data", "agent_workflow", "sessions", sid_safe, tail)
        if low.startswith(p2):
            tail = rel_clean[len(p2) :]
            return os.path.join("data", "agent_workflow", "sessions", sid_safe, tail)
        return rel_clean

    def _strip_repo_virtual_prefixes(rel_clean: str) -> str:
        s = str(rel_clean or "").replace("\\", "/").strip("/")
        prefixes = [
            "llmloader2/data/agent_workflow/repo/",
            "data/agent_workflow/repo/",
            "llmloader2/data/agent_workflow/sessions/",
            "data/agent_workflow/sessions/",
        ]
        low = s.lower()
        for p in prefixes:
            if low.startswith(p):
                tail = s[len(p) :]
                # sessions/<sid>/<tail> -> <tail>
                if "sessions/" in p:
                    parts = tail.split("/", 1)
                    return parts[1] if len(parts) > 1 else ""
                return tail
        return s

    def _normalize_repo_user_path(raw_path: str) -> str:
        text = str(raw_path or "").strip().replace("\\", "/")
        low = text.lower().lstrip("/")
        if any(low.startswith(prefix) for prefix in (
            "data/agent_workflow/repo/",
            "llmloader2/data/agent_workflow/repo/",
            "data/agent_workflow/sessions/",
            "llmloader2/data/agent_workflow/sessions/",
        )):
            return _strip_repo_virtual_prefixes(text)
        if text.startswith("/") or re.match(r"^[A-Za-z]:/", text):
            return text
        return _strip_repo_virtual_prefixes(text)


    def _target_repo_scoped_rel_path(rel: str, target_repo_root: str, ctx: Dict[str, Any]) -> str:
        rel_clean = _strip_repo_virtual_prefixes(_normalize_rel_path(rel))
        rel_clean = rel_clean.replace("\\", "/").strip("/")
        tr_raw = str(target_repo_root or "").strip()
        if tr_raw:
            scan_base = _resolve_target_repo_scan_base(tr_raw)
            scan_base_abs = os.path.abspath(scan_base)
            root_abs = os.path.abspath(root)
            if scan_base_abs == root_abs:
                return rel_clean.replace("/", os.sep)
            if scan_base_abs.startswith(root_abs + os.sep):
                base_rel = os.path.relpath(scan_base_abs, root_abs).replace("\\", "/").strip("/")
                if rel_clean.startswith(base_rel + "/") or rel_clean == base_rel:
                    return rel_clean.replace("/", os.sep)
                return f"{base_rel}/{rel_clean}".replace("/", os.sep)
            tr = tr_raw.replace("\\", "/").strip("/")
            if rel_clean.startswith(tr + "/") or rel_clean == tr:
                return rel_clean.replace("/", os.sep)
            return f"{tr}/{rel_clean}".replace("/", os.sep)
        return _session_scoped_rel_path(rel, ctx)

    def _slugify_request_title(text: str) -> str:
        raw = re.sub(r"[^A-Za-z0-9]+", "_", str(text or "").strip().lower()).strip("_")
        raw = re.sub(r"_+", "_", raw)
        if not raw:
            return "generated_app"
        parts = [p for p in raw.split("_") if p and p not in {"create", "generate", "build", "write", "make", "me", "a", "an", "the", "in", "with", "and", "to"}]
        slug = "_".join(parts[:8]).strip("_")
        return slug[:64] or "generated_app"

    def _rewrite_generated_write_rel(rel: str, target_repo_root: str, ctx: Dict[str, Any], request_title: str) -> str:
        rel_norm = _normalize_rel_path(rel).replace("\\", "/").strip("/")
        if not rel_norm or not str(target_repo_root or "").strip() or not str(request_title or "").strip():
            return rel_norm or rel
        base = os.path.basename(rel_norm)
        stem, ext = os.path.splitext(base)
        ext = ext.lower()
        if ext not in {".html", ".js", ".css", ".ts", ".tsx", ".jsx", ".json", ".md", ".py"}:
            return rel_norm
        generic_names = {
            "index.html",
            "index.js",
            "game.html",
            "game.js",
            "app.html",
            "app.js",
            "main.js",
            "main.html",
            "app.py",
            "main.py",
            "server.py",
            "backend.py",
        }
        top_level = "/" not in rel_norm
        slug = _slugify_request_title(request_title)
        rel_scoped = _target_repo_scoped_rel_path(rel_norm, target_repo_root, ctx)
        abs_current = _safe_path(rel_scoped, ctx, already_scoped=True)
        should_rewrite = bool(top_level and (base.lower() in generic_names or os.path.exists(abs_current)))
        if not should_rewrite:
            return rel_norm
        candidate_slug = slug
        n = 1
        while True:
            candidate_dir = candidate_slug
            candidate_file = f"{candidate_slug}{ext}"
            candidate_rel = f"{candidate_dir}/{candidate_file}".replace("/", os.sep)
            scoped_candidate = _target_repo_scoped_rel_path(candidate_rel, target_repo_root, ctx)
            abs_candidate = _safe_path(scoped_candidate, ctx, already_scoped=True)
            if not os.path.exists(abs_candidate):
                return candidate_rel.replace("\\", "/")
            n += 1
            candidate_slug = f"{slug}_{n}"

    def _safe_path(rel: str, ctx: Dict[str, Any] | None = None, *, already_scoped: bool = False) -> str:
        rel_clean = str(rel or "").strip() if already_scoped else _session_scoped_rel_path(rel, ctx or {})
        path = os.path.abspath(os.path.join(root, rel_clean))
        if not path.startswith(root):
            raise ValueError(f"path_outside_workspace:{rel}")
        return path

    def _default_workflow_repo_cwd() -> str:
        candidates = [
            os.path.join(root, "data", "agent_workflow", "repo"),
            os.path.join(root, "llmloader2", "data", "agent_workflow", "repo"),
        ]
        for candidate in candidates:
            if os.path.isdir(candidate):
                return os.path.abspath(candidate)
        return root

    def code_apply_patch(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        ops = params.get("ops")
        if not isinstance(ops, list) or not ops:
            return {"ok": False, "data": {}, "warnings": ["ops_required"]}
        target_repo_root = str(params.get("target_repo_root") or "").strip()
        request_title = str(params.get("request_title") or "").strip()
        changed: List[str] = []
        errors: List[str] = []
        rewritten_paths: Dict[str, str] = {}
        requested_paths: List[str] = []
        final_paths: List[str] = []
        for i, raw in enumerate(ops):
            if not isinstance(raw, dict):
                errors.append(f"op_{i}:invalid_op")
                continue
            op = str(raw.get("op") or "").strip().lower()
            rel = str(raw.get("path") or "").strip()
            if not rel:
                errors.append(f"op_{i}:path_required")
                continue
            rel_key = rel.replace("\\", "/")
            requested_paths.append(rel_key)
            if rel_key in rewritten_paths:
                rel = rewritten_paths.get(rel_key) or rel
            elif op == "write" and request_title:
                rel = _rewrite_generated_write_rel(rel, target_repo_root, ctx, request_title)
                rewritten_paths[rel_key] = rel
            final_paths.append(str(rel or "").replace("\\", "/"))
            try:
                rel_scoped = _target_repo_scoped_rel_path(rel, target_repo_root, ctx)
                path = _safe_path(rel_scoped, ctx, already_scoped=True)
            except Exception as exc:
                errors.append(f"op_{i}:{exc}")
                continue
            try:
                if op == "write":
                    content = str(raw.get("content") or "")
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    if os.path.exists(path) and raw.get("if_missing"):
                        errors.append(f"op_{i}:file_exists:{rel_scoped}")
                        continue
                    with open(path, "w", encoding="utf-8", newline="") as fh:
                        fh.write(content)
                    changed.append(rel_scoped.replace("\\", "/"))
                elif op == "replace":
                    search = str(raw.get("search") or "")
                    repl = str(raw.get("replace") or "")
                    count = int(raw.get("count") or 1)
                    if not os.path.isfile(path):
                        errors.append(f"op_{i}:missing_file:{rel_scoped}")
                        continue
                    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                        txt = fh.read()
                    if search not in txt:
                        errors.append(f"op_{i}:search_not_found:{rel_scoped}")
                        continue
                    new_txt = txt.replace(search, repl, count)
                    with open(path, "w", encoding="utf-8", newline="") as fh:
                        fh.write(new_txt)
                    changed.append(rel_scoped.replace("\\", "/"))
                elif op == "append":
                    content = str(raw.get("content") or "")
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "a", encoding="utf-8", newline="") as fh:
                        fh.write(content)
                    changed.append(rel_scoped.replace("\\", "/"))
                else:
                    errors.append(f"op_{i}:unknown_op:{op}")
            except Exception as exc:
                errors.append(f"op_{i}:{rel_scoped}:{exc}")
        return {
            "ok": len(errors) == 0,
            "data": {
                "changed_files": changed,
                "errors": errors,
                "op_count": len(ops),
                "path": (changed[0] if changed else (final_paths[0] if final_paths else "")),
                "requested_paths": requested_paths,
                "final_paths": final_paths,
                "rewritten_paths": [
                    {"requested": k, "final": str(v or "").replace("\\", "/")}
                    for k, v in rewritten_paths.items()
                ],
            },
            "warnings": [],
        }

    def repo_write(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        rel = str(params.get("path") or params.get("file_path") or params.get("target") or "").strip()
        if not rel:
            return {"ok": False, "data": {}, "warnings": ["path_required"]}
        content = str(params.get("content") or "")
        target_repo_root = str(params.get("target_repo_root") or "").strip()
        request_title = str(params.get("request_title") or "").strip()
        mapped = {
            "ops": [{"op": "write", "path": rel, "content": content}],
            "target_repo_root": target_repo_root,
            "request_title": request_title,
        }
        return code_apply_patch(ctx, mapped)

    def _parse_pytest_output(out: str) -> Dict[str, Any]:
        text = str(out or "")
        fails = re.findall(r"^FAILED\s+([^\s]+)\s+-\s+(.+)$", text, flags=re.MULTILINE)
        if not fails:
            fails = re.findall(r"^FAILED\s+([^\s]+)$", text, flags=re.MULTILINE)
            fails = [(x, "") for x in fails]
        parsed = [{"test": a, "error": b} for (a, b) in fails]
        m = re.search(r"=+\s*(.+?)\s*=+\s*$", text, flags=re.MULTILINE)
        summary = m.group(1).strip() if m else ""
        return {"framework": "pytest", "failures": parsed, "summary": summary}

    def _parse_npm_output(out: str) -> Dict[str, Any]:
        text = str(out or "")
        failed_lines = []
        for ln in text.splitlines():
            low = ln.lower()
            if "failed" in low or "error" in low:
                failed_lines.append(ln.strip())
        return {"framework": "npm", "failures": failed_lines[:50], "summary": failed_lines[0] if failed_lines else ""}

    def _parse_unittest_output(out: str) -> Dict[str, Any]:
        text = str(out or "")
        failures: List[Dict[str, str]] = []
        for m in re.finditer(r"^(FAIL|ERROR):\s+([^\s(]+)", text, flags=re.MULTILINE):
            failures.append({"test": str(m.group(2) or "").strip(), "error": str(m.group(1) or "").strip()})
        summary = ""
        for ln in reversed(text.splitlines()):
            s = str(ln or "").strip()
            if s:
                summary = s
                break
        return {"framework": "unittest", "failures": failures, "summary": summary}

    def _fallback_file_checks(cwd: str, changed_files: List[str]) -> Dict[str, Any]:
        runs: List[Dict[str, Any]] = []
        warnings: List[str] = []
        if not changed_files:
            return {"ok": False, "data": {"executed": False, "runs": []}, "warnings": ["no_test_adapter_detected"]}
        all_ok = True
        for rel in changed_files:
            rel_s = str(rel or "").strip()
            if not rel_s:
                continue
            abs_path = os.path.abspath(os.path.join(cwd, rel_s.replace("/", os.sep)))
            if not abs_path.startswith(cwd):
                all_ok = False
                runs.append(
                    {
                        "command": ["fallback", "exists", rel_s],
                        "exit_code": 1,
                        "ok": False,
                        "parsed": {"framework": "fallback", "summary": "path_outside_workspace", "failures": [f"path_outside_workspace:{rel_s}"]},
                        "output_tail": "",
                    }
                )
                continue
            if not os.path.isfile(abs_path):
                all_ok = False
                runs.append(
                    {
                        "command": ["fallback", "exists", rel_s],
                        "exit_code": 1,
                        "ok": False,
                        "parsed": {"framework": "fallback", "summary": "missing_file", "failures": [f"missing_file:{rel_s}"]},
                        "output_tail": "",
                    }
                )
                continue
            ext = os.path.splitext(rel_s)[1].lower()
            if ext == ".py":
                try:
                    py_compile.compile(abs_path, doraise=True)
                    runs.append(
                        {
                            "command": ["python", "-m", "py_compile", rel_s],
                            "exit_code": 0,
                            "ok": True,
                            "parsed": {"framework": "fallback", "summary": "python_compile_ok", "failures": []},
                            "output_tail": "",
                        }
                    )
                except Exception as exc:
                    all_ok = False
                    runs.append(
                        {
                            "command": ["python", "-m", "py_compile", rel_s],
                            "exit_code": 1,
                            "ok": False,
                            "parsed": {"framework": "fallback", "summary": "python_compile_failed", "failures": [f"{rel_s}:{exc}"]},
                            "output_tail": "",
                        }
                    )
            elif ext == ".js":
                try:
                    cp = subprocess.run(["node", "--check", abs_path], cwd=cwd, capture_output=True, text=True, timeout=60, shell=False)
                    out = f"{cp.stdout or ''}\n{cp.stderr or ''}".strip()
                    ok = int(cp.returncode) == 0
                    all_ok = all_ok and ok
                    runs.append(
                        {
                            "command": ["node", "--check", rel_s],
                            "exit_code": int(cp.returncode),
                            "ok": ok,
                            "parsed": {"framework": "fallback", "summary": "node_check_ok" if ok else "node_check_failed", "failures": [] if ok else [out[-400:]]},
                            "output_tail": out[-2000:],
                        }
                    )
                except Exception as exc:
                    all_ok = False
                    warnings.append(f"node_check_error:{rel_s}:{exc}")
                    runs.append(
                        {
                            "command": ["node", "--check", rel_s],
                            "exit_code": 1,
                            "ok": False,
                            "parsed": {"framework": "fallback", "summary": "node_unavailable_or_failed", "failures": [f"{rel_s}:{exc}"]},
                            "output_tail": "",
                        }
                    )
            else:
                runs.append(
                    {
                        "command": ["fallback", "exists", rel_s],
                        "exit_code": 0,
                        "ok": True,
                        "parsed": {"framework": "fallback", "summary": "exists_ok", "failures": []},
                        "output_tail": "",
                    }
                )
        return {"ok": all_ok, "data": {"executed": True, "runs": runs, "all_ok": all_ok}, "warnings": warnings + ["no_test_adapter_detected"]}

    def tests_run_project(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        project_dir = str(params.get("project_dir") or ".")
        target_repo_root = str(params.get("target_repo_root") or "").strip()
        try:
            if project_dir in ("", ".", "./") and not target_repo_root:
                cwd = _default_workflow_repo_cwd()
            elif target_repo_root:
                cwd = _safe_path(_target_repo_scoped_rel_path(project_dir or ".", target_repo_root, ctx), ctx, already_scoped=True)
            else:
                cwd = _safe_path(project_dir, ctx)
        except Exception:
            cwd = _default_workflow_repo_cwd() if project_dir in ("", ".", "./") else root
        timeout = int(params.get("timeout_sec") or 300)
        framework = str(params.get("framework") or "auto").lower()
        commands: List[List[str]] = []
        warnings: List[str] = []

        has_pytest = os.path.isfile(os.path.join(cwd, "pytest.ini")) or os.path.isfile(os.path.join(cwd, "pyproject.toml"))
        tests_dir = os.path.join(cwd, "tests")
        has_unittest = os.path.isdir(tests_dir) and any(
            str(name or "").startswith("test") and str(name or "").endswith(".py")
            for name in os.listdir(tests_dir)
        )
        has_package = os.path.isfile(os.path.join(cwd, "package.json"))
        explicit_framework = framework not in ("", "auto")
        if framework in ("auto", "pytest") and has_pytest:
            commands.append(["python", "-m", "pytest", "-q"])
        if framework == "unittest" and has_unittest:
            commands.append(["python", "-m", "unittest", "discover", "-s", "tests", "-p", "test*.py"])
        elif framework in ("auto", "unittest") and has_unittest and not has_pytest:
            commands.append(["python", "-m", "unittest", "discover", "-s", "tests", "-p", "test*.py"])
        if framework in ("auto", "npm") and has_package:
            commands.append(["npm", "test", "--", "--silent"])
        if not commands:
            changed_files = params.get("changed_files")
            files = [str(x) for x in changed_files] if isinstance(changed_files, list) else []
            result = _fallback_file_checks(cwd, files)
            if explicit_framework:
                warnings = list(result.get("warnings") or [])
                warnings.append(f"requested_framework_not_detected:{framework}")
                result["warnings"] = warnings
            return result

        runs = []
        for cmd in commands:
            try:
                cp = subprocess.run(
                    cmd,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    shell=False,
                )
                out = f"{cp.stdout or ''}\n{cp.stderr or ''}".strip()
                if "pytest" in cmd:
                    parsed = _parse_pytest_output(out)
                elif "unittest" in cmd:
                    parsed = _parse_unittest_output(out)
                else:
                    parsed = _parse_npm_output(out)
                runs.append(
                    {
                        "command": cmd,
                        "exit_code": int(cp.returncode),
                        "ok": int(cp.returncode) == 0,
                        "parsed": parsed,
                        "output_tail": out[-4000:],
                    }
                )
            except subprocess.TimeoutExpired:
                runs.append({"command": cmd, "exit_code": 124, "ok": False, "parsed": {"summary": "timeout"}, "output_tail": ""})
                warnings.append(f"test_timeout:{' '.join(cmd)}")
            except Exception as exc:
                runs.append({"command": cmd, "exit_code": 1, "ok": False, "parsed": {"summary": str(exc)}, "output_tail": ""})
                warnings.append(f"test_error:{' '.join(cmd)}:{exc}")

        all_ok = all(bool(r.get("ok")) for r in runs) if runs else False
        return {"ok": all_ok, "data": {"executed": True, "runs": runs, "all_ok": all_ok}, "warnings": warnings}

    def _find_js_target_from_text(text: str) -> str:
        m = re.search(r"([A-Za-z0-9_./\\-]+\.js)\b", str(text or ""), flags=re.IGNORECASE)
        if not m:
            return ""
        return str(m.group(1) or "").strip().replace("\\", "/")

    def _ensure_html_runner_candidates(user_input: str, plan: Dict[str, Any], candidates: List[List[Dict[str, Any]]]) -> List[List[Dict[str, Any]]]:
        msg = " ".join([str(user_input or ""), str(plan.get("input") or "")]).lower()
        if "html runner" not in msg and "html" not in msg:
            return candidates
        js_path = _find_js_target_from_text(msg)
        if not js_path:
            for cand in candidates:
                for op in cand:
                    if isinstance(op, dict) and str(op.get("op")) == "write" and str(op.get("path", "")).lower().endswith(".js"):
                        js_path = str(op.get("path") or "").replace("\\", "/")
                        break
                if js_path:
                    break
        if not js_path:
            return candidates
        html_path = re.sub(r"\.js$", ".html", js_path, flags=re.IGNORECASE)
        html_script = "./" + os.path.basename(js_path)
        html_content = (
            "<!doctype html>\n"
            "<html><head><meta charset='utf-8'><title>Runner</title></head>\n"
            "<body>\n"
            "<script src='" + html_script + "'></script>\n"
            "</body></html>\n"
        )
        if not candidates:
            return [[{"op": "write", "path": html_path, "content": html_content}]]
        out: List[List[Dict[str, Any]]] = []
        for cand in candidates:
            has_html = any(isinstance(op, dict) and str(op.get("path", "")).replace("\\", "/").lower() == html_path.lower() for op in cand)
            if has_html:
                out.append(cand)
            else:
                out.append(list(cand) + [{"op": "write", "path": html_path, "content": html_content}])
        return out

    def _heuristic_patch_candidates(plan: Dict[str, Any], context: Dict[str, Any], failures: List[Any], user_input: str = "") -> List[List[Dict[str, Any]]]:
        plan_input = str(plan.get("input") or "").strip()
        user_input = str(user_input or "").strip()
        targets = (context.get("targets") or {}) if isinstance(context, dict) else {}
        target_files = list(targets.get("files") or []) if isinstance(targets, dict) else []
        msg = " ".join([plan_input, user_input, json.dumps(failures, ensure_ascii=False)]).lower()
        intent_text = " ".join([plan_input, user_input]).lower()
        if "snake" in msg:
            js_target = "data/agent_workflow/snake_game.js"
            html_target = "data/agent_workflow/snake_game.html"
            explicit_js = _find_js_target_from_text(" ".join([user_input, plan_input]))
            if explicit_js:
                js_target = explicit_js
                html_target = re.sub(r"\.js$", ".html", explicit_js, flags=re.IGNORECASE)
            return _ensure_html_runner_candidates(user_input, plan, [
                [
                    {
                        "op": "write",
                        "path": js_target,
                        "content": (
                            "const canvas = document.getElementById('game');\n"
                            "const ctx = canvas.getContext('2d');\n"
                            "const grid = 20;\n"
                            "let snake = [{x: 160, y: 160}];\n"
                            "let food = {x: 320, y: 320};\n"
                            "let dx = grid;\n"
                            "let dy = 0;\n"
                            "let score = 0;\n"
                            "function placeFood(){\n"
                            "  food.x = Math.floor(Math.random()*20)*grid;\n"
                            "  food.y = Math.floor(Math.random()*20)*grid;\n"
                            "}\n"
                            "document.addEventListener('keydown', (e)=>{\n"
                            "  if(e.key==='ArrowLeft'&&dx===0){dx=-grid;dy=0;}\n"
                            "  if(e.key==='ArrowUp'&&dy===0){dx=0;dy=-grid;}\n"
                            "  if(e.key==='ArrowRight'&&dx===0){dx=grid;dy=0;}\n"
                            "  if(e.key==='ArrowDown'&&dy===0){dx=0;dy=grid;}\n"
                            "});\n"
                            "function loop(){\n"
                            "  const head={x:snake[0].x+dx,y:snake[0].y+dy};\n"
                            "  if(head.x<0||head.x>=400||head.y<0||head.y>=400||snake.some(s=>s.x===head.x&&s.y===head.y)){\n"
                            "    snake=[{x:160,y:160}];dx=grid;dy=0;score=0;placeFood();\n"
                            "  }\n"
                            "  snake.unshift(head);\n"
                            "  if(head.x===food.x&&head.y===food.y){score++;placeFood();}\n"
                            "  else{snake.pop();}\n"
                            "  ctx.fillStyle='#111';ctx.fillRect(0,0,400,400);\n"
                            "  ctx.fillStyle='#0f0';snake.forEach(s=>ctx.fillRect(s.x,s.y,grid-1,grid-1));\n"
                            "  ctx.fillStyle='#f00';ctx.fillRect(food.x,food.y,grid-1,grid-1);\n"
                            "  ctx.fillStyle='#fff';ctx.font='16px monospace';ctx.fillText('Score: '+score,10,20);\n"
                            "}\n"
                            "placeFood();\n"
                            "setInterval(loop,100);\n"
                        ),
                    },
                    {
                        "op": "write",
                        "path": html_target,
                        "content": (
                            "<!doctype html>\n"
                            "<html><head><meta charset='utf-8'><title>Snake Game</title></head>\n"
                            "<body style='margin:0;display:grid;place-items:center;height:100vh;background:#222;'>\n"
                            "<canvas id='game' width='400' height='400' style='border:1px solid #555;'></canvas>\n"
                            "<script src='./snake_game.js'></script>\n"
                            "</body></html>\n"
                        ),
                    },
                ]
            ])
        if "game" in msg and ("javascript" in msg or "js" in msg):
            js_target = "data/agent_workflow/game.js"
            html_target = "data/agent_workflow/game.html"
            if "shoot" in intent_text or "shooter" in intent_text:
                js_target = "data/agent_workflow/shooting_game.js"
                html_target = "data/agent_workflow/shooting_game.html"
            elif "racing" in intent_text:
                js_target = "data/agent_workflow/racing_game.js"
                html_target = "data/agent_workflow/racing_game.html"
            explicit_js = _find_js_target_from_text(" ".join([user_input, plan_input]))
            if explicit_js:
                js_target = explicit_js
                html_target = re.sub(r"\.js$", ".html", explicit_js, flags=re.IGNORECASE)
            game_js = ""
            if "shoot" in intent_text or "shooter" in intent_text:
                game_js = (
                    "const canvas = document.getElementById('game');\n"
                    "const ctx = canvas.getContext('2d');\n"
                    "const W = canvas.width, H = canvas.height;\n"
                    "let left=false,right=false,fire=false;\n"
                    "const player={x:W/2,y:H-30,w:24,h:12,s:5};\n"
                    "let bullets=[]; let enemies=[]; let t=0; let score=0;\n"
                    "addEventListener('keydown',e=>{if(e.key==='ArrowLeft')left=true;if(e.key==='ArrowRight')right=true;if(e.key===' ')fire=true;});\n"
                    "addEventListener('keyup',e=>{if(e.key==='ArrowLeft')left=false;if(e.key==='ArrowRight')right=false;if(e.key===' ')fire=false;});\n"
                    "function spawn(){enemies.push({x:Math.random()*(W-18),y:-20,w:18,h:18,v:1+Math.random()*1.8});}\n"
                    "function hit(a,b){return a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y;}\n"
                    "function step(){t++;if(t%35===0)spawn();if(left)player.x-=player.s;if(right)player.x+=player.s;player.x=Math.max(0,Math.min(W-player.w,player.x));\n"
                    " if(fire&&t%8===0)bullets.push({x:player.x+player.w/2-2,y:player.y-8,w:4,h:8,v:7});\n"
                    " bullets.forEach(b=>b.y-=b.v); enemies.forEach(e=>e.y+=e.v);\n"
                    " bullets=bullets.filter(b=>b.y>-20); enemies=enemies.filter(e=>e.y<H+20);\n"
                    " for(let i=enemies.length-1;i>=0;i--){for(let j=bullets.length-1;j>=0;j--){if(hit(enemies[i],bullets[j])){enemies.splice(i,1);bullets.splice(j,1);score++;break;}}}\n"
                    " if(enemies.some(e=>hit(e,player))){score=0;enemies=[];bullets=[];}\n"
                    "}\n"
                    "function draw(){ctx.fillStyle='#10131a';ctx.fillRect(0,0,W,H);ctx.fillStyle='#6cf';ctx.fillRect(player.x,player.y,player.w,player.h);\n"
                    " ctx.fillStyle='#ffd166';bullets.forEach(b=>ctx.fillRect(b.x,b.y,b.w,b.h));ctx.fillStyle='#ef476f';enemies.forEach(e=>ctx.fillRect(e.x,e.y,e.w,e.h));\n"
                    " ctx.fillStyle='#fff';ctx.font='14px monospace';ctx.fillText('Score: '+score,10,20);ctx.fillText('Move: <- -> | Fire: Space',10,H-10);}\n"
                    "function loop(){step();draw();requestAnimationFrame(loop);}loop();\n"
                )
            elif "racing" in intent_text:
                game_js = (
                    "const canvas = document.getElementById('game');\n"
                    "const ctx = canvas.getContext('2d');\n"
                    "const W = canvas.width, H = canvas.height;\n"
                    "const keys = {};\n"
                    "document.addEventListener('keydown', e => keys[e.key] = true);\n"
                    "document.addEventListener('keyup', e => keys[e.key] = false);\n"
                    "const p1 = { x: 120, y: H - 80, color: '#35d0ff', name: 'P1' };\n"
                    "const p2 = { x: 280, y: H - 80, color: '#ff7a7a', name: 'P2' };\n"
                    "const speed = 3;\n"
                    "let winner = '';\n"
                    "function move() {\n"
                    "  if (winner) return;\n"
                    "  if (keys['a']) p1.x -= speed; if (keys['d']) p1.x += speed; if (keys['w']) p1.y -= speed; if (keys['s']) p1.y += speed;\n"
                    "  if (keys['ArrowLeft']) p2.x -= speed; if (keys['ArrowRight']) p2.x += speed; if (keys['ArrowUp']) p2.y -= speed; if (keys['ArrowDown']) p2.y += speed;\n"
                    "  [p1,p2].forEach(p=>{p.x=Math.max(10,Math.min(W-30,p.x));p.y=Math.max(10,Math.min(H-30,p.y));});\n"
                    "  if (p1.y <= 12) winner = 'Player 1'; if (p2.y <= 12) winner = 'Player 2';\n"
                    "}\n"
                    "function drawTrack(){ctx.fillStyle='#111';ctx.fillRect(0,0,W,H);ctx.fillStyle='#1e1e1e';for(let y=0;y<H;y+=40)ctx.fillRect(0,y,W,20);ctx.fillStyle='#f7e36a';ctx.fillRect(0,0,W,12);}\n"
                    "function drawCar(p){ctx.fillStyle=p.color;ctx.fillRect(p.x,p.y,20,28);}\n"
                    "function render(){drawTrack();drawCar(p1);drawCar(p2);ctx.fillStyle='#fff';ctx.font='14px monospace';ctx.fillText('P1: WASD | P2: Arrow keys',12,H-14);if(winner){ctx.font='22px monospace';ctx.fillText(winner+' wins!',110,200);}}\n"
                    "function loop(){move();render();requestAnimationFrame(loop);}loop();\n"
                )
            else:
                prompt_txt = (user_input or plan_input or "game").replace("\\", " ").replace("`", "'")
                game_js = (
                    "const canvas=document.getElementById('game');\n"
                    "const ctx=canvas.getContext('2d');\n"
                    "const W=canvas.width,H=canvas.height;\n"
                    "let t=0;\n"
                    f"const REQUEST={json.dumps(prompt_txt)};\n"
                    "function draw(){\n"
                    "  t+=0.02;\n"
                    "  ctx.fillStyle='#111';ctx.fillRect(0,0,W,H);\n"
                    "  ctx.fillStyle='#4cc9f0';ctx.beginPath();ctx.arc(W/2+Math.cos(t)*80,H/2+Math.sin(t)*50,20,0,Math.PI*2);ctx.fill();\n"
                    "  ctx.fillStyle='#fff';ctx.font='16px monospace';ctx.fillText('Generic JS game scaffold',12,24);\n"
                    "  ctx.font='12px monospace';ctx.fillText(REQUEST.slice(0,70),12,44);\n"
                    "  requestAnimationFrame(draw);\n"
                    "}\n"
                    "draw();\n"
                )
            html = (
                "<!doctype html>\n"
                "<html><head><meta charset='utf-8'><title>Racing Game</title></head>\n"
                "<body style='margin:0;display:grid;place-items:center;height:100vh;background:#222;'>\n"
                "<canvas id='game' width='480' height='320' style='border:1px solid #555;'></canvas>\n"
                "<script src='./" + os.path.basename(js_target) + "'></script>\n"
                "</body></html>\n"
            )
            return _ensure_html_runner_candidates(user_input, plan, [[
                {"op": "write", "path": js_target, "content": game_js},
                {"op": "write", "path": html_target, "content": html},
            ]])
        if target_files:
            for tf in target_files:
                p = str(tf or "").strip()
                if p:
                    return _ensure_html_runner_candidates(user_input, plan, [[{"op": "write", "path": p, "content": "// TODO: implement requested change\n"}]])
        # Parse explicit "create <path>" requests from user input/plan text.
        source = " ".join([user_input, plan_input])
        m = re.search(r"(?:create|write)\s+([A-Za-z0-9_./\\-]+\.(?:py|js|ts|html|css|md|json))", source, flags=re.IGNORECASE)
        if m:
            p = str(m.group(1) or "").strip().replace("\\", "/")
            if p:
                content = "// TODO: implement requested change\n"
                if p.endswith(".html"):
                    content = "<!doctype html>\n<html><body></body></html>\n"
                elif p.endswith(".md"):
                    content = "# TODO\n"
                elif p.endswith(".json"):
                    content = "{\n  \"todo\": true\n}\n"
                return _ensure_html_runner_candidates(user_input, plan, [[{"op": "write", "path": p, "content": content}]])
        return []

    def debug_fix_from_errors(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        failures = params.get("failures") or []
        files_hint = params.get("files_hint") or []
        suggestions = []
        for f in failures[:8]:
            if isinstance(f, dict):
                test_name = str(f.get("test") or "")
                err = str(f.get("error") or "")
            else:
                test_name = ""
                err = str(f)
            suggestions.append(
                {
                    "test": test_name,
                    "error": err,
                    "action": "inspect_failure_and_patch",
                    "files_hint": list(files_hint),
                }
            )
        return {"ok": True, "data": {"suggestions": suggestions}, "warnings": []}

    def _extract_text_from_route(out: Any) -> str:
        if isinstance(out, str):
            return out
        if isinstance(out, dict):
            for key in ("answer", "text", "final_text", "content", "result", "description"):
                v = out.get(key)
                if isinstance(v, str):
                    return v
            try:
                return out["choices"][0]["message"]["content"]
            except Exception:
                return ""
        return ""

    def _extract_balanced_json_segment(raw: str) -> str:
        s = str(raw or "")
        if not s:
            return ""
        start = -1
        opener = ""
        for i, ch in enumerate(s):
            if ch in "{[":
                start = i
                opener = ch
                break
        if start < 0:
            return ""
        closer = "}" if opener == "{" else "]"
        depth = 0
        in_str = False
        esc = False
        for j in range(start, len(s)):
            ch = s[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return s[start : j + 1]
        return ""

    def _repair_json_text(raw: str) -> str:
        s = str(raw or "").strip()
        if not s:
            return ""
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
        seg = _extract_balanced_json_segment(s)
        if seg:
            s = seg
        # Remove trailing commas before closing braces/brackets.
        s = re.sub(r",\s*([}\]])", r"\1", s)
        return s

    def _extract_json_block(text: str) -> Any:
        raw = str(text or "").strip()
        if not raw:
            return None
        repaired = _repair_json_text(raw)
        if repaired:
            try:
                return json.loads(repaired)
            except Exception:
                pass
        try:
            return json.loads(raw)
        except Exception:
            pass
        m = re.search(r"```json\s*([\s\S]*?)\s*```", raw, flags=re.IGNORECASE)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                return None
        m2 = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", raw)
        if m2:
            try:
                repaired2 = _repair_json_text(m2.group(1))
                return json.loads(repaired2 or m2.group(1))
            except Exception:
                return None
        return None

    def _normalize_candidates(payload: Any) -> List[List[Dict[str, Any]]]:
        if isinstance(payload, dict):
            cands = payload.get("patch_candidates")
        else:
            cands = payload
        if not isinstance(cands, list):
            return []
        norm: List[List[Dict[str, Any]]] = []
        for cand in cands:
            if not isinstance(cand, list):
                continue
            ops: List[Dict[str, Any]] = []
            for op in cand:
                if not isinstance(op, dict):
                    continue
                kind = str(op.get("op") or "").strip().lower()
                path = str(op.get("path") or "").strip()
                if kind not in {"write", "replace", "append"} or not path:
                    continue
                clean: Dict[str, Any] = {"op": kind, "path": path}
                if kind in {"write", "append"}:
                    clean["content"] = str(op.get("content") or "")
                elif kind == "replace":
                    clean["search"] = str(op.get("search") or "")
                    clean["replace"] = str(op.get("replace") or "")
                    try:
                        clean["count"] = int(op.get("count") or 1)
                    except Exception:
                        clean["count"] = 1
                ops.append(clean)
            if ops:
                norm.append(ops)
        return norm

    def code_generate_patch_candidates(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        plan = params.get("plan") or {}
        context = params.get("context") or {}
        failures = params.get("failures") or []
        user_input = str(params.get("user_input") or "").strip()
        route_preferred = str(params.get("route_id") or "code_patch_candidate").strip()
        allowed_routes_default = ["code_patch_candidate"]
        settings = getattr(app.state, "settings", None)
        cfg = settings() if callable(settings) else {}
        allowed_routes_cfg = cfg.get("agent_workflow_allowed_coding_routes")
        if isinstance(allowed_routes_cfg, list):
            allowed_routes = [str(x).strip() for x in allowed_routes_cfg if str(x).strip()]
        else:
            allowed_routes = list(allowed_routes_default)
        if not allowed_routes:
            allowed_routes = list(allowed_routes_default)
        if route_preferred not in allowed_routes:
            return {
                "ok": False,
                "data": {"requested_route": route_preferred, "allowed_routes": allowed_routes},
                "warnings": [f"coding_route_not_allowed:{route_preferred}"],
            }
        route_fallbacks = [route_preferred] + [r for r in allowed_routes if r != route_preferred]
        use_agent_flow_engine = bool(params.get("use_agent_flow_engine"))
        route_fallbacks = [x for x in route_fallbacks if x]

        try:
            from plugins.ai_routes import load_routes
            from plugins.ai_routes.base import RouterCore
        except Exception as exc:
            return {"ok": False, "data": {}, "warnings": [f"ai_routes_unavailable:{exc}"]}

        model_diag: Dict[str, Any] = {}
        model_obj = _resolve_chat_model(str(ctx.get("sid") or "_default"), model_diag)
        model_diag.update({
            "registry_present": bool(getattr(app.state, "model_loader_registry", None)),
            "provider_present": callable(getattr(app.state, "main_text_llm_provider", None)),
        })
        model_diag = {
            **model_diag,
            "model_provider": getattr(model_obj, "provider", None),
            "model_name": getattr(model_obj, "model_name", None),
            "model_class": type(model_obj).__name__ if model_obj is not None else None,
        }
        if model_obj is None:
            heur = _heuristic_patch_candidates(plan, context, failures, user_input=user_input)
            if heur:
                heur = _ensure_html_runner_candidates(user_input, plan, heur)
                return {
                    "ok": True,
                    "data": {"route_id": "heuristic_no_model", "patch_candidates": heur, "model_diag": model_diag},
                    "warnings": ["chat_model_unavailable", "heuristic_patch_fallback_used"],
                }
            return {
                "ok": False,
                "data": {"route_id": "", "model_diag": model_diag},
                "warnings": ["chat_model_unavailable"],
            }
        core_settings = _runtime_base_settings()
        core_settings["__pid"] = str(ctx.get("pid") or "_default")
        core_settings["__sid"] = str(ctx.get("sid") or "_default")
        core_settings["__model_loader_registry"] = getattr(app.state, "model_loader_registry", None)
        core = RouterCore(chat_llm=model_obj, backend_type="auto", settings=core_settings)
        routes = load_routes(core) or []
        route_by_id = {r.route_id: r for r in routes}

        prompt = (
            "You are a coding patch planner. Return ONLY strict JSON.\n"
            "Goal: produce patch candidates using safe operations for code.apply_patch.\n"
            "JSON schema:\n"
            "{\n"
            '  "patch_candidates": [\n'
            "    [\n"
            '      {"op":"replace","path":"relative/file.py","search":"old","replace":"new","count":1},\n'
            '      {"op":"write","path":"relative/file.py","content":"..."}\n'
            "    ]\n"
            "  ]\n"
            "}\n"
            "Constraints:\n"
            "- relative paths only\n"
            "- small minimal edits\n"
            "- preserve plugin boundaries\n"
            "- no markdown, no prose\n\n"
            f"User request:\n{user_input}\n\n"
            f"Plan:\n{json.dumps(plan, ensure_ascii=False)}\n\n"
            f"Context:\n{json.dumps(context, ensure_ascii=False)}\n\n"
            f"Failures:\n{json.dumps(failures, ensure_ascii=False)}\n"
        )

        if use_agent_flow_engine and "agent_flow" in route_by_id:
            flow_id = f"wf_tmp_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
            flow_def = {
                "start": "n1",
                "nodes": {
                    "n1": {
                        "label": "Generate patch candidates",
                        "plugin_id": route_preferred,
                        "system_prompt": "",
                        "transitions": [],
                        "return_only_text": True,
                    }
                },
            }
            req_obj = SimpleNamespace(
                messages=[{"role": "user", "content": prompt}],
                ext={
                    "pid": core_settings["__pid"],
                    "sid": core_settings["__sid"],
                    "agent_flow_flows": {flow_id: flow_def},
                    "agent_flow_active_flow": flow_id,
                },
                route_id="agent_flow",
                router_enabled_plugins=["agent_flow", route_preferred],
                model="",
                backend_type="auto",
            )
            old_mode = core.settings.get("agent_flow_mode")
            old_max = core.settings.get("agent_flow_max_steps")
            core.settings["agent_flow_mode"] = "execute"
            core.settings["agent_flow_max_steps"] = 8
            try:
                af_out = route_by_id["agent_flow"].handle(req_obj)
            except Exception as exc:
                return {"ok": False, "data": {}, "warnings": [f"agent_flow_engine_error:{exc}"]}
            finally:
                core.settings["agent_flow_mode"] = old_mode
                core.settings["agent_flow_max_steps"] = old_max
            msgs = list((af_out or {}).get("messages") or []) if isinstance(af_out, dict) else []
            txt = ""
            for m in reversed(msgs):
                if isinstance(m, dict) and str(m.get("role") or "") == "assistant":
                    txt = str(m.get("content") or "")
                    break
            obj = _extract_json_block(txt)
            norm = _normalize_candidates(obj)
            if norm:
                norm = _ensure_html_runner_candidates(user_input, plan, norm)
                return {
                    "ok": True,
                    "data": {"route_id": "agent_flow->" + route_preferred, "patch_candidates": norm, "model_diag": model_diag},
                    "warnings": [],
                }
            # fall through to direct route path if parse failed

        out = None
        used_route = ""
        route_errors: List[str] = []
        for rid in route_fallbacks:
            r = route_by_id.get(rid)
            if not r:
                route_errors.append(f"{rid}:missing")
                continue
            req_obj = SimpleNamespace(
                messages=[{"role": "user", "content": prompt}],
                ext={"pid": core_settings["__pid"], "sid": core_settings["__sid"]},
                route_id=rid,
                router_enabled_plugins=[rid],
                model="",
                backend_type="auto",
            )
            try:
                out = r.handle(req_obj)
                used_route = rid
                break
            except Exception as exc:
                route_errors.append(f"{rid}:exception:{exc}")
                continue

        if out is None:
            return {"ok": False, "data": {"model_diag": model_diag, "route_errors": route_errors}, "warnings": ["no_coding_route_available"]}
        # Fast path: route already returned structured candidates
        if isinstance(out, dict):
            norm_direct = _normalize_candidates(out)
            if norm_direct:
                norm_direct = _ensure_html_runner_candidates(user_input, plan, norm_direct)
                return {"ok": True, "data": {"route_id": used_route, "patch_candidates": norm_direct, "model_diag": model_diag}, "warnings": []}
        txt = _extract_text_from_route(out)
        if not txt and isinstance(out, dict):
            # Some routes return parse-failure payloads with raw_text instead of content/text.
            txt = str(out.get("raw_text") or "")
        obj = _extract_json_block(txt)
        if not isinstance(obj, dict):
            heur = _heuristic_patch_candidates(plan, context, failures, user_input=user_input)
            if heur:
                return {
                    "ok": True,
                    "data": {"route_id": used_route or "heuristic_fallback", "patch_candidates": heur, "model_diag": model_diag},
                    "warnings": ["invalid_json_from_coding_route", "heuristic_patch_fallback_used"] + route_errors,
                }
            detail = str((out or {}).get("error") or "") if isinstance(out, dict) else ""
            warnings = ["invalid_json_from_coding_route"] + route_errors
            if detail:
                warnings.append(f"coding_route_error:{detail}")
            return {
                "ok": False,
                "data": {"route_id": used_route, "raw_text": txt[:2000], "model_diag": model_diag},
                "warnings": warnings,
            }

        norm = _normalize_candidates(obj)
        if not norm:
            return {
                "ok": False,
                "data": {"route_id": used_route, "json": obj, "model_diag": model_diag},
                "warnings": ["patch_candidates_missing"] + route_errors,
            }

        norm = _ensure_html_runner_candidates(user_input, plan, norm)
        return {
            "ok": len(norm) > 0,
            "data": {"route_id": used_route, "patch_candidates": norm, "model_diag": model_diag},
            "warnings": ([] if norm else ["no_valid_ops_generated"]) + route_errors,
        }

    def _model_patch_terms(text: str) -> List[str]:
        stop = {
            "about", "after", "again", "also", "before", "change", "changes", "chat", "chatjs",
            "clear", "code", "commit", "file", "find", "from", "handle", "into", "make", "need",
            "plugin", "please", "request", "search", "that", "then", "there", "this", "update",
            "using", "where", "with", "work", "workflow",
        }
        words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", str(text or ""))
        out: List[str] = []
        for word in words:
            for part in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|[0-9]+", word):
                p = part.lower()
                if len(p) >= 4 and p not in stop and p not in out:
                    out.append(p)
            low = word.lower()
            if len(low) >= 4 and low not in stop and low not in out:
                out.append(low)
        return out[:24]

    def _model_patch_collect_evidence(path: str, user_request: str, explicit_evidence: Any, max_snippets: int = 10) -> Dict[str, Any]:
        evidence_items: List[Any] = []
        if explicit_evidence:
            evidence_items.append(explicit_evidence)
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                lines = fh.read().splitlines()
        except Exception as exc:
            return {"read_error": str(exc), "evidence": evidence_items, "snippets": []}

        terms = _model_patch_terms(user_request)
        scored: List[tuple[int, int, str]] = []
        for idx, line in enumerate(lines):
            low = line.lower()
            score = sum(1 for term in terms if term in low)
            if score:
                scored.append((score, idx, line))
        scored.sort(key=lambda x: (-x[0], x[1]))

        snippets: List[Dict[str, Any]] = []
        used_ranges: List[tuple[int, int]] = []
        for _score, idx, _line in scored:
            start = max(0, idx - 8)
            end = min(len(lines), idx + 9)
            if any(not (end < a or start > b) for a, b in used_ranges):
                continue
            used_ranges.append((start, end))
            snippets.append({
                "start_line": start + 1,
                "end_line": end,
                "text": "\n".join(f"{i + 1}: {lines[i]}" for i in range(start, end)),
            })
            if len(snippets) >= max_snippets:
                break
        if not snippets and lines:
            end = min(len(lines), 120)
            snippets.append({
                "start_line": 1,
                "end_line": end,
                "text": "\n".join(f"{i + 1}: {lines[i]}" for i in range(0, end)),
            })
        return {
            "terms": terms,
            "evidence": evidence_items,
            "snippets": snippets,
            "file_line_count": len(lines),
        }

    def _model_patch_target_path(op_path: str, target_path: str) -> str:
        raw = str(op_path or "").replace("\\", "/").strip()
        target = str(target_path or "").replace("\\", "/").strip() or raw
        if not raw:
            return target
        if raw == target or raw.endswith("/" + target) or os.path.basename(raw) == os.path.basename(target):
            return target
        return raw

    def _model_patch_comment_text(user_request: str) -> str:
        text = str(user_request or "").strip()
        reason = ""
        m = re.search(r"\bexplaining?\s+(.*?)(?:\.|$)", text, flags=re.IGNORECASE)
        if m:
            reason = str(m.group(1) or "").strip()
        if not reason:
            m = re.search(r"\bcomment\s+(?:near|about|for)?\s*(.*?)(?:\.|$)", text, flags=re.IGNORECASE)
            if m:
                reason = str(m.group(1) or "").strip()
        reason = re.sub(r"^(why|that)\s+", "", reason, flags=re.IGNORECASE).strip()
        if not reason:
            reason = "Keep this behavior intentional for future maintainers"
        reason = reason[0].upper() + reason[1:] if reason else reason
        if not reason.endswith((".", "!", "?")):
            reason += "."
        return "// " + reason

    def _model_patch_comment_fallback(ctx: Dict[str, Any], params: Dict[str, Any], abs_path: str, target_path: str, evidence: Dict[str, Any]) -> Dict[str, Any]:
        user_request = str(params.get("user_request") or params.get("request") or params.get("instruction") or "").strip()
        if not re.search(r"\b(comment|document|explain)\b", user_request, flags=re.IGNORECASE):
            return {"ok": False, "data": {}, "warnings": ["comment_fallback_not_applicable"]}
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as fh:
                lines = fh.read().splitlines()
        except Exception as exc:
            return {"ok": False, "data": {}, "warnings": [f"comment_fallback_read_failed:{exc}"]}
        if not lines:
            return {"ok": False, "data": {}, "warnings": ["comment_fallback_empty_file"]}
        terms = list(evidence.get("terms") or _model_patch_terms(user_request))
        best_idx = -1
        best_score = 0
        for idx, line in enumerate(lines):
            low = line.lower()
            score = sum(1 for term in terms if term and term in low)
            if score > best_score:
                best_idx = idx
                best_score = score
        if best_idx < 0:
            snippets = evidence.get("snippets") if isinstance(evidence.get("snippets"), list) else []
            if snippets and isinstance(snippets[0], dict):
                best_idx = max(0, int(snippets[0].get("start_line") or 1) - 1)
            else:
                best_idx = 0
        line = lines[best_idx]
        indent = re.match(r"\s*", line).group(0)
        comment = indent + _model_patch_comment_text(user_request)
        if best_idx > 0 and _model_patch_comment_text(user_request).strip() in lines[best_idx - 1]:
            return {"ok": True, "data": {"changed_files": [], "final_paths": [], "already_present": True}, "warnings": ["comment_already_present"]}
        search = line
        replace = comment + "\n" + line
        return code_apply_patch(ctx, {
            "target_repo_root": str(params.get("target_repo_root") or "").strip(),
            "ops": [{"op": "replace", "path": target_path, "search": search, "replace": replace, "count": 1}],
        })

    def code_model_patch(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        params = params or {}
        target_repo_root = str(params.get("target_repo_root") or "").strip()
        target_path = str(params.get("path") or params.get("file") or "chat.js").strip().replace("\\", "/")
        user_request = str(params.get("user_request") or params.get("request") or params.get("instruction") or "").strip()
        if not user_request:
            return {"ok": False, "data": {}, "warnings": ["user_request_required"]}
        if not target_path:
            return {"ok": False, "data": {}, "warnings": ["path_required"]}
        try:
            rel_scoped = _target_repo_scoped_rel_path(target_path, target_repo_root, ctx)
            abs_path = _safe_path(rel_scoped, ctx, already_scoped=True)
        except Exception as exc:
            return {"ok": False, "data": {"path": target_path, "target_repo_root": target_repo_root}, "warnings": [f"path_error:{exc}"]}
        if not os.path.isfile(abs_path):
            return {
                "ok": False,
                "data": {"path": target_path, "resolved_path": abs_path, "target_repo_root": target_repo_root},
                "warnings": ["target_file_not_found"],
            }

        explicit_evidence = params.get("evidence")
        if explicit_evidence is None:
            explicit_evidence = params.get("context")
        evidence = _model_patch_collect_evidence(abs_path, user_request, explicit_evidence)
        attempts: List[Dict[str, Any]] = []
        failures: List[Any] = list(params.get("failures") or [])
        max_attempts = max(1, min(int(params.get("max_attempts") or 2), 4))
        for attempt in range(max_attempts):
            gen = code_generate_patch_candidates(ctx, {
                "user_input": (
                    user_request
                    + "\n\nReturn exact minimal replace ops only. Use path "
                    + json.dumps(target_path)
                    + " because target_repo_root is "
                    + json.dumps(target_repo_root)
                    + "."
                ),
                "plan": {
                    "input": user_request,
                    "target_repo_root": target_repo_root,
                    "path": target_path,
                    "attempt": attempt + 1,
                },
                "context": {
                    "target_file": target_path,
                    "target_repo_root": target_repo_root,
                    "evidence": evidence,
                },
                "failures": failures,
            })
            candidates = []
            if isinstance(gen, dict):
                data0 = gen.get("data") if isinstance(gen.get("data"), dict) else {}
                candidates = data0.get("patch_candidates") if isinstance(data0.get("patch_candidates"), list) else []
            attempts.append({"attempt": attempt + 1, "generate_ok": bool(gen.get("ok")) if isinstance(gen, dict) else False, "candidate_count": len(candidates)})
            if not candidates:
                failures.append({"attempt": attempt + 1, "error": "no_patch_candidates", "generate": gen})
                continue
            for cand_idx, cand in enumerate(candidates):
                if not isinstance(cand, list):
                    continue
                ops: List[Dict[str, Any]] = []
                for op in cand:
                    if not isinstance(op, dict):
                        continue
                    clean = dict(op)
                    clean["path"] = _model_patch_target_path(str(clean.get("path") or ""), target_path)
                    ops.append(clean)
                if not ops:
                    continue
                patch = code_apply_patch(ctx, {"target_repo_root": target_repo_root, "ops": ops})
                attempts[-1].setdefault("patch_results", []).append({
                    "candidate": cand_idx,
                    "ok": bool(patch.get("ok")) if isinstance(patch, dict) else False,
                    "warnings": list(patch.get("warnings") or []) if isinstance(patch, dict) and isinstance(patch.get("warnings"), list) else [],
                    "errors": ((patch.get("data") or {}).get("errors") if isinstance(patch, dict) and isinstance(patch.get("data"), dict) else []),
                })
                if isinstance(patch, dict) and patch.get("ok") and isinstance(patch.get("data"), dict):
                    changed = patch["data"].get("changed_files")
                    if isinstance(changed, list) and changed:
                        data = dict(patch["data"])
                        data.update({
                            "model_patch": True,
                            "path": data.get("path") or target_path,
                            "target_repo_root": target_repo_root,
                            "attempts": attempts,
                            "evidence_summary": {
                                "terms": evidence.get("terms"),
                                "snippet_count": len(evidence.get("snippets") or []),
                            },
                        })
                        return {"ok": True, "data": data, "warnings": []}
                failures.append({
                    "attempt": attempt + 1,
                    "candidate": cand_idx,
                    "patch": patch,
                })
        fallback = _model_patch_comment_fallback(ctx, params, abs_path, target_path, evidence)
        if fallback.get("ok") and isinstance(fallback.get("data"), dict):
            changed = fallback["data"].get("changed_files")
            if isinstance(changed, list) and changed:
                data = dict(fallback["data"])
                data.update({
                    "model_patch": True,
                    "fallback": "comment_insert",
                    "path": data.get("path") or target_path,
                    "target_repo_root": target_repo_root,
                    "attempts": attempts,
                    "evidence_summary": {
                        "terms": evidence.get("terms"),
                        "snippet_count": len(evidence.get("snippets") or []),
                    },
                })
                return {"ok": True, "data": data, "warnings": ["model_patch_comment_fallback_used"]}
        return {
            "ok": False,
            "data": {
                "path": target_path,
                "target_repo_root": target_repo_root,
                "attempts": attempts,
                "failures": failures[-6:],
                "evidence_summary": {
                    "terms": evidence.get("terms"),
                    "snippet_count": len(evidence.get("snippets") or []),
                },
            },
            "warnings": ["model_patch_failed"],
        }

    def auth_project_context(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True, "data": {"pid": ctx.get("pid"), "sid": ctx.get("sid"), "session_guard": True}, "warnings": []}

    def collab_session_context(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        db = getattr(app.state, "collab_db", None)
        if db is None or not hasattr(db, "list_messages"):
            return {"ok": True, "data": {"available": False}, "warnings": ["collab_db_unavailable"]}
        try:
            msgs = db.list_messages(pid=str(ctx.get("pid") or ""), sid=str(ctx.get("sid") or ""), limit=20)
            return {"ok": True, "data": {"available": True, "recent_messages": msgs[-5:] if isinstance(msgs, list) else []}, "warnings": []}
        except Exception as exc:
            return {"ok": True, "data": {"available": False}, "warnings": [f"collab_context_error:{exc}"]}

    def learning_capture_feedback(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        rows = _load_learning()
        rec = {
            "feedback_id": f"fb_{len(rows) + 1}",
            "timestamp": _utc_now(),
            "pid": str(ctx.get("pid") or ""),
            "sid": str(ctx.get("sid") or ""),
            "workflow_id": str(params.get("workflow_id") or ""),
            "pattern": str(params.get("pattern") or "").strip(),
            "correction_type": str(params.get("correction_type") or "").strip(),
            "notes": str(params.get("notes") or "").strip(),
            "preferred_files": list(params.get("preferred_files") or []),
            "avoid": list(params.get("avoid") or []),
            "workflow_family": str(params.get("workflow_family") or "").strip(),
        }
        if not rec["pattern"]:
            return {"ok": False, "data": {}, "warnings": ["pattern_required"]}
        rows.append(rec)
        _save_learning(rows)
        return {"ok": True, "data": rec, "warnings": []}

    def learning_get_hints(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        rows = _load_learning()
        query = str(params.get("query") or "").lower().strip()
        if not query:
            return {"ok": True, "data": {"query": query, "hints": []}, "warnings": ["empty_query"]}
        terms = [t for t in query.split() if t]
        hits: List[Dict[str, Any]] = []
        for row in rows:
            hay = " ".join(
                [
                    str(row.get("pattern") or ""),
                    str(row.get("notes") or ""),
                    " ".join(row.get("preferred_files") or []),
                ]
            ).lower()
            score = sum(1 for t in terms if t in hay)
            if score > 0:
                out = dict(row)
                out["score"] = score
                hits.append(out)
        hits.sort(key=lambda x: int(x.get("score") or 0), reverse=True)
        return {"ok": True, "data": {"query": query, "hints": hits[:8]}, "warnings": []}

    def learning_list(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        rows = _load_learning()
        limit = int(params.get("limit") or 40)
        return {"ok": True, "data": {"items": rows[-limit:]}, "warnings": []}

    registry.register_tool("repo.tree", repo_tree)
    registry.register_tool("repo.context", repo_context)
    registry.register_tool("repo.find_file", repo_find_file)
    registry.register_tool("repo.read", repo_read)
    registry.register_tool("repo.read_range", repo_read_range)
    registry.register_tool("repo.search", repo_search)
    registry.register_tool("repo.write", repo_write)
    registry.register_tool("repo.ingest", repo_ingest)
    registry.register_tool("rag.search", rag_search)
    registry.register_tool("tests.smoke", tests_smoke)
    registry.register_tool("auth.project_context", auth_project_context)
    registry.register_tool("collab.session_context", collab_session_context)
    registry.register_tool("learning.capture_feedback", learning_capture_feedback)
    registry.register_tool("learning.get_hints", learning_get_hints)
    registry.register_tool("learning.list", learning_list)
    registry.register_tool("code.apply_patch", code_apply_patch)
    registry.register_tool("code.generate_patch_candidates", code_generate_patch_candidates)
    registry.register_tool("code.model_patch", code_model_patch)
    registry.register_tool("tests.run_project", tests_run_project)
    registry.register_tool("debug.fix_from_errors", debug_fix_from_errors)
