"""Unit tests for app.agents.tools — each tool with mocked GrafanaService."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.models import ServiceGraph
from app.agents.tools import (
    TOOL_REGISTRY,
    ToolContext,
    analyze_log_pattern,
    get_service_dependencies,
    get_service_list,
    get_tool_specs,
    query_loki_logs,
    query_metric,
    search_related_logs,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_grafana() -> MagicMock:
    """Return a MagicMock with async Grafana methods."""
    svc = MagicMock()
    svc.query_loki = AsyncMock()
    svc.get_loki_label_values = AsyncMock()
    svc.query_prometheus = AsyncMock()
    svc.query_prometheus_range = AsyncMock()
    return svc


def _ctx(grafana: MagicMock) -> ToolContext:
    return ToolContext(grafana=grafana)


def _loki_response(*lines: tuple[str, str], labels: dict | None = None) -> dict[str, Any]:
    """Build a minimal Loki query_range response with one stream."""
    if labels is None:
        labels = {"service": "api", "level": "error"}
    return {
        "status": "success",
        "data": {
            "resultType": "streams",
            "result": [
                {
                    "stream": labels,
                    "values": [(ts, msg) for ts, msg in lines],
                }
            ],
        },
    }


@pytest.fixture()
def service_graph_fixture() -> ServiceGraph:
    return ServiceGraph(
        services=["api", "db", "cache"],
        edges=[
            {"source": "api", "target": "db", "call_count": 500, "error_rate": 0.01},
            {"source": "api", "target": "cache", "call_count": 200, "error_rate": 0.0},
        ],
    )


# ---------------------------------------------------------------------------
# Tool registry smoke
# ---------------------------------------------------------------------------


class TestToolRegistry:
    def test_all_tools_registered(self) -> None:
        expected = {
            "query_loki_logs",
            "get_service_list",
            "analyze_log_pattern",
            "query_metric",
            "get_service_dependencies",
            "search_related_logs",
        }
        assert expected.issubset(set(TOOL_REGISTRY.keys()))

    def test_get_tool_specs_returns_openai_format(self) -> None:
        specs = get_tool_specs()
        assert len(specs) >= 6
        for spec in specs:
            assert spec["type"] == "function"
            fn = spec["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn
            assert fn["parameters"]["type"] == "object"

    def test_tool_specs_have_descriptions(self) -> None:
        specs = get_tool_specs()
        for spec in specs:
            desc = spec["function"]["description"]
            assert len(desc) > 10, f"Tool {spec['function']['name']} has a very short description"


# ---------------------------------------------------------------------------
# query_loki_logs
# ---------------------------------------------------------------------------


class TestQueryLokiLogs:
    async def test_returns_log_entries(self) -> None:
        grafana = _make_grafana()
        ts_ns = str(int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1e9))
        grafana.query_loki.return_value = _loki_response(
            (ts_ns, "error: connection refused"),
            labels={"service": "api", "level": "error"},
        )
        ctx = _ctx(grafana)

        entries = await query_loki_logs(ctx, logql='{service="api"} |= "error"')

        assert len(entries) == 1
        assert entries[0]["service"] == "api"
        assert entries[0]["level"] == "error"
        assert "connection refused" in entries[0]["message"]

    async def test_unknown_level_normalised(self) -> None:
        grafana = _make_grafana()
        ts_ns = "1704067200000000000"
        grafana.query_loki.return_value = _loki_response(
            (ts_ns, "some log"),
            labels={"service": "svc", "level": "TRACE"},
        )
        ctx = _ctx(grafana)

        entries = await query_loki_logs(ctx, logql="{service=\"svc\"}")
        assert entries[0]["level"] == "unknown"

    async def test_empty_loki_response(self) -> None:
        grafana = _make_grafana()
        grafana.query_loki.return_value = {"data": {"resultType": "streams", "result": []}}
        ctx = _ctx(grafana)

        entries = await query_loki_logs(ctx, logql='{service="empty"}')
        assert entries == []

    async def test_passes_params_to_grafana(self) -> None:
        grafana = _make_grafana()
        grafana.query_loki.return_value = {"data": {"result": []}}
        ctx = _ctx(grafana)

        await query_loki_logs(ctx, logql="{j}", start="now-2h", end="now", limit=50)
        grafana.query_loki.assert_called_once_with(
            logql="{j}", start="now-2h", end="now", limit=50
        )


# ---------------------------------------------------------------------------
# get_service_list
# ---------------------------------------------------------------------------


class TestGetServiceList:
    async def test_returns_sorted_services(self) -> None:
        grafana = _make_grafana()
        grafana.get_loki_label_values.return_value = ["zservice", "api", "worker"]
        ctx = _ctx(grafana)

        services = await get_service_list(ctx)

        assert services == ["api", "worker", "zservice"]

    async def test_falls_back_to_app_label(self) -> None:
        grafana = _make_grafana()
        # First call (service label) returns empty; second call (app label) returns values
        grafana.get_loki_label_values.side_effect = [[], ["frontend", "backend"]]
        ctx = _ctx(grafana)

        services = await get_service_list(ctx)
        assert services == ["backend", "frontend"]

    async def test_deduplicates_services(self) -> None:
        grafana = _make_grafana()
        grafana.get_loki_label_values.return_value = ["api", "api", "worker"]
        ctx = _ctx(grafana)

        services = await get_service_list(ctx)
        assert len(services) == len(set(services))


# ---------------------------------------------------------------------------
# analyze_log_pattern
# ---------------------------------------------------------------------------


class TestAnalyzeLogPattern:
    async def test_clusters_repeated_messages(self) -> None:
        grafana = _make_grafana()
        ts_base = 1704067200000000000
        repeated_line = "error: db connection timeout at line 42"
        grafana.query_loki.return_value = _loki_response(
            (str(ts_base), repeated_line),
            (str(ts_base + 1_000_000_000), repeated_line),
            (str(ts_base + 2_000_000_000), repeated_line),
            labels={"service": "api", "level": "error"},
        )
        ctx = _ctx(grafana)

        summaries = await analyze_log_pattern(ctx, service="api")

        assert len(summaries) == 1
        assert summaries[0]["count"] == 3
        assert summaries[0]["pattern"][:30] == repeated_line[:30]

    async def test_sorted_by_count_descending(self) -> None:
        grafana = _make_grafana()
        ts = 1704067200000000000
        grafana.query_loki.return_value = {
            "data": {
                "resultType": "streams",
                "result": [
                    {
                        "stream": {"service": "api", "level": "error"},
                        "values": [
                            (str(ts), "rare error"),
                            (str(ts + 1), "common error"),
                            (str(ts + 2), "common error"),
                            (str(ts + 3), "common error"),
                        ],
                    }
                ],
            }
        }
        ctx = _ctx(grafana)

        summaries = await analyze_log_pattern(ctx, service="api")
        assert summaries[0]["count"] >= summaries[-1]["count"]

    async def test_empty_when_no_logs(self) -> None:
        grafana = _make_grafana()
        grafana.query_loki.return_value = {"data": {"result": []}}
        ctx = _ctx(grafana)

        summaries = await analyze_log_pattern(ctx, service="quiet-svc")
        assert summaries == []


# ---------------------------------------------------------------------------
# query_metric
# ---------------------------------------------------------------------------


class TestQueryMetric:
    async def test_passes_promql_to_grafana(self) -> None:
        grafana = _make_grafana()
        expected = {"status": "success", "data": {"resultType": "vector", "result": []}}
        grafana.query_prometheus.return_value = expected
        ctx = _ctx(grafana)

        result = await query_metric(ctx, promql='rate(http_requests_total[5m])')

        grafana.query_prometheus.assert_called_once_with(
            promql='rate(http_requests_total[5m])', time=None
        )
        assert result == expected

    async def test_passes_time_param(self) -> None:
        grafana = _make_grafana()
        grafana.query_prometheus.return_value = {"status": "success"}
        ctx = _ctx(grafana)

        await query_metric(ctx, promql="up", time="2024-01-01T00:00:00Z")
        grafana.query_prometheus.assert_called_once_with(
            promql="up", time="2024-01-01T00:00:00Z"
        )


# ---------------------------------------------------------------------------
# get_service_dependencies
# ---------------------------------------------------------------------------


class TestGetServiceDependencies:
    async def test_returns_dependency_structure(self) -> None:
        grafana = _make_grafana()
        grafana.query_prometheus.return_value = {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {"metric": {"service": "api", "peer_service": "db"}, "value": [1, "10"]}
                ],
            },
        }
        ctx = _ctx(grafana)

        result = await get_service_dependencies(ctx, service="api")

        assert "upstream" in result
        assert "downstream" in result
        assert "graph" in result
        assert "db" in result["upstream"]

    async def test_empty_result_on_prometheus_error(self) -> None:
        grafana = _make_grafana()
        grafana.query_prometheus.side_effect = Exception("Prometheus unreachable")
        ctx = _ctx(grafana)

        result = await get_service_dependencies(ctx, service="api")

        assert result["upstream"] == []
        assert result["downstream"] == []

    def test_service_graph_fixture(self, service_graph_fixture: ServiceGraph) -> None:
        graph = service_graph_fixture
        assert "db" in graph.downstream_of("api")
        assert "cache" in graph.downstream_of("api")
        assert graph.upstream_of("db") == ["api"]
        assert graph.upstream_of("cache") == ["api"]
        assert graph.upstream_of("api") == []


# ---------------------------------------------------------------------------
# search_related_logs
# ---------------------------------------------------------------------------


class TestSearchRelatedLogs:
    async def test_uses_service_selector_when_provided(self) -> None:
        grafana = _make_grafana()
        grafana.query_loki.return_value = {"data": {"result": []}}
        ctx = _ctx(grafana)

        await search_related_logs(ctx, keyword="timeout", service="api")

        call_kwargs = grafana.query_loki.call_args[1]
        assert 'service="api"' in call_kwargs["logql"]
        assert "timeout" in call_kwargs["logql"]

    async def test_uses_wildcard_selector_without_service(self) -> None:
        grafana = _make_grafana()
        grafana.query_loki.return_value = {"data": {"result": []}}
        ctx = _ctx(grafana)

        await search_related_logs(ctx, keyword="OOM")

        call_kwargs = grafana.query_loki.call_args[1]
        assert "OOM" in call_kwargs["logql"]
        # Should not restrict to a specific service
        assert 'service="' not in call_kwargs["logql"]

    async def test_returns_entries_with_timestamps(self) -> None:
        grafana = _make_grafana()
        ts_ns = "1704067200000000000"
        grafana.query_loki.return_value = _loki_response(
            (ts_ns, "timeout occurred"),
            labels={"service": "api", "level": "warn"},
        )
        ctx = _ctx(grafana)

        entries = await search_related_logs(ctx, keyword="timeout", service="api")

        assert len(entries) == 1
        assert entries[0]["service"] == "api"
        assert isinstance(entries[0]["timestamp"], float)
