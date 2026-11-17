import asyncio
import logging

from langchain_core.messages import AIMessage

from src.llm.state.state import WorkflowState
from src.llm.nodes._helpers import _log

from src.llm.tools.mcp_client import load_mcp_tools
from src.llm.tools.ogc_client import clean_catalog_text, list_ogc_processes, search_ogc_processes


logger = logging.getLogger(__name__)


async def retriever_node(state: WorkflowState, llm) -> dict:
    """Query the OGC catalog for the manager's search step and record the candidates.

    Returns only the newly produced status message; `messages` is an appending channel.
    """
    step = state.get("step") or {}
    instruction = step.get("instruction", "")

    query = instruction if isinstance(instruction, str) and instruction else str(instruction)
    logger.info("Retriever query: %s", query)
    try:
        candidates = await search_ogc_processes.ainvoke({"query": query})
    except Exception as exc:
        logger.exception("Retriever search failed for query: %s", query)
        return {
            "messages": [AIMessage(content=f"Retriever failed: {exc}")],
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
        status = AIMessage(content="\n".join(summary))
    else:
        status = AIMessage(content="Retriever returned no matching OGC processes.")

    return {
        "messages": [status],
        "candidate_processes": candidates,
        "decision_history": _log(state, "retriever", instruction, candidates),
    }


async def mcp_retriever_node(state: WorkflowState, llm) -> dict:
    """List every OGC process tool of the MCP server as candidates for the manager's search step.

    The `mcp` variant of `retriever_node`: nothing is ranked or filtered by the query, auto_build
    chooses among all tools. A candidate carries what MCP sends for the tool (name, description,
    input schema) plus `process_id`, `server_url`, title and outputs from its `_meta.ogc`, so it is
    picked and executed the same way as a catalog candidate.
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
        {
            "tool": t.name,
            "process_id": ogc["process_id"],
            "server_url": ogc["server_url"],
            "title": clean_catalog_text(ogc.get("title") or ""),
            "description": clean_catalog_text(t.description or ""),
            "inputs": clean_catalog_text((t.args_schema or {}).get("properties", {})),
            "outputs": clean_catalog_text(ogc.get("outputs") or {}),
        }
        for t in tools
        if (ogc := ((t.metadata or {}).get("_meta") or {}).get("ogc"))
    ]
    logger.info("Retriever listed %d MCP process tools", len(candidates))

    if candidates:
        lines = [f"{i}. {c['process_id']} | {c['title']}" for i, c in enumerate(candidates, start=1)]
        status = AIMessage(content="\n".join(["MCP process tools:", *lines]))
    else:
        status = AIMessage(content="MCP server exposes no OGC process tools.")

    return {
        "messages": [status],
        "candidate_processes": candidates,
        "decision_history": _log(state, "retriever", instruction, candidates),
    }


async def catalog_retriever_node(state: WorkflowState, llm) -> dict:
    """List every process of the pgvector catalog as candidates for the manager's search step.

    The `fewshot` variant of `retriever_node`: like `mcp_retriever_node` nothing is ranked or
    filtered by the query, but the processes come from the catalog database, in the same shape as
    the catalog search returns them (without a similarity score).
    """
    instruction = (state.get("step") or {}).get("instruction", "")
    try:
        candidates = await asyncio.to_thread(list_ogc_processes)
    except Exception as exc:
        logger.exception("Retriever could not list the catalog")
        return {
            "messages": [AIMessage(content=f"Retriever failed: {exc}")],
            "candidate_processes": [],
            "decision_history": _log(state, "retriever", instruction, error=str(exc)),
        }
    logger.info("Retriever listed %d catalog processes", len(candidates))

    if candidates:
        lines = [f"{i}. {c['process_id']} | {c['title']}" for i, c in enumerate(candidates, start=1)]
        status = AIMessage(content="\n".join(["Catalog processes:", *lines]))
    else:
        status = AIMessage(content="The catalog holds no OGC processes.")

    return {
        "messages": [status],
        "candidate_processes": candidates,
        "decision_history": _log(state, "retriever", instruction, candidates),
    }
