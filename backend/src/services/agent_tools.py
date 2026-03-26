"""Grafana tool definitions and executor for the agentic loop."""
from __future__ import annotations
import json
from typing import Any
from src.services.grafana import GrafanaClient

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_active_alerts",
            "description": "Fetch currently firing Grafana alerts. Call this first to understand what is broken.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_datasources",
            "description": "List available Grafana datasources (Loki, Prometheus, etc.) and their UIDs.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_loki",
            "description": "Run a LogQL query against Loki via the Grafana datasource proxy. Use to fetch logs for a service, pod, or namespace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "logql":          {"type": "string",  "description": "LogQL expression, e.g. '{namespace=\"prod\",app=\"checkout\"} |= \"error\"'"},
                    "datasource_uid": {"type": "string",  "description": "UID of the Loki datasource (from the datasource list in your context). Required."},
                    "start":          {"type": "string",  "description": "Range start as Loki duration string (e.g. 'now-1h'). Default: now-1h."},
                    "end":            {"type": "string",  "description": "Range end. Default: now."},
                    "limit":          {"type": "integer", "description": "Max log lines to return. Default: 50."},
                },
                "required": ["logql", "datasource_uid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_prometheus",
            "description": "Run a PromQL instant query against Prometheus via the Grafana datasource proxy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "promql":         {"type": "string", "description": "PromQL expression, e.g. 'rate(http_requests_total{job=\"checkout\"}[5m])'"},
                    "datasource_uid": {"type": "string", "description": "UID of the Prometheus datasource (from the datasource list in your context). Required."},
                },
                "required": ["promql", "datasource_uid"],
            },
        },
    },
]


async def execute_tool(name: str, args: dict[str, Any], client: GrafanaClient) -> str:
    """Execute a named tool call and return the result as a plain string."""
    if name == "get_active_alerts":
        alerts = await client.get_active_alerts()
        if not alerts:
            return "No active alerts."
        return "\n".join(
            f"[{a.severity.upper()}] {a.name} — {a.state}" + (f": {a.summary}" if a.summary else "")
            for a in alerts
        )

    if name == "list_datasources":
        sources = client.get_datasources()
        if not sources:
            return "No datasources configured."
        return "\n".join(
            f"- {ds.name} (type={ds.type}, uid={ds.uid}{'  [default]' if ds.is_default else ''})"
            for ds in sources
        )

    if name == "query_loki":
        logql          = str(args["logql"])
        datasource_uid = args.get("datasource_uid") or None
        start          = str(args.get("start", "now-1h"))
        end            = str(args.get("end", "now"))
        limit          = int(args.get("limit", 50))
        result = await client.query_loki(logql, start=start, end=end, limit=limit, datasource_uid=datasource_uid)
        lines: list[str] = []
        for stream in (result.get("data") or {}).get("result", []):
            for _ts, line in stream.get("values", []):
                lines.append(str(line))
        if not lines:
            return "No logs found for this query."
        return "\n".join(lines[:limit])

    if name == "query_prometheus":
        promql         = str(args["promql"])
        datasource_uid = args.get("datasource_uid") or None
        result = await client.query_prometheus(promql, datasource_uid=datasource_uid)
        results = (result.get("data") or {}).get("result", [])
        if not results:
            return "No data found for this PromQL query."
        lines2: list[str] = []
        for r in results[:10]:
            metric = r.get("metric", {})
            value  = (r.get("value") or [None, None])[1]
            label_str = ", ".join(f'{k}="{v}"' for k, v in metric.items())
            lines2.append(f"{label_str}: {value}")
        return "\n".join(lines2)

    return f"Unknown tool: {name}"
