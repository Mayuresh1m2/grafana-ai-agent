"""Agent query endpoint."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException

from src.models.requests import AgentQueryRequest
from src.models.responses import AgentQueryResponse
from src.services.ollama import OllamaService, get_ollama_service

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post(
    "/query",
    response_model=AgentQueryResponse,
    summary="Send a query to the AI agent",
    description=(
        "Sends a natural-language query to the configured Ollama model. "
        "Optional context key-value pairs are injected into the system prompt."
    ),
    status_code=200,
)
async def agent_query(
    request: AgentQueryRequest,
    ollama: Annotated[OllamaService, Depends(get_ollama_service)],
) -> AgentQueryResponse:
    log = logger.bind(
        query_preview=request.query[:80],
        model=request.model,
        context_keys=list(request.context.keys()),
    )
    log.info("agent_query_received")

    try:
        answer, tokens_used = await ollama.generate(
            prompt=request.query,
            context=request.context,
            model=request.model,
            temperature=request.temperature,
        )
    except Exception as exc:
        log.error("agent_query_failed", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=f"Upstream Ollama error: {exc}",
        ) from exc

    log.info("agent_query_completed", tokens_used=tokens_used)
    return AgentQueryResponse(
        answer=answer,
        query=request.query,
        model=request.model or ollama.default_model,
        tokens_used=tokens_used,
    )
