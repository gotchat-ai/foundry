from __future__ import annotations

from typing import Any, Callable

from app_main.core.jobs import _GenScheduler


class GenerationSchedulerRuntime:
    """Lazy singleton holder for generation workers."""

    def __init__(self, *, settings_getter: Callable[[], dict[str, Any] | None]):
        self._settings_getter = settings_getter
        self._scheduler: _GenScheduler | None = None

    def get(self) -> _GenScheduler:
        if self._scheduler is None:
            settings = self._settings_getter() or {}
            n = int(settings.get("gen_workers", 2) or 2)
            self._scheduler = _GenScheduler(num_workers=n)
            self._scheduler.start()
        return self._scheduler
