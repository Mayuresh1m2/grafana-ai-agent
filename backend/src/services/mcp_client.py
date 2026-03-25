"""Grafana MCP server client.

Wraps the official ``grafana/mcp-grafana`` MCP server.  Supports two transports:

* **SSE** (preferred for a long-running server): set ``GRAFANA_MCP_URL`` to the
  server's ``/sse`` endpoint, e.g. ``http://localhost:8888/sse``.
* **stdio** (spawns the binary per query): set ``GRAFANA_MCP_COMMAND`` to the
  binary name/path, e.g. ``mcp-grafana`` or ``npx @grafana/mcp-grafana``.
  The binary must be accessible in ``$PATH`` or given as an absolute path.
  Install options:
    - Go:  ``go install github.com/grafana/mcp-grafana/cmd/mcp-grafana@latest``
    - npm: ``npm install -g @grafana/mcp-grafana``

Usage (async context manager — one instance per agent query)::

    async with GrafanaMCPSession(grafana_url, api_token, settings) as mcp:
        tool_defs = mcp.tool_definitions()  # text for LLM system prompt
        result = await mcp.call_tool("query_prometheus", {"expr": "up"})
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

import structlog

from src.config import Settings

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


def _tool_schema_to_text(tool: object) -> str:
    """Format an MCP Tool object into a concise text description for the LLM."""
    name = getattr(tool, "name", "unknown")
    desc = (getattr(tool, "description", "") or "").strip()
    schema = getattr(tool, "inputSchema", {}) or {}
    props: dict = schema.get("properties", {})
    required: list = schema.get("required", [])

    args_parts = []
    for param, info in props.items():
        p_type = info.get("type", "any")
        p_desc = info.get("description", "")
        req_marker = "" if param in required else "?"
        args_parts.append(f"    {param}{req_marker}: {p_type}  # {p_desc}" if p_desc else f"    {param}{req_marker}: {p_type}")

    args_block = "\n".join(args_parts) if args_parts else "    (no arguments)"
    return f"{name}:\n  {desc}\n  Arguments:\n{args_block}"


class GrafanaMCPSession:
    """Async context manager for one Grafana MCP server session.

    Connects on ``__aenter__``, initialises the MCP session, lists tools, and
    disconnects on ``__aexit__``.
    """

    def __init__(self, grafana_url: str, api_token: str, settings: Settings) -> None:
        self._grafana_url = grafana_url
        self._api_token = api_token
        self._settings = settings
        self._tools: list = []
        self._session = None
        self._exit_stack = None

    async def __aenter__(self) -> "GrafanaMCPSession":
        from contextlib import AsyncExitStack

        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()
        try:
            await self._connect()
        except Exception:
            await self._exit_stack.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._exit_stack:
            await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)

    async def _connect(self) -> None:
        from mcp import ClientSession

        if self._settings.grafana_mcp_url:
            read, write = await self._exit_stack.enter_async_context(  # type: ignore[union-attr]
                self._sse_transport()
            )
        else:
            read, write = await self._exit_stack.enter_async_context(  # type: ignore[union-attr]
                self._stdio_transport()
            )

        self._session = await self._exit_stack.enter_async_context(  # type: ignore[union-attr]
            ClientSession(read, write)
        )
        await self._session.initialize()
        result = await self._session.list_tools()
        self._tools = result.tools
        logger.info("mcp_connected", tool_count=len(self._tools))

    def _sse_transport(self):
        from mcp.client.sse import sse_client
        url = self._settings.grafana_mcp_url
        logger.debug("mcp_sse_transport", url=url)
        return sse_client(url)

    def _stdio_transport(self):
        from mcp.client.stdio import stdio_client
        from mcp import StdioServerParameters

        cmd_str = self._settings.grafana_mcp_command
        parts = shlex.split(cmd_str)
        command, args = parts[0], parts[1:]

        env = {
            "GRAFANA_URL": self._grafana_url,
            "GRAFANA_API_KEY": self._api_token,
        }
        logger.debug("mcp_stdio_transport", command=command, args=args)
        return stdio_client(StdioServerParameters(command=command, args=args, env=env))

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def tools(self) -> list:
        return self._tools

    def tool_definitions(self) -> str:
        """Return a text block describing all tools for the LLM system prompt."""
        if not self._tools:
            return "(no tools available)"
        return "\n\n".join(_tool_schema_to_text(t) for t in self._tools)

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Call an MCP tool and return the result as a plain string."""
        if self._session is None:
            return "MCP session not initialised."
        try:
            result = await self._session.call_tool(name, arguments)
        except Exception as exc:
            logger.warning("mcp_tool_error", tool=name, error=str(exc))
            return f"Tool error: {exc}"

        # Flatten content items to text
        parts: list[str] = []
        for item in result.content:
            if hasattr(item, "text"):
                parts.append(item.text)
            else:
                parts.append(str(item))

        return "\n".join(parts) if parts else "(empty result)"
