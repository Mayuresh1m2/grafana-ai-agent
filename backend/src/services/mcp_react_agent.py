"""ReAct agent loop driven by the Grafana MCP server.

Tools are discovered dynamically from the MCP server at the start of each
query — no hand-written tool schemas needed.  The LLM receives the full tool
catalogue from the server and calls them by name.

SSE events emitted: thinking, tool_call, tool_result, content, suggestions, done, error
"""
from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

import structlog

from src.config import Settings
from src.services.mcp_client import GrafanaMCPSession
from src.services.ollama import OllamaService, parse_suggestions

logger = structlog.get_logger(__name__)

MAX_TOOL_CALLS = 8

_RESPONSE_FORMAT = """\
To call a tool, output ONLY:
Thought: <your reasoning>
Action: tool_name({"param": "value", ...})

After receiving an Observation, continue or give your final answer:
Thought: <final reasoning>
Answer: <markdown response to the user>
SUGGESTIONS: ["follow-up 1?", "follow-up 2?", "follow-up 3?"]

Rules:
- tool_name must be one of the tools listed above
- Arguments must be a valid JSON object on the same line as Action:
- Answer must be complete markdown — do not truncate
- Always append SUGGESTIONS after Answer
"""


def _build_system(context: dict[str, str], tool_defs: str, has_mcp: bool) -> str:
    base = (
        "You are a Grafana AI assistant helping SREs investigate incidents. "
        "Be concise, factual, and actionable. When uncertain, say so."
    )
    if has_mcp:
        base += (
            "\n\nYou have access to the following live Grafana tools:\n\n"
            + tool_defs
            + "\n\n"
            + _RESPONSE_FORMAT
        )
    else:
        base += (
            "\n\nNo Grafana tools available — answer general observability questions only.\n\n"
            "Write your answer in markdown, then:\n"
            'SUGGESTIONS: ["follow-up 1?", "follow-up 2?", "follow-up 3?"]'
        )
    if context:
        base += "\n\nSession context:\n" + "\n".join(f"  {k}: {v}" for k, v in context.items())
    return base


def _parse_action(text: str) -> tuple[str, dict] | None:
    """Extract (tool_name, args_dict) from an Action: line, or None."""
    match = re.search(r"\bAction:\s*(\w+)\s*\((\{.*?\})\)", text, re.DOTALL)
    if not match:
        return None
    tool_name = match.group(1).strip()
    try:
        args = json.loads(match.group(2))
        if not isinstance(args, dict):
            return None
        return tool_name, args
    except json.JSONDecodeError:
        return None


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def stream_mcp_react_response(
    query: str,
    context: dict[str, str],
    grafana_url: str,
    api_token: str,
    ollama: OllamaService,
    settings: Settings,
    model: str | None = None,
    temperature: float = 0.3,
) -> AsyncIterator[str]:
    """Run the MCP-backed ReAct loop and yield SSE event strings."""
    log = logger.bind(query_preview=query[:80])
    log.info("mcp_react_start")

    try:
        async with GrafanaMCPSession(grafana_url, api_token, settings) as mcp:
            tool_defs = mcp.tool_definitions()
            known_tools = {t.name for t in mcp.tools}
            system = _build_system(context, tool_defs, has_mcp=True)
            messages: list[dict[str, str]] = [{"role": "user", "content": query}]
            tool_calls_made = 0

            while True:
                try:
                    llm_text = await ollama.chat(
                        messages=messages,
                        system=system,
                        model=model,
                        temperature=temperature,
                    )
                except Exception as exc:
                    log.error("mcp_llm_error", error=str(exc))
                    yield _sse({"type": "error", "message": f"LLM error: {exc}"})
                    return

                action = _parse_action(llm_text) if known_tools else None

                if action is not None and tool_calls_made < MAX_TOOL_CALLS:
                    tool_name, args = action

                    # Validate tool exists (prevent hallucinated tool names)
                    if tool_name not in known_tools:
                        messages.append({"role": "assistant", "content": llm_text})
                        messages.append({
                            "role": "user",
                            "content": (
                                f"Observation: Unknown tool '{tool_name}'. "
                                f"Available tools: {', '.join(sorted(known_tools))}. "
                                "Please use a valid tool name."
                            ),
                        })
                        tool_calls_made += 1
                        continue

                    # Stream thought
                    thought_match = re.search(r"Thought:\s*(.+?)(?:\nAction:|$)", llm_text, re.DOTALL)
                    if thought_match:
                        yield _sse({"type": "thinking", "chunk": thought_match.group(1).strip()})

                    yield _sse({"type": "tool_call", "tool": tool_name, "args": args})
                    log.info("mcp_tool_call", tool=tool_name, args=list(args.keys()))

                    observation = await mcp.call_tool(tool_name, args)

                    had_data = not any(
                        observation.startswith(p)
                        for p in ("Tool error", "MCP session", "(empty", "Unknown tool")
                    )
                    summary = observation.split("\n")[0]

                    yield _sse({
                        "type": "tool_result",
                        "tool": tool_name,
                        "summary": summary,
                        "had_data": had_data,
                    })
                    log.info("mcp_tool_result", tool=tool_name, had_data=had_data)

                    tool_calls_made += 1
                    messages.append({"role": "assistant", "content": llm_text})
                    messages.append({"role": "user", "content": f"Observation: {observation}"})
                    continue

                # Force answer if max tool calls reached
                if action is not None and tool_calls_made >= MAX_TOOL_CALLS:
                    messages.append({"role": "assistant", "content": llm_text})
                    messages.append({
                        "role": "user",
                        "content": "Maximum tool calls reached. Provide your final Answer: now.",
                    })
                    continue

                # ── Answer ────────────────────────────────────────────────────
                answer_match = re.search(r"\bAnswer:\s*(.*)", llm_text, re.DOTALL)
                answer_text = answer_match.group(1).strip() if answer_match else llm_text.strip()

                clean_answer, suggestions = parse_suggestions(answer_text)
                yield _sse({"type": "content", "chunk": clean_answer})
                if suggestions:
                    yield _sse({"type": "suggestions", "items": suggestions})
                yield _sse({"type": "done"})
                return

    except Exception as exc:
        log.error("mcp_react_unhandled", error=str(exc), exc_info=True)
        yield _sse({"type": "error", "message": str(exc)})


async def stream_fallback_response(
    query: str,
    context: dict[str, str],
    ollama: OllamaService,
    model: str | None = None,
    temperature: float = 0.3,
) -> AsyncIterator[str]:
    """Simple single-turn response when MCP is not available."""
    system = _build_system(context, "", has_mcp=False)
    try:
        text = await ollama.chat(
            messages=[{"role": "user", "content": query}],
            system=system,
            model=model,
            temperature=temperature,
        )
    except Exception as exc:
        yield _sse({"type": "error", "message": f"LLM error: {exc}"})
        return

    clean, suggestions = parse_suggestions(text)
    yield _sse({"type": "content", "chunk": clean})
    if suggestions:
        yield _sse({"type": "suggestions", "items": suggestions})
    yield _sse({"type": "done"})
