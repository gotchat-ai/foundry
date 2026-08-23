import json
import os
from typing import Any, Callable


class ChatControlRoutes:
    """Small chat/model control endpoints."""

    def __init__(
        self,
        *,
        settings_getter: Callable[[], dict[str, Any]],
        model_getter: Callable[[], Any],
        compute_sane_settings: Callable[[int], dict[str, Any]],
        deep_merge: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
        session_trace_getter: Callable[[], dict[str, Any]],
        cancel_flags_getter: Callable[[], dict[str, bool]],
    ) -> None:
        self._settings_getter = settings_getter
        self._model_getter = model_getter
        self._compute_sane_settings = compute_sane_settings
        self._deep_merge = deep_merge
        self._session_trace_getter = session_trace_getter
        self._cancel_flags_getter = cancel_flags_getter

    def compute_and_apply_sane_settings(self, req: dict | None = None) -> dict[str, Any]:
        settings = self._settings_getter()
        def _context_default() -> int:
            value = settings.get("max_context_tokens", 32000)
            if value is None:
                value = 32000
            return int(value)

        try:
            apply_flag = bool((req or {}).get("apply"))
        except Exception:
            apply_flag = False

        try:
            active_model = self._model_getter()
            ctx = int(active_model.context_limit() if active_model else _context_default())
        except Exception:
            ctx = _context_default()

        sane = self._compute_sane_settings(ctx)
        result: dict[str, Any] = {"context_limit": ctx, "sane": sane, "applied": False}

        if apply_flag:
            try:
                new_settings = self._deep_merge(settings, sane)
                settings.clear()
                settings.update(new_settings)
                try:
                    settings_path = os.path.join(os.getcwd(), "settings.json")
                    with open(settings_path, "w", encoding="utf-8") as handle:
                        json.dump(settings, handle, indent=2)
                except Exception:
                    pass
                result["applied"] = True
            except Exception as exc:
                result["error"] = str(exc)

        return result

    def get_session_trace(self, req: dict) -> dict[str, Any]:
        sid = (req or {}).get("sid") or (req or {}).get("session_id") or "default"
        reset = bool((req or {}).get("reset", False))
        session_trace = self._session_trace_getter()
        items = list(session_trace.get(sid, []) or [])
        if reset:
            try:
                session_trace[sid].clear()
            except Exception:
                pass
        return {"trace": items}

    def cancel_chat(self, req: dict) -> dict[str, bool]:
        sid = (req or {}).get("sid") or (req or {}).get("session_id") or "default"
        self._cancel_flags_getter()[sid] = True
        return {"ok": True}
