import logging

from langchain_core.messages import AIMessage

from src.llm.state.state import WorkflowState
from src.llm.nodes._helpers import _log
from src.llm.tools.mcp_client import load_mcp_tools


logger = logging.getLogger(__name__)


async def retriever_node(state: WorkflowState, llm) -> dict:
    """List every OGC process tool of the MCP server as candidates for the manager's search step.

    Nothing is ranked here: auto_build lets the LLM choose among all tools. Returns only the
    newly produced status message; `messages` is an appending channel.
    """
    instruction = (state.get("step") or {}).get("instruction", "")
    try:
        tools = await load_mcp_tools()
    except Exception as exc:
        logger.exception("Retriever could not list MCP tools")
        return {
            "messages": [AIMessage(content=f"Retriever failed: {exc}")],
            "candidate_processes": [],
            "decision_history": _log(state, "retriever", instruction, error=str(exc)),
        }

    candidates = [
        {"tool": t.name, **t.metadata["_meta"]["ogc"], "description": t.description, "inputs": t.args_schema.get("properties", {})}
        for t in tools if "ogc" in ((t.metadata or {}).get("_meta") or {})
    ]
    logger.info("Retriever listed %d MCP process tools", len(candidates))
    lines = [f"{i}. {c['tool']} | {c.get('title') or ''}" for i, c in enumerate(candidates, start=1)]
    status = "\n".join(["MCP process tools:", *lines]) if candidates else "MCP server exposes no OGC process tools."
    return {
        "messages": [AIMessage(content=status)],
        "candidate_processes": candidates,
        "decision_history": _log(state, "retriever", instruction, candidates),
    }
