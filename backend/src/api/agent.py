"""Agent query endpoint — agentic loop with Grafana tool calling, SSE streaming."""
from __future__ import annotations

from typing import Annotated, AsyncIterator

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from src.api._sse import sse_event as _sse
from src.models.requests import AgentQueryRequest
from src.services.agent_tools import execute_tool, get_tools
from src.services.compactor import compress
from src.services.entity_store import EntityStore, get_entity_store
from src.services.grafana import GrafanaClient
from src.services.investigation_store import (
    InvestigationStore,
    extract_findings,
    get_investigation_store,
)
from src.services.llm.base import LLMProvider, parse_suggestions
from src.services.llm.factory import get_llm_provider
from src.services.prompt_builder import build as build_prompt
from src.services.rag.store import get_example_store
from src.services.session_store import SessionStore, get_session_store

logger = structlog.get_logger(__name__)
router = APIRouter()

_MAX_TOOL_ROUNDS = 6


async def _run_agent(
    request:   AgentQueryRequest,
    llm:       LLMProvider,
    store:     SessionStore,
    entities:  EntityStore,
    inv_store: InvestigationStore,
) -> AsyncIterator[str]:
    log = logger.bind(session_id=request.session_id, query_preview=request.query[:80])
    log.info("agent_query_start", query=request.query, model=request.model, context=request.context)

    # ── Resolve Grafana session ───────────────────────────────────────────────
    session = None
    if request.session_id:
        session = await store.get(request.session_id)
        log.info("agent_session_resolved", found=session is not None,
                 grafana_url=session.grafana_url if session else None)
    else:
        log.warning("agent_no_session_id", detail="No session_id — Grafana tools will be unavailable")

    # ── Instance-scoped RAG store ─────────────────────────────────────────────
    examples = get_example_store(session.grafana_url if session else "")

    client: GrafanaClient | None = None
    datasources = None
    if session:
        client = await GrafanaClient.create(session)
        datasources = client.get_datasources()
        log.info("agent_datasources_injected", datasources=[f"{d.name}({d.type})" for d in datasources])

    # ── Tool availability ─────────────────────────────────────────────────────
    tools = get_tools() if client else None

    if tools:
        tool_names = [t["function"]["name"] for t in tools]
        log.info("agent_tools_enabled", tools=tool_names)
        yield _sse({"type": "thinking", "chunk": f"Grafana tools available: {', '.join(tool_names)}\n"})
    else:
        if not request.session_id:
            reason = "no session_id in request — complete the setup flow first"
        elif session is None:
            reason = f"session '{request.session_id}' not found — reconnect to Grafana (backend may have restarted)"
        else:
            reason = "Grafana client could not be created"
        log.warning("agent_tools_disabled", reason=reason)
        yield _sse({"type": "thinking", "chunk": f"⚠ Grafana tools unavailable: {reason}\n"})

    # ── Investigation state (prior turns) ────────────────────────────────────
    investigation = None
    if request.session_id:
        investigation = await inv_store.get(request.session_id)
        if investigation and investigation.turn_count > 0:
            log.info("investigation_state_loaded", turn=investigation.turn_count,
                     findings=len(investigation.findings))

    # ── System prompt ─────────────────────────────────────────────────────────
    system_prompt, rag_chars, entity_count = await build_prompt(
        request, datasources, examples, entities, investigation
    )
    if rag_chars:
        log.info("rag_injected", chars=rag_chars)
    if entity_count:
        log.info("entity_resolution_injected", count=entity_count)

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": request.query},
    ]
    final_answer = ""   # captured for investigation state update

    # ── Agentic tool loop ─────────────────────────────────────────────────────
    try:
        for round_num in range(_MAX_TOOL_ROUNDS):
            log.info("agent_llm_call", round=round_num, message_count=len(messages))

            msg = await llm.chat(
                messages,
                tools=tools,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )

            if msg.get("_tools_skipped") and round_num == 0:
                yield _sse({"type": "thinking", "chunk": (
                    f"⚠ Model '{request.model or llm.default_model}' does not support tool calling — "
                    "answering from training data only. Switch to llama3.1, llama3.2, or mistral-nemo "
                    "for live Grafana data.\n"
                )})

            tool_calls: list[dict] = msg.get("tool_calls") or []

            if not tool_calls:
                content: str = msg.get("content") or ""
                log.info("agent_final_answer", round=round_num, content_length=len(content))
                clean, suggestions = parse_suggestions(content)
                final_answer = clean
                yield _sse({"type": "content", "chunk": clean})
                if suggestions:
                    yield _sse({"type": "suggestions", "items": suggestions})
                log.info("agent_query_done", rounds=round_num + 1)
                yield _sse({"type": "done"})
                return

            log.info("agent_tool_calls_selected", round=round_num, count=len(tool_calls),
                     tools=[c.get("function", {}).get("name") for c in tool_calls])

            messages.append({
                "role":       "assistant",
                "content":    msg.get("content") or "",
                "tool_calls": tool_calls,
            })

            for call in tool_calls:
                fn   = call.get("function") or {}
                name = str(fn.get("name", ""))
                args: dict = fn.get("arguments") or {}
                if not isinstance(args, dict):
                    args = {}

                args_str = ", ".join(f"{k}={v}" for k, v in args.items()) if args else ""
                log.info("agent_tool_executing", tool=name, args=args)
                yield _sse({"type": "thinking", "chunk": f"→ {name}({args_str})\n"})

                if client:
                    try:
                        result = await execute_tool(name, args, client)
                    except Exception as exc:
                        result = f"Tool error: {exc}"
                        log.error("agent_tool_error", tool=name, error=str(exc), exc_info=True)
                else:
                    result = "No Grafana session — connect first."

                result = await compress(result, name, llm)
                messages.append({"role": "tool", "content": result})

        # Exhausted rounds — get a final answer without tools
        log.warning("agent_max_rounds_reached", rounds=_MAX_TOOL_ROUNDS)
        msg = await llm.chat(messages, tools=None, model=request.model, max_tokens=request.max_tokens)
        content = msg.get("content") or ""
        clean, suggestions = parse_suggestions(content)
        final_answer = clean
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
        if request.session_id and final_answer:
            try:
                await inv_store.update(
                    request.session_id,
                    extract_findings(messages),
                    final_answer,
                )
            except Exception as exc:
                log.warning("investigation_state_save_failed", error=str(exc))


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
    request:   AgentQueryRequest,
    llm:       Annotated[LLMProvider,        Depends(get_llm_provider)],
    store:     Annotated[SessionStore,       Depends(get_session_store)],
    entities:  Annotated[EntityStore,        Depends(get_entity_store)],
    inv_store: Annotated[InvestigationStore, Depends(get_investigation_store)],
) -> StreamingResponse:
    return StreamingResponse(
        _run_agent(request, llm, store, entities, inv_store),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
