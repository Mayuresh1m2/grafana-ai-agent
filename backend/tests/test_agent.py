"""Tests for POST /api/v1/agent/query."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.services.ollama import OllamaService


def _make_mock_ollama(answer: str = "CPU is at 42%.", tokens: int = 64) -> OllamaService:
    mock = AsyncMock(spec=OllamaService)
    mock.generate = AsyncMock(return_value=(answer, tokens))
    mock.default_model = "llama3"
    return mock  # type: ignore[return-value]


def test_agent_module_smoke() -> None:
    """Smoke: agent module imports and router is present."""
    from src.api.agent import router

    assert router is not None


def test_agent_query_returns_200() -> None:
    with patch("src.api.agent.get_ollama_service", return_value=_make_mock_ollama()):
        with TestClient(create_app()) as client:
            response = client.post(
                "/api/v1/agent/query",
                json={"query": "What is the CPU usage?"},
            )
    assert response.status_code == 200


def test_agent_query_response_body() -> None:
    expected_answer = "CPU is at 42%."
    with patch("src.api.agent.get_ollama_service", return_value=_make_mock_ollama(expected_answer)):
        with TestClient(create_app()) as client:
            data = client.post(
                "/api/v1/agent/query",
                json={"query": "CPU?"},
            ).json()

    assert data["answer"] == expected_answer
    assert data["query"] == "CPU?"
    assert "model" in data


def test_agent_query_with_context() -> None:
    mock = _make_mock_ollama()
    with patch("src.api.agent.get_ollama_service", return_value=mock):
        with TestClient(create_app()) as client:
            client.post(
                "/api/v1/agent/query",
                json={
                    "query": "Any errors?",
                    "context": {"environment": "production"},
                },
            )

    mock.generate.assert_called_once()
    call_kwargs = mock.generate.call_args
    assert call_kwargs.kwargs.get("context") == {"environment": "production"}


def test_agent_query_empty_string_returns_422() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/agent/query", json={"query": ""})
    assert response.status_code == 422


def test_agent_query_missing_query_returns_422() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/agent/query", json={})
    assert response.status_code == 422


def test_agent_query_ollama_error_returns_502() -> None:
    mock = AsyncMock(spec=OllamaService)
    mock.generate = AsyncMock(side_effect=RuntimeError("connection refused"))
    mock.default_model = "llama3"

    with patch("src.api.agent.get_ollama_service", return_value=mock):
        with TestClient(create_app()) as client:
            response = client.post(
                "/api/v1/agent/query",
                json={"query": "anything"},
            )
    assert response.status_code == 502
    assert "Ollama" in response.json()["detail"]
