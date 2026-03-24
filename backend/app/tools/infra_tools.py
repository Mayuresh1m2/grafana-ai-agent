"""Infrastructure awareness and metrics analysis tools.

Provides ``InfrastructureAnalyzer`` — a high-level async interface over
Prometheus / Grafana that discovers topology, evaluates health thresholds,
detects statistical anomalies, and correlates log errors with metric spikes.

Four agent tools are registered via ``@agent_tool``:
  - ``discover_infra``
  - ``check_service_health``
  - ``detect_anomalies_in_namespace``
  - ``correlate_logs_metrics``
"""

from __future__ import annotations

import asyncio
import statistics
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog
from pydantic import BaseModel, Field

from app.agents.models import LogEntry
from app.agents.tools import TOOL_REGISTRY, ToolContext, agent_tool  # noqa: F401
from app.tools import promql_templates as Q
from src.services.grafana import GrafanaService

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CheckStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class MetricCheck(BaseModel):
    """Result of evaluating a single metric against its thresholds."""

    name: str
    metric_type: str
    current_value: float | None
    threshold_warning: float
    threshold_critical: float
    status: CheckStatus
    unit: str = ""
    details: str = ""


class Anomaly(BaseModel):
    """A metric value that deviates significantly from its 6-hour baseline."""

    metric: str
    service: str
    namespace: str
    current_value: float
    baseline_mean: float
    baseline_std: float
    z_score: float
    severity: CheckStatus
    detected_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


class HealthReport(BaseModel):
    """Aggregated health state for a single service."""

    service: str
    namespace: str
    window_minutes: int
    checks: list[MetricCheck]
    overall_status: CheckStatus
    anomalies: list[Anomaly]
    human_summary: str
    checked_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


class TopologyNode(BaseModel):
    """A service or deployment in the namespace."""

    name: str
    kind: str = "service"
    namespace: str
    replicas_current: int | None = None
    replicas_desired: int | None = None
    replicas_max_hpa: int | None = None
    cpu_limit: str = ""
    memory_limit: str = ""
    cpu_request: str = ""
    memory_request: str = ""


class TopologyEdge(BaseModel):
    """Inferred dependency edge between two services."""

    source: str
    target: str
    edge_type: str = "inferred"


class NamespaceTopology(BaseModel):
    """Complete namespace topology snapshot."""

    namespace: str
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]
    discovered_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


class CorrelatedEvent(BaseModel):
    """A log error entry aligned with a nearby metric anomaly."""

    log_timestamp: float
    log_message: str
    log_service: str
    anomaly_metric: str
    anomaly_service: str
    anomaly_z_score: float
    time_delta_seconds: float
    correlation_confidence: float = Field(ge=0.0, le=1.0)


class CorrelationReport(BaseModel):
    """Result of aligning log error spikes with metric anomalies."""

    namespace: str
    correlated_events: list[CorrelatedEvent]
    uncorrelated_log_count: int
    uncorrelated_anomaly_count: int
    correlation_window_seconds: int = 300
    human_summary: str


# ---------------------------------------------------------------------------
# Threshold evaluation helper
# ---------------------------------------------------------------------------


def evaluate_threshold(
    value: float | None,
    warning: float,
    critical: float,
    *,
    higher_is_worse: bool = True,
) -> CheckStatus:
    """Return the ``CheckStatus`` for *value* against *warning* and *critical*.

    When ``higher_is_worse=True`` (default) — exceeding *critical* → CRITICAL,
    exceeding *warning* → WARNING.  Invert for metrics where lower is worse
    (e.g. replica count dropping below minimum).
    """
    if value is None:
        return CheckStatus.OK  # no data — assume OK, surface as detail text

    if higher_is_worse:
        if value >= critical:
            return CheckStatus.CRITICAL
        if value >= warning:
            return CheckStatus.WARNING
        return CheckStatus.OK
    else:
        if value <= critical:
            return CheckStatus.CRITICAL
        if value <= warning:
            return CheckStatus.WARNING
        return CheckStatus.OK


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------


def _extract_scalar(prom_result: dict[str, Any]) -> float | None:
    """Pull the first scalar value from an instant Prometheus query result."""
    try:
        results = prom_result["data"]["result"]
        if not results:
            return None
        # instant query: each result is {"metric": {...}, "value": [ts, "val"]}
        return float(results[0]["value"][1])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _extract_series_values(prom_result: dict[str, Any]) -> list[float]:
    """Pull all numeric values from a range query result (all series merged)."""
    values: list[float] = []
    try:
        for series in prom_result["data"]["result"]:
            for _ts, val in series.get("values", []):
                try:
                    values.append(float(val))
                except ValueError:
                    pass
    except (KeyError, TypeError):
        pass
    return values


def _compute_z_score(baseline: list[float], current_values: list[float]) -> float:
    """Return the z-score of *current_values* mean against *baseline* statistics."""
    if not baseline or not current_values:
        return 0.0
    baseline_mean = statistics.mean(baseline)
    try:
        baseline_std = statistics.stdev(baseline)
    except statistics.StatisticsError:
        baseline_std = 0.0
    if baseline_std < 1e-10:
        return 0.0
    current_mean = statistics.mean(current_values)
    return (current_mean - baseline_mean) / baseline_std


# ---------------------------------------------------------------------------
# InfrastructureAnalyzer
# ---------------------------------------------------------------------------


class InfrastructureAnalyzer:
    """Async analysis layer over a ``GrafanaService`` instance."""

    def __init__(self, grafana: GrafanaService) -> None:
        self._g = grafana

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def discover_namespace_topology(
        self, namespace: str
    ) -> NamespaceTopology:
        """Query Prometheus for services, deployments, resources, and HPAs.

        Edges are inferred from Istio traffic metrics when available;
        otherwise the edge list is empty.
        """
        log = logger.bind(namespace=namespace)
        log.debug("topology_discovery_start")

        (
            svc_result,
            replicas_current,
            replicas_desired,
            cpu_limits,
            mem_limits,
            cpu_requests,
            mem_requests,
            hpa_max,
        ) = await asyncio.gather(
            self._safe_query(Q.render(Q.SERVICES_INFO, namespace=namespace)),
            self._safe_query(Q.render(Q.DEPLOYMENT_REPLICAS_CURRENT, namespace=namespace)),
            self._safe_query(Q.render(Q.DEPLOYMENT_REPLICAS_DESIRED, namespace=namespace)),
            self._safe_query(Q.render(Q.POD_CPU_LIMITS, namespace=namespace)),
            self._safe_query(Q.render(Q.POD_MEMORY_LIMITS, namespace=namespace)),
            self._safe_query(Q.render(Q.POD_CPU_REQUESTS, namespace=namespace)),
            self._safe_query(Q.render(Q.POD_MEMORY_REQUESTS, namespace=namespace)),
            self._safe_query(Q.render(Q.HPA_MAX_REPLICAS, namespace=namespace)),
        )

        # Index replicas by deployment name
        current_by_name = self._index_by_label(replicas_current, "deployment")
        desired_by_name = self._index_by_label(replicas_desired, "deployment")
        hpa_by_name = self._index_by_label(hpa_max, "horizontalpodautoscaler")
        cpu_limit_by_pod = self._index_by_label(cpu_limits, "pod")
        mem_limit_by_pod = self._index_by_label(mem_limits, "pod")
        cpu_req_by_pod = self._index_by_label(cpu_requests, "pod")
        mem_req_by_pod = self._index_by_label(mem_requests, "pod")

        nodes: list[TopologyNode] = []
        seen: set[str] = set()

        # Services from kube_service_info
        for series in (svc_result or {}).get("data", {}).get("result", []):
            metric = series.get("metric", {})
            name = metric.get("service", metric.get("name", ""))
            if not name or name in seen:
                continue
            seen.add(name)
            nodes.append(
                TopologyNode(name=name, kind="service", namespace=namespace)
            )

        # Deployments
        for dep_name, cur_val in current_by_name.items():
            if dep_name in seen:
                continue
            seen.add(dep_name)
            # Match pod resource entries by prefix
            pod_prefix = dep_name
            cpu_lim = next(
                (v for p, v in cpu_limit_by_pod.items() if p.startswith(pod_prefix)), ""
            )
            mem_lim = next(
                (v for p, v in mem_limit_by_pod.items() if p.startswith(pod_prefix)), ""
            )
            cpu_req = next(
                (v for p, v in cpu_req_by_pod.items() if p.startswith(pod_prefix)), ""
            )
            mem_req = next(
                (v for p, v in mem_req_by_pod.items() if p.startswith(pod_prefix)), ""
            )
            nodes.append(
                TopologyNode(
                    name=dep_name,
                    kind="deployment",
                    namespace=namespace,
                    replicas_current=int(float(cur_val)) if cur_val else None,
                    replicas_desired=int(float(desired_by_name.get(dep_name, 0))) or None,
                    replicas_max_hpa=int(float(hpa_by_name.get(dep_name, 0))) or None,
                    cpu_limit=cpu_lim,
                    memory_limit=mem_lim,
                    cpu_request=cpu_req,
                    memory_request=mem_req,
                )
            )

        edges = await self._infer_edges(namespace, [n.name for n in nodes])
        log.debug("topology_discovery_done", nodes=len(nodes), edges=len(edges))
        return NamespaceTopology(namespace=namespace, nodes=nodes, edges=edges)

    async def check_key_metrics(
        self,
        service: str,
        namespace: str,
        window_minutes: int = 30,
    ) -> HealthReport:
        """Evaluate CPU, memory, restarts, OOMKill, error rate, and latency."""
        log = logger.bind(service=service, namespace=namespace)
        log.debug("health_check_start")
        window = f"{window_minutes}m"

        (
            cpu_ratio,
            mem_ratio,
            restart_count,
            oom_count,
            error_rate_istio,
            error_rate_nginx,
            p99_istio,
            p99_custom,
            queue_depth,
        ) = await asyncio.gather(
            self._safe_query(Q.render(Q.CPU_USAGE_RATIO, namespace=namespace, service=service, window=window)),
            self._safe_query(Q.render(Q.MEMORY_USAGE_RATIO, namespace=namespace, service=service, window=window)),
            self._safe_query(Q.render(Q.POD_RESTART_COUNT, namespace=namespace, service=service, window=window)),
            self._safe_query(Q.render(Q.OOMKILL_EVENTS, namespace=namespace, service=service)),
            self._safe_query(Q.render(Q.HTTP_ERROR_RATE_ISTIO, namespace=namespace, service=service, window=window)),
            self._safe_query(Q.render(Q.HTTP_ERROR_RATE_NGINX, namespace=namespace, service=service, window=window)),
            self._safe_query(Q.render(Q.HTTP_P99_LATENCY_ISTIO, namespace=namespace, service=service, window=window)),
            self._safe_query(Q.render(Q.HTTP_P99_LATENCY_CUSTOM, namespace=namespace, service=service, window=window)),
            self._safe_query(Q.render(Q.REQUEST_QUEUE_DEPTH, namespace=namespace, service=service)),
        )

        checks: list[MetricCheck] = []

        # CPU
        cpu_val = _extract_scalar(cpu_ratio) if cpu_ratio else None
        checks.append(
            MetricCheck(
                name="CPU Usage",
                metric_type="cpu",
                current_value=round(cpu_val * 100, 1) if cpu_val is not None else None,
                threshold_warning=80.0,
                threshold_critical=95.0,
                status=evaluate_threshold(
                    cpu_val * 100 if cpu_val is not None else None,
                    warning=80.0,
                    critical=95.0,
                ),
                unit="%",
                details="CPU usage as % of container limit",
            )
        )

        # Memory
        mem_val = _extract_scalar(mem_ratio) if mem_ratio else None
        checks.append(
            MetricCheck(
                name="Memory Usage",
                metric_type="memory",
                current_value=round(mem_val * 100, 1) if mem_val is not None else None,
                threshold_warning=85.0,
                threshold_critical=95.0,
                status=evaluate_threshold(
                    mem_val * 100 if mem_val is not None else None,
                    warning=85.0,
                    critical=95.0,
                ),
                unit="%",
                details="Working set memory as % of container limit",
            )
        )

        # Pod restarts
        restart_val = _extract_scalar(restart_count) if restart_count else None
        checks.append(
            MetricCheck(
                name="Pod Restarts",
                metric_type="restarts",
                current_value=restart_val,
                threshold_warning=2.0,
                threshold_critical=5.0,
                status=evaluate_threshold(
                    restart_val, warning=2.0, critical=5.0
                ),
                unit="restarts",
                details=f"Restart count in last {window_minutes}m",
            )
        )

        # OOMKill
        oom_val = _extract_scalar(oom_count) if oom_count else None
        oom_status = (
            CheckStatus.CRITICAL if (oom_val is not None and oom_val > 0) else CheckStatus.OK
        )
        checks.append(
            MetricCheck(
                name="OOMKill Events",
                metric_type="oom",
                current_value=oom_val,
                threshold_warning=0.0,
                threshold_critical=0.0,
                status=oom_status,
                unit="events",
                details="Any OOMKill = CRITICAL",
            )
        )

        # Error rate — prefer Istio, fall back to nginx
        err_val = _extract_scalar(error_rate_istio) if error_rate_istio else None
        if err_val is None:
            err_val = _extract_scalar(error_rate_nginx) if error_rate_nginx else None
        checks.append(
            MetricCheck(
                name="HTTP Error Rate",
                metric_type="error_rate",
                current_value=round(err_val * 100, 3) if err_val is not None else None,
                threshold_warning=1.0,
                threshold_critical=5.0,
                status=evaluate_threshold(
                    err_val * 100 if err_val is not None else None,
                    warning=1.0,
                    critical=5.0,
                ),
                unit="%",
                details="5xx responses / total requests",
            )
        )

        # p99 latency — prefer Istio histogram, fall back to custom
        p99_val = _extract_scalar(p99_istio) if p99_istio else None
        if p99_val is None:
            p99_val = _extract_scalar(p99_custom) if p99_custom else None
        checks.append(
            MetricCheck(
                name="p99 Latency",
                metric_type="latency",
                current_value=round(p99_val, 1) if p99_val is not None else None,
                threshold_warning=500.0,
                threshold_critical=2000.0,
                status=evaluate_threshold(
                    p99_val, warning=500.0, critical=2000.0
                ),
                unit="ms",
                details="99th percentile request latency",
            )
        )

        # Queue depth (optional)
        queue_val = _extract_scalar(queue_depth) if queue_depth else None
        if queue_val is not None:
            checks.append(
                MetricCheck(
                    name="Request Queue Depth",
                    metric_type="queue_depth",
                    current_value=queue_val,
                    threshold_warning=100.0,
                    threshold_critical=500.0,
                    status=evaluate_threshold(
                        queue_val, warning=100.0, critical=500.0
                    ),
                    unit="requests",
                    details="Pending requests in ingress queue",
                )
            )

        overall = self._aggregate_status(checks)
        anomalies: list[Anomaly] = []  # populated by detect_anomalies if called separately
        human_summary = self._generate_health_summary(
            service, namespace, window_minutes, checks, overall, anomalies
        )

        log.debug("health_check_done", overall=overall.value)
        return HealthReport(
            service=service,
            namespace=namespace,
            window_minutes=window_minutes,
            checks=checks,
            overall_status=overall,
            anomalies=anomalies,
            human_summary=human_summary,
        )

    async def detect_anomalies(
        self,
        namespace: str,
        window_minutes: int = 60,
    ) -> list[Anomaly]:
        """Flag metrics whose current-window mean deviates > 3σ from baseline.

        Baseline: 6 hours prior to the current window.
        Method: z-score = (current_mean - baseline_mean) / baseline_std.
        """
        log = logger.bind(namespace=namespace, window_minutes=window_minutes)
        log.debug("anomaly_detection_start")

        now = time.time()
        window_sec = window_minutes * 60
        baseline_hours = 6
        total_sec = baseline_hours * 3600 + window_sec

        # Prometheus timestamps
        range_start = str(int(now - total_sec))
        range_end = str(int(now))
        step = "60s"
        window = f"{window_minutes}m"

        metric_queries = {
            "cpu_usage": Q.render(Q.CPU_USAGE_RATE_BY_SERVICE, namespace=namespace, window=window),
            "memory_usage": Q.render(Q.MEMORY_USAGE_BY_SERVICE, namespace=namespace, window=window),
            "error_rate": Q.render(Q.HTTP_ERROR_RATE_BY_SERVICE, namespace=namespace, window=window),
            "request_rate": Q.render(Q.REQUEST_RATE_BY_SERVICE, namespace=namespace, window=window),
        }

        results = await asyncio.gather(
            *[
                self._safe_range_query(q, range_start, range_end, step)
                for q in metric_queries.values()
            ]
        )

        split_ts = now - window_sec
        anomalies: list[Anomaly] = []

        for metric_name, raw in zip(metric_queries.keys(), results, strict=True):
            if raw is None:
                continue
            for series in raw.get("data", {}).get("result", []):
                svc = (
                    series.get("metric", {}).get("destination_service_name")
                    or series.get("metric", {}).get("pod", "unknown")
                )
                all_points: list[tuple[float, float]] = []
                for ts_str, val_str in series.get("values", []):
                    try:
                        all_points.append((float(ts_str), float(val_str)))
                    except ValueError:
                        continue

                baseline_vals = [v for ts, v in all_points if ts < split_ts]
                current_vals = [v for ts, v in all_points if ts >= split_ts]

                if not baseline_vals or not current_vals:
                    continue

                z = _compute_z_score(baseline_vals, current_vals)
                abs_z = abs(z)
                if abs_z < 3.0:
                    continue

                severity = CheckStatus.CRITICAL if abs_z >= 5.0 else CheckStatus.WARNING
                b_mean = statistics.mean(baseline_vals)
                b_std = statistics.stdev(baseline_vals) if len(baseline_vals) > 1 else 0.0
                c_mean = statistics.mean(current_vals)

                anomalies.append(
                    Anomaly(
                        metric=metric_name,
                        service=svc,
                        namespace=namespace,
                        current_value=round(c_mean, 4),
                        baseline_mean=round(b_mean, 4),
                        baseline_std=round(b_std, 4),
                        z_score=round(z, 2),
                        severity=severity,
                    )
                )

        log.debug("anomaly_detection_done", count=len(anomalies))
        return anomalies

    async def correlate_logs_and_metrics(
        self,
        log_entries: list[LogEntry],
        namespace: str,
        window_minutes: int = 60,
        correlation_window_seconds: int = 300,
    ) -> CorrelationReport:
        """Align log error spikes with metric anomalies by timestamp.

        Correlation window: ±``correlation_window_seconds`` (default ±5 min).
        Confidence is 1 - (|Δt| / correlation_window_seconds).
        """
        log = logger.bind(namespace=namespace)
        log.debug("correlation_start", log_count=len(log_entries))

        anomalies = await self.detect_anomalies(namespace, window_minutes)

        # Only correlate error-level log entries
        error_entries = [
            e
            for e in log_entries
            if e.level in ("error", "critical", "warn", "warning")
        ]

        correlated: list[CorrelatedEvent] = []
        matched_anomaly_indices: set[int] = set()

        for entry in error_entries:
            ts = entry.timestamp.timestamp()
            best: CorrelatedEvent | None = None
            best_delta = float("inf")

            for idx, anomaly in enumerate(anomalies):
                a_ts = anomaly.detected_at.timestamp()
                delta = abs(ts - a_ts)
                if delta <= correlation_window_seconds and delta < best_delta:
                    confidence = 1.0 - delta / correlation_window_seconds
                    best = CorrelatedEvent(
                        log_timestamp=ts,
                        log_message=entry.message[:200],
                        log_service=entry.service,
                        anomaly_metric=anomaly.metric,
                        anomaly_service=anomaly.service,
                        anomaly_z_score=anomaly.z_score,
                        time_delta_seconds=round(delta, 1),
                        correlation_confidence=round(confidence, 3),
                    )
                    best_delta = delta
                    matched_anomaly_indices.add(idx)

            if best is not None:
                correlated.append(best)

        uncorrelated_logs = len(error_entries) - len(correlated)
        uncorrelated_anomalies = len(anomalies) - len(matched_anomaly_indices)
        human_summary = self._generate_correlation_summary(
            namespace, correlated, uncorrelated_logs, uncorrelated_anomalies
        )

        log.debug(
            "correlation_done",
            correlated=len(correlated),
            uncorrelated_logs=uncorrelated_logs,
            uncorrelated_anomalies=uncorrelated_anomalies,
        )
        return CorrelationReport(
            namespace=namespace,
            correlated_events=correlated,
            uncorrelated_log_count=uncorrelated_logs,
            uncorrelated_anomaly_count=uncorrelated_anomalies,
            correlation_window_seconds=correlation_window_seconds,
            human_summary=human_summary,
        )

    # ------------------------------------------------------------------
    # Human-readable summary generators
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_health_summary(
        service: str,
        namespace: str,
        window_minutes: int,
        checks: list[MetricCheck],
        overall: CheckStatus,
        anomalies: list[Anomaly],
    ) -> str:
        failing = [c for c in checks if c.status != CheckStatus.OK]
        if not failing:
            return (
                f"The {service} service in namespace {namespace} is healthy "
                f"with all {len(checks)} checks passing in the last {window_minutes} minutes. "
                f"No threshold violations were detected."
            )

        critical = [c for c in failing if c.status == CheckStatus.CRITICAL]
        warnings = [c for c in failing if c.status == CheckStatus.WARNING]
        parts: list[str] = []
        if critical:
            names = ", ".join(c.name for c in critical[:3])
            parts.append(f"{len(critical)} critical issue(s) in {names}")
        if warnings:
            names = ", ".join(c.name for c in warnings[:3])
            parts.append(f"{len(warnings)} warning(s) in {names}")

        sentence1 = (
            f"The {service} service in namespace {namespace} is in "
            f"{overall.upper()} state with {' and '.join(parts)}."
        )

        top = (critical or warnings)[0]
        val_str = (
            f"{top.current_value:.1f}{top.unit}"
            if top.current_value is not None
            else "N/A"
        )
        threshold = (
            top.threshold_critical
            if top.status == CheckStatus.CRITICAL
            else top.threshold_warning
        )
        sentence2 = (
            f"{top.name} is at {val_str}, exceeding the "
            f"{'critical' if top.status == CheckStatus.CRITICAL else 'warning'} "
            f"threshold of {threshold:.1f}{top.unit}."
        )
        return f"{sentence1} {sentence2}"

    @staticmethod
    def _generate_correlation_summary(
        namespace: str,
        correlated: list[CorrelatedEvent],
        uncorrelated_logs: int,
        uncorrelated_anomalies: int,
    ) -> str:
        if not correlated:
            return (
                f"No correlation was found between log errors and metric anomalies "
                f"in namespace {namespace}. "
                f"{uncorrelated_logs} error log(s) and {uncorrelated_anomalies} anomaly(ies) "
                f"remain unexplained."
            )

        top = max(correlated, key=lambda e: e.correlation_confidence)
        sentence1 = (
            f"Found {len(correlated)} correlated event(s) in namespace {namespace}; "
            f"the strongest match links {top.log_service!r} log errors "
            f"to a {top.anomaly_metric} anomaly on {top.anomaly_service!r} "
            f"(Δt={top.time_delta_seconds:.0f}s, confidence={top.correlation_confidence:.0%})."
        )
        sentence2 = (
            f"{uncorrelated_logs} error log(s) and "
            f"{uncorrelated_anomalies} anomaly(ies) had no counterpart within the correlation window."
        )
        return f"{sentence1} {sentence2}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _safe_query(self, promql: str) -> dict[str, Any] | None:
        try:
            return await self._g.query_prometheus(promql=promql)
        except Exception as exc:  # noqa: BLE001
            logger.debug("prometheus_query_failed", promql=promql[:80], error=str(exc))
            return None

    async def _safe_range_query(
        self, promql: str, start: str, end: str, step: str
    ) -> dict[str, Any] | None:
        try:
            return await self._g.query_prometheus_range(
                promql=promql, start=start, end=end, step=step
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("prometheus_range_query_failed", promql=promql[:80], error=str(exc))
            return None

    @staticmethod
    def _index_by_label(
        result: dict[str, Any] | None, label: str
    ) -> dict[str, str]:
        """Return {label_value: scalar_value} from an instant query result."""
        out: dict[str, str] = {}
        if result is None:
            return out
        for series in result.get("data", {}).get("result", []):
            key = series.get("metric", {}).get(label, "")
            if key:
                try:
                    out[key] = series["value"][1]
                except (KeyError, IndexError):
                    pass
        return out

    async def _infer_edges(
        self, namespace: str, service_names: list[str]
    ) -> list[TopologyEdge]:
        """Attempt to infer service-to-service edges from Istio call metrics.

        Falls back to an empty list if Istio metrics are unavailable.
        """
        try:
            promql = (
                f'sum by (source_app, destination_service_name) ('
                f'rate(istio_requests_total{{namespace="{namespace}"}}[5m]))'
            )
            result = await self._g.query_prometheus(promql=promql)
            edges: list[TopologyEdge] = []
            for series in result.get("data", {}).get("result", []):
                src = series.get("metric", {}).get("source_app", "")
                dst = series.get("metric", {}).get("destination_service_name", "")
                if src and dst and src != dst:
                    edges.append(
                        TopologyEdge(source=src, target=dst, edge_type="istio")
                    )
            return edges
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _aggregate_status(checks: list[MetricCheck]) -> CheckStatus:
        """Return the worst status across all checks."""
        if any(c.status == CheckStatus.CRITICAL for c in checks):
            return CheckStatus.CRITICAL
        if any(c.status == CheckStatus.WARNING for c in checks):
            return CheckStatus.WARNING
        return CheckStatus.OK


# ---------------------------------------------------------------------------
# Agent tool registrations
# ---------------------------------------------------------------------------


@agent_tool
async def discover_infra(
    ctx: ToolContext,
    namespace: str,
    environment: str = "production",
) -> dict[str, Any]:
    """Discover all services, deployments, resource limits, and HPAs in a namespace.

    Args:
        namespace: Kubernetes namespace to inspect.
        environment: Human-readable environment label (e.g. "production", "staging").
            Used only for logging context — does not affect the query.

    Returns:
        Serialised ``NamespaceTopology`` dict with ``nodes``, ``edges``,
        and ``discovered_at``.
    """
    logger.info("discover_infra_tool", namespace=namespace, environment=environment)
    analyzer = InfrastructureAnalyzer(ctx.grafana)
    topology = await analyzer.discover_namespace_topology(namespace)
    return topology.model_dump(mode="json")


@agent_tool
async def check_service_health(
    ctx: ToolContext,
    namespace: str,
    service: str,
    window_minutes: int = 30,
) -> dict[str, Any]:
    """Evaluate CPU, memory, restarts, OOMKill, error rate, and latency for a service.

    Args:
        namespace: Kubernetes namespace.
        service: Service name as it appears in Prometheus labels.
        window_minutes: Evaluation window in minutes (default 30).

    Returns:
        Serialised ``HealthReport`` including ``overall_status``, per-check
        details, and a ``human_summary`` ready for inclusion in an LLM response.
    """
    analyzer = InfrastructureAnalyzer(ctx.grafana)
    report = await analyzer.check_key_metrics(
        service=service, namespace=namespace, window_minutes=window_minutes
    )
    return report.model_dump(mode="json")


@agent_tool
async def detect_anomalies_in_namespace(
    ctx: ToolContext,
    namespace: str,
    window_minutes: int = 60,
) -> list[dict[str, Any]]:
    """Detect metrics that deviate more than 3σ from their 6-hour baseline.

    Args:
        namespace: Kubernetes namespace to scan.
        window_minutes: Current-window length in minutes (default 60).
            Anomalies are detected in this window relative to the prior 6 hours.

    Returns:
        List of ``Anomaly`` dicts, each with ``metric``, ``service``,
        ``z_score``, ``severity``, and baseline statistics.
    """
    analyzer = InfrastructureAnalyzer(ctx.grafana)
    anomalies = await analyzer.detect_anomalies(
        namespace=namespace, window_minutes=window_minutes
    )
    return [a.model_dump(mode="json") for a in anomalies]


@agent_tool
async def correlate_logs_metrics(
    ctx: ToolContext,
    namespace: str,
    service: str = "",
    window_minutes: int = 60,
) -> dict[str, Any]:
    """Fetch error logs and correlate them with metric anomalies by timestamp.

    Fetches recent logs for ``service`` (all services if empty), detects
    anomalies in the namespace, and aligns them within a ±5-minute window.

    Args:
        namespace: Kubernetes namespace.
        service: Optional service name to restrict log fetching.
        window_minutes: Analysis window in minutes (default 60).

    Returns:
        Serialised ``CorrelationReport`` with ``correlated_events``,
        uncorrelated counts, and a ``human_summary``.
    """
    # Fetch error logs for the service (or all services)
    logql = (
        f'{{service="{service}"}} |= "error"'
        if service
        else f'{{namespace="{namespace}"}} |= "error"'
    )
    try:
        raw = await ctx.grafana.query_loki(
            logql=logql, start=f"now-{window_minutes}m", limit=500
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("correlate_logs_fetch_failed", error=str(exc))
        raw = {}

    # Parse log entries
    log_entries: list[LogEntry] = []
    for stream in raw.get("data", {}).get("result", []):
        labels: dict[str, str] = stream.get("stream", {})
        svc = labels.get("service", labels.get("app", service or "unknown"))
        for ts_ns, line in stream.get("values", []):
            try:
                log_entries.append(
                    LogEntry(
                        timestamp=datetime.fromtimestamp(
                            int(ts_ns) / 1e9, tz=timezone.utc
                        ),
                        level="error",
                        service=svc,
                        message=line,
                        labels=labels,
                    )
                )
            except Exception:  # noqa: BLE001
                continue

    analyzer = InfrastructureAnalyzer(ctx.grafana)
    report = await analyzer.correlate_logs_and_metrics(
        log_entries=log_entries,
        namespace=namespace,
        window_minutes=window_minutes,
    )
    return report.model_dump(mode="json")
