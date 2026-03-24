"""Outbound response models."""

from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response body for health/readiness endpoints."""

    status: str
    version: str


class AgentQueryResponse(BaseModel):
    """Response body for POST /api/v1/agent/query."""

    answer: str
    query: str
    model: str
    tokens_used: int | None = None
