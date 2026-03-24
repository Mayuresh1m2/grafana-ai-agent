"""On-call agent package — models and tool registry."""

from app.agents.models import (
    LogEntry,
    LogPatternSummary,
    ServiceEdge,
    ServiceGraph,
    ToolExecutionError,
)
from app.agents.tools import (
    TOOL_REGISTRY,
    ToolContext,
    agent_tool,
    get_tool_specs,
)

__all__ = [
    # models
    "LogEntry",
    "LogPatternSummary",
    "ServiceEdge",
    "ServiceGraph",
    "ToolExecutionError",
    # tools
    "TOOL_REGISTRY",
    "ToolContext",
    "agent_tool",
    "get_tool_specs",
]
