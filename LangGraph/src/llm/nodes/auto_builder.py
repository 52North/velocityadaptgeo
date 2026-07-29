import logging
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.llm.state.state import WorkflowState
from src.llm.nodes._helpers import _log
from src.llm.nodes.builder import apply_build_op
from src.llm.nodes.validator import validate_graph

logger = logging.getLogger(__name__)


class GraphBuildDecision(BaseModel):
    """Which retrieved OGC process to add to the workflow graph, and how to wire it in."""

    process_id: str = Field(description="process_id of the chosen candidate. Must exactly match one of the given candidates.")
    server_url: str = Field(description="server_url of the chosen candidate. Must exactly match the same candidate.")
    inputs: dict = Field(default_factory=dict, description="Static input parameters implied by the user's goal, e.g. {'distance': 500}. Leave empty if unknown.")
    connect_from_node: Optional[str] = Field(default=None, description="id of an existing node in the current graph whose output feeds this new node's primary input. Null if there is no such node yet.")
    connect_from_output: Optional[str] = Field(default=None, description="Output name on connect_from_node. Required if connect_from_node is set.")
    connect_to_input: Optional[str] = Field(default=None, description="Input name on the new node that connect_from_output feeds. Required if connect_from_node is set.")
    reasoning: str = Field(description="One sentence justification for this choice.")


AUTO_BUILD_SYSTEM = """You turn one freshly retrieved OGC process candidate into a
concrete node in the user's workflow graph.

Rules:
- Choose exactly one candidate from the list given - whichever best advances the
  user's goal right now. Copy its process_id and server_url exactly as given.
- Prefer a candidate that adds a capability the graph does not have yet. Never pick a
  candidate that is already present as a node in the current graph.
- Wiring is required whenever it is possible: if an existing node produces what this
  new node consumes (e.g. a geocoder's geometry output feeding a buffer's geometry
  input), you MUST set connect_from_node, connect_from_output and connect_to_input.
  Leave them null only when the graph is empty or no existing node can feed this one.
- Node ids in the graph look like "<process_id>_<n>"; connect_from_node must be one of
  the ids actually present in the current graph.
- Do not invent process ids, servers, or node ids that are not present in the given
  candidates or graph.
"""


def _graph_processes(graph: dict) -> set[tuple[str | None, str | None]]:
    """Return the (process_id, server_url) pairs already present as nodes.

    A node stores its process id as `type` and its server in `config` - see
    `src.llm.state.graph.new_graph_node`.
    """
    return {
        (node.get("type"), (node.get("config") or {}).get("server_url"))
        for node in graph.get("nodes", [])
    }


async def auto_build_node(state: WorkflowState, llm) -> dict:
    """Turn the newest search result into a wired graph node, then validate the graph.

    Control returns to the manager afterwards, so this runs once per search and the
    graph grows one capability at a time. Re-adding a process the graph already has is
    refused deterministically: the manager would otherwise be able to stack duplicate
    nodes by searching the same capability twice.
    """
    candidates = (state.get("candidate_processes") or [])[:5]
    graph = state.get("workflow_graph") or {"nodes": [], "edges": []}
    messages = state.get("messages", [])

    if not candidates:
        logger.info("Auto-build skipped: no candidate processes to build from.")
        return {
            "decision_history": _log(state, "auto_build", None, error="No candidates to build from."),
        }

    latest_user = None
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            latest_user = m.content
            break

    prompt = [
        SystemMessage(content=AUTO_BUILD_SYSTEM),
        HumanMessage(content=f"""USER GOAL:
{latest_user or "(unknown)"}

CANDIDATE PROCESSES:
{candidates}

CURRENT WORKFLOW GRAPH:
{graph}

Pick one candidate and decide how to wire it in."""),
    ]

    try:
        decision = await llm.with_structured_output(GraphBuildDecision).ainvoke(prompt)
    except Exception as exc:
        logger.exception("Auto-build structured decision failed")
        return {
            "decision_history": _log(state, "auto_build", None, error=str(exc)),
        }

    if (decision.process_id, decision.server_url) in _graph_processes(graph):
        logger.info(
            "Auto-build skipped: process %s is already a node in the graph.",
            decision.process_id,
        )
        return {
            "decision_history": _log(
                state, "auto_build", decision.model_dump(),
                error=f"Process '{decision.process_id}' is already present in the graph; no node added.",
            ),
        }

    try:
        new_graph = apply_build_op(graph, "add_node", {
            "process_id": decision.process_id,
            "server_url": decision.server_url,
            "inputs": decision.inputs,
        })
        new_node_id = new_graph["nodes"][-1]["id"]
    except (ValueError, TypeError) as exc:
        logger.exception("Auto-build failed to add node")
        return {
            "decision_history": _log(state, "auto_build", decision.model_dump(), error=str(exc)),
        }

    wiring_error = None
    if decision.connect_from_node:
        connect_args = {"source": decision.connect_from_node, "target": new_node_id}
        if decision.connect_from_output:
            connect_args["source_output"] = decision.connect_from_output
        if decision.connect_to_input:
            connect_args["target_input"] = decision.connect_to_input
        try:
            new_graph = apply_build_op(new_graph, "connect", connect_args)
        except (ValueError, TypeError) as exc:
            wiring_error = str(exc)
            logger.warning("Auto-build added %s but could not wire it: %s", new_node_id, exc)

    validation = validate_graph(new_graph)
    logger.info("Auto-build added node %s, validation=%s", new_node_id, validation)

    return {
        "workflow_graph": new_graph,
        "last_validation": validation,
        "decision_history": _log(
            state, "auto_build", decision.model_dump(),
            result={"graph": new_graph, "validation": validation, "added_node": new_node_id},
            error=wiring_error,
        ),
    }
