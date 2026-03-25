"""ReAct (Reasoning + Acting) agent — streams SSE events.

Loop:
  1. Send messages to LLM
  2. If LLM outputs Action: → execute tool, feed Observation back, repeat
  3. If LLM outputs Answer: → stream content + suggestions + done

SSE event types emitted: thinking, tool_call, tool_result, content, suggestions, done, error
"""
from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

import structlog

from src.services.grafana import GrafanaClient
from src.services.ollama import OllamaService, parse_suggestions
from src.services.tools import TOOL_DEFINITIONS, execute_tool, parse_action

logger = structlog.get_logger(__name__)

MAX_TOOL_CALLS = 6


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _build_system(context: dict[str, str], has_grafana: bool) -> str:
    base = (
        "You are a Grafana AI assistant helping SREs investigate incidents. "
        "Be concise, factual, and actionable. When uncertain, say so rather than guessing."
    )
    if has_grafana:
        base += "\n\n" + TOOL_DEFINITIONS
    else:
        base += (
            "\n\nNo active Grafana session — answer general observability questions but "
            "do not attempt to fetch live data."
            "\n\nFor your response, just write your answer in markdown, then on its own line:\n"
            'SUGGESTIONS: ["follow-up 1?", "follow-up 2?", "follow-up 3?"]'
        )
    if context:
        ctx_lines = "\n".join(f"  {k}: {v}" for k, v in context.items())
        base += f"\n\nSession context:\n{ctx_lines}"
    return base


async def stream_react_response(
    query: str,
    context: dict[str, str],
    client: GrafanaClient | None,
    ollama: OllamaService,
    model: str | None = None,
    temperature: float = 0.3,
) -> AsyncIterator[str]:
    """Run the ReAct loop and yield SSE event strings."""
    log = logger.bind(query_preview=query[:80])
    log.info("react_agent_start", has_grafana=client is not None)

    system = _build_system(context, has_grafana=client is not None)
    messages: list[dict[str, str]] = [{"role": "user", "content": query}]
    tool_calls_made = 0

    try:
        while True:
            # ── LLM turn ──────────────────────────────────────────────────────
            try:
                llm_text = await ollama.chat(
                    messages=messages,
                    system=system,
                    model=model,
                    temperature=temperature,
                )
            except Exception as exc:
                log.error("react_llm_error", error=str(exc))
                yield _sse({"type": "error", "message": f"LLM error: {exc}"})
                return

            log.debug("react_llm_response", length=len(llm_text))

            # ── Check for tool call ───────────────────────────────────────────
            action = parse_action(llm_text) if client is not None else None

            if action is not None and tool_calls_made < MAX_TOOL_CALLS:
                tool_name, kwargs = action

                # Stream thought so user can see reasoning
                thought_match = re.search(
                    r"Thought:\s*(.+?)(?:\nAction:|$)", llm_text, re.DOTALL
                )
                if thought_match:
                    yield _sse({"type": "thinking", "chunk": thought_match.group(1).strip()})

                yield _sse({"type": "tool_call", "tool": tool_name, "args": kwargs})
                log.info("react_tool_call", tool=tool_name, kwargs=list(kwargs.keys()))

                # Execute
                try:
                    observation = await execute_tool(client, tool_name, kwargs)
                except Exception as exc:
                    observation = f"Tool error: {exc}"
                    log.warning("react_tool_error", tool=tool_name, error=str(exc))

                had_data = not any(
                    observation.startswith(p)
                    for p in ("No ", "Unknown tool", "Tool error", "Error parsing")
                )
                summary = observation.split("\n")[0]

                yield _sse({
                    "type": "tool_result",
                    "tool": tool_name,
                    "summary": summary,
                    "had_data": had_data,
                })
                log.info("react_tool_result", tool=tool_name, had_data=had_data)

                tool_calls_made += 1
                messages.append({"role": "assistant", "content": llm_text})
                messages.append({"role": "user", "content": f"Observation: {observation}"})
                continue

            # ── Answer path ───────────────────────────────────────────────────
            # If we hit MAX_TOOL_CALLS force the LLM to answer
            if action is not None and tool_calls_made >= MAX_TOOL_CALLS:
                messages.append({"role": "assistant", "content": llm_text})
                messages.append({
                    "role": "user",
                    "content": (
                        "You have used the maximum number of tool calls. "
                        "Please provide your final Answer: based on the data collected so far."
                    ),
                })
                continue

            # Extract Answer: block if present, otherwise use full response
            answer_match = re.search(r"\bAnswer:\s*(.*)", llm_text, re.DOTALL)
            answer_text = answer_match.group(1).strip() if answer_match else llm_text.strip()

            clean_answer, suggestions = parse_suggestions(answer_text)

            yield _sse({"type": "content", "chunk": clean_answer})
            if suggestions:
                yield _sse({"type": "suggestions", "items": suggestions})
            yield _sse({"type": "done"})
            return

    except GeneratorExit:
        pass
    except Exception as exc:
        log.error("react_agent_unhandled", error=str(exc), exc_info=True)
        yield _sse({"type": "error", "message": str(exc)})
