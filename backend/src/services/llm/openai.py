"""OpenAI LLM provider (GPT-4o, GPT-4-turbo, etc.).

Also works with any OpenAI-compatible endpoint (Azure OpenAI, local vLLM,
LM Studio) by setting ``OPENAI_BASE_URL`` in the environment.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import structlog

from src.config import Settings
from src.services.llm.base import LLMProvider

logger = structlog.get_logger(__name__)

# Models that support the Responses API structured output — kept as a reference.
# All models listed here support tool calling.
_KNOWN_MODELS = [
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4-turbo",
    "gpt-4",
    "gpt-3.5-turbo",
    "o1",
    "o1-mini",
    "o3-mini",
]


def _ollama_tools_to_openai(tools: list[dict]) -> list[dict]:
    """Convert Ollama-style tool schemas to OpenAI format.

    Ollama uses the same wrapper structure as OpenAI
    (``{"type": "function", "function": {...}}``), so this is a pass-through
    with a light normalisation guard.
    """
    out = []
    for t in tools:
        fn = t.get("function", {})
        out.append({
            "type": "function",
            "function": {
                "name":        fn["name"],
                "description": fn.get("description", ""),
                "parameters":  fn.get("parameters", {"type": "object", "properties": {}}),
            },
        })
    return out


def _ollama_messages_to_openai(messages: list[dict]) -> list[dict]:
    """Convert Ollama-format messages to OpenAI Chat format.

    Key differences from the Ollama format:
    - Tool calls carry an ``id`` (we generate deterministic ones by position).
    - Tool results are ``{"role": "tool", "tool_call_id": "...", "content": "..."}``.
    - Arguments in tool calls must be a JSON *string* (not a dict).
    """
    result: list[dict] = []
    # Track generated IDs so tool-result messages can reference them in order
    tool_call_ids: list[str] = []
    tool_result_index = 0

    for msg in messages:
        role       = msg["role"]
        content    = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []

        if role in ("system", "user"):
            result.append({"role": role, "content": content})
            continue

        if role == "assistant":
            if tool_calls:
                oai_calls = []
                for call in tool_calls:
                    fn     = call.get("function", {})
                    tc_id  = f"call_{uuid.uuid4().hex[:12]}"
                    tool_call_ids.append(tc_id)
                    args   = fn.get("arguments") or {}
                    oai_calls.append({
                        "id":   tc_id,
                        "type": "function",
                        "function": {
                            "name":      fn.get("name", ""),
                            "arguments": json.dumps(args) if isinstance(args, dict) else args,
                        },
                    })
                out: dict = {"role": "assistant", "tool_calls": oai_calls}
                if content:
                    out["content"] = content
                result.append(out)
            else:
                result.append({"role": "assistant", "content": content})
            continue

        if role == "tool":
            tc_id = (
                tool_call_ids[tool_result_index]
                if tool_result_index < len(tool_call_ids)
                else f"call_unknown_{tool_result_index}"
            )
            tool_result_index += 1
            result.append({"role": "tool", "tool_call_id": tc_id, "content": content})
            continue

    return result


def _openai_message_to_ollama(msg) -> dict:
    """Convert an OpenAI response ChatCompletion message to Ollama-compatible format."""
    content    = msg.content or ""
    tool_calls = msg.tool_calls or []

    result: dict = {"content": content}
    if tool_calls:
        result["tool_calls"] = [
            {
                "function": {
                    "name":      tc.function.name,
                    "arguments": json.loads(tc.function.arguments or "{}"),
                }
            }
            for tc in tool_calls
        ]
    return result


class OpenAIProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Lazy import so the package is only required when this provider is used
        import openai
        kwargs: dict = {"api_key": settings.openai_api_key}
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url
        self._client = openai.AsyncOpenAI(**kwargs)

    @property
    def default_model(self) -> str:
        return self._settings.openai_model

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict:
        effective_model = model or self._settings.openai_model
        oai_messages    = _ollama_messages_to_openai(messages)

        kwargs: dict = {
            "model":       effective_model,
            "messages":    oai_messages,
            "temperature": temperature,
            "max_tokens":  max_tokens,
        }
        if tools:
            kwargs["tools"]       = _ollama_tools_to_openai(tools)
            kwargs["tool_choice"] = "auto"

        logger.debug(
            "openai_chat_request",
            model=effective_model,
            message_count=len(oai_messages),
            tools_available=[t["function"]["name"] for t in _ollama_tools_to_openai(tools or [])],
        )

        response = await self._client.chat.completions.create(**kwargs)
        choice   = response.choices[0]

        logger.debug(
            "openai_chat_response",
            model=effective_model,
            finish_reason=choice.finish_reason,
            prompt_tokens=response.usage.prompt_tokens if response.usage else None,
            completion_tokens=response.usage.completion_tokens if response.usage else None,
        )

        return _openai_message_to_ollama(choice.message)

    async def stream(
        self,
        prompt: str,
        system: str,
        model: str | None = None,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        effective_model = model or self._settings.openai_model
        stream = await self._client.chat.completions.create(
            model=effective_model,
            messages=[
                {"role": "system",  "content": system},
                {"role": "user",    "content": prompt},
            ],
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    async def list_models(self) -> list[str]:
        try:
            models = await self._client.models.list()
            # Filter to chat-capable models (exclude embeddings, tts, etc.)
            chat_models = sorted(
                m.id for m in models.data
                if "gpt" in m.id or m.id.startswith("o1") or m.id.startswith("o3")
            )
            return chat_models or _KNOWN_MODELS
        except Exception:
            return _KNOWN_MODELS
