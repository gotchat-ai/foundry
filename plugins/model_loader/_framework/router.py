from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from .registry import ModelLoaderRegistry


def build_model_loader_router(registry: ModelLoaderRegistry) -> APIRouter:
    r = APIRouter()

    @r.get("/v1/model_loaders")
    def list_model_loaders() -> Dict[str, Any]:
        return {"ok": True, "model_loaders": registry.list()}

    @r.get("/v1/model_loaders/{plugin_id}/schema")
    def schema(plugin_id: str) -> Dict[str, Any]:
        p = registry.get(plugin_id)
        if not p:
            raise HTTPException(404, f"unknown model loader: {plugin_id}")
        return {"ok": True, "plugin_id": plugin_id, "schema": p.schema()}

    @r.get("/v1/model_loaders/{plugin_id}/sane_settings")
    def sane_settings(plugin_id: str, model: str | None = None) -> Dict[str, Any]:
        p = registry.get(plugin_id)
        if not p:
            raise HTTPException(404, f"unknown model loader: {plugin_id}")
        return {"ok": True, "plugin_id": plugin_id, "sane": p.sane_settings(model=model)}

    # The remaining endpoints are plugin-owned but routed through framework
    @r.post("/v1/model_loaders/{plugin_id}/download")
    async def download(plugin_id: str, request: Request) -> Dict[str, Any]:
        p = registry.get(plugin_id)
        if not p:
            raise HTTPException(404, f"unknown model loader: {plugin_id}")
        return await p.download(request)

    @r.post("/v1/model_loaders/{plugin_id}/load")
    async def load(plugin_id: str, request: Request) -> Dict[str, Any]:
        p = registry.get(plugin_id)
        if not p:
            raise HTTPException(404, f"unknown model loader: {plugin_id}")
        return await p.load(request)

    @r.post("/v1/model_loaders/{plugin_id}/unload")
    async def unload(plugin_id: str, request: Request) -> Dict[str, Any]:
        p = registry.get(plugin_id)
        if not p:
            raise HTTPException(404, f"unknown model loader: {plugin_id}")
        return await p.unload(request)

    @r.get("/v1/model_loaders/{plugin_id}/status")
    async def status(plugin_id: str, request: Request) -> Dict[str, Any]:
        p = registry.get(plugin_id)
        if not p:
            raise HTTPException(404, f"unknown model loader: {plugin_id}")
        return await p.status(request)

    @r.post("/v1/model_loaders/{plugin_id}/plan")
    async def plan(plugin_id: str, request: Request) -> Dict[str, Any]:
        p = registry.get(plugin_id)
        if not p:
            raise HTTPException(404, f"unknown model loader: {plugin_id}")
        return await p.plan_thinking(request)

    @r.post("/v1/model_loaders/{plugin_id}/summarize")
    async def summarize(plugin_id: str, request: Request) -> Dict[str, Any]:
        p = registry.get(plugin_id)
        if not p:
            raise HTTPException(404, f"unknown model loader: {plugin_id}")
        return await p.summarize_thinking(request)

    return r
