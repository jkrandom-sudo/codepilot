from __future__ import annotations

import asyncio
import json
from typing import Any

from langchain_core.tools import tool

from codepilot.config.settings import MCPServerConfig, load_config


@tool
def mcp_list_servers() -> str:
    """List configured MCP servers from ~/.codepilot/config.yaml."""
    config = load_config()
    if not config.mcp:
        return "No MCP servers configured. Add servers under the 'mcp' section in ~/.codepilot/config.yaml."
    lines = []
    for name, server in config.mcp.items():
        status = "enabled" if server.enabled else "disabled"
        target = server.command if server.transport == "stdio" else server.url
        lines.append(f"- {name}: {server.transport} {status} {target}".strip())
    return "\n".join(lines)


@tool
def mcp_list_tools(server: str) -> str:
    """List tools exposed by a configured MCP server.

    Args:
        server: MCP server name from config.
    """
    cfg = _get_server(server)
    if isinstance(cfg, str):
        return cfg
    return _run_mcp(_list_tools(cfg))


@tool
def mcp_call_tool(server: str, tool_name: str, arguments: str = "{}") -> str:
    """Call a tool exposed by a configured stdio MCP server.

    Args:
        server: MCP server name from config.
        tool_name: MCP tool name.
        arguments: JSON object string with tool arguments.
    """
    cfg = _get_server(server)
    if isinstance(cfg, str):
        return cfg
    try:
        parsed_args = json.loads(arguments or "{}")
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON arguments: {e}"
    if not isinstance(parsed_args, dict):
        return "Error: arguments must be a JSON object"
    return _run_mcp(_call_tool(cfg, tool_name, parsed_args))


def _get_server(name: str) -> MCPServerConfig | str:
    config = load_config()
    server = config.mcp.get(name)
    if server is None:
        names = ", ".join(config.mcp.keys()) or "none"
        return f"Error: MCP server '{name}' not found. Configured servers: {names}"
    if not server.enabled:
        return f"Error: MCP server '{name}' is disabled"
    if server.transport != "stdio":
        return "Error: Only stdio MCP servers are supported in this version"
    if not server.command:
        return f"Error: MCP server '{name}' has no command configured"
    return server


def _run_mcp(coro) -> str:
    try:
        return asyncio.run(coro)
    except ImportError:
        return 'Error: MCP SDK is not installed. Install with `pip install "codepilot[mcp]"`.'
    except Exception as e:
        return f"Error: MCP request failed: {e}"


async def _list_tools(server: MCPServerConfig) -> str:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        raise

    params = StdioServerParameters(command=server.command, args=server.args, env=server.env or None)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            tools = getattr(result, "tools", [])
            if not tools:
                return "No tools exposed by MCP server."
            lines = []
            for item in tools:
                desc = getattr(item, "description", "") or ""
                lines.append(f"- {item.name}: {desc}".rstrip())
            return "\n".join(lines)


async def _call_tool(server: MCPServerConfig, tool_name: str, arguments: dict[str, Any]) -> str:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        raise

    params = StdioServerParameters(command=server.command, args=server.args, env=server.env or None)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return str(result)
