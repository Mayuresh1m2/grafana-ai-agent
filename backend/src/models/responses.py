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


class AlertInfo(BaseModel):
    """A single active Grafana alert, normalised from either the Alertmanager v2
    API or the legacy /api/alerts endpoint."""

    name: str
    severity: str = "unknown"   # critical | warning | info | unknown
    state: str = "firing"       # firing | pending
    summary: str = ""
    labels: dict[str, str] = {}
    started_at: str | None = None
