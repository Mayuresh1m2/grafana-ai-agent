"""Anthropic LLM provider (Claude models)."""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import structlog

from src.config import Settings
from src.services.llm.base import LLMProvider

logger = structlog.get_logger(__name__)


def _ollama_tools_to_anthropic(tools: list[dict]) -> list[dict]:
    """Convert Ollama-style tool schemas to Anthropic format."""
    out = []
    for t in tools:
        fn = t.get("function", {})
        out.append({
            "name": fn["name"],
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return out


def _ollama_messages_to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    """Convert Ollama-format messages to Anthropic format.

    Returns (system_prompt, anthropic_messages).
    Tool calls and results are paired by position — each assistant tool_calls
    turn is immediately followed by one or more tool result turns.
    """
    system = ""
    anthro: list[dict] = []

    # We need to track generated tool_use IDs so tool results can reference them
    # tool_call_ids[i] = id for the i-th tool call across the whole conversation
    tool_call_ids: list[str] = []
    tool_result_index = 0

    for msg in messages:
        role = msg["role"]
        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []

        if role == "system":
            system = content
            continue

        if role == "user":
            anthro.append({"role": "user", "content": content})
            continue

        if role == "assistant":
            if tool_calls:
                blocks = []
                if content:
                    blocks.append({"type": "text", "text": content})
                for call in tool_calls:
                    fn = call.get("function", {})
                    tool_id = f"toolu_{uuid.uuid4().hex[:8]}"
                    tool_call_ids.append(tool_id)
                    blocks.append({
                        "type": "tool_use",
                        "id": tool_id,
                        "name": fn.get("name", ""),
                        "input": fn.get("arguments") or {},
                    })
                anthro.append({"role": "assistant", "content": blocks})
            else:
                anthro.append({"role": "assistant", "content": content})
            continue

        if role == "tool":
            # Each tool result consumes one tool_call_id in order
            if tool_result_index < len(tool_call_ids):
                tool_use_id = tool_call_ids[tool_result_index]
            else:
                tool_use_id = f"toolu_unknown_{tool_result_index}"
            tool_result_index += 1

            # Anthropic requires tool results as a user turn
            anthro.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                }],
            })
            continue

    return system, anthro


def _anthropic_message_to_ollama(msg) -> dict:
    """Convert an Anthropic response message to Ollama-compatible format."""
    content_blocks = msg.content  # list of ContentBlock objects
    text_parts: list[str] = []
    tool_calls: list[dict] = []

    for block in content_blocks:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append({
                "function": {
                    "name": block.name,
                    "arguments": block.input,
                }
            })

    result: dict = {"content": "\n".join(text_parts)}
    if tool_calls:
        result["tool_calls"] = tool_calls
    return result


class AnthropicProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Lazy import so the package is optional
        import anthropic
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    @property
    def default_model(self) -> str:
        return self._settings.anthropic_model

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        temperature: float = 0.3,
    ) -> dict:
        effective_model = model or self._settings.anthropic_model
        system, anthro_messages = _ollama_messages_to_anthropic(messages)

        kwargs: dict = {
            "model": effective_model,
            "max_tokens": 4096,
            "temperature": temperature,
            "messages": anthro_messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = _ollama_tools_to_anthropic(tools)

        logger.debug(
            "anthropic_chat_request",
            model=effective_model,
            message_count=len(anthro_messages),
            tools_available=[t["name"] for t in _ollama_tools_to_anthropic(tools or [])],
        )

        response = await self._client.messages.create(**kwargs)

        logger.debug(
            "anthropic_chat_response",
            model=effective_model,
            stop_reason=response.stop_reason,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        return _anthropic_message_to_ollama(response)

    async def stream(
        self,
        prompt: str,
        system: str,
        model: str | None = None,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        effective_model = model or self._settings.anthropic_model
        async with self._client.messages.stream(
            model=effective_model,
            max_tokens=4096,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def list_models(self) -> list[str]:
        # Anthropic doesn't have a list-models API; return known Claude models
        return [
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
        ]
