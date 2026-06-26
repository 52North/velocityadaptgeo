from src.llm.state.state import WorkflowState
from src.llm.tools.mcp_client import load_mcp_tools

async def tool_registry_node(state: WorkflowState) -> WorkflowState:
    tools = await load_mcp_tools() #old MCP-based tool loading

    # Keep only metadata that helps planning (no executable objects stored in state)
    tools_meta = []
    for t in tools:
        # Try to capture args schema where possible (varies by tool implementation)
        args_schema = None
        if hasattr(t, "args_schema") and t.args_schema:
            try:
                args_schema = t.args_schema.model_json_schema()
            except Exception:
                args_schema = str(t.args_schema)

        tools_meta.append({
            "name": getattr(t, "name", type(t).__name__),
            "description": getattr(t, "description", "") or "",
            "args_schema": args_schema,  # may be None
        })

    decision_history = state.get("decision_history", [])
    decision_history.append({
        "node": "tool_registry_node",
        "tools_available": [tm["name"] for tm in tools_meta],
        "reasoning": "Loaded MCP tools and stored metadata for planning/execution."
    })

    return {
        "tools_meta": tools_meta,
        "decision_history": decision_history,
        "next_action": "plan",
    }
