from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import os
from typing import Any, Callable


class MainTextLlmService:
    def __init__(
        self,
        *,
        app: Any,
        settings_getter: Callable[[], dict[str, Any]],
        model_getter: Callable[[], Any],
        model_setter: Callable[[Any], None],
        gguf_chat_model_cls: type,
    ) -> None:
        self.app = app
        self._settings_getter = settings_getter
        self._model_getter = model_getter
        self._model_setter = model_setter
        self._gguf_chat_model_cls = gguf_chat_model_cls

    def _call_maybe_async(self, func, *args, **kwargs):
        res = func(*args, **kwargs)
        if inspect.isawaitable(res):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(res)
            # Avoid deadlocks when called from the running event loop thread.
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(lambda: asyncio.run(res)).result()
        return res

    def _get_main_text_llm_if_loaded(self):
        reg = getattr(self.app.state, "model_loader_registry", None)
        if not hasattr(reg, "get"):
            return None
        gguf_plugin = reg.get("model_loader.gguf")
        if gguf_plugin is None:
            return None
        sid = "_default"
        slot = "text_llm_main"
        try:
            loaded = gguf_plugin.get_model_for(sid, slot)
        except Exception:
            loaded = None
        if loaded is None:
            return None
        try:
            setter = getattr(self.app.state, "set_model", None)
            if callable(setter):
                setter(loaded)
        except Exception:
            pass
        return loaded

    def _ensure_main_text_llm_loaded(self):
        reg = getattr(self.app.state, "model_loader_registry", None)
        if not hasattr(reg, "get"):
            try:
                print("[main_text_llm] model_loader_registry missing")
            except Exception:
                pass
            return None

        provider = getattr(self.app.state, "main_text_llm_provider", None)
        if not callable(provider):
            try:
                print("[main_text_llm] main_text_llm provider missing")
            except Exception:
                pass
            return None

        try:
            provider_result = provider() or {}
        except Exception as exc:
            try:
                print(f"[main_text_llm] provider error: {exc}")
            except Exception:
                pass
            return None

        mid = str(provider_result.get("model_id") or "").strip()
        if not mid:
            try:
                print("[main_text_llm] no main/default model set for text_llm")
            except Exception:
                pass
            return None
        loader_id = str(provider_result.get("loader_id") or "")
        if loader_id not in ("model_loader.model_deck.text_llm", "model_loader.gguf"):
            try:
                print(f"[main_text_llm] unsupported loader_id: {loader_id}")
            except Exception:
                pass
            return None

        gguf_plugin = reg.get("model_loader.gguf")
        if gguf_plugin is None:
            try:
                print("[main_text_llm] model_loader.gguf not available")
            except Exception:
                pass
            return None

        sid = "_default"
        slot = "text_llm_main"

        try:
            existing = gguf_plugin.get_model_for(sid, slot)
        except Exception:
            existing = None
        if existing is not None:
            try:
                setter = getattr(self.app.state, "set_model", None)
                if callable(setter):
                    setter(existing)
                else:
                    self._model_setter(existing)
            except Exception:
                self._model_setter(existing)
            return existing

        raw_settings = dict(provider_result.get("settings") or {})
        gguf_filename = str(raw_settings.get("gguf_filename") or "").strip() or None
        settings = dict(raw_settings)
        try:
            from plugins.model_loader.model_deck.local_loaders.gguf_bridge import map_gguf_settings

            settings = map_gguf_settings(settings)
        except Exception:
            pass
        backend_mode = str(settings.get("backend_mode") or "embedded").strip().lower() or "embedded"
        model = self._model_getter()
        if model is not None:
            try:
                if backend_mode != "llama_server" and isinstance(model, self._gguf_chat_model_cls):
                    return model
            except Exception:
                return model
        try:
            from plugins.model_loader.gguf import plugin as gguf_module

            model_id = str(settings.get("model_id") or "").strip()
            if model_id:
                try:
                    print(f"[main_text_llm] resolve gguf path for {model_id}")
                except Exception:
                    pass
                resolved = gguf_module._resolve_gguf_path(self.app, model_id, gguf_filename)
                if resolved:
                    settings["model_id"] = resolved
                    try:
                        print(f"[main_text_llm] resolved gguf path -> {resolved}")
                    except Exception:
                        pass
        except Exception as exc:
            try:
                print(f"[main_text_llm] resolve gguf path error: {exc}")
            except Exception:
                pass
        model_path = str(settings.get("model_id") or "").strip()
        if model_path and not os.path.exists(model_path):
            try:
                print(f"[main_text_llm] model path missing: {model_path}")
            except Exception:
                pass

        if backend_mode == "llama_server":
            try:
                managed_id = str(settings.get("llama_server_managed_id") or "").strip()
                if managed_id:
                    from plugins.gui_helpers.model_deck.routes import (
                        _ensure_llama_server_model_copy,
                        _start_managed_llama_server_if_needed,
                    )

                    _, rel_model_path = _ensure_llama_server_model_copy(model_path)
                    managed_url = _start_managed_llama_server_if_needed(settings, rel_model_path)
                    if managed_url:
                        settings["llama_server_url"] = managed_url
                        try:
                            print(f"[main_text_llm] managed llama_server_url -> {managed_url}")
                        except Exception:
                            pass
                    else:
                        try:
                            print("[main_text_llm] managed llama.cpp server did not return a URL")
                        except Exception:
                            pass
                        return None
                elif not str(settings.get("llama_server_url") or "").strip():
                    try:
                        print("[main_text_llm] llama_server backend configured without managed id or llama_server_url")
                    except Exception:
                        pass
                    return None
            except Exception as exc:
                try:
                    print(f"[main_text_llm] llama_server prepare failed: {exc}")
                except Exception:
                    pass
                return None

        try:
            try:
                print(
                    f"[main_text_llm] load_for backend_mode={backend_mode} "
                    f"managed_id={settings.get('llama_server_managed_id')} "
                    f"llama_server_url={settings.get('llama_server_url')}",
                    flush=True,
                )
            except Exception:
                pass
            res = self._call_maybe_async(gguf_plugin.load_for, sid, slot, settings=settings)
        except Exception as exc:
            try:
                print(f"[main_text_llm] load_for error: {exc}")
            except Exception:
                pass
            return None
        if not (res or {}).get("ok", False):
            try:
                print(f"[main_text_llm] load_for failed: {res}")
            except Exception:
                pass
            return None

        try:
            loaded = gguf_plugin.get_model_for(sid, slot)
        except Exception:
            loaded = None
        if loaded is None:
            try:
                print("[main_text_llm] load_for ok but model missing")
            except Exception:
                pass
            return None

        try:
            setter = getattr(self.app.state, "set_model", None)
            if callable(setter):
                setter(loaded)
            else:
                self._model_setter(loaded)
        except Exception:
            self._model_setter(loaded)
        return loaded

    def _main_text_llm_has_other_active_jobs(self, current_job_id: str) -> bool:
        ai_jobs = getattr(self.app.state, "ai_jobs", None)
        if ai_jobs is None or not hasattr(ai_jobs, "snapshot"):
            return False
        try:
            jobs = ai_jobs.snapshot()
        except Exception:
            return False
        current = str(current_job_id or "")
        active_status = {"queued", "running"}
        for job in jobs:
            if not isinstance(job, dict):
                continue
            if str(job.get("job_id") or "") == current:
                continue
            if str(job.get("status") or "").strip().lower() not in active_status:
                continue
            if str(job.get("kind") or "messages").strip().lower() == "messages":
                return True
        return False

    def _managed_id_still_loaded_elsewhere(self, gguf_plugin: Any, managed_id: str) -> bool:
        wanted = str(managed_id or "").strip()
        if not wanted:
            return False
        try:
            state = getattr(gguf_plugin, "_state", {}) or {}
        except Exception:
            state = {}
        for _key, st in state.items():
            if not isinstance(st, dict):
                continue
            settings = st.get("settings") or {}
            other = str(settings.get("llama_server_managed_id") or "").strip()
            if other == wanted:
                return True
        return False

    def _unload_main_text_llm_if_non_persistent(self, active_model: Any, current_job_id: str) -> None:
        provider = getattr(self.app.state, "main_text_llm_provider", None)
        if not callable(provider):
            return
        try:
            provider_result = provider() or {}
        except Exception as exc:
            try:
                print(f"[main_text_llm] non-persist cleanup provider error: {exc}", flush=True)
            except Exception:
                pass
            return

        if bool(provider_result.get("persist", False)):
            return
        if self._main_text_llm_has_other_active_jobs(current_job_id):
            try:
                print("[main_text_llm] non-persist cleanup skipped: other message jobs still active", flush=True)
            except Exception:
                pass
            return

        reg = getattr(self.app.state, "model_loader_registry", None)
        if not hasattr(reg, "get"):
            return
        gguf_plugin = reg.get("model_loader.gguf")
        if gguf_plugin is None:
            return

        sid = "_default"
        slot = "text_llm_main"
        try:
            loaded = gguf_plugin.get_model_for(sid, slot)
        except Exception:
            loaded = None
        if loaded is not None and active_model is not None and loaded is not active_model:
            try:
                print("[main_text_llm] non-persist cleanup skipped: active model differs from main slot", flush=True)
            except Exception:
                pass
            return

        settings = dict(provider_result.get("settings") or {})
        try:
            from plugins.model_loader.model_deck.local_loaders.gguf_bridge import map_gguf_settings

            settings = map_gguf_settings(settings)
        except Exception:
            pass
        backend_mode = str(settings.get("backend_mode") or "embedded").strip().lower() or "embedded"
        managed_id = str(settings.get("llama_server_managed_id") or "").strip()

        model = self._model_getter()
        try:
            setter = getattr(self.app.state, "set_model", None)
            if callable(setter):
                current_model = self.app.state.model() if callable(getattr(self.app.state, "model", None)) else model
                if (loaded is not None and current_model is loaded) or (active_model is not None and current_model is active_model):
                    setter(None)
            elif (loaded is not None and model is loaded) or (active_model is not None and model is active_model):
                self._model_setter(None)
        except Exception:
            if (loaded is not None and model is loaded) or (active_model is not None and model is active_model):
                self._model_setter(None)

        try:
            self._call_maybe_async(gguf_plugin.unload_for, sid, slot)
        except Exception as exc:
            try:
                print(f"[main_text_llm] non-persist unload_for failed: {exc}", flush=True)
            except Exception:
                pass

        if backend_mode == "llama_server" and managed_id:
            if self._managed_id_still_loaded_elsewhere(gguf_plugin, managed_id):
                try:
                    print(f"[main_text_llm] managed stop skipped: still referenced id={managed_id}", flush=True)
                except Exception:
                    pass
                return
            try:
                from plugins.gui_helpers.model_deck.routes import _stop_managed_llama_server_if_needed

                _stop_managed_llama_server_if_needed(settings)
                print(f"[main_text_llm] stopped non-persist managed llama-server id={managed_id}", flush=True)
            except Exception as exc:
                try:
                    print(f"[main_text_llm] managed stop failed id={managed_id} error={exc}", flush=True)
                except Exception:
                    pass

    def _resolve_chat_model_and_settings(
        self,
        req: Any,
        *,
        ensure_main_text_llm_loaded: Callable[[], Any],
        get_main_text_llm_if_loaded: Callable[[], Any],
    ):
        """
        Existing logic that decides backend_type, gets the chat model, and builds
        the base settings dict plus per-session plugin overrides.
        """
        backend_type = (req.backend_type or "auto").lower()
        chat_llm = self._model_getter()
        if chat_llm is None:
            main_loaded = ensure_main_text_llm_loaded()
            if main_loaded is not None:
                chat_llm = main_loaded
                backend_type = "gguf"
        elif backend_type in ("gguf", "auto"):
            if not isinstance(chat_llm, self._gguf_chat_model_cls):
                main_loaded = get_main_text_llm_if_loaded()
                if main_loaded is None:
                    main_loaded = ensure_main_text_llm_loaded()
                if main_loaded is not None:
                    chat_llm = main_loaded
                    if backend_type == "auto":
                        backend_type = "gguf"
        base_settings = dict(self._settings_getter())

        ext = req.ext or {}
        plugin_settings = ext.get("router_plugin_settings") or {}

        settings = dict(base_settings)
        for plugin_id, plugin_cfg in plugin_settings.items():
            if not isinstance(plugin_cfg, dict):
                continue
            for k, v in plugin_cfg.items():
                settings[k] = v

        try:
            settings["__model_loader_registry"] = getattr(self.app.state, "model_loader_registry", None)
            settings["__server_app"] = self.app
        except Exception:
            pass

        return chat_llm, backend_type, settings
