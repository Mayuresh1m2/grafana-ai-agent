"""Async HTTP client for the Grafana / Loki / Prometheus APIs."""

from __future__ import annotations

import structlog
import httpx

from src.config import Settings, get_settings

logger = structlog.get_logger(__name__)


class GrafanaService:
    """Thin async client around Grafana HTTP API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        headers: dict[str, str] = {"Accept": "application/json"}
        if settings.grafana_api_key:
            headers["Authorization"] = f"Bearer {settings.grafana_api_key}"

        self._grafana = httpx.AsyncClient(
            base_url=settings.grafana_base_url,
            headers=headers,
            timeout=30.0,
        )
        self._loki = httpx.AsyncClient(
            base_url=settings.loki_base_url,
            timeout=30.0,
        )
        self._prometheus = httpx.AsyncClient(
            base_url=settings.prometheus_base_url,
            timeout=30.0,
        )

    async def get_datasources(self) -> list[dict[str, object]]:
        """List all data sources configured in Grafana."""
        log = logger.bind(service="grafana")
        log.debug("fetching_datasources")
        response = await self._grafana.get("/api/datasources")
        response.raise_for_status()
        result: list[dict[str, object]] = response.json()
        log.debug("datasources_fetched", count=len(result))
        return result

    async def query_loki(
        self,
        logql: str,
        start: str = "now-1h",
        end: str = "now",
        limit: int = 100,
    ) -> dict[str, object]:
        """Execute a LogQL instant or range query against Loki."""
        log = logger.bind(service="loki", logql_preview=logql[:60])
        log.debug("loki_query_start")
        params = {
            "query": logql,
            "start": start,
            "end": end,
            "limit": str(limit),
        }
        response = await self._loki.get("/loki/api/v1/query_range", params=params)
        response.raise_for_status()
        result: dict[str, object] = response.json()
        log.debug("loki_query_done")
        return result

    async def get_loki_label_values(
        self,
        label_name: str,
        selector: str | None = None,
        start: str = "now-6h",
        end: str = "now",
    ) -> list[str]:
        """Return all values for a Loki label (e.g. all service names).

        Args:
            label_name: Loki label key (e.g. ``"service"``).
            selector: Optional LogQL stream selector to restrict the search
                (e.g. ``'{namespace="prod"}'``).
            start: Range start — Loki duration string or RFC3339.
            end: Range end.
        """
        log = logger.bind(service="loki", label=label_name)
        log.debug("loki_label_values_start")
        params: dict[str, str] = {"start": start, "end": end}
        if selector:
            params["query"] = selector
        response = await self._loki.get(
            f"/loki/api/v1/label/{label_name}/values", params=params
        )
        response.raise_for_status()
        data: dict[str, object] = response.json()
        values: list[str] = data.get("data", [])  # type: ignore[assignment]
        log.debug("loki_label_values_done", count=len(values))
        return values

    async def query_prometheus(
        self,
        promql: str,
        time: str | None = None,
    ) -> dict[str, object]:
        """Execute a PromQL instant query against Prometheus."""
        log = logger.bind(service="prometheus", promql_preview=promql[:60])
        log.debug("prometheus_query_start")
        params: dict[str, str] = {"query": promql}
        if time:
            params["time"] = time
        response = await self._prometheus.get("/api/v1/query", params=params)
        response.raise_for_status()
        result: dict[str, object] = response.json()
        log.debug("prometheus_query_done")
        return result

    async def query_prometheus_range(
        self,
        promql: str,
        start: str,
        end: str,
        step: str = "60s",
    ) -> dict[str, object]:
        """Execute a PromQL range query against Prometheus.

        Args:
            promql: PromQL expression.
            start: Range start as RFC3339 or Unix timestamp.
            end: Range end as RFC3339 or Unix timestamp.
            step: Resolution step (e.g. ``"60s"``, ``"5m"``).
        """
        log = logger.bind(service="prometheus", promql_preview=promql[:60])
        log.debug("prometheus_range_query_start")
        params: dict[str, str] = {
            "query": promql,
            "start": start,
            "end": end,
            "step": step,
        }
        response = await self._prometheus.get("/api/v1/query_range", params=params)
        response.raise_for_status()
        result: dict[str, object] = response.json()
        log.debug("prometheus_range_query_done")
        return result

    async def aclose(self) -> None:
        await self._grafana.aclose()
        await self._loki.aclose()
        await self._prometheus.aclose()


def get_grafana_service() -> GrafanaService:
    """FastAPI dependency."""
    return GrafanaService(get_settings())
