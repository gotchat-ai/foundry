import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

@dataclass
class _TurnStream:
    turn_id: str
    qs: List[queue.Queue]
    done: bool = False
    err: Optional[str] = None
    created_ts: float = 0.0
    # Backlog for late subscribers (session switch/reconnect)
    # Stored as (event_name, payload) tuples.
    history: Optional[List[tuple]] = None


class TurnStreamBus:
    """
    In-memory fanout for ONE turn's token stream.
    - Background worker publishes token chunks
    - Any number of subscribers can read them (SSE clients)
    - If a subscriber disconnects, we just remove its queue
    - Turn continues to run and can still persist via hooks
    """
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._turns: Dict[str, _TurnStream] = {}
        # Max backlog events per turn for late subscribers
        self._max_hist_events = 2000

    # def new_turn(self, turn_id: str) -> None:
    #     with self._lock:
    #         self._turns[turn_id] = _TurnStream(turn_id=turn_id, qs=[], done=False, err=None, created_ts=time.time())

    def new_turn(self, turn_id: str) -> None:
        with self._lock:
            self._turns[turn_id] = _TurnStream(
                turn_id=turn_id,
                qs=[],
                done=False,
                err=None,
                created_ts=time.time(),
                history=[],
            )

    # def subscribe(self, turn_id: str) -> queue.Queue:
    #     q: queue.Queue = queue.Queue(maxsize=512)
    #     with self._lock:
    #         t = self._turns.get(turn_id)
    #         if not t:
    #             t = _TurnStream(turn_id=turn_id, qs=[], done=True, err="missing", created_ts=time.time())
    #             self._turns[turn_id] = t
    #         t.qs.append(q)
    #     return q

    def subscribe(self, turn_id: str) -> queue.Queue:
        # Unbounded to avoid dropping tokens if the event loop is briefly busy.
        q: queue.Queue = queue.Queue(maxsize=0)
        # Capture backlog for late subscriber replay
        hist: List[tuple] = []
        with self._lock:
            t = self._turns.get(turn_id)
            if not t:
                t = _TurnStream(
                    turn_id=turn_id,
                    qs=[],
                    done=True,
                    err="missing",
                    created_ts=time.time(),
                    history=[("done", {"ok": False, "error": "missing"})],
                )
                self._turns[turn_id] = t
            t.qs.append(q)
            if t.history:
                hist = list(t.history)

        # Replay backlog outside the lock (best effort)
        for evt, payload in hist:
            try:
                q.put_nowait((evt, payload))
            except Exception:
                break
        return q

    def unsubscribe(self, turn_id: str, q: queue.Queue) -> None:
        with self._lock:
            t = self._turns.get(turn_id)
            if not t:
                return
            try:
                t.qs.remove(q)
            except ValueError:
                pass

    # def publish_token(self, turn_id: str, text: str) -> None:
    #     with self._lock:
    #         t = self._turns.get(turn_id)
    #         if not t:
    #             return
    #         qs = list(t.qs)
    #     for q in qs:
    #         try:
    #             q.put_nowait(("token", {"text": text}))
    #         except Exception:
    #             pass

    def publish_token(self, turn_id: str, text: str) -> None:
        payload = {"text": text}
        with self._lock:
            t = self._turns.get(turn_id)
            if not t:
                return
            if t.history is None:
                t.history = []
            t.history.append(("token", payload))
            if len(t.history) > self._max_hist_events:
                t.history = t.history[-self._max_hist_events :]
            qs = list(t.qs)

        for q in qs:
            try:
                q.put_nowait(("token", payload))
            except Exception:
                pass

    # def publish_event(self, turn_id: str, event: str, data: Any) -> None:
    #     with self._lock:
    #         t = self._turns.get(turn_id)
    #         if not t:
    #             return
    #         qs = list(t.qs)
    #     for q in qs:
    #         try:
    #             q.put_nowait((event, data))
    #         except Exception:
    #             pass

    def publish_event(self, turn_id: str, event: str, data: Any) -> None:
        with self._lock:
            t = self._turns.get(turn_id)
            if not t:
                return
            if t.history is None:
                t.history = []
            t.history.append((event, data))
            if len(t.history) > self._max_hist_events:
                t.history = t.history[-self._max_hist_events :]
            qs = list(t.qs)

        for q in qs:
            try:
                q.put_nowait((event, data))
            except Exception:
                pass

    # def finish(self, turn_id: str, *, ok: bool, err: Optional[str] = None, ext: Optional[dict] = None) -> None:
    #     with self._lock:
    #         t = self._turns.get(turn_id)
    #         if not t:
    #             return
    #         t.done = True
    #         t.err = err
    #         qs = list(t.qs)

    #     # push done to subscribers
    #     payload = {"ok": bool(ok)}
    #     if err:
    #         payload["error"] = err
    #     if ext:
    #         payload["ext"] = ext

    #     for q in qs:
    #         try:
    #             q.put_nowait(("done", payload))
    #         except Exception:
    #             pass

    def finish(self, turn_id: str, *, ok: bool, err: Optional[str] = None, ext: Optional[dict] = None) -> None:
        # push done to subscribers
        payload = {"ok": bool(ok)}
        if err:
            payload["error"] = err
        if ext:
            payload["ext"] = ext

        with self._lock:
            t = self._turns.get(turn_id)
            if not t:
                return
            t.done = True
            t.err = err
            if t.history is None:
                t.history = []
            t.history.append(("done", payload))
            if len(t.history) > self._max_hist_events:
                t.history = t.history[-self._max_hist_events :]
            qs = list(t.qs)

        for q in qs:
            try:
                q.put_nowait(("done", payload))
            except Exception:
                pass

    def gc(self, max_age_sec: int = 3600) -> None:
        now = time.time()
        with self._lock:
            drop = [tid for tid, t in self._turns.items() if (now - t.created_ts) > max_age_sec and t.done]
            for tid in drop:
                self._turns.pop(tid, None)


TURN_BUS = TurnStreamBus()
