"""LLM status probe endpoint."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.llm.client import OllamaModel, get_ollama_client

router = APIRouter()


class LLMStatusResponse(BaseModel):
    """Response model for GET /api/v1/llm/status."""

    ollama_reachable: bool
    base_url: str
    available_models: list[str]


@router.get("/status", response_model=LLMStatusResponse)
async def llm_status() -> LLMStatusResponse:
    """Probe the Ollama service and return reachability status.

    Always returns 200 — callers should inspect ``ollama_reachable`` to
    determine whether the LLM back-end is usable.
    """
    client = get_ollama_client()
    reachable = await client.health_check()
    return LLMStatusResponse(
        ollama_reachable=reachable,
        base_url=client._base_url,
        available_models=[m.value for m in OllamaModel],
    )
