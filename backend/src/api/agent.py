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
from src.services.llm.factory import get_llm_provider
from src.services.llm.base import LLMProvider
from src.services.ollama import parse_suggestions
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
    llm: LLMProvider,
    store: SessionStore,
) -> AsyncIterator[str]:
    log = logger.bind(session_id=request.session_id, query_preview=request.query[:80])
    log.info("agent_query_start", query=request.query, model=request.model, context=request.context)

    # Resolve Grafana session
    session = None
    if request.session_id:
        session = await store.get(request.session_id)
        log.info("agent_session_resolved", found=session is not None, grafana_url=session.grafana_url if session else None)
    else:
        log.warning("agent_no_session_id", detail="No session_id provided — Grafana tools will be unavailable")

    client: GrafanaClient | None = None
    if session:
        client = await GrafanaClient.create(session)

    tools = TOOLS if client else None

    if tools:
        tool_names = [t["function"]["name"] for t in tools]
        log.info("agent_tools_enabled", tools=tool_names)
        yield _sse({"type": "thinking", "chunk": f"Grafana tools available: {', '.join(tool_names)}\n"})
    else:
        if not request.session_id:
            reason = "no session_id in request — complete the setup flow first"
        elif session is None:
            reason = f"session '{request.session_id}' not found in store — reconnect to Grafana (backend may have restarted)"
        else:
            reason = "Grafana client could not be created"
        log.warning("agent_tools_disabled", reason=reason, session_id=request.session_id)
        yield _sse({"type": "thinking", "chunk": f"⚠ Grafana tools unavailable: {reason}\n"})

    system_prompt = _build_system(request.context or {})

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": request.query},
    ]

    log.debug("agent_prompt_built", system_prompt=system_prompt, tools_enabled=tools is not None)

    try:
        for round_num in range(_MAX_TOOL_ROUNDS):
            log.info("agent_llm_call", round=round_num, message_count=len(messages))

            msg = await llm.chat(
                messages,
                tools=tools,
                model=request.model,
                temperature=request.temperature,
            )

            if msg.get("_tools_skipped") and round_num == 0:
                yield _sse({"type": "thinking", "chunk": (
                    f"⚠ Model '{request.model or llm.default_model}' does not support tool calling — "
                    "answering from training data only. Switch to llama3.1, llama3.2, or mistral-nemo "
                    "for live Grafana data.\n"
                )})

            tool_calls: list[dict] = msg.get("tool_calls") or []  # type: ignore[assignment]

            if not tool_calls:
                # Final answer — stream it
                content: str = msg.get("content") or ""  # type: ignore[assignment]
                log.info("agent_final_answer", round=round_num, content_length=len(content), content=content)
                clean, suggestions = parse_suggestions(content)
                yield _sse({"type": "content", "chunk": clean})
                if suggestions:
                    log.debug("agent_suggestions", suggestions=suggestions)
                    yield _sse({"type": "suggestions", "items": suggestions})
                log.info("agent_query_done", rounds=round_num + 1)
                yield _sse({"type": "done"})
                return

            log.info("agent_tool_calls_selected", round=round_num, count=len(tool_calls),
                     tools=[c.get("function", {}).get("name") for c in tool_calls])

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
                log.info("agent_tool_executing", tool=name, args=args)
                yield _sse({"type": "thinking", "chunk": f"→ {name}({args_str})\n"})

                if client:
                    try:
                        result = await execute_tool(name, args, client)
                    except Exception as exc:
                        result = f"Tool error: {exc}"
                        log.error("agent_tool_error", tool=name, args=args, error=str(exc), exc_info=True)
                else:
                    result = "No Grafana session — connect first."

                log.info("agent_tool_result", tool=name, result_length=len(result), result=result)
                messages.append({"role": "tool", "content": result})

        # Exhausted rounds — get final answer without tools
        log.warning("agent_max_rounds_reached", rounds=_MAX_TOOL_ROUNDS)
        msg = await llm.chat(messages, tools=None, model=request.model)
        content = msg.get("content") or ""  # type: ignore[assignment]
        log.info("agent_final_answer_after_max_rounds", content=content)
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
    llm:   Annotated[LLMProvider,  Depends(get_llm_provider)],
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> StreamingResponse:
    return StreamingResponse(
        _run_agent(request, llm, store),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
