import json
import os

from langchain_mcp_adapters.client import MultiServerMCPClient


def mcp_client() -> MultiServerMCPClient:
    """Build a client for the servers in mcp_servers.json; `MCP_CLIENT_URL` overrides the geometry server's url."""
    with open(os.path.join(os.path.dirname(__file__), "mcp_servers.json"), "r") as f:
        mcp_config = json.load(f)
    mcp_config["geometry"]["url"] = os.getenv("MCP_CLIENT_URL", mcp_config["geometry"]["url"])
    return MultiServerMCPClient(mcp_config)


async def load_mcp_tools():
    """
    Load the tools of every configured MCP server as LangChain-compatible tools.

    Returns:
        list:
            A list of LangChain-compatible tool objects aggregated from all
            configured MCP servers.

    Example:
        >>> tools = await load_mcp_tools()
        >>> agent = create_agent(model="gpt-4", tools=tools)
    """
    return await mcp_client().get_tools()
