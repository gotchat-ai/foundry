import json
import os
import shutil
import tempfile
import time
from typing import Any, Callable

from fastapi import HTTPException


class PatchRoutes:
    """Patch application, patch logs, and natural-language code-edit endpoints."""

    def __init__(
        self,
        *,
        user_rag_getter: Callable[[], Any],
        user_rag_enabled_getter: Callable[[], bool],
        model_getter: Callable[[], Any],
        patcher_module: Any,
        repo_ingest_module: Any,
    ) -> None:
        self._user_rag_getter = user_rag_getter
        self._user_rag_enabled_getter = user_rag_enabled_getter
        self._model_getter = model_getter
        self._patcher = patcher_module
        self._repo_ingest = repo_ingest_module

    def _require_user_rag(self) -> Any:
        user_rag = self._user_rag_getter()
        if not self._user_rag_enabled_getter() or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        return user_rag

    def _patch_log_root(self, sid: str, entry: str | None = None) -> str:
        user_rag = self._user_rag_getter()
        root = os.path.join(user_rag.cold_base_dir or (user_rag.base_dir or "."), "_patch_logs", sid)
        if entry is not None:
            root = os.path.join(root, entry)
        return root

    def patch_apply(self, req: Any) -> dict[str, Any]:
        user_rag = self._require_user_rag()
        parent_dir = user_rag.repo_version_dir(req.sid, req.repo_id, req.parent_version) if req.parent_version else None
        work = tempfile.mkdtemp(prefix="patchwork_")
        if parent_dir and os.path.isdir(parent_dir):
            shutil.copytree(parent_dir, work, dirs_exist_ok=True)

        plan = {"operations": req.plan.operations}
        result = self._patcher.apply_patch_plan(work, plan)

        stats = self._repo_ingest.ingest_dir_to_user_rag_cold(
            user_rag,
            req.sid,
            req.repo_id,
            work,
            self._model_getter().tokenizer,
            version=req.new_version,
            parent_version=req.parent_version,
        )

        timestamp = int(time.time())
        log_dir = os.path.join(
            user_rag.cold_base_dir or (user_rag.base_dir or "."),
            "_patch_logs",
            req.sid,
            f"{timestamp}_{req.new_version}",
        )
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "plan.json"), "w", encoding="utf-8") as handle:
            json.dump(plan, handle, ensure_ascii=False, indent=2)
        with open(os.path.join(log_dir, "apply_and_verify.json"), "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)

        return {"ok": True, "new_version": req.new_version, "ingest_stats": stats, "log_dir": log_dir}

    def patch_logs(self, sid: str) -> dict[str, Any]:
        root = self._patch_log_root(sid)
        if not os.path.isdir(root):
            return {"data": []}
        entries = sorted(os.listdir(root))
        return {"data": entries}

    def patch_log(self, sid: str, entry: str) -> dict[str, str]:
        root = self._patch_log_root(sid, entry)
        if not os.path.isdir(root):
            raise HTTPException(404, "not found")
        out = {}
        for filename in os.listdir(root):
            with open(os.path.join(root, filename), "r", encoding="utf-8") as handle:
                out[filename] = handle.read()
        return out

    def synthesize_plan_with_model(self, user_text: str) -> dict[str, Any]:
        system_text = (
            "You are a code patch planner. Output ONLY JSON with a 'operations' list—no prose. "
            "Each item has a 'type' in {add_param','create_file','upsert_function','upsert_class','add_imports','replace_region, 'html_patch'}, "
            "and the fields required by that type. Keep it minimal and safe."
        )
        messages = [{"role": "system", "content": system_text}, {"role": "user", "content": user_text}]
        if not messages:
            messages = [{"role": "user", "content": ""}]
        else:
            last = messages[-1]
            if not (isinstance(last, dict) and last.get("role") == "user"):
                messages = messages + [{"role": "user", "content": ""}]

        response = self._model_getter().chat(messages=messages, max_tokens=768, temperature=0.2)
        text = response["content"]
        try:
            payload = json.loads(text)
            if "operations" in payload:
                return payload
        except Exception:
            pass
        return {"operations": []}

    def chat_code_edit(self, req: Any, *, synthesize_plan: Callable[[str], dict[str, Any]] | None = None) -> dict[str, Any]:
        user_rag = self._require_user_rag()
        parent_dir = user_rag.repo_version_dir(req.sid, req.repo_id, req.parent_version) if req.parent_version else None
        work = tempfile.mkdtemp(prefix="patchwork_")
        if parent_dir and os.path.isdir(parent_dir):
            shutil.copytree(parent_dir, work, dirs_exist_ok=True)

        plan_fn = synthesize_plan or self.synthesize_plan_with_model
        plan = req.plan or plan_fn(req.request or "")
        result = self._patcher.apply_patch_plan(work, plan)

        stats = self._repo_ingest.ingest_dir_to_user_rag_cold(
            user_rag,
            req.sid,
            req.repo_id,
            work,
            self._model_getter().tokenizer,
            version=req.new_version,
            parent_version=req.parent_version,
        )

        timestamp = int(time.time())
        log_dir = os.path.join(
            user_rag.cold_base_dir or (user_rag.base_dir or "."),
            "_patch_logs",
            req.sid,
            f"{timestamp}_{req.new_version}",
        )
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "plan.json"), "w", encoding="utf-8") as handle:
            json.dump(plan, handle, ensure_ascii=False, indent=2)
        with open(os.path.join(log_dir, "apply_and_verify.json"), "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)

        return {
            "ok": True,
            "new_version": req.new_version,
            "ingest_stats": stats,
            "log_dir": log_dir,
            "applied_plan": plan,
            "verify": result.get("verifications", []),
        }
