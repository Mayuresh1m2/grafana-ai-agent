"""Unit tests for app.tools.infra_tools and app.tools.promql_templates."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.models import LogEntry
from app.agents.tools import TOOL_REGISTRY, ToolContext
from app.tools import promql_templates as Q
from app.tools.infra_tools import (
    Anomaly,
    CheckStatus,
    CorrelationReport,
    HealthReport,
    InfrastructureAnalyzer,
    MetricCheck,
    NamespaceTopology,
    _compute_z_score,
    evaluate_threshold,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_grafana(**overrides: AsyncMock) -> MagicMock:
    svc = MagicMock()
    svc.query_prometheus = AsyncMock(return_value=_empty_prom())
    svc.query_prometheus_range = AsyncMock(return_value=_empty_prom_range())
    svc.query_loki = AsyncMock(return_value={"data": {"result": []}})
    for attr, mock in overrides.items():
        setattr(svc, attr, mock)
    return svc


def _empty_prom() -> dict[str, Any]:
    return {"status": "success", "data": {"resultType": "vector", "result": []}}


def _empty_prom_range() -> dict[str, Any]:
    return {"status": "success", "data": {"resultType": "matrix", "result": []}}


def _scalar_prom(value: float, labels: dict[str, str] | None = None) -> dict[str, Any]:
    """Build a Prometheus instant-query response with a single scalar result."""
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [{"metric": labels or {}, "value": [1704067200, str(value)]}],
        },
    }


def _range_prom(
    series_values: list[tuple[float, float]],
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a Prometheus range-query response with a single series."""
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": labels or {},
                    "values": [[str(ts), str(val)] for ts, val in series_values],
                }
            ],
        },
    }


def _log_entry(
    ts: float,
    message: str = "error: something failed",
    service: str = "api",
    level: str = "error",
) -> LogEntry:
    return LogEntry(
        timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
        level=level,
        service=service,
        message=message,
    )


# ---------------------------------------------------------------------------
# 1. Threshold evaluation
# ---------------------------------------------------------------------------


class TestEvaluateThreshold:
    """Boundary-condition tests for evaluate_threshold()."""

    # --- higher_is_worse (default) ---

    def test_below_warning_is_ok(self) -> None:
        assert evaluate_threshold(50.0, warning=80.0, critical=95.0) == CheckStatus.OK

    def test_at_warning_boundary_is_warning(self) -> None:
        assert evaluate_threshold(80.0, warning=80.0, critical=95.0) == CheckStatus.WARNING

    def test_above_warning_below_critical_is_warning(self) -> None:
        assert evaluate_threshold(90.0, warning=80.0, critical=95.0) == CheckStatus.WARNING

    def test_at_critical_boundary_is_critical(self) -> None:
        assert evaluate_threshold(95.0, warning=80.0, critical=95.0) == CheckStatus.CRITICAL

    def test_above_critical_is_critical(self) -> None:
        assert evaluate_threshold(99.9, warning=80.0, critical=95.0) == CheckStatus.CRITICAL

    def test_none_value_is_ok(self) -> None:
        assert evaluate_threshold(None, warning=80.0, critical=95.0) == CheckStatus.OK

    def test_zero_is_ok_when_thresholds_are_positive(self) -> None:
        assert evaluate_threshold(0.0, warning=1.0, critical=5.0) == CheckStatus.OK

    # --- lower_is_worse ---

    def test_lower_is_worse_above_warning_is_ok(self) -> None:
        # e.g. replica count: warning if <= 2, critical if <= 1
        assert evaluate_threshold(5.0, warning=2.0, critical=1.0, higher_is_worse=False) == CheckStatus.OK

    def test_lower_is_worse_at_warning_is_warning(self) -> None:
        assert evaluate_threshold(2.0, warning=2.0, critical=1.0, higher_is_worse=False) == CheckStatus.WARNING

    def test_lower_is_worse_at_critical_is_critical(self) -> None:
        assert evaluate_threshold(1.0, warning=2.0, critical=1.0, higher_is_worse=False) == CheckStatus.CRITICAL

    def test_lower_is_worse_below_critical_is_critical(self) -> None:
        assert evaluate_threshold(0.0, warning=2.0, critical=1.0, higher_is_worse=False) == CheckStatus.CRITICAL

    # --- per MetricCheck type ---

    def test_cpu_warning_at_80_percent(self) -> None:
        assert evaluate_threshold(80.0, 80.0, 95.0) == CheckStatus.WARNING

    def test_cpu_ok_at_79_percent(self) -> None:
        assert evaluate_threshold(79.9, 80.0, 95.0) == CheckStatus.OK

    def test_memory_warning_at_85_percent(self) -> None:
        assert evaluate_threshold(85.0, 85.0, 95.0) == CheckStatus.WARNING

    def test_restarts_warning_at_2(self) -> None:
        assert evaluate_threshold(2.0, 2.0, 5.0) == CheckStatus.WARNING

    def test_restarts_critical_at_5(self) -> None:
        assert evaluate_threshold(5.0, 2.0, 5.0) == CheckStatus.CRITICAL

    def test_error_rate_warning_at_1_percent(self) -> None:
        assert evaluate_threshold(1.0, 1.0, 5.0) == CheckStatus.WARNING

    def test_latency_warning_at_500ms(self) -> None:
        assert evaluate_threshold(500.0, 500.0, 2000.0) == CheckStatus.WARNING

    def test_latency_critical_at_2000ms(self) -> None:
        assert evaluate_threshold(2000.0, 500.0, 2000.0) == CheckStatus.CRITICAL


# ---------------------------------------------------------------------------
# 2. Anomaly detection — synthetic spike dataset
# ---------------------------------------------------------------------------


class TestComputeZScore:
    def test_no_anomaly_flat_series(self) -> None:
        baseline = [1.0] * 100
        current = [1.0] * 10
        assert abs(_compute_z_score(baseline, current)) < 0.1

    def test_spike_above_mean_positive_z(self) -> None:
        # baseline mean≈1, std≈0.1; current mean=4 → z≈30
        import random
        rng = random.Random(42)
        baseline = [rng.gauss(1.0, 0.1) for _ in range(360)]
        current = [4.0] * 10
        z = _compute_z_score(baseline, current)
        assert z > 3.0

    def test_drop_below_mean_negative_z(self) -> None:
        import random
        rng = random.Random(42)
        baseline = [rng.gauss(10.0, 0.5) for _ in range(360)]
        current = [1.0] * 10  # sudden drop
        z = _compute_z_score(baseline, current)
        assert z < -3.0

    def test_zero_variance_baseline_returns_zero(self) -> None:
        # All identical values → std = 0 → z-score undefined → 0
        baseline = [5.0] * 50
        current = [10.0] * 10
        assert _compute_z_score(baseline, current) == 0.0

    def test_empty_baseline_returns_zero(self) -> None:
        assert _compute_z_score([], [1.0, 2.0]) == 0.0

    def test_empty_current_returns_zero(self) -> None:
        assert _compute_z_score([1.0, 2.0, 3.0], []) == 0.0


class TestDetectAnomalies:
    """End-to-end anomaly detection through InfrastructureAnalyzer."""

    async def test_detects_cpu_spike(self) -> None:
        """A CPU spike > 3σ above baseline should appear in the anomaly list."""
        import random
        rng = random.Random(42)
        now = time.time()
        window_sec = 3600  # 1h
        baseline_sec = 6 * 3600  # 6h

        # Build time-series: 6h baseline (mean=0.3, std=0.05) + 1h spike (mean=0.8)
        total_points = int((baseline_sec + window_sec) / 60)
        baseline_ts = now - baseline_sec - window_sec
        points: list[tuple[float, float]] = []
        for i in range(total_points):
            ts = baseline_ts + i * 60
            if ts < now - window_sec:
                val = rng.gauss(0.3, 0.05)
            else:
                val = rng.gauss(0.8, 0.02)  # clear spike
            points.append((ts, max(0.0, val)))

        range_response = _range_prom(
            points, labels={"pod": "api-abc-xyz", "destination_service_name": "api"}
        )

        grafana = _make_grafana(
            query_prometheus_range=AsyncMock(return_value=range_response)
        )
        analyzer = InfrastructureAnalyzer(grafana)
        anomalies = await analyzer.detect_anomalies(namespace="prod", window_minutes=60)

        assert len(anomalies) >= 1
        top = max(anomalies, key=lambda a: abs(a.z_score))
        assert abs(top.z_score) >= 3.0

    async def test_no_anomaly_on_flat_series(self) -> None:
        """A perfectly flat series should produce no anomalies."""
        now = time.time()
        total_sec = 7 * 3600
        points = [(now - total_sec + i * 60, 0.4) for i in range(420)]

        range_response = _range_prom(points, labels={"destination_service_name": "stable-svc"})
        grafana = _make_grafana(
            query_prometheus_range=AsyncMock(return_value=range_response)
        )
        analyzer = InfrastructureAnalyzer(grafana)
        anomalies = await analyzer.detect_anomalies(namespace="prod", window_minutes=60)
        assert anomalies == []

    async def test_anomaly_severity_critical_above_5sigma(self) -> None:
        import random
        rng = random.Random(0)
        now = time.time()
        window_sec = 3600
        baseline_sec = 6 * 3600
        baseline_ts = now - baseline_sec - window_sec
        total = int((baseline_sec + window_sec) / 60)

        points: list[tuple[float, float]] = []
        for i in range(total):
            ts = baseline_ts + i * 60
            if ts < now - window_sec:
                points.append((ts, rng.gauss(0.1, 0.01)))
            else:
                points.append((ts, 10.0))  # extreme spike: >5σ

        range_response = _range_prom(points, labels={"destination_service_name": "svc"})
        grafana = _make_grafana(
            query_prometheus_range=AsyncMock(return_value=range_response)
        )
        analyzer = InfrastructureAnalyzer(grafana)
        anomalies = await analyzer.detect_anomalies(namespace="prod", window_minutes=60)

        critical = [a for a in anomalies if a.severity == CheckStatus.CRITICAL]
        assert len(critical) >= 1


# ---------------------------------------------------------------------------
# 3. PromQL template substitution and injection prevention
# ---------------------------------------------------------------------------


class TestPromQLRender:
    def test_basic_substitution(self) -> None:
        result = Q.render(Q.SERVICES_INFO, namespace="prod")
        assert 'namespace="prod"' in result
        assert "{namespace}" not in result

    def test_multi_placeholder_substitution(self) -> None:
        result = Q.render(Q.CPU_USAGE_RATIO, namespace="prod", service="api", window="5m")
        assert 'namespace="prod"' in result
        assert 'service="api"' not in result  # service appears in pod regex, not label
        assert "[5m]" in result

    def test_window_duration_accepted(self) -> None:
        for duration in ("1m", "5m", "30m", "1h", "6h", "1d"):
            result = Q.render(Q.POD_RESTART_COUNT, namespace="ns", service="svc", window=duration)
            assert f"[{duration}]" in result

    def test_raises_on_special_chars_in_namespace(self) -> None:
        with pytest.raises(ValueError, match="Unsafe value"):
            Q.render(Q.SERVICES_INFO, namespace="prod}; malicious")

    def test_raises_on_injection_with_closing_brace(self) -> None:
        with pytest.raises(ValueError, match="Unsafe value"):
            Q.render(Q.SERVICES_INFO, namespace='prod"} OR vector(1) #{')

    def test_raises_on_sql_injection_style_service(self) -> None:
        with pytest.raises(ValueError, match="Unsafe value"):
            Q.render(
                Q.CPU_USAGE_RATIO,
                namespace="prod",
                service="api;drop",
                window="5m",
            )

    def test_raises_on_invalid_window(self) -> None:
        with pytest.raises(ValueError, match="Unsafe value"):
            Q.render(Q.POD_RESTART_COUNT, namespace="ns", service="svc", window="5minutes")

    def test_raises_on_missing_placeholder(self) -> None:
        with pytest.raises(ValueError, match="Missing placeholder"):
            Q.render(Q.CPU_USAGE_RATIO, namespace="prod", window="5m")  # service missing

    def test_uppercase_letters_in_service_accepted(self) -> None:
        # k8s names are lowercase, but Prometheus labels may be mixed
        result = Q.render(Q.HTTP_ERROR_RATE_NGINX, namespace="prod", service="MyService", window="5m")
        assert "MyService" in result

    def test_hyphen_in_namespace_accepted(self) -> None:
        result = Q.render(Q.SERVICES_INFO, namespace="my-namespace")
        assert "my-namespace" in result

    def test_newlines_in_value_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unsafe value"):
            Q.render(Q.SERVICES_INFO, namespace="prod\nOR vector(1)")

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unsafe value"):
            Q.render(Q.SERVICES_INFO, namespace="")


# ---------------------------------------------------------------------------
# 4. Correlation with misaligned timestamps
# ---------------------------------------------------------------------------


class TestCorrelateLogsAndMetrics:
    """Tests for InfrastructureAnalyzer.correlate_logs_and_metrics."""

    def _make_anomaly(
        self,
        ts: float,
        service: str = "api",
        metric: str = "cpu_usage",
        z: float = 4.5,
    ) -> Anomaly:
        return Anomaly(
            metric=metric,
            service=service,
            namespace="prod",
            current_value=0.9,
            baseline_mean=0.3,
            baseline_std=0.05,
            z_score=z,
            severity=CheckStatus.CRITICAL,
            detected_at=datetime.fromtimestamp(ts, tz=timezone.utc),
        )

    async def _run_correlation(
        self,
        log_entries: list[LogEntry],
        anomalies: list[Anomaly],
        correlation_window: int = 300,
    ) -> CorrelationReport:
        grafana = _make_grafana()
        analyzer = InfrastructureAnalyzer(grafana)
        # Patch detect_anomalies to return our fixture anomalies
        async def _mock_detect(*_: Any, **__: Any) -> list[Anomaly]:
            return anomalies
        analyzer.detect_anomalies = _mock_detect  # type: ignore[method-assign]
        return await analyzer.correlate_logs_and_metrics(
            log_entries=log_entries,
            namespace="prod",
            correlation_window_seconds=correlation_window,
        )

    async def test_exact_timestamp_match(self) -> None:
        ts = time.time()
        logs = [_log_entry(ts)]
        anomalies = [self._make_anomaly(ts)]

        report = await self._run_correlation(logs, anomalies)

        assert len(report.correlated_events) == 1
        assert report.correlated_events[0].time_delta_seconds == pytest.approx(0.0, abs=0.1)
        assert report.correlated_events[0].correlation_confidence == pytest.approx(1.0, abs=0.01)

    async def test_within_window_correlated(self) -> None:
        """Log 3 minutes before anomaly — within the 5-minute window."""
        ts = time.time()
        logs = [_log_entry(ts - 180)]  # 3 min before
        anomalies = [self._make_anomaly(ts)]

        report = await self._run_correlation(logs, anomalies)
        assert len(report.correlated_events) == 1
        ev = report.correlated_events[0]
        assert ev.time_delta_seconds == pytest.approx(180.0, abs=1.0)
        # confidence = 1 - 180/300 = 0.4
        assert ev.correlation_confidence == pytest.approx(0.4, abs=0.01)

    async def test_outside_window_not_correlated(self) -> None:
        """Log 10 minutes before anomaly — outside the 5-minute window."""
        ts = time.time()
        logs = [_log_entry(ts - 600)]
        anomalies = [self._make_anomaly(ts)]

        report = await self._run_correlation(logs, anomalies)
        assert report.correlated_events == []
        assert report.uncorrelated_log_count == 1
        assert report.uncorrelated_anomaly_count == 1

    async def test_log_after_anomaly_correlated(self) -> None:
        """Log 2 minutes after anomaly is within the window."""
        ts = time.time()
        logs = [_log_entry(ts + 120)]
        anomalies = [self._make_anomaly(ts)]

        report = await self._run_correlation(logs, anomalies)
        assert len(report.correlated_events) == 1

    async def test_multiple_logs_best_match_selected(self) -> None:
        """Two logs near the same anomaly: both get correlated (one anomaly, one match each)."""
        ts = time.time()
        # Two separate logs at different distances from the anomaly
        logs = [
            _log_entry(ts - 60, message="error A"),
            _log_entry(ts - 240, message="error B"),
        ]
        anomalies = [self._make_anomaly(ts)]

        report = await self._run_correlation(logs, anomalies)
        # Each log independently matches the anomaly (no one-to-one exclusion)
        assert len(report.correlated_events) == 2

    async def test_non_error_logs_not_correlated(self) -> None:
        """Info-level logs should not be correlated."""
        ts = time.time()
        logs = [_log_entry(ts, level="info", message="all good")]
        anomalies = [self._make_anomaly(ts)]

        report = await self._run_correlation(logs, anomalies)
        assert report.correlated_events == []

    async def test_no_anomalies_produces_empty_correlation(self) -> None:
        ts = time.time()
        logs = [_log_entry(ts)]

        report = await self._run_correlation(logs, anomalies=[])
        assert report.correlated_events == []
        assert report.uncorrelated_anomaly_count == 0

    async def test_human_summary_present_and_non_empty(self) -> None:
        ts = time.time()
        logs = [_log_entry(ts)]
        anomalies = [self._make_anomaly(ts)]

        report = await self._run_correlation(logs, anomalies)
        assert len(report.human_summary) > 20

    async def test_human_summary_no_correlation(self) -> None:
        report = await self._run_correlation(
            logs=[_log_entry(time.time() - 3600)],
            anomalies=[self._make_anomaly(time.time())],
            correlation_window=1,  # 1 second window → no match
        )
        assert "No correlation" in report.human_summary or len(report.correlated_events) == 0

    async def test_correlation_window_respected(self) -> None:
        ts = time.time()
        logs = [_log_entry(ts - 100)]
        anomalies = [self._make_anomaly(ts)]

        # Narrow window of 50 seconds — 100s offset is outside
        report = await self._run_correlation(logs, anomalies, correlation_window=50)
        assert report.correlated_events == []

        # Wider window of 200 seconds — 100s offset is inside
        report2 = await self._run_correlation(logs, anomalies, correlation_window=200)
        assert len(report2.correlated_events) == 1


# ---------------------------------------------------------------------------
# 5. HealthReport human_summary generation
# ---------------------------------------------------------------------------


class TestHealthSummary:
    def _make_check(
        self,
        name: str,
        metric_type: str,
        value: float | None,
        status: CheckStatus,
        unit: str = "%",
    ) -> MetricCheck:
        return MetricCheck(
            name=name,
            metric_type=metric_type,
            current_value=value,
            threshold_warning=80.0,
            threshold_critical=95.0,
            status=status,
            unit=unit,
        )

    def test_all_ok_summary(self) -> None:
        checks = [
            self._make_check("CPU Usage", "cpu", 30.0, CheckStatus.OK),
            self._make_check("Memory Usage", "memory", 40.0, CheckStatus.OK),
        ]
        summary = InfrastructureAnalyzer._generate_health_summary(
            "api", "prod", 30, checks, CheckStatus.OK, []
        )
        assert "healthy" in summary.lower()
        assert "api" in summary

    def test_critical_check_in_summary(self) -> None:
        checks = [
            self._make_check("CPU Usage", "cpu", 97.0, CheckStatus.CRITICAL),
        ]
        summary = InfrastructureAnalyzer._generate_health_summary(
            "api", "prod", 30, checks, CheckStatus.CRITICAL, []
        )
        assert "CRITICAL" in summary or "critical" in summary.lower()
        assert "97.0" in summary

    def test_warning_check_in_summary(self) -> None:
        checks = [
            self._make_check("Memory Usage", "memory", 88.0, CheckStatus.WARNING),
        ]
        summary = InfrastructureAnalyzer._generate_health_summary(
            "worker", "staging", 15, checks, CheckStatus.WARNING, []
        )
        assert "WARNING" in summary or "warning" in summary.lower()
        assert "worker" in summary

    def test_summary_is_two_sentences(self) -> None:
        checks = [
            self._make_check("CPU Usage", "cpu", 99.0, CheckStatus.CRITICAL),
        ]
        summary = InfrastructureAnalyzer._generate_health_summary(
            "svc", "ns", 30, checks, CheckStatus.CRITICAL, []
        )
        # Two sentences → exactly two periods ending sentences (rough check)
        sentences = [s.strip() for s in summary.split(".") if s.strip()]
        assert len(sentences) >= 2


# ---------------------------------------------------------------------------
# 6. Agent tools registered in TOOL_REGISTRY
# ---------------------------------------------------------------------------


class TestInfraToolsRegistered:
    def test_discover_infra_registered(self) -> None:
        assert "discover_infra" in TOOL_REGISTRY

    def test_check_service_health_registered(self) -> None:
        assert "check_service_health" in TOOL_REGISTRY

    def test_detect_anomalies_in_namespace_registered(self) -> None:
        assert "detect_anomalies_in_namespace" in TOOL_REGISTRY

    def test_correlate_logs_metrics_registered(self) -> None:
        assert "correlate_logs_metrics" in TOOL_REGISTRY

    async def test_discover_infra_returns_topology_shape(self) -> None:
        grafana = _make_grafana()
        ctx = ToolContext(grafana=grafana)
        result = await TOOL_REGISTRY["discover_infra"](ctx, namespace="prod")
        assert "nodes" in result
        assert "edges" in result
        assert "namespace" in result

    async def test_check_service_health_returns_report_shape(self) -> None:
        grafana = _make_grafana()
        ctx = ToolContext(grafana=grafana)
        result = await TOOL_REGISTRY["check_service_health"](
            ctx, namespace="prod", service="api"
        )
        assert "overall_status" in result
        assert "checks" in result
        assert "human_summary" in result
        assert len(result["human_summary"]) > 10

    async def test_detect_anomalies_returns_list(self) -> None:
        grafana = _make_grafana()
        ctx = ToolContext(grafana=grafana)
        result = await TOOL_REGISTRY["detect_anomalies_in_namespace"](
            ctx, namespace="prod"
        )
        assert isinstance(result, list)

    async def test_correlate_logs_metrics_returns_report_shape(self) -> None:
        grafana = _make_grafana()
        ctx = ToolContext(grafana=grafana)
        result = await TOOL_REGISTRY["correlate_logs_metrics"](
            ctx, namespace="prod"
        )
        assert "correlated_events" in result
        assert "human_summary" in result
