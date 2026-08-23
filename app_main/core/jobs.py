import dataclasses
import queue
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

from app_main.core.stream_bus import TURN_BUS

@dataclasses.dataclass
class _GenJob:
    job_id: str
    turn_id: str
    model_key: str
    cap: int  # max parallel for this model_key
    run: Callable[[], None]


class _GenScheduler:
    def __init__(self, *, num_workers: int = 2) -> None:
        self._num_workers = max(1, int(num_workers))
        self._lock = threading.Lock()

        # per-model FIFO job queues
        self._q_by_model: Dict[str, Deque[_GenJob]] = {}
        # per-model in-flight counts
        self._inflight: Dict[str, int] = {}
        # per-model cap (max concurrency per model)
        self._cap: Dict[str, int] = {}

        # ready queue of model keys that have runnable work
        self._ready: "queue.Queue[str]" = queue.Queue()
        self._ready_set: set[str] = set()

        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        for i in range(self._num_workers):
            t = threading.Thread(target=self._worker_loop, daemon=True, name=f"genq-worker-{i}")
            t.start()

    def submit(self, job: _GenJob) -> None:
        with self._lock:
            dq = self._q_by_model.get(job.model_key)
            if dq is None:
                dq = deque()
                self._q_by_model[job.model_key] = dq
                self._inflight[job.model_key] = 0
                self._cap[job.model_key] = max(1, int(job.cap))
            else:
                # cap may change across calls; keep the max (safer for enabling later)
                self._cap[job.model_key] = max(self._cap.get(job.model_key, 1), max(1, int(job.cap)))

            dq.append(job)

            # mark model as ready
            if job.model_key not in self._ready_set:
                self._ready_set.add(job.model_key)
                self._ready.put(job.model_key)

    def _maybe_mark_ready_locked(self, model_key: str) -> None:
        # only mark ready if there is pending work and we can run (inflight < cap)
        dq = self._q_by_model.get(model_key)
        if not dq:
            return
        inflight = int(self._inflight.get(model_key, 0))
        cap = int(self._cap.get(model_key, 1))
        if inflight >= cap:
            return
        if model_key not in self._ready_set:
            self._ready_set.add(model_key)
            self._ready.put(model_key)

    def _worker_loop(self) -> None:
        while True:
            model_key = self._ready.get()
            job: _GenJob | None = None

            with self._lock:
                # allow this model_key to be re-enqueued later
                self._ready_set.discard(model_key)

                dq = self._q_by_model.get(model_key)
                if not dq:
                    continue

                inflight = int(self._inflight.get(model_key, 0))
                cap = int(self._cap.get(model_key, 1))

                # if can't run now, re-mark ready later (someone will call _maybe_mark_ready_locked)
                if inflight >= cap:
                    # keep it in backlog; someone finishing will re-ready it
                    continue

                # pop FIFO
                job = dq.popleft()
                self._inflight[model_key] = inflight + 1

                # if more work and still capacity, keep ready
                self._maybe_mark_ready_locked(model_key)

            # run outside lock
            try:
                assert job is not None
                job.run()
            except Exception as e:
                # never kill the worker thread
                try:
                    TURN_BUS.publish_event(job.turn_id, "diag", {"error": f"gen_worker_error: {e}"})
                    TURN_BUS.finish(job.turn_id, ok=False, err=str(e))
                except Exception:
                    pass
            finally:
                with self._lock:
                    # decrement inflight and possibly ready this model
                    try:
                        self._inflight[model_key] = max(0, int(self._inflight.get(model_key, 1)) - 1)
                    except Exception:
                        self._inflight[model_key] = 0
                    self._maybe_mark_ready_locked(model_key)

    def queue_positions(self) -> Dict[str, int]:
        with self._lock:
            positions: Dict[str, int] = {}
            for model_key, dq in self._q_by_model.items():
                if not dq:
                    continue
                for idx, job in enumerate(dq):
                    try:
                        positions[str(job.job_id)] = idx + 1
                    except Exception:
                        continue
            return positions

    def cancel(self, job_id: str) -> bool:
        key = str(job_id or "")
        if not key:
            return False
        removed = False
        with self._lock:
            for model_key, dq in list(self._q_by_model.items()):
                if not dq:
                    continue
                remaining = deque([job for job in dq if str(job.job_id) != key])
                if len(remaining) != len(dq):
                    self._q_by_model[model_key] = remaining
                    removed = True
            return removed


class AiJobRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, Dict[str, Any]] = {}

    def upsert(self, job_id: str, **fields: Any) -> Dict[str, Any]:
        now = time.time()
        key = str(job_id or "")
        if not key:
            return {}
        with self._lock:
            entry = dict(self._jobs.get(key) or {})
            if not entry:
                entry["job_id"] = key
                entry["created_ts"] = now
            entry.update(fields)
            if entry.get("status") == "running" and not entry.get("started_ts"):
                entry["started_ts"] = now
            entry["updated_ts"] = now
            self._jobs[key] = entry
            return dict(entry)

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        key = str(job_id or "")
        if not key:
            return None
        with self._lock:
            entry = self._jobs.get(key)
            return dict(entry) if entry else None

    def remove(self, job_id: str) -> None:
        key = str(job_id or "")
        if not key:
            return
        with self._lock:
            self._jobs.pop(key, None)

    def snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(v) for v in self._jobs.values()]
