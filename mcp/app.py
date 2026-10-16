"""MCP server exposing every process of the crawled OGC API servers as a tool, for the `mcp` workflow variant."""

import asyncio
import logging

from fastmcp import FastMCP
from ogc_processes import register_ogc_tools

mcp = FastMCP(name="ogc-processes")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(register_ogc_tools(mcp))
    mcp.run(transport="http", host="0.0.0.0", port=8001)
