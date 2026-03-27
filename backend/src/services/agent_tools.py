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
        "description": "Run a PromQL instant query against Prometheus via the Grafana datasource proxy.",
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
            },
            "required": ["promql", "datasource_uid"],
        },
    },
})
async def _query_prometheus(args: dict[str, Any], client: "GrafanaClient") -> str:
    promql         = str(args["promql"])
    datasource_uid = args.get("datasource_uid") or None

    result  = await client.query_prometheus(promql, datasource_uid=datasource_uid)
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
