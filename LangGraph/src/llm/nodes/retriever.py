import logging

from langchain_core.messages import AIMessage

from src.llm.state.state import WorkflowState
from src.llm.nodes._helpers import _log, _last_tool_result

from src.llm.tools.ogc_client import search_ogc_processes


logger = logging.getLogger(__name__)


RETRIEVER_SYSTEM = """You are an OGC process retrieval agent.

Use `search_ogc_processes` to find candidates that match the current need.

Rules:
- Issue focused, capability-oriented queries (e.g. "buffer polygon by distance").
- Do not invent process IDs. Only return what the tools provide.
- Do not attempt to build or modify the workflow graph.
"""


async def retriever_node(state: WorkflowState, llm) -> dict:
    step = state.get("step") or {}
    instruction = step.get("instruction", "")
    messages = list(state.get("messages", []))

    query = instruction if isinstance(instruction, str) and instruction else str(instruction)
    logger.info("Retriever query: %s", query)
    try:
        candidates = await search_ogc_processes.ainvoke({"query": query})
    except Exception as exc:
        logger.exception("Retriever search failed for query: %s", query)
        messages.append(AIMessage(content=f"Retriever failed: {exc}"))
        return {
            "messages": messages,
            "candidate_processes": [],
            "decision_history": _log(state, "retriever", instruction, error=str(exc)),
        }

    candidate_ids = [
        f"{candidate.get('process_id')}@{candidate.get('server_url')}"
        for candidate in candidates[:5]
        if isinstance(candidate, dict)
    ]
    logger.info(
        "Retriever returned %d candidates: %s",
        len(candidates),
        ", ".join(candidate_ids) if candidate_ids else "none",
    )

    if candidates:
        summary = ["Top retrieved processes:"]
        for i, candidate in enumerate(candidates[:5], start=1):
            if isinstance(candidate, dict):
                pid = candidate.get("process_id", "unknown")
                title = candidate.get("title", "")
                sim = candidate.get("similarity")
                summary.append(f"{i}. {pid} | {title} | similarity={sim}")
        messages.append(AIMessage(content="\n".join(summary)))
    else:
        messages.append(AIMessage(content="Retriever returned no matching OGC processes."))

    return {
        "messages": messages,
        "candidate_processes": candidates,
        "decision_history": _log(state, "retriever", instruction, candidates),
    }
