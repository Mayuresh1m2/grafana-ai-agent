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


class DatasourceInfo(BaseModel):
    """Grafana datasource summary returned to the frontend."""

    uid: str
    name: str
    type: str
    is_default: bool = False


class GrafanaConnectResponse(BaseModel):
    """Response body for POST /api/v1/grafana/connect."""

    session_id: str
    grafana_url: str
    datasources: list[DatasourceInfo]
