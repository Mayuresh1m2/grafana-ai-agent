"""Agent query endpoint — SSE streaming response (ReAct loop)."""
from __future__ import annotations

import json
from typing import Annotated, AsyncIterator

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from src.models.requests import AgentQueryRequest
from src.services.grafana import GrafanaClient
from src.services.ollama import OllamaService, get_ollama_service
from src.services.react_agent import stream_react_response
from src.services.session_store import SessionStore, get_session_store

logger = structlog.get_logger(__name__)
router = APIRouter()


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def _stream(
    request: AgentQueryRequest,
    ollama: OllamaService,
    store: SessionStore,
) -> AsyncIterator[str]:
    log = logger.bind(query_preview=request.query[:80], session_id=request.session_id)
    log.info("agent_query_received")

    # Resolve Grafana client if session is active
    client: GrafanaClient | None = None
    if request.session_id:
        session = await store.get(request.session_id)
        if session is not None:
            try:
                client = await GrafanaClient.create(session)
            except Exception as exc:
                log.warning("agent_grafana_client_failed", error=str(exc))
                # Non-fatal — fall back to no-tool mode

    context = request.build_context()
    log.info("agent_context_built", keys=list(context.keys()), has_grafana=client is not None)

    try:
        async for event_str in stream_react_response(
            query=request.query,
            context=context,
            client=client,
            ollama=ollama,
            model=request.model,
            temperature=request.temperature,
        ):
            yield event_str
    finally:
        if client is not None:
            await client.aclose()


@router.post(
    "/query",
    summary="Send a query to the AI agent (SSE stream)",
    description=(
        "Streams the assistant response as Server-Sent Events. "
        "Event types: thinking, tool_call, tool_result, content, suggestions, done, error."
    ),
)
async def agent_query(
    request: AgentQueryRequest,
    ollama: Annotated[OllamaService, Depends(get_ollama_service)],
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> StreamingResponse:
    return StreamingResponse(
        _stream(request, ollama, store),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
