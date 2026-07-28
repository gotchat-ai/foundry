from __future__ import annotations

from typing import Any, Dict, List, Optional
import multiprocessing
import threading
import time
import uuid

try:
    from plugins.gui_helpers._framework.event_bus import publish_gui_event
except Exception:
    publish_gui_event = None


def _vlm_worker_once(conn, model_cfg: Dict[str, Any], messages: List[Dict[str, Any]], params: Dict[str, Any]) -> None:
    from model_loader_gguf import GGUFChatModel

    model = GGUFChatModel(
        model_path=model_cfg["model_path"],
        n_ctx=int(model_cfg.get("n_ctx") or 4096),
        n_threads=model_cfg.get("n_threads"),
        n_gpu_layers=int(model_cfg.get("n_gpu_layers") or 0),
        chat_format=model_cfg.get("chat_format"),
        mmproj_path=model_cfg.get("mmproj_path"),
        vision_handler=model_cfg.get("vision_handler") or "auto",
        verbose=False,
    )
    try:
        max_new_tokens = int(params.get("max_new_tokens") or 512)
        temperature = float(params.get("temperature") or 0.2)
        top_p = float(params.get("top_p") or 0.3)
        top_k = int(params.get("top_k") or 30)
        out = ""
        if hasattr(model, "chat_mm"):
            out = model.chat_mm(
                messages=messages,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
            )
        if not out:
            out = model.chat(
                messages=messages,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
            )
        conn.send({"ok": True, "raw": out})
    except Exception as exc:
        conn.send({"ok": False, "error": str(exc)})
    finally:
        try:
            model.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


def _vlm_worker_stream_once(conn, model_cfg: Dict[str, Any], messages: List[Dict[str, Any]], params: Dict[str, Any]) -> None:
    from model_loader_gguf import GGUFChatModel

    model = GGUFChatModel(
        model_path=model_cfg["model_path"],
        n_ctx=int(model_cfg.get("n_ctx") or 4096),
        n_threads=model_cfg.get("n_threads"),
        n_gpu_layers=int(model_cfg.get("n_gpu_layers") or 0),
        chat_format=model_cfg.get("chat_format"),
        mmproj_path=model_cfg.get("mmproj_path"),
        vision_handler=model_cfg.get("vision_handler") or "auto",
        verbose=False,
    )
    try:
        max_new_tokens = int(params.get("max_new_tokens") or 512)
        temperature = float(params.get("temperature") or 0.2)
        top_p = float(params.get("top_p") or 0.3)
        token_chunk_size = int(params.get("token_chunk_size") or 8)
        out = ""
        for piece in model.stream_chat(
            messages=messages,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            token_chunk_size=token_chunk_size,
        ):
            if not piece:
                continue
            out += piece
            try:
                conn.send({"type": "delta", "text": piece})
            except Exception:
                pass
        conn.send({"type": "done", "ok": True, "raw": out})
    except Exception as exc:
        try:
            conn.send({"type": "error", "ok": False, "error": str(exc)})
        except Exception:
            pass
    finally:
        try:
            model.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


def _vlm_worker_loop(conn, model_cfg: Dict[str, Any]) -> None:
    from model_loader_gguf import GGUFChatModel

    model = GGUFChatModel(
        model_path=model_cfg["model_path"],
        n_ctx=int(model_cfg.get("n_ctx") or 4096),
        n_threads=model_cfg.get("n_threads"),
        n_gpu_layers=int(model_cfg.get("n_gpu_layers") or 0),
        chat_format=model_cfg.get("chat_format"),
        mmproj_path=model_cfg.get("mmproj_path"),
        vision_handler=model_cfg.get("vision_handler") or "auto",
        verbose=False,
    )
    try:
        while True:
            try:
                msg = conn.recv()
            except EOFError:
                break
            if not isinstance(msg, dict):
                continue
            cmd = msg.get("cmd")
            if cmd == "shutdown":
                break
            if cmd != "plan":
                if cmd != "stream":
                    continue
            payload = msg.get("payload") or {}
            messages = payload.get("messages") or []
            params = payload.get("params") or {}
            try:
                max_new_tokens = int(params.get("max_new_tokens") or 512)
                temperature = float(params.get("temperature") or 0.2)
                top_p = float(params.get("top_p") or 0.3)
                if cmd == "stream":
                    token_chunk_size = int(params.get("token_chunk_size") or 8)
                    out = ""
                    for piece in model.stream_chat(
                        messages=messages,
                        max_new_tokens=max_new_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        token_chunk_size=token_chunk_size,
                    ):
                        if not piece:
                            continue
                        out += piece
                        try:
                            conn.send({"type": "delta", "text": piece})
                        except Exception:
                            pass
                    conn.send({"type": "done", "ok": True, "raw": out})
                else:
                    top_k = int(params.get("top_k") or 30)
                    out = ""
                    if hasattr(model, "chat_mm"):
                        out = model.chat_mm(
                            messages=messages,
                            max_new_tokens=max_new_tokens,
                            temperature=temperature,
                            top_p=top_p,
                            top_k=top_k,
                        )
                    if not out:
                        out = model.chat(
                            messages=messages,
                            max_new_tokens=max_new_tokens,
                            temperature=temperature,
                            top_p=top_p,
                            top_k=top_k,
                        )
                    conn.send({"ok": True, "raw": out})
            except Exception as exc:
                if cmd == "stream":
                    try:
                        conn.send({"type": "error", "ok": False, "error": str(exc)})
                    except Exception:
                        pass
                else:
                    conn.send({"ok": False, "error": str(exc)})
    finally:
        try:
            model.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


class RouterWorkerManager:
    _ACTIVE_WORKERS: Dict[str, Dict[str, Any]] = {}
    _LOCK = threading.Lock()

    def __init__(self) -> None:
        self._ctx = multiprocessing.get_context("spawn")

    @classmethod
    def _register_worker(cls, worker: "VLMWorker", meta: Optional[Dict[str, Any]] = None) -> str:
        worker_id = f"vlm:{uuid.uuid4().hex}"
        info = {
            "worker_id": worker_id,
            "pid": worker.pid,
            "started_ts": time.time(),
            "meta": dict(meta or {}),
            "worker": worker,
        }
        with cls._LOCK:
            cls._ACTIVE_WORKERS[worker_id] = info
        worker._worker_id = worker_id
        worker._manager = cls
        if callable(publish_gui_event):
            try:
                publish_gui_event(
                    "processes.changed",
                    {"kind": "worker", "action": "start", "worker_id": worker_id, "meta": dict(meta or {})},
                )
            except Exception:
                pass
        return worker_id

    @classmethod
    def _unregister_worker(cls, worker_id: Optional[str]) -> None:
        if not worker_id:
            return
        with cls._LOCK:
            cls._ACTIVE_WORKERS.pop(worker_id, None)
        if callable(publish_gui_event):
            try:
                publish_gui_event("processes.changed", {"kind": "worker", "action": "stop", "worker_id": worker_id})
            except Exception:
                pass

    @classmethod
    def list_workers(cls) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        stale: List[str] = []
        with cls._LOCK:
            items = list(cls._ACTIVE_WORKERS.items())
        for wid, info in items:
            worker = info.get("worker")
            alive = bool(worker.is_alive()) if worker else False
            if not alive:
                stale.append(wid)
                continue
            out.append({
                "worker_id": wid,
                "pid": info.get("pid"),
                "started_ts": info.get("started_ts"),
                "meta": dict(info.get("meta") or {}),
                "alive": True,
            })
        if stale:
            with cls._LOCK:
                for wid in stale:
                    cls._ACTIVE_WORKERS.pop(wid, None)
        return out

    @classmethod
    def stop_worker(cls, worker_id: str) -> Dict[str, Any]:
        with cls._LOCK:
            info = cls._ACTIVE_WORKERS.get(worker_id)
        if not info:
            return {"ok": False, "error": "worker_not_found"}
        worker = info.get("worker")
        try:
            if worker is not None:
                worker.close()
        finally:
            cls._unregister_worker(worker_id)
        return {"ok": True}

    def run_vlm_plan(
        self,
        model_cfg: Dict[str, Any],
        messages: List[Dict[str, Any]],
        params: Dict[str, Any],
        timeout_s: int = 120,
    ) -> Dict[str, Any]:
        parent, child = self._ctx.Pipe()
        proc = self._ctx.Process(
            target=_vlm_worker_once,
            args=(child, model_cfg, messages, params),
            daemon=True,
        )
        proc.start()
        try:
            if not parent.poll(timeout_s):
                return {"ok": False, "error": "worker_timeout"}
            return parent.recv()
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

    def run_vlm_stream(
        self,
        model_cfg: Dict[str, Any],
        messages: List[Dict[str, Any]],
        params: Dict[str, Any],
        timeout_s: int = 120,
        token_cb: Optional[Any] = None,
    ) -> Dict[str, Any]:
        parent, child = self._ctx.Pipe()
        proc = self._ctx.Process(
            target=_vlm_worker_stream_once,
            args=(child, model_cfg, messages, params),
            daemon=True,
        )
        proc.start()
        start = time.time()
        chunks: List[str] = []
        try:
            while True:
                if not parent.poll(0.1):
                    if time.time() - start > timeout_s:
                        return {"ok": False, "error": "worker_timeout"}
                    continue
                msg = parent.recv()
                if not isinstance(msg, dict):
                    continue
                mtype = msg.get("type")
                if mtype == "delta":
                    piece = msg.get("text") or ""
                    if piece:
                        chunks.append(piece)
                        if callable(token_cb):
                            try:
                                token_cb(piece)
                            except Exception:
                                pass
                    continue
                if mtype == "done":
                    return {"ok": bool(msg.get("ok", True)), "raw": msg.get("raw") or "".join(chunks)}
                if mtype == "error":
                    return {"ok": False, "error": msg.get("error") or "worker_error"}
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

    def spawn_vlm_worker(self, model_cfg: Dict[str, Any], meta: Optional[Dict[str, Any]] = None) -> "VLMWorker":
        worker = VLMWorker(self._ctx, model_cfg)
        self._register_worker(worker, meta=meta)
        return worker


class VLMWorker:
    def __init__(self, ctx: multiprocessing.context.BaseContext, model_cfg: Dict[str, Any]) -> None:
        parent, child = ctx.Pipe()
        self._parent = parent
        self._proc = ctx.Process(target=_vlm_worker_loop, args=(child, model_cfg), daemon=True)
        self._proc.start()
        self._worker_id: Optional[str] = None
        self._manager: Optional[type] = None

    def plan(self, messages: List[Dict[str, Any]], params: Dict[str, Any], timeout_s: int = 120) -> Dict[str, Any]:
        self._parent.send({"cmd": "plan", "payload": {"messages": messages, "params": params}})
        if not self._parent.poll(timeout_s):
            return {"ok": False, "error": "worker_timeout"}
        return self._parent.recv()

    def stream(
        self,
        messages: List[Dict[str, Any]],
        params: Dict[str, Any],
        timeout_s: int = 120,
        token_cb: Optional[Any] = None,
    ) -> Dict[str, Any]:
        self._parent.send({"cmd": "stream", "payload": {"messages": messages, "params": params}})
        start = time.time()
        chunks: List[str] = []
        while True:
            if not self._parent.poll(0.1):
                if time.time() - start > timeout_s:
                    return {"ok": False, "error": "worker_timeout"}
                continue
            msg = self._parent.recv()
            if not isinstance(msg, dict):
                continue
            mtype = msg.get("type")
            if mtype == "delta":
                piece = msg.get("text") or ""
                if piece:
                    chunks.append(piece)
                    if callable(token_cb):
                        try:
                            token_cb(piece)
                        except Exception:
                            pass
                continue
            if mtype == "done":
                return {"ok": bool(msg.get("ok", True)), "raw": msg.get("raw") or "".join(chunks)}
            if mtype == "error":
                return {"ok": False, "error": msg.get("error") or "worker_error"}

    def close(self) -> None:
        try:
            self._parent.send({"cmd": "shutdown"})
        except Exception:
            pass
        try:
            if self._proc.is_alive():
                self._proc.join(timeout=3)
        except Exception:
            pass
        try:
            if self._proc.is_alive():
                self._proc.terminate()
        except Exception:
            pass
        try:
            if self._manager is not None:
                self._manager._unregister_worker(self._worker_id)
        except Exception:
            pass

    def is_alive(self) -> bool:
        try:
            return bool(self._proc.is_alive())
        except Exception:
            return False

    @property
    def pid(self) -> Optional[int]:
        try:
            return self._proc.pid
        except Exception:
            return None
