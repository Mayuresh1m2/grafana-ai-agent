"""Agent query endpoint — agentic loop with Grafana tool calling, SSE streaming."""
from __future__ import annotations

import json
from typing import Annotated, AsyncIterator

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from src.models.requests import AgentQueryRequest
from src.services.agent_tools import TOOLS, execute_tool
from src.services.grafana import GrafanaClient
from src.services.ollama import OllamaService, get_ollama_service, parse_suggestions
from src.services.session_store import SessionStore, get_session_store

logger = structlog.get_logger(__name__)
router = APIRouter()

_MAX_TOOL_ROUNDS = 6

_SYSTEM_PROMPT = (
    "You are an on-call AI assistant for a Kubernetes environment monitored by Grafana, Loki, and Prometheus. "
    "You have tools to fetch live data: active alerts, logs (LogQL), and metrics (PromQL). "
    "Always look up real data before answering questions about incidents, errors, or performance. "
    "Be concise and actionable. When uncertain, say so."
)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _build_system(context: dict[str, str]) -> str:
    base = _SYSTEM_PROMPT
    if context:
        ctx = "\n".join(f"  {k}: {v}" for k, v in context.items())
        base = f"{base}\n\nSession context:\n{ctx}"
    return base


async def _run_agent(
    request: AgentQueryRequest,
    ollama: OllamaService,
    store: SessionStore,
) -> AsyncIterator[str]:
    log = logger.bind(session_id=request.session_id, query_preview=request.query[:80])
    log.info("agent_query_start")

    # Resolve Grafana session
    session = None
    if request.session_id:
        session = await store.get(request.session_id)

    client: GrafanaClient | None = None
    if session:
        client = await GrafanaClient.create(session)

    tools = TOOLS if client else None

    messages: list[dict] = [
        {"role": "system", "content": _build_system(request.context or {})},
        {"role": "user",   "content": request.query},
    ]

    try:
        for round_num in range(_MAX_TOOL_ROUNDS):
            msg = await ollama.chat(
                messages,
                tools=tools,
                model=request.model,
                temperature=request.temperature,
            )

            tool_calls: list[dict] = msg.get("tool_calls") or []  # type: ignore[assignment]

            if not tool_calls:
                # Final answer — stream it
                content: str = msg.get("content") or ""  # type: ignore[assignment]
                clean, suggestions = parse_suggestions(content)
                yield _sse({"type": "content", "chunk": clean})
                if suggestions:
                    yield _sse({"type": "suggestions", "items": suggestions})
                log.info("agent_query_done", rounds=round_num + 1)
                yield _sse({"type": "done"})
                return

            # Append assistant turn with tool calls
            messages.append({
                "role":       "assistant",
                "content":    msg.get("content") or "",
                "tool_calls": tool_calls,
            })

            # Execute each tool call
            for call in tool_calls:
                fn   = call.get("function") or {}
                name = str(fn.get("name", ""))
                raw_args = fn.get("arguments") or {}
                args: dict = raw_args if isinstance(raw_args, dict) else {}

                args_str = ", ".join(f"{k}={v}" for k, v in args.items()) if args else ""
                yield _sse({"type": "thinking", "chunk": f"→ {name}({args_str})\n"})

                if client:
                    try:
                        result = await execute_tool(name, args, client)
                    except Exception as exc:
                        result = f"Tool error: {exc}"
                else:
                    result = "No Grafana session — connect first."

                log.info("tool_executed", tool=name, result_len=len(result))
                messages.append({"role": "tool", "content": result})

        # Exhausted rounds — get final answer without tools
        msg = await ollama.chat(messages, tools=None, model=request.model)
        content = msg.get("content") or ""  # type: ignore[assignment]
        clean, suggestions = parse_suggestions(content)
        yield _sse({"type": "content", "chunk": clean})
        if suggestions:
            yield _sse({"type": "suggestions", "items": suggestions})
        yield _sse({"type": "done"})

    except Exception as exc:
        log.error("agent_query_error", error=str(exc), exc_info=True)
        yield _sse({"type": "error", "message": str(exc)})
    finally:
        if client:
            await client.aclose()


@router.post(
    "/query",
    summary="Send a query to the AI agent (SSE stream)",
    description=(
        "Streams the assistant response as Server-Sent Events. "
        "The agent autonomously decides which Grafana tools to call. "
        "Event types: thinking (tool calls in progress), content, suggestions, done, error."
    ),
)
async def agent_query(
    request: AgentQueryRequest,
    ollama:  Annotated[OllamaService,  Depends(get_ollama_service)],
    store:   Annotated[SessionStore,   Depends(get_session_store)],
) -> StreamingResponse:
    return StreamingResponse(
        _run_agent(request, ollama, store),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
