import threading as _threading
from typing import Any, Callable

class _LazyResource:
    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._value: Any = None
        self._ready = False
        self._lock = _threading.RLock()

    def _get(self) -> Any:
        if self._ready:
            return self._value
        with self._lock:
            if not self._ready:
                self._value = self._factory()
                self._ready = True
        return self._value

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get(), name)

    def __bool__(self) -> bool:
        return True
