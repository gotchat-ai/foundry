from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .registry import ModelLoaderRegistry


class DownloadRequest(BaseModel):
    model_id: str
    gguf_filename: Optional[str] = None


class LoadRequest(BaseModel):
    settings: Dict[str, Any] = {}


class SaneSettingsRequest(BaseModel):
    model: Optional[str] = None


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]]
    settings: Dict[str, Any] = {}


class SummarizeThinkingRequest(BaseModel):
    messages: list[dict[str, Any]]
    reply_text: str
    settings: Dict[str, Any] = {}


def build_model_loader_router(reg: ModelLoaderRegistry) -> APIRouter:
    router = APIRouter(prefix="/v1/model_loaders", tags=["model_loaders"])

    def _get_plugin(pid: str):
        plugin = reg.get(pid)
        if plugin is None:
            raise HTTPException(404, f"unknown model_loader plugin: {pid}")
        return plugin

    @router.get("")
    def list_model_loaders():
        return {"plugins": reg.list_metas()}

    @router.get("/{plugin_id}/schema")
    def schema(plugin_id: str):
        plugin = _get_plugin(plugin_id)
        return {"plugin": plugin_id, "schema": plugin.schema()}

    @router.post("/{plugin_id}/sane_settings")
    def sane_settings(plugin_id: str, req: SaneSettingsRequest):
        plugin = _get_plugin(plugin_id)
        return {"plugin": plugin_id, "sane": plugin.sane_settings(model=req.model)}

    @router.post("/{plugin_id}/download")
    async def download(plugin_id: str, req: DownloadRequest):
        plugin = _get_plugin(plugin_id)
        return await plugin.download(model_id=req.model_id, gguf_filename=req.gguf_filename)

    @router.post("/{plugin_id}/load")
    async def load(plugin_id: str, request: Request, req: LoadRequest):
        plugin = _get_plugin(plugin_id)
        return await plugin.load(request, settings=req.settings or {})

    @router.post("/{plugin_id}/unload")
    async def unload(plugin_id: str, request: Request):
        plugin = _get_plugin(plugin_id)
        return await plugin.unload(request)

    @router.get("/{plugin_id}/status")
    async def status(plugin_id: str, request: Request):
        plugin = _get_plugin(plugin_id)
        return await plugin.status(request)

    @router.post("/{plugin_id}/chat")
    async def chat(plugin_id: str, request: Request, req: ChatRequest):
        plugin = _get_plugin(plugin_id)
        return await plugin.chat(request, messages=req.messages, settings=req.settings or {})

    @router.post("/{plugin_id}/chat_stream")
    async def chat_stream(plugin_id: str, request: Request, req: ChatRequest):
        plugin = _get_plugin(plugin_id)
        gen = await plugin.chat_stream(request, messages=req.messages, settings=req.settings or {})
        return StreamingResponse(gen, media_type="text/event-stream")

    @router.post("/{plugin_id}/plan_thinking")
    async def plan_thinking(plugin_id: str, request: Request, req: ChatRequest):
        plugin = _get_plugin(plugin_id)
        return await plugin.plan_thinking(request, messages=req.messages, settings=req.settings or {})

    @router.post("/{plugin_id}/plan_thinking_stream")
    async def plan_thinking_stream(plugin_id: str, request: Request, req: ChatRequest):
        plugin = _get_plugin(plugin_id)
        gen = await plugin.plan_thinking_stream(request, messages=req.messages, settings=req.settings or {})
        return StreamingResponse(gen, media_type="text/event-stream")

    @router.post("/{plugin_id}/summarize_thinking")
    async def summarize_thinking(plugin_id: str, request: Request, req: SummarizeThinkingRequest):
        plugin = _get_plugin(plugin_id)
        return await plugin.summarize_thinking(request, messages=req.messages, reply_text=req.reply_text, settings=req.settings or {})

    @router.post("/{plugin_id}/summarize_thinking_stream")
    async def summarize_thinking_stream(plugin_id: str, request: Request, req: SummarizeThinkingRequest):
        plugin = _get_plugin(plugin_id)
        gen = await plugin.summarize_thinking_stream(request, messages=req.messages, reply_text=req.reply_text, settings=req.settings or {})
        return StreamingResponse(gen, media_type="text/event-stream")

    return router
