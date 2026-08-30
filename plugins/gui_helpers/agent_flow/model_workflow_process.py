from __future__ import annotations

import hashlib
import json
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional


EVENT_PREFIX = "__MODEL_WORKFLOW_WORKER__"


def _python_exe_works(path: str) -> bool:
    exe = str(path or "").strip()
    if not exe:
        return False
    try:
        proc = subprocess.run(
            [exe, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=8.0,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _resolve_python_exe(preferred: str | None = None) -> str:
    """Resolve a Python executable that can spawn model workflow workers.

    On Windows some venv launchers can keep pointing at an old/moved base
    python.exe. The parent server may already be running, but a child worker
    spawned with that stale launcher fails with "Unable to create process".
    Prefer the current interpreter, then nearby venv executables, then PATH.
    """
    candidates: list[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in candidates:
            candidates.append(text)

    add(preferred)
    add(sys.executable)
    add(getattr(sys, "_base_executable", ""))
    add(os.environ.get("PYTHON"))
    add(os.environ.get("PYTHON_EXE"))
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        add(str(Path(venv) / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")))
        add(str(Path(venv) / "bin" / ("python.exe" if os.name == "nt" else "python")))
    add("python")
    add("python3")

    for candidate in candidates:
        if _python_exe_works(candidate):
            return candidate
    return str(preferred or sys.executable or "python").strip()


class ModelWorkflowProcess:
    def __init__(
        self,
        *,
        run_id: str,
        workspace_root: str,
        python_exe: str | None = None,
        worker_key: str | None = None,
        persistent: bool = False,
    ) -> None:
        self.run_id = str(run_id or "").strip()
        self.worker_key = str(worker_key or self.run_id or "").strip()
        self.persistent = bool(persistent)
        self.workspace_root = str(workspace_root or "").strip()
        self.python_exe = str(python_exe or sys.executable or "python").strip()
        self.proc: subprocess.Popen[str] | None = None
        self.events: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self.log_lines: list[str] = []
        self._reader: threading.Thread | None = None
        self._lock = threading.Lock()
        self._closed = False

    def start(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        if self._closed:
            raise RuntimeError("model workflow worker is closed")
        script = Path(__file__).resolve().with_name("model_workflow_worker.py")
        root = Path(self.workspace_root or Path(__file__).resolve().parents[3]).resolve()
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["LLMLOADER2_MODEL_WORKFLOW_WORKER"] = "1"
        self.proc = subprocess.Popen(
            [self.python_exe, "-u", str(script), "--workspace-root", str(root)],
            cwd=str(root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
        self._reader = threading.Thread(target=self._read_loop, name=f"model-workflow-worker-{self.worker_key}", daemon=True)
        self._reader.start()
        deadline = time.time() + 90.0
        while time.time() < deadline:
            try:
                event = self.events.get(timeout=0.2)
            except queue.Empty:
                if self.proc and self.proc.poll() is not None:
                    raise RuntimeError(f"model workflow worker exited during startup rc={self.proc.returncode}")
                continue
            if event.get("event") == "ready":
                if not event.get("ok"):
                    raise RuntimeError(str(event.get("error") or "model workflow worker failed to start"))
                return
            self.events.put(event)
        raise TimeoutError("model workflow worker did not become ready")

    def _read_loop(self) -> None:
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            text = str(line or "").rstrip("\r\n")
            if not text:
                continue
            if text.startswith(EVENT_PREFIX):
                payload = text[len(EVENT_PREFIX) :]
                try:
                    event = json.loads(payload)
                    self.events.put(event)
                    continue
                except Exception:
                    pass
            self.log_lines.append(text)
            if len(self.log_lines) > 500:
                del self.log_lines[:-500]

    def call_tool(
        self,
        *,
        tool_name: str,
        ctx: Dict[str, Any],
        params: Dict[str, Any],
        call_run_id: str | None = None,
        progress: Callable[[str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        timeout_s: float | None = None,
    ) -> Dict[str, Any]:
        self.start()
        proc = self.proc
        if proc is None or proc.stdin is None:
            raise RuntimeError("model workflow worker stdin unavailable")
        call_id = secrets.token_hex(8)
        payload = {
            "cmd": "call",
            "call_id": call_id,
            "run_id": str(call_run_id or self.run_id or "").strip(),
            "tool_name": str(tool_name or ""),
            "ctx": self._strip_ctx(ctx),
            "params": params or {},
        }
        with self._lock:
            proc.stdin.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
            proc.stdin.flush()
        deadline = time.time() + float(timeout_s or 0) if timeout_s and timeout_s > 0 else None
        while True:
            if cancel_check and cancel_check():
                self.terminate()
                return {"ok": False, "warnings": ["model_workflow_worker_cancelled"], "data": {"error": "cancelled", "tool": tool_name}}
            if deadline and time.time() > deadline:
                self.terminate()
                return {"ok": False, "warnings": ["model_workflow_worker_timeout"], "data": {"error": "worker timeout", "tool": tool_name}}
            if proc.poll() is not None:
                return {
                    "ok": False,
                    "warnings": ["model_workflow_worker_exited"],
                    "data": {
                        "error": f"model workflow worker exited rc={proc.returncode}",
                        "tool": tool_name,
                        "worker_log_tail": list(self.log_lines[-80:]),
                    },
                }
            try:
                event = self.events.get(timeout=0.25)
            except queue.Empty:
                continue
            if str(event.get("call_id") or "") not in {"", call_id}:
                self.events.put(event)
                time.sleep(0.05)
                continue
            kind = str(event.get("event") or "")
            if kind == "progress":
                msg = str(event.get("message") or "").strip()
                if msg and progress:
                    progress(msg)
                continue
            if kind == "result":
                result = event.get("result")
                if isinstance(result, dict):
                    data = result.get("data")
                    if not isinstance(data, dict):
                        data = {}
                    data.setdefault("model_workflow_worker", True)
                    data.setdefault("model_workflow_worker_pid", proc.pid)
                    data.setdefault("model_workflow_worker_run_id", str(call_run_id or self.run_id or "").strip())
                    data.setdefault("model_workflow_worker_key", self.worker_key)
                    data.setdefault("model_workflow_worker_persistent", self.persistent)
                    result["data"] = data
                    return result
                return {"ok": bool(event.get("ok")), "warnings": ["model_workflow_worker_invalid_result"], "data": {"result": result}}
            if kind in {"error", "shutdown"}:
                return {"ok": False, "warnings": [f"model_workflow_worker_{kind}"], "data": dict(event)}

    def shutdown(self, *, keep_cache: bool = False, timeout_s: float = 10.0) -> None:
        if self._closed:
            return
        self._closed = True
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        try:
            if proc.stdin:
                proc.stdin.write(
                    json.dumps({"cmd": "shutdown", "call_id": secrets.token_hex(8), "run_id": self.run_id, "keep_cache": bool(keep_cache)}) + "\n"
                )
                proc.stdin.flush()
            proc.wait(timeout=max(0.5, float(timeout_s)))
        except Exception:
            self.terminate()
        finally:
            if proc is not None and proc.poll() is not None:
                self.proc = None

    def terminate(self) -> None:
        self._closed = True
        proc = self.proc
        if proc is None:
            return
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=3.0)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=3.0)
            except Exception:
                pass
        finally:
            if proc is not None and proc.poll() is not None:
                self.proc = None

    @staticmethod
    def _strip_ctx(ctx: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if not isinstance(ctx, dict):
            return out
        for key, value in ctx.items():
            if key == "app" or callable(value):
                continue
            try:
                json.dumps(value, default=str)
                out[key] = value
            except Exception:
                out[key] = str(value)
        return out


class ModelWorkflowProcessManager:
    def __init__(self, *, workspace_root: str, python_exe: str | None = None) -> None:
        self.workspace_root = str(workspace_root or "")
        self.python_exe = _resolve_python_exe(python_exe)
        self._workers: Dict[str, ModelWorkflowProcess] = {}
        self._run_to_key: Dict[str, str] = {}
        self._lock = threading.Lock()

    @staticmethod
    def stable_cache_key(*, pid: str = "", sid: str = "", flow_name: str = "", model_id: str = "", type_id: str = "", extra: str = "") -> str:
        parts = [
            "model_workflow",
            str(pid or "").strip() or "default",
            # Cached model workers are intentionally keyed by model/workflow,
            # not by transient chat session. Model Deck's Play button does not
            # have a session id, but the later Agent Flow run does; both must
            # resolve to the same worker when the user explicitly warmed it.
            "_shared",
            str(type_id or "").strip(),
            str(model_id or "").strip(),
            str(flow_name or "").strip(),
            str(extra or "").strip(),
        ]
        raw = "|".join(parts)
        digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:24]
        return f"cache:{digest}"

    def get(self, run_id: str, *, worker_key: str | None = None, persistent: bool = False) -> ModelWorkflowProcess:
        rid = str(run_id or "").strip()
        if not rid:
            raise ValueError("run_id required")
        key = str(worker_key or rid).strip()
        if not key:
            key = rid
        with self._lock:
            worker = self._workers.get(key)
            if worker is not None and self._worker_is_stale(worker):
                self._workers.pop(key, None)
                for mapped_rid, mapped_key in list(self._run_to_key.items()):
                    if mapped_key == key:
                        self._run_to_key.pop(mapped_rid, None)
                worker = None
            if worker is None:
                worker = ModelWorkflowProcess(
                    run_id=rid,
                    workspace_root=self.workspace_root,
                    python_exe=self.python_exe,
                    worker_key=key,
                    persistent=bool(persistent),
                )
                self._workers[key] = worker
            elif persistent:
                worker.persistent = True
            self._run_to_key[rid] = key
            return worker

    def call_tool(self, run_id: str, *, worker_key: str | None = None, keep_alive: bool = False, **kwargs: Any) -> Dict[str, Any]:
        worker = self.get(run_id, worker_key=worker_key, persistent=bool(keep_alive))
        try:
            return worker.call_tool(call_run_id=str(run_id or "").strip(), **kwargs)
        except RuntimeError as exc:
            # A cached worker can be released or killed between the manager
            # lookup and the actual call. If that happens, purge the stale
            # object once and create a fresh worker for this explicit request.
            if "worker is closed" not in str(exc).lower():
                raise
            key = str(worker_key or run_id or "").strip()
            if key:
                with self._lock:
                    stale = self._workers.get(key)
                    if stale is worker:
                        self._workers.pop(key, None)
                    for mapped_rid, mapped_key in list(self._run_to_key.items()):
                        if mapped_key == key:
                            self._run_to_key.pop(mapped_rid, None)
            worker = self.get(run_id, worker_key=worker_key, persistent=bool(keep_alive))
            return worker.call_tool(call_run_id=str(run_id or "").strip(), **kwargs)

    def has_worker(self, worker_key: str) -> bool:
        key = str(worker_key or "").strip()
        if not key:
            return False
        with self._lock:
            worker = self._workers.get(key)
            if worker is not None and self._worker_is_stale(worker):
                self._workers.pop(key, None)
                for rid, mapped in list(self._run_to_key.items()):
                    if mapped == key:
                        self._run_to_key.pop(rid, None)
                return False
        return bool(worker and worker.proc and worker.proc.poll() is None)

    def list_workers(self) -> list[Dict[str, Any]]:
        with self._lock:
            rows = list(self._workers.items())
        out: list[Dict[str, Any]] = []
        for key, worker in rows:
            proc = worker.proc
            out.append(
                {
                    "worker_key": key,
                    "run_id": worker.run_id,
                    "pid": proc.pid if proc else None,
                    "alive": bool(proc and proc.poll() is None),
                    "persistent": bool(worker.persistent),
                }
            )
        return out

    def shutdown(self, run_id: str, *, keep_cache: bool = False) -> None:
        rid = str(run_id or "").strip()
        if not rid:
            return
        worker: ModelWorkflowProcess | None = None
        with self._lock:
            key = self._run_to_key.pop(rid, rid)
            worker = self._workers.get(key)
            if worker and self._worker_is_stale(worker):
                self._workers.pop(key, None)
                for mapped_rid, mapped_key in list(self._run_to_key.items()):
                    if mapped_key == key:
                        self._run_to_key.pop(mapped_rid, None)
                return
            if worker and (keep_cache or worker.persistent):
                return
            worker = self._workers.pop(key, None)
        if worker:
            worker.shutdown(keep_cache=keep_cache)

    def terminate(self, run_id: str) -> bool:
        rid = str(run_id or "").strip()
        worker: ModelWorkflowProcess | None = None
        with self._lock:
            key = self._run_to_key.pop(rid, rid)
            worker = self._workers.pop(key, None)
        if worker:
            worker.terminate()
            return True
        return False

    def release_cached(self, worker_key: str) -> bool:
        key = str(worker_key or "").strip()
        if not key:
            return False
        worker: ModelWorkflowProcess | None = None
        with self._lock:
            worker = self._workers.pop(key, None)
            for rid, mapped in list(self._run_to_key.items()):
                if mapped == key:
                    self._run_to_key.pop(rid, None)
        if worker:
            # Cached worker release is a user-facing "Stop" action. Prefer a
            # graceful shutdown so workflow cleanup hooks get a chance to drop
            # prompt/model caches before the OS tears down the process. If the
            # process is wedged, shutdown() falls back to terminate().
            worker.shutdown(keep_cache=False, timeout_s=15.0)
            return True
        return False

    @staticmethod
    def _worker_is_stale(worker: ModelWorkflowProcess | None) -> bool:
        if worker is None:
            return True
        if getattr(worker, "_closed", False):
            return True
        proc = getattr(worker, "proc", None)
        return bool(proc is not None and proc.poll() is not None)

    def terminate_all(self) -> int:
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
            self._run_to_key.clear()
        for worker in workers:
            worker.terminate()
        return len(workers)
