"""Agent tool registry with @agent_tool decorator and OpenAI-compatible spec export.

Each tool is a plain ``async def`` decorated with ``@agent_tool``.  The
decorator:
  - Extracts the one-line summary from the first line of the docstring.
  - Builds a JSON schema from ``inspect.signature`` + ``get_type_hints``.
  - Wraps the function with structured timing / structlog logging.
  - Registers the wrapped callable in ``TOOL_REGISTRY``.

The full OpenAI-compatible tool-spec list is available via ``get_tool_specs()``.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, get_type_hints

import structlog

from app.agents.models import (
    LogPatternSummary,  # noqa: F401 — re-exported for callers
    ServiceGraph,  # noqa: F401 — re-exported for callers
    ToolExecutionError,  # noqa: F401 — re-exported for callers
)
from src.services.grafana import GrafanaService

_KNOWN_LEVELS = frozenset({"debug", "info", "warn", "warning", "error", "critical"})

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# ToolContext — dependency bundle passed to every tool call
# ---------------------------------------------------------------------------


@dataclass
class ToolContext:
    """Runtime context injected into every tool invocation."""

    grafana: GrafanaService
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal registry
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, Callable[..., Coroutine[Any, Any, Any]]] = {}
_TOOL_SPECS: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# JSON-type mapping
# ---------------------------------------------------------------------------

_PY_TO_JSON: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _python_type_to_json_type(annotation: Any) -> str:
    origin = getattr(annotation, "__origin__", None)
    if origin is list:
        return "array"
    if origin is dict:
        return "object"
    return _PY_TO_JSON.get(annotation, "string")


def _build_parameters_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """Build a JSON Schema *parameters* object from a function's signature.

    The first parameter (``ctx: ToolContext``) is excluded — it is injected
    by the agent runner, not provided by the LLM.
    """
    sig = inspect.signature(func)
    hints = get_type_hints(func)
    properties: dict[str, Any] = {}
    required: list[str] = []

    params = list(sig.parameters.items())
    # Skip 'ctx' (first param) and 'return'
    for name, param in params[1:]:
        annotation = hints.get(name, str)
        json_type = _python_type_to_json_type(annotation)
        prop: dict[str, Any] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(name)
        properties[name] = prop

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


def _parse_description(func: Callable[..., Any]) -> str:
    """Return the first non-blank line of the docstring."""
    doc = inspect.getdoc(func) or ""
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return line
    return func.__name__


# ---------------------------------------------------------------------------
# @agent_tool decorator
# ---------------------------------------------------------------------------


def agent_tool(
    func: Callable[..., Coroutine[Any, Any, Any]],
) -> Callable[..., Coroutine[Any, Any, Any]]:
    """Decorator that registers an async tool and wraps it with timing/logging.

    Usage::

        @agent_tool
        async def my_tool(ctx: ToolContext, arg: str) -> dict[str, object]:
            \"\"\"Short description used in the OpenAI tool spec.\"\"\"
            ...
    """
    name = func.__name__
    description = _parse_description(func)
    parameters = _build_parameters_schema(func)

    # OpenAI-compatible spec entry
    spec: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }
    _TOOL_SPECS.append(spec)

    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        log = logger.bind(tool=name)
        log.info("tool_call_start", kwargs=list(kwargs.keys()))
        t0 = time.monotonic()
        try:
            result = await func(*args, **kwargs)
            elapsed = time.monotonic() - t0
            log.info("tool_call_done", elapsed_ms=round(elapsed * 1000, 1))
            return result
        except Exception as exc:
            elapsed = time.monotonic() - t0
            log.error(
                "tool_call_error",
                error=str(exc),
                elapsed_ms=round(elapsed * 1000, 1),
            )
            raise

    wrapper.__name__ = name
    wrapper.__doc__ = func.__doc__
    TOOL_REGISTRY[name] = wrapper
    return wrapper


def get_tool_specs() -> list[dict[str, Any]]:
    """Return the OpenAI-compatible tool spec list (snapshot at call time)."""
    return list(_TOOL_SPECS)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


@agent_tool
async def query_loki_logs(
    ctx: ToolContext,
    logql: str,
    start: str = "now-1h",
    end: str = "now",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Query Loki logs using a LogQL expression and return structured log entries.

    Args:
        logql: LogQL stream selector + optional filter pipeline, e.g.
               ``'{service="api"} |= "error"'``.
        start: Range start as a Loki duration (e.g. ``"now-1h"``) or RFC3339.
        end: Range end.
        limit: Maximum number of log lines to return (default 100).

    Returns:
        List of raw log entry dicts with keys ``timestamp``, ``message``,
        ``labels``, ``level``.
    """
    raw = await ctx.grafana.query_loki(logql=logql, start=start, end=end, limit=limit)
    results = raw.get("data", {})
    streams = results.get("result", []) if isinstance(results, dict) else []

    entries: list[dict[str, Any]] = []
    for stream in streams:
        labels: dict[str, str] = stream.get("stream", {})
        service = labels.get("service", labels.get("app", ""))
        for ts_ns, line in stream.get("values", []):
            # Loki timestamps are nanosecond Unix strings
            ts_sec = int(ts_ns) / 1e9
            level_raw = labels.get("level", "unknown").lower()
            level = level_raw if level_raw in _KNOWN_LEVELS else "unknown"
            entries.append(
                {
                    "timestamp": ts_sec,
                    "message": line,
                    "labels": labels,
                    "service": service,
                    "level": level,
                }
            )

    return entries


@agent_tool
async def get_service_list(
    ctx: ToolContext,
    start: str = "now-6h",
    end: str = "now",
) -> list[str]:
    """Return the list of services currently emitting logs to Loki.

    Args:
        start: Look-back window start (Loki duration or RFC3339).
        end: Look-back window end.

    Returns:
        Sorted list of unique service name strings.
    """
    services = await ctx.grafana.get_loki_label_values(
        label_name="service", start=start, end=end
    )
    # Also try "app" label as fallback
    if not services:
        services = await ctx.grafana.get_loki_label_values(
            label_name="app", start=start, end=end
        )
    return sorted(set(services))


@agent_tool
async def analyze_log_pattern(
    ctx: ToolContext,
    service: str,
    start: str = "now-1h",
    end: str = "now",
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Analyse recurring log patterns for a given service and return a summary.

    Fetches error-level logs for ``service``, clusters repeated messages by
    their first 120 characters, and returns a ranked summary.

    Args:
        service: Service name as it appears in the Loki ``service`` label.
        start: Range start.
        end: Range end.
        limit: Maximum raw log lines to fetch before clustering.

    Returns:
        List of pattern-summary dicts sorted by count descending.
    """
    logql = f'{{service="{service}"}} |= "error"'
    raw = await ctx.grafana.query_loki(logql=logql, start=start, end=end, limit=limit)
    results = raw.get("data", {})
    streams = results.get("result", []) if isinstance(results, dict) else []

    pattern_counts: dict[str, dict[str, Any]] = {}
    for stream in streams:
        for ts_ns, line in stream.get("values", []):
            key = line[:120]
            if key not in pattern_counts:
                pattern_counts[key] = {
                    "pattern": key,
                    "count": 0,
                    "first_ts": int(ts_ns),
                    "last_ts": int(ts_ns),
                    "example": line,
                }
            entry = pattern_counts[key]
            entry["count"] += 1
            entry["first_ts"] = min(entry["first_ts"], int(ts_ns))
            entry["last_ts"] = max(entry["last_ts"], int(ts_ns))

    summaries = sorted(
        pattern_counts.values(), key=lambda x: x["count"], reverse=True
    )
    # Normalise timestamps to seconds
    for s in summaries:
        s["first_seen"] = s.pop("first_ts") / 1e9
        s["last_seen"] = s.pop("last_ts") / 1e9

    return summaries


@agent_tool
async def query_metric(
    ctx: ToolContext,
    promql: str,
    time: str | None = None,
) -> dict[str, Any]:
    """Execute an instant PromQL query and return the raw Prometheus result.

    Args:
        promql: PromQL expression, e.g.
                ``'rate(http_requests_total{service="api"}[5m])'``.
        time: Optional evaluation timestamp (RFC3339 or Unix). Defaults to now.

    Returns:
        Raw Prometheus API response dict with ``status``, ``data.resultType``,
        and ``data.result``.
    """
    return await ctx.grafana.query_prometheus(promql=promql, time=time)


@agent_tool
async def get_service_dependencies(
    ctx: ToolContext,
    service: str,
    window: str = "5m",
) -> dict[str, Any]:
    """Derive upstream and downstream service dependencies from Prometheus metrics.

    Uses the ``traces_spanmetrics_calls_total`` metric (Tempo span metrics) if
    available, otherwise falls back to ``http_requests_total`` with ``upstream``
    / ``downstream`` labels.

    Args:
        service: Target service name.
        window: PromQL rate window (e.g. ``"5m"``).

    Returns:
        Dict with ``upstream`` and ``downstream`` lists plus a partial
        ``ServiceGraph`` payload.
    """
    span_promql = (
        f'sum by (service, span_name) ('
        f'rate(traces_spanmetrics_calls_total{{service="{service}"}}[{window}])'
        f')'
    )
    fallback_promql = (
        f'sum by (upstream) ('
        f'rate(http_requests_total{{service="{service}"}}[{window}])'
        f')'
    )

    upstreams: list[str] = []
    downstreams: list[str] = []

    try:
        result = await ctx.grafana.query_prometheus(promql=span_promql)
        data = result.get("data", {})
        for series in data.get("result", []):
            metric = series.get("metric", {})
            related = metric.get("peer_service", metric.get("upstream", ""))
            if related and related != service:
                upstreams.append(related)
    except Exception:  # noqa: BLE001
        # Try fallback metric
        try:
            result = await ctx.grafana.query_prometheus(promql=fallback_promql)
            data = result.get("data", {})
            for series in data.get("result", []):
                metric = series.get("metric", {})
                upstream = metric.get("upstream", "")
                if upstream:
                    upstreams.append(upstream)
        except Exception:  # noqa: BLE001
            pass

    all_services = list({service, *upstreams, *downstreams})
    edges = [
        {"source": u, "target": service, "call_count": 0, "error_rate": 0.0}
        for u in upstreams
    ] + [
        {"source": service, "target": d, "call_count": 0, "error_rate": 0.0}
        for d in downstreams
    ]

    return {
        "service": service,
        "upstream": upstreams,
        "downstream": downstreams,
        "graph": {"services": all_services, "edges": edges},
    }


@agent_tool
async def search_related_logs(
    ctx: ToolContext,
    keyword: str,
    service: str = "",
    start: str = "now-1h",
    end: str = "now",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search Loki for log lines containing ``keyword``, optionally scoped to a service.

    Args:
        keyword: Substring to search for (passed to ``|=`` filter).
        service: Optional service label to narrow the stream selector.
        start: Range start.
        end: Range end.
        limit: Maximum log lines to return.

    Returns:
        List of matching log entry dicts.
    """
    if service:
        logql = f'{{service="{service}"}} |= "{keyword}"'
    else:
        logql = f'{{job=~".+"}} |= "{keyword}"'

    raw = await ctx.grafana.query_loki(logql=logql, start=start, end=end, limit=limit)
    results = raw.get("data", {})
    streams = results.get("result", []) if isinstance(results, dict) else []

    entries: list[dict[str, Any]] = []
    for stream in streams:
        labels: dict[str, str] = stream.get("stream", {})
        svc = labels.get("service", labels.get("app", ""))
        for ts_ns, line in stream.get("values", []):
            entries.append(
                {
                    "timestamp": int(ts_ns) / 1e9,
                    "service": svc,
                    "message": line,
                    "labels": labels,
                }
            )

    return entries


# ---------------------------------------------------------------------------
# Emit tool names to log at module-import time (useful for diagnostics)
# ---------------------------------------------------------------------------

logger.info(
    "agent_tool_registry_loaded",
    tools=[s["function"]["name"] for s in _TOOL_SPECS],
)
