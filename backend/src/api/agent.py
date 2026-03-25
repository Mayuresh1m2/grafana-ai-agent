"""Agent query endpoint — SSE streaming response (MCP ReAct loop)."""
from __future__ import annotations

import json
from typing import Annotated, AsyncIterator

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from src.config import Settings, get_settings
from src.models.requests import AgentQueryRequest
from src.services.mcp_react_agent import stream_fallback_response, stream_mcp_react_response
from src.services.ollama import OllamaService, get_ollama_service
from src.services.session_store import SessionStore, get_session_store

logger = structlog.get_logger(__name__)
router = APIRouter()


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def _stream(
    request: AgentQueryRequest,
    ollama: OllamaService,
    store: SessionStore,
    settings: Settings,
) -> AsyncIterator[str]:
    log = logger.bind(query_preview=request.query[:80], session_id=request.session_id)
    log.info("agent_query_received")

    context = request.build_context()

    # ── Resolve Grafana credentials for MCP ───────────────────────────────────
    grafana_url: str | None = None
    api_token: str | None = None

    if request.session_id:
        session = await store.get(request.session_id)
        if session is not None:
            grafana_url = session.grafana_url
            api_token = session.service_account_token

    # Fall back to env-level credentials if session doesn't have a token
    if not api_token and settings.grafana_api_key:
        api_token = settings.grafana_api_key
        grafana_url = grafana_url or settings.grafana_base_url

    use_mcp = (
        settings.grafana_mcp_enabled
        and bool(grafana_url)
        and bool(api_token)
    )
    log.info("agent_mode", use_mcp=use_mcp, has_url=bool(grafana_url))

    if use_mcp:
        async for event_str in stream_mcp_react_response(
            query=request.query,
            context=context,
            grafana_url=grafana_url,  # type: ignore[arg-type]
            api_token=api_token,      # type: ignore[arg-type]
            ollama=ollama,
            settings=settings,
            model=request.model,
            temperature=request.temperature,
        ):
            yield event_str
    else:
        log.info("agent_mcp_unavailable", reason="no token or MCP disabled")
        async for event_str in stream_fallback_response(
            query=request.query,
            context=context,
            ollama=ollama,
            model=request.model,
            temperature=request.temperature,
        ):
            yield event_str


@router.post(
    "/query",
    summary="Send a query to the AI agent (SSE stream)",
    description=(
        "Streams the assistant response as Server-Sent Events using a ReAct loop "
        "backed by the Grafana MCP server. "
        "Event types: thinking, tool_call, tool_result, content, suggestions, done, error."
    ),
)
async def agent_query(
    request: AgentQueryRequest,
    ollama: Annotated[OllamaService, Depends(get_ollama_service)],
    store: Annotated[SessionStore, Depends(get_session_store)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    return StreamingResponse(
        _stream(request, ollama, store, settings),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
