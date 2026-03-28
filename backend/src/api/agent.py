"""Agent query endpoint — agentic loop with Grafana tool calling, SSE streaming."""
from __future__ import annotations

from typing import Annotated, AsyncIterator

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from src.api._sse import sse_event as _sse
from src.models.entity import resolve_entities
from src.models.requests import AgentQueryRequest
from src.services.agent_tools import execute_tool, get_tools
from src.services.entity_store import EntityStore, get_entity_store
from src.services.grafana import GrafanaClient
from src.services.llm.base import LLMProvider, parse_suggestions
from src.services.llm.factory import get_llm_provider
from src.services.rag.retriever import retrieve_examples
from src.services.rag.store import ExampleStore, get_example_store
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


# ── System prompt assembly ────────────────────────────────────────────────────

def _datasource_block(datasources: list) -> str:
    lines = "\n".join(
        f"  - {ds.name}  type={ds.type}  uid={ds.uid}{' [default]' if ds.is_default else ''}"
        for ds in datasources
    )
    return (
        f"\n\nAvailable Grafana datasources (use these UIDs directly in tool calls):\n{lines}\n"
        "When querying logs use the uid of the datasource with type=loki. "
        "When querying metrics use the uid of the datasource with type=prometheus."
    )


def _context_block(context: dict[str, str]) -> str:
    lines = "\n".join(f"  {k}: {v}" for k, v in context.items())
    return f"\n\nSession context:\n{lines}"


def _entity_block(query: str, entities: EntityStore) -> str:
    matched = resolve_entities(query, entities.list_all())
    if not matched:
        return ""
    lines = [
        f"  - {e.name}  namespace={e.namespace}  type={e.entity_type.value}"
        + (f"  # {e.description}" if e.description else "")
        for e in matched
    ]
    return (
        "\n\nResolved entities from your query "
        "(use these exact names and namespaces in tool calls):\n"
        + "\n".join(lines)
    )


async def _build_system_prompt(
    request: AgentQueryRequest,
    datasources: list | None,
    examples: ExampleStore,
    entities: EntityStore,
) -> tuple[str, int, int]:
    """Assemble the full system prompt.

    Returns ``(system_prompt, rag_chars, entity_count)`` for logging.
    """
    prompt = _SYSTEM_PROMPT

    if datasources:
        prompt += _datasource_block(datasources)
    if request.context:
        prompt += _context_block(request.context)

    rag_block = await retrieve_examples(
        query=request.query,
        context=request.context or {},
        store=examples,
    )
    if rag_block:
        prompt += rag_block

    entity_block = _entity_block(request.query, entities)
    if entity_block:
        prompt += entity_block

    matched_count = len(resolve_entities(request.query, entities.list_all()))
    return prompt, len(rag_block), matched_count


# ── Tool result compaction ────────────────────────────────────────────────────

# Results shorter than this (chars) are kept verbatim — they're already concise.
_COMPRESS_THRESHOLD = 400
# Token budget for the compressed summary — tight by design.
_COMPRESS_MAX_TOKENS = 180


async def _compress(raw: str, tool_name: str, llm: LLMProvider) -> str:
    """Summarise a verbose tool result into a few bullet points.

    Only called when the raw result exceeds ``_COMPRESS_THRESHOLD`` characters.
    Uses a minimal prompt and low token cap so it adds little latency and does
    not itself consume significant context budget.
    """
    msg = await llm.chat(
        messages=[{"role": "user", "content": (
            f"Summarise the key findings from this {tool_name} result "
            f"in 3-5 concise bullet points. Preserve specific values "
            f"(numbers, service names, error messages). Be terse.\n\n{raw}"
        )}],
        tools=None,
        temperature=0.0,
        max_tokens=_COMPRESS_MAX_TOKENS,
    )
    summary = (msg.get("content") or "").strip()
    return summary if summary else raw


# ── Agent loop ────────────────────────────────────────────────────────────────

async def _run_agent(
    request: AgentQueryRequest,
    llm: LLMProvider,
    store: SessionStore,
    examples: ExampleStore,
    entities: EntityStore,
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
        log.warning("agent_no_session_id", detail="No session_id provided — Grafana tools will be unavailable")

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

    # ── Prompt assembly ───────────────────────────────────────────────────────
    system_prompt, rag_chars, entity_count = await _build_system_prompt(
        request, datasources, examples, entities
    )
    if rag_chars:
        log.info("rag_injected", chars=rag_chars)
    if entity_count:
        log.info("entity_resolution_injected", count=entity_count)

    log.debug("agent_prompt_built", tools_enabled=tools is not None)

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": request.query},
    ]

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

                raw_len = len(result)
                if raw_len > _COMPRESS_THRESHOLD:
                    result = await _compress(result, name, llm)
                    log.info("agent_tool_result_compressed", tool=name,
                             raw_chars=raw_len, compressed_chars=len(result))
                else:
                    log.info("agent_tool_result", tool=name, result_length=raw_len)

                messages.append({"role": "tool", "content": result})

        # Exhausted rounds — get a final answer without tools
        log.warning("agent_max_rounds_reached", rounds=_MAX_TOOL_ROUNDS)
        msg = await llm.chat(messages, tools=None, model=request.model, max_tokens=request.max_tokens)
        content = msg.get("content") or ""
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


# ── Endpoint ──────────────────────────────────────────────────────────────────

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
    request:  AgentQueryRequest,
    llm:      Annotated[LLMProvider,    Depends(get_llm_provider)],
    store:    Annotated[SessionStore,   Depends(get_session_store)],
    examples: Annotated[ExampleStore,   Depends(get_example_store)],
    entities: Annotated[EntityStore,    Depends(get_entity_store)],
) -> StreamingResponse:
    return StreamingResponse(
        _run_agent(request, llm, store, examples, entities),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
