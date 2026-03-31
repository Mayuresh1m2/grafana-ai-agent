"""Grafana tool registry for the agentic loop.

Each tool is defined in one place: a ``@tool`` decorator registers both the
JSON schema (used by the LLM) and the async handler (used by ``execute_tool``).
To add a new tool, write a single decorated coroutine — nothing else needs
to change.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.services.grafana import GrafanaClient

# ── Registry internals ────────────────────────────────────────────────────────

_Handler = Callable[[dict[str, Any], "GrafanaClient"], Awaitable[str]]
_registry: dict[str, tuple[dict, _Handler]] = {}


def tool(schema: dict) -> Callable[[_Handler], _Handler]:
    """Register a coroutine as a Grafana tool.

    The *schema* is the full Ollama-compatible function descriptor that will be
    forwarded to the LLM.  The decorated coroutine becomes the handler invoked
    by :func:`execute_tool`.
    """
    def decorator(fn: _Handler) -> _Handler:
        name: str = schema["function"]["name"]
        _registry[name] = (schema, fn)
        return fn
    return decorator


def get_tools() -> list[dict]:
    """Return all registered tool schemas (passed directly to the LLM)."""
    return [schema for schema, _ in _registry.values()]


async def execute_tool(name: str, args: dict[str, Any], client: "GrafanaClient") -> str:
    """Dispatch *name* to its registered handler and return the result string."""
    entry = _registry.get(name)
    if entry is None:
        return f"Unknown tool: {name}"
    _, handler = entry
    return await handler(args, client)


# ── Tool definitions ──────────────────────────────────────────────────────────

@tool({
    "type": "function",
    "function": {
        "name": "get_active_alerts",
        "description": "Fetch currently firing Grafana alerts. Call this first to understand what is broken.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
})
async def _get_active_alerts(args: dict[str, Any], client: "GrafanaClient") -> str:
    alerts = await client.get_active_alerts()
    if not alerts:
        return "No active alerts."
    return "\n".join(
        f"[{a.severity.upper()}] {a.name} — {a.state}" + (f": {a.summary}" if a.summary else "")
        for a in alerts
    )


@tool({
    "type": "function",
    "function": {
        "name": "list_datasources",
        "description": "List available Grafana datasources (Loki, Prometheus, etc.) and their UIDs.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
})
async def _list_datasources(args: dict[str, Any], client: "GrafanaClient") -> str:
    sources = client.get_datasources()
    if not sources:
        return "No datasources configured."
    return "\n".join(
        f"- {ds.name} (type={ds.type}, uid={ds.uid}{'  [default]' if ds.is_default else ''})"
        for ds in sources
    )


@tool({
    "type": "function",
    "function": {
        "name": "query_loki",
        "description": (
            "Run a LogQL query against Loki via the Grafana datasource proxy. "
            "Use to fetch logs for a service, pod, or namespace."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "logql": {
                    "type": "string",
                    "description": "LogQL expression, e.g. '{namespace=\"prod\",app=\"checkout\"} |= \"error\"'",
                },
                "datasource_uid": {
                    "type": "string",
                    "description": "UID of the Loki datasource (from the datasource list in your context). Required.",
                },
                "start": {
                    "type": "string",
                    "description": "Range start as Loki duration string (e.g. 'now-1h'). Default: now-1h.",
                },
                "end": {
                    "type": "string",
                    "description": "Range end. Default: now.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max log lines to return. Default: 50.",
                },
            },
            "required": ["logql", "datasource_uid"],
        },
    },
})
async def _query_loki(args: dict[str, Any], client: "GrafanaClient") -> str:
    logql          = str(args["logql"])
    datasource_uid = args.get("datasource_uid") or None
    start          = str(args.get("start", "now-1h"))
    end            = str(args.get("end", "now"))
    limit          = int(args.get("limit", 50))

    result = await client.query_loki(logql, start=start, end=end, limit=limit, datasource_uid=datasource_uid)
    lines: list[str] = [
        str(line)
        for stream in (result.get("data") or {}).get("result", [])
        for _ts, line in stream.get("values", [])
    ]
    if not lines:
        return "No logs found for this query."
    return "\n".join(lines[:limit])


@tool({
    "type": "function",
    "function": {
        "name": "query_prometheus",
        "description": (
            "Run a PromQL instant query against Prometheus via the Grafana datasource proxy. "
            "Use for current / point-in-time metric values. "
            "For trends over a time window use query_prometheus_range instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "promql": {
                    "type": "string",
                    "description": "PromQL expression, e.g. 'rate(http_requests_total{job=\"checkout\"}[5m])'",
                },
                "datasource_uid": {
                    "type": "string",
                    "description": "UID of the Prometheus datasource (from the datasource list in your context). Required.",
                },
                "time": {
                    "type": "string",
                    "description": (
                        "Evaluation timestamp as a relative string (e.g. 'now-30m') or Unix seconds. "
                        "Defaults to now when omitted."
                    ),
                },
            },
            "required": ["promql", "datasource_uid"],
        },
    },
})
async def _query_prometheus(args: dict[str, Any], client: "GrafanaClient") -> str:
    promql         = str(args["promql"])
    datasource_uid = args.get("datasource_uid") or None
    time_param     = args.get("time") or None

    result  = await client.query_prometheus(promql, time=time_param, datasource_uid=datasource_uid)
    results = (result.get("data") or {}).get("result", [])
    if not results:
        return "No data found for this PromQL query."

    lines: list[str] = []
    for r in results[:10]:
        metric    = r.get("metric", {})
        value     = (r.get("value") or [None, None])[1]
        label_str = ", ".join(f'{k}="{v}"' for k, v in metric.items())
        lines.append(f"{label_str}: {value}")
    return "\n".join(lines)


@tool({
    "type": "function",
    "function": {
        "name": "query_prometheus_range",
        "description": (
            "Run a PromQL range query against Prometheus via the Grafana datasource proxy. "
            "Use this to fetch metric trends over a time window (e.g. last hour of CPU usage, "
            "request rate over the past 30 minutes)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "promql": {
                    "type": "string",
                    "description": "PromQL expression, e.g. 'rate(http_requests_total{job=\"checkout\"}[5m])'",
                },
                "datasource_uid": {
                    "type": "string",
                    "description": "UID of the Prometheus datasource. Required.",
                },
                "start": {
                    "type": "string",
                    "description": "Range start as a relative string (e.g. 'now-1h') or Unix seconds. Default: now-1h.",
                },
                "end": {
                    "type": "string",
                    "description": "Range end as a relative string (e.g. 'now') or Unix seconds. Default: now.",
                },
                "step": {
                    "type": "string",
                    "description": "Resolution step, e.g. '60s', '5m'. Default: 60s.",
                },
            },
            "required": ["promql", "datasource_uid"],
        },
    },
})
async def _query_prometheus_range(args: dict[str, Any], client: "GrafanaClient") -> str:
    promql         = str(args["promql"])
    datasource_uid = args.get("datasource_uid") or None
    start          = str(args.get("start", "now-1h"))
    end            = str(args.get("end", "now"))
    step           = str(args.get("step", "60s"))

    result  = await client.query_prometheus_range(
        promql, start=start, end=end, step=step, datasource_uid=datasource_uid
    )
    results = (result.get("data") or {}).get("result", [])
    if not results:
        return "No data found for this PromQL range query."

    lines: list[str] = []
    for r in results[:5]:          # cap series returned to avoid flooding context
        metric    = r.get("metric", {})
        values    = r.get("values") or []
        label_str = ", ".join(f'{k}="{v}"' for k, v in metric.items()) or "(no labels)"
        # Summarise: first, last, and min/max values
        nums = [float(v) for _, v in values if v is not None]
        if nums:
            summary = f"min={min(nums):.3g} max={max(nums):.3g} last={nums[-1]:.3g} ({len(nums)} points)"
        else:
            summary = "(no values)"
        lines.append(f"{label_str}: {summary}")
    return "\n".join(lines)
