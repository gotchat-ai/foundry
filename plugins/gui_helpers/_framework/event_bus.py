from __future__ import annotations

from typing import Any, List, Tuple
import queue
import threading
import time


class GuiEventBus:
    """In-memory pub/sub for GUI-triggered events."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: List[queue.Queue] = []
        self._history: List[Tuple[str, Any]] = []
        self._max_hist = 200

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=0)
        hist: List[Tuple[str, Any]] = []
        with self._lock:
            self._subs.append(q)
            if self._history:
                hist = list(self._history)
        for ev, payload in hist:
            try:
                q.put_nowait((ev, payload))
            except Exception:
                break
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._subs.remove(q)
            except ValueError:
                pass

    def publish(self, event: str, data: Any) -> None:
        payload = {
            "event": str(event or ""),
            "data": data,
            "ts": time.time(),
        }
        with self._lock:
            self._history.append((event, payload))
            if len(self._history) > self._max_hist:
                self._history = self._history[-self._max_hist :]
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait((event, payload))
            except Exception:
                pass


GUI_EVENT_BUS = GuiEventBus()


def publish_gui_event(event: str, data: Any) -> None:
    GUI_EVENT_BUS.publish(event, data)
