"""Tools of the MCP server in `mcp/`, for the `mcp` workflow variant."""

import os

from langchain_mcp_adapters.client import MultiServerMCPClient

MCP_URL = os.environ.get("MCP_URL", "http://mcp:8001/mcp")


async def load_mcp_tools() -> list:
    """List every tool of the MCP server as LangChain tools; each OGC process tool carries `_meta.ogc`."""
    return await MultiServerMCPClient(
        {"ogc": {"transport": "streamable_http", "url": MCP_URL}}
    ).get_tools()
