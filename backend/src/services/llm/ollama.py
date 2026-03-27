"""Ollama LLM provider."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import structlog

from src.config import Settings
from src.services.llm.base import LLMProvider

logger = structlog.get_logger(__name__)


class OllamaProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            timeout=httpx.Timeout(settings.ollama_timeout),
        )

    @property
    def default_model(self) -> str:
        return self._settings.ollama_model

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict:
        effective_model = model or self._settings.ollama_model
        payload: dict = {
            "model": effective_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = tools

        tool_names = [t["function"]["name"] for t in (tools or [])]
        logger.debug(
            "ollama_chat_request",
            model=effective_model,
            temperature=temperature,
            message_count=len(messages),
            tools_available=tool_names,
            messages=messages,
        )

        response = await self._client.post("/api/chat", json=payload)

        if response.status_code == 400 and tools:
            # Model does not support tool calling — retry without tools
            logger.warning(
                "ollama_tools_not_supported",
                model=effective_model,
                detail=response.text[:300],
                hint="Switch to llama3.1, llama3.2, mistral-nemo, or qwen2.5 for tool calling",
            )
            payload.pop("tools")
            response = await self._client.post("/api/chat", json=payload)

        response.raise_for_status()
        data: dict = response.json()
        msg: dict = data.get("message", {})

        if tools and not msg.get("tool_calls"):
            # Flag so the agent loop can warn the user
            msg["_tools_skipped"] = True

        tool_calls = msg.get("tool_calls") or []
        logger.debug(
            "ollama_chat_response",
            model=effective_model,
            has_tool_calls=bool(tool_calls),
            tool_calls=tool_calls,
            content_preview=(str(msg.get("content") or "")[:200] or None),
            eval_count=data.get("eval_count"),
            prompt_eval_count=data.get("prompt_eval_count"),
        )
        return msg

    async def stream(
        self,
        prompt: str,
        system: str,
        model: str | None = None,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        effective_model = model or self._settings.ollama_model
        payload: dict = {
            "model": effective_model,
            "prompt": prompt,
            "system": system,
            "stream": True,
            "options": {"temperature": temperature},
        }
        async with self._client.stream("POST", "/api/generate", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    token: str = chunk.get("response", "")
                    if token:
                        yield token
                    if chunk.get("done"):
                        break
                except (json.JSONDecodeError, KeyError):
                    continue

    async def list_models(self) -> list[str]:
        try:
            response = await self._client.get("/api/tags")
            response.raise_for_status()
            data: dict = response.json()
            return [str(m.get("name", "")) for m in data.get("models", [])]
        except Exception:
            return [self._settings.ollama_model]
