# src/llm/nodes/retriever.py
import json
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from src.llm.state.state import WorkflowState
from src.llm.nodes._helpers import _log, _last_tool_result

from src.llm.tools.ogc_client import load_ogc_tools

RETRIEVER_SYSTEM = """You are an OGC process retrieval agent.

Use `search_ogc_processes` to find candidates that match the current need.
If a candidate looks promising but its schema is truncated, follow up with
`get_process_details` to fetch the full inputs/outputs.

Rules:
- Issue focused, capability-oriented queries (e.g. "buffer polygon by distance").
- Do not invent process IDs. Only return what the tools provide.
- Do not attempt to build or modify the workflow graph.
"""


async def retriever_node(state: WorkflowState, llm) -> dict:
    step = state.get("step") or {}
    instruction = step.get("instruction", "")

    tools = await load_ogc_tools()
    tools = [t for t in tools if t.name in {"search_ogc_processes", "get_process_details"}]
    agent = create_agent(llm, tools, system_prompt=RETRIEVER_SYSTEM)

    result = await agent.ainvoke({
        "messages": [*state.get("messages", []), HumanMessage(content=instruction)]
    })

    # Extract the latest search result from the transcript
    candidates = _last_tool_result(result["messages"], "search_ogc_processes") or []

    return {
        "messages": result["messages"],
        "candidate_processes": candidates,
        "decision_history": _log(state, "retriever", instruction, candidates),
    }
