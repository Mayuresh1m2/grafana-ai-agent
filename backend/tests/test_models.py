"""Tests for src.models — Pydantic v2 request/response models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.requests import AgentQueryRequest
from src.models.responses import AgentQueryResponse, HealthResponse


# ── Smoke tests ───────────────────────────────────────────────────────────────

def test_models_module_smoke() -> None:
    """Smoke: models package exports all expected symbols."""
    from src import models

    assert hasattr(models, "AgentQueryRequest")
    assert hasattr(models, "AgentQueryResponse")
    assert hasattr(models, "HealthResponse")


# ── AgentQueryRequest ─────────────────────────────────────────────────────────

def test_agent_query_request_minimal() -> None:
    req = AgentQueryRequest(query="What is CPU usage?")
    assert req.query == "What is CPU usage?"
    assert req.context == {}
    assert req.model is None
    assert req.temperature == pytest.approx(0.7)
    assert req.max_tokens == 2048


def test_agent_query_request_full() -> None:
    req = AgentQueryRequest(
        query="Show errors",
        context={"env": "prod", "service": "checkout"},
        model="mistral",
        temperature=0.2,
        max_tokens=512,
    )
    assert req.context["env"] == "prod"
    assert req.model == "mistral"


def test_agent_query_request_empty_string_raises() -> None:
    with pytest.raises(ValidationError):
        AgentQueryRequest(query="")


def test_agent_query_request_too_long_raises() -> None:
    with pytest.raises(ValidationError):
        AgentQueryRequest(query="x" * 8193)


def test_agent_query_request_temperature_out_of_range() -> None:
    with pytest.raises(ValidationError):
        AgentQueryRequest(query="test", temperature=3.0)


def test_agent_query_request_max_tokens_zero_raises() -> None:
    with pytest.raises(ValidationError):
        AgentQueryRequest(query="test", max_tokens=0)


# ── AgentQueryResponse ────────────────────────────────────────────────────────

def test_agent_query_response_minimal() -> None:
    resp = AgentQueryResponse(answer="The CPU is fine.", query="CPU?", model="llama3")
    assert resp.answer == "The CPU is fine."
    assert resp.tokens_used is None


def test_agent_query_response_with_tokens() -> None:
    resp = AgentQueryResponse(
        answer="ok", query="q", model="llama3", tokens_used=128
    )
    assert resp.tokens_used == 128


# ── HealthResponse ────────────────────────────────────────────────────────────

def test_health_response_smoke() -> None:
    resp = HealthResponse(status="ok", version="0.1.0")
    assert resp.status == "ok"
    assert resp.version == "0.1.0"
