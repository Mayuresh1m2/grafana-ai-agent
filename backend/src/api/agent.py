"""Agent query endpoint — SSE streaming response."""

from __future__ import annotations

import json
from typing import Annotated, AsyncIterator

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from src.models.requests import AgentQueryRequest
from src.services.ollama import OllamaService, get_ollama_service, parse_suggestions

logger = structlog.get_logger(__name__)
router = APIRouter()


def _sse(event: dict) -> str:
    """Serialise a dict as an SSE data line."""
    return f"data: {json.dumps(event)}\n\n"


async def _stream(
    request: AgentQueryRequest,
    ollama: OllamaService,
) -> AsyncIterator[str]:
    log = logger.bind(
        query_preview=request.query[:80],
        model=request.model,
        context_keys=list(request.context.keys()),
    )
    log.info("agent_query_received")

    try:
        raw_answer, tokens_used = await ollama.generate(
            prompt=request.query,
            context=request.context,
            model=request.model,
            temperature=request.temperature,
        )
    except Exception as exc:
        log.error("agent_query_failed", error=str(exc), exc_info=True)
        yield _sse({"type": "error", "message": f"Upstream Ollama error: {exc}"})
        return

    # Split suggestions marker out of the answer before streaming content
    clean_answer, suggestions = parse_suggestions(raw_answer)

    log.info("agent_query_completed", tokens_used=tokens_used, suggestions=len(suggestions))

    yield _sse({"type": "content", "chunk": clean_answer})

    if suggestions:
        yield _sse({"type": "suggestions", "items": suggestions})

    yield _sse({"type": "done"})


@router.post(
    "/query",
    summary="Send a query to the AI agent (SSE stream)",
    description=(
        "Streams the assistant response as Server-Sent Events. "
        "Event types: content, suggestions, done, error."
    ),
)
async def agent_query(
    request: AgentQueryRequest,
    ollama: Annotated[OllamaService, Depends(get_ollama_service)],
) -> StreamingResponse:
    return StreamingResponse(
        _stream(request, ollama),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )
