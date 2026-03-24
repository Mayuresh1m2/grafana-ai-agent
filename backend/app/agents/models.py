"""Pydantic models used by the agent tool layer."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LogEntry(BaseModel):
    """A single log line returned from Loki."""

    timestamp: datetime
    level: Literal["debug", "info", "warn", "error", "critical", "unknown"] = "unknown"
    service: str = ""
    message: str
    labels: dict[str, str] = Field(default_factory=dict)


class LogPatternSummary(BaseModel):
    """Aggregated summary of a recurring log pattern."""

    pattern: str
    count: int
    first_seen: datetime
    last_seen: datetime
    example: str = ""
    severity: Literal["info", "warn", "error"] = "info"


class ServiceEdge(BaseModel):
    """Directed dependency edge between two services."""

    source: str
    target: str
    call_count: int = 0
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    p99_latency_ms: float | None = None


class ServiceGraph(BaseModel):
    """Service dependency graph derived from trace / metric data."""

    services: list[str] = Field(default_factory=list)
    edges: list[ServiceEdge] = Field(default_factory=list)

    def upstream_of(self, service: str) -> list[str]:
        """Return all services that call *service*."""
        return [e.source for e in self.edges if e.target == service]

    def downstream_of(self, service: str) -> list[str]:
        """Return all services called by *service*."""
        return [e.target for e in self.edges if e.source == service]


class ToolExecutionError(BaseModel):
    """Structured error returned when an agent tool fails."""

    tool: str
    error: str
    details: str = ""
