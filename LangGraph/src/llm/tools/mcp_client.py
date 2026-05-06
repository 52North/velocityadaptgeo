from langchain_mcp_adapters.client import MultiServerMCPClient

async def load_mcp_tools():
    """
    Initialize MCP clients and load tools from multiple MCP servers.

    This function creates a `MultiServerMCPClient` configured with one or more
    MCP servers using different transports (e.g. stdio, HTTP), then queries
    those servers for their exposed tools.

    The returned tools are compatible with LangChain agents and can be passed
    directly into agent constructors (e.g. `create_agent`) or LangGraph
    workflows.

    MCP servers must implement the Model Context Protocol and expose their
    tools according to the MCP specification.

    Returns:
        list:
            A list of LangChain-compatible tool objects aggregated from all
            configured MCP servers.

    Example:
        >>> tools = await load_mcp_tools()
        >>> agent = create_agent(model="gpt-4", tools=tools)

    Notes:
        - `stdio` servers are launched as subprocesses and communicate via
          standard input/output.
        - `http` servers must expose an MCP endpoint (commonly `/mcp`).
        - Tool loading is asynchronous and should be awaited.
    """

    import json
    import os
    config_path = os.path.join(os.path.dirname(__file__), "mcp_servers.json")
    with open(config_path, "r") as f:
        mcp_config = json.load(f)

    env_url = os.getenv("MCP_CLIENT_URL", "http://localhost:8001/mcp")
    if env_url and "geometry" in mcp_config:
        mcp_config["geometry"]["url"] = env_url

    client = MultiServerMCPClient(mcp_config)

    # Get all MCP tools from the configured servers
    tools = await client.get_tools()
    return tools
