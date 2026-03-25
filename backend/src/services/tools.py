"""Tool definitions and execution for the ReAct agent loop."""
from __future__ import annotations

import ast
import re
from typing import Any

from src.services.grafana import GrafanaClient

TOOL_DEFINITIONS = """\
You have access to the following tools to query real-time Grafana data.

TOOLS:
  query_loki(logql, start="now-1h", end="now", limit=50)
    Execute a LogQL range query. logql is required.
    Example: query_loki(logql='{app="my-service"} |= "error"', start="now-30m")

  query_prometheus(promql, time=None)
    Execute a PromQL instant query. promql is required.
    Example: query_prometheus(promql='rate(http_requests_total{job="api"}[5m])')

  query_prometheus_range(promql, start="now-1h", end="now", step="60s")
    Execute a PromQL range query. promql is required.
    Example: query_prometheus_range(promql='up', start="now-1h", end="now")

  get_loki_label_values(label_name, selector=None, start="now-6h", end="now")
    Get all values for a Loki label (discover service names, namespaces, etc.)
    Example: get_loki_label_values(label_name="app")

  get_active_alerts()
    Return currently firing Grafana alerts. No arguments.

RESPONSE FORMAT:
To call a tool, output ONLY:
Thought: <your reasoning about what to look up>
Action: tool_name(arg1="value1", arg2="value2")

After you receive an Observation, continue reasoning or give your final answer:
Thought: <final reasoning>
Answer: <your complete markdown response>
SUGGESTIONS: ["follow-up 1?", "follow-up 2?", "follow-up 3?"]

Rules:
- Always include Thought: before Action: or Answer:
- In Action lines, always use keyword arguments with quoted string values
- The Answer section is your final response to the user — write it in clear markdown
- Always append SUGGESTIONS on its own line after Answer
"""


def parse_action(text: str) -> tuple[str, dict[str, Any]] | None:
    """Extract (tool_name, kwargs) from an Action: line, or None if absent."""
    match = re.search(r"\bAction:\s*(\w+)\(([^)]*)\)", text, re.DOTALL)
    if not match:
        return None

    tool_name = match.group(1).strip()
    args_str = match.group(2).strip()

    if not args_str:
        return tool_name, {}

    # Parse kwargs safely via ast
    try:
        tree = ast.parse(f"_({args_str})", mode="eval")
        call = tree.body  # type: ignore[attr-defined]
        kwargs: dict[str, Any] = {
            kw.arg: ast.literal_eval(kw.value)
            for kw in call.keywords
            if kw.arg is not None
        }
        return tool_name, kwargs
    except (SyntaxError, ValueError):
        return None


async def execute_tool(
    client: GrafanaClient,
    tool_name: str,
    kwargs: dict[str, Any],
) -> str:
    """Dispatch tool call to GrafanaClient and return a human-readable observation."""
    if tool_name == "query_loki":
        result = await client.query_loki(
            logql=str(kwargs.get("logql", "")),
            start=str(kwargs.get("start", "now-1h")),
            end=str(kwargs.get("end", "now")),
            limit=int(kwargs.get("limit", 50)),
        )
        return _fmt_loki(result)

    if tool_name == "query_prometheus":
        result = await client.query_prometheus(
            promql=str(kwargs.get("promql", "")),
            time=kwargs.get("time"),
        )
        return _fmt_prometheus(result)

    if tool_name == "query_prometheus_range":
        result = await client.query_prometheus_range(
            promql=str(kwargs.get("promql", "")),
            start=str(kwargs.get("start", "now-1h")),
            end=str(kwargs.get("end", "now")),
            step=str(kwargs.get("step", "60s")),
        )
        return _fmt_prometheus_range(result)

    if tool_name == "get_loki_label_values":
        values = await client.get_loki_label_values(
            label_name=str(kwargs.get("label_name", "")),
            selector=kwargs.get("selector"),
            start=str(kwargs.get("start", "now-6h")),
            end=str(kwargs.get("end", "now")),
        )
        return _fmt_label_values(str(kwargs.get("label_name", "")), values)

    if tool_name == "get_active_alerts":
        alerts = await client.get_active_alerts()
        return _fmt_alerts(alerts)

    return f"Unknown tool: {tool_name!r}. Available: query_loki, query_prometheus, query_prometheus_range, get_loki_label_values, get_active_alerts"


# ── Result formatters ──────────────────────────────────────────────────────────

def _fmt_loki(data: dict[str, Any]) -> str:
    try:
        result = data.get("data", {}).get("result", [])
        if not result:
            return "No log entries found."

        lines: list[tuple[int, str]] = []
        for stream in result:
            labels = stream.get("stream", {})
            label_str = " ".join(f'{k}="{v}"' for k, v in labels.items())
            for ts_ns, line in stream.get("values", []):
                try:
                    ts_s = int(ts_ns) // 1_000_000_000
                except (ValueError, TypeError):
                    ts_s = 0
                lines.append((ts_s, f"[{label_str}] {line}"))

        lines.sort(key=lambda x: x[0])
        total = len(lines)
        shown = lines[-100:]
        formatted = "\n".join(ln for _, ln in shown)
        prefix = f"{total} log lines" + (" (showing last 100)" if total > 100 else "") + ":\n"
        return prefix + formatted
    except Exception as exc:
        return f"Error parsing Loki response: {exc}\nRaw (truncated): {str(data)[:400]}"


def _fmt_prometheus(data: dict[str, Any]) -> str:
    try:
        result = data.get("data", {}).get("result", [])
        if not result:
            return "No metrics found."

        lines = []
        for item in result:
            metric = item.get("metric", {})
            _ts, val = item.get("value", [None, "N/A"])
            label_str = ", ".join(f'{k}="{v}"' for k, v in metric.items()) or "(no labels)"
            lines.append(f"  {label_str}: {val}")

        return f"{len(result)} series:\n" + "\n".join(lines[:40])
    except Exception as exc:
        return f"Error parsing Prometheus response: {exc}\nRaw (truncated): {str(data)[:400]}"


def _fmt_prometheus_range(data: dict[str, Any]) -> str:
    try:
        result = data.get("data", {}).get("result", [])
        if not result:
            return "No metric data found."

        lines = []
        for item in result:
            metric = item.get("metric", {})
            values = item.get("values", [])
            label_str = ", ".join(f'{k}="{v}"' for k, v in metric.items()) or "(no labels)"
            nums = []
            for _ts, v in values:
                try:
                    nums.append(float(v))
                except (ValueError, TypeError):
                    pass
            if nums:
                lines.append(
                    f"  {label_str}: min={min(nums):.4g}, max={max(nums):.4g},"
                    f" last={nums[-1]:.4g} ({len(values)} pts)"
                )
            else:
                lines.append(f"  {label_str}: {len(values)} points (all NaN/Inf)")

        return f"{len(result)} series:\n" + "\n".join(lines[:30])
    except Exception as exc:
        return f"Error parsing Prometheus range response: {exc}\nRaw (truncated): {str(data)[:400]}"


def _fmt_label_values(label_name: str, values: list[str]) -> str:
    if not values:
        return f"No values found for label '{label_name}'."
    shown = values[:60]
    suffix = f" (showing {len(shown)} of {len(values)})" if len(values) > 60 else ""
    return f"Values for label '{label_name}' ({len(values)} total{suffix}):\n" + ", ".join(shown)


def _fmt_alerts(alerts: list[Any]) -> str:
    if not alerts:
        return "No active alerts."
    lines = []
    for a in alerts:
        summary = f": {a.summary}" if getattr(a, "summary", "") else ""
        lines.append(f"  [{a.severity.upper()}] {a.name} ({a.state}){summary}")
    return f"{len(alerts)} active alert(s):\n" + "\n".join(lines)
