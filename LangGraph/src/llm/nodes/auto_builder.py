import logging
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.llm.state.state import WorkflowState
from src.llm.nodes._helpers import _log, _unmet
from src.llm.nodes.builder import apply_build_op
from src.llm.nodes.validator import validate_graph

logger = logging.getLogger(__name__)


class GraphBuildDecision(BaseModel):
    """Which retrieved OGC process to add to the workflow graph, and how to wire it in."""

    performs_capability: bool = Field(description="True if the chosen candidate actually PERFORMS the operation named in CAPABILITY SEARCHED FOR. False only if the catalog has nothing for that one capability. Judge the single searched capability, NOT the whole user goal.")
    process_id: str = Field(description="process_id of the chosen candidate. Must exactly match one of the given candidates. When performs_capability is false, name the closest candidate anyway so the user can be told what was found instead.")
    server_url: str = Field(description="server_url of the chosen candidate. Must exactly match the same candidate.")
    inputs: dict = Field(default_factory=dict, description="Static input parameters implied by the user's goal, e.g. {'distance': 500}. Leave empty if unknown.")
    connect_from_node: Optional[str] = Field(default=None, description="id of an existing node in the current graph whose output feeds this new node's primary input. Null if there is no such node yet.")
    connect_from_output: Optional[str] = Field(default=None, description="Output name on connect_from_node. Required if connect_from_node is set.")
    connect_to_input: Optional[str] = Field(default=None, description="Input name on the new node that connect_from_output feeds. Required if connect_from_node is set.")
    reasoning: str = Field(description="One sentence justification for this choice.")


AUTO_BUILD_SYSTEM = """You turn one freshly retrieved OGC process candidate into a
concrete node in the user's workflow graph.

Rules:
- You judge ONE capability at a time: the one in CAPABILITY SEARCHED FOR. The user goal
  is given as context for wiring, input values, and choosing between candidates (see
  below). A candidate that performs the searched capability belongs in the graph even
  though it does not, on its own, satisfy the whole goal - the goal is built up over
  several turns, one capability per turn.
- Judge the core operation of the capability - what it turns which input into - not
  every detail of its wording. A candidate that performs that operation performs the
  capability even if its description does not repeat an incidental detail of the query,
  such as the projection used for metric distances or a particular algorithm. Refuse
  only when the operation itself is different or missing, not because a description is
  shorter or worded differently than the query.
- Decide whether any candidate performs THAT capability. The candidates are the nearest
  vector matches, NOT a guarantee of fitness: the search always returns something, even
  when nothing in the catalog performs the requested operation. If none of them performs
  it, set performs_capability=false. Do NOT settle for a process that merely operates on
  similar data, belongs to the same domain, or sounds related - a viewshed process is
  not a shadow simulation, and a buffer is not a travel-time isochrone.
- A `similarity` at or below ~0.55 is a hint that the capability may be absent
  altogether; a genuine match usually scores well above that. The description decides,
  though - the score is only evidence.
- When performs_capability=false nothing is added to the graph. That is the correct,
  useful outcome for a capability the catalog lacks: far better than adding a process
  that does the wrong thing, which would silently produce a workflow that cannot answer
  the goal. It does NOT abandon the goal - the remaining capabilities are still built.
- Otherwise choose exactly one candidate from the list given - whichever best performs
  the searched capability - and copy its process_id and server_url exactly as given.
- When more than one candidate performs the capability, choose the one whose result
  best fits the USER GOAL. For example, if the goal asks for noise zones every 50 m
  from a road, a process that returns several distance bands fits better than one that
  returns a single buffer, even if the query only says "buffer".
- Prefer a candidate that adds a capability the graph does not have yet. Never pick a
  candidate that is already present as a node in the current graph.
- Wiring is required whenever it is possible: if an existing node produces what this
  new node consumes (e.g. a geocoder's geometry output feeding a buffer's geometry
  input), you MUST set connect_from_node, connect_from_output and connect_to_input.
  Leave them null only when the graph is empty or no existing node can feed this one.
- Node ids in the graph look like "<process_id>_<n>"; connect_from_node must be one of
  the ids actually present in the current graph.
- Port names are NOT free text. connect_from_output must be one of the source node's
  declared "outputs" keys, and connect_to_input one of this candidate's declared
  "inputs" keys, spelled exactly as given. Never reuse the input's name for the output
  or invent a port: a graph wired to a port that does not exist cannot be executed.
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

    capability = (state.get("step") or {}).get("instruction")

    if not candidates:
        logger.info("Auto-build skipped: no candidate processes to build from.")
        return {
            "unmet_capabilities": _unmet(state, capability, None, None),
            "decision_history": _log(state, "auto_build", None, error="No candidates to build from."),
        }

    latest_user = None
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            latest_user = m.content
            break

    prompt = [
        SystemMessage(content=AUTO_BUILD_SYSTEM),
        HumanMessage(content=f"""CAPABILITY SEARCHED FOR (judge the candidates against THIS):
{capability or "(unknown)"}

USER GOAL (context for wiring, input values and choosing between matching candidates - the graph is built one capability per turn):
{latest_user or "(unknown)"}

CANDIDATE PROCESSES:
{candidates}

CURRENT WORKFLOW GRAPH:
{graph}

Decide whether a candidate performs the searched capability, and if so how to wire it in."""),
    ]

    try:
        decision = await llm.with_structured_output(GraphBuildDecision).ainvoke(prompt)
    except Exception as exc:
        logger.exception("Auto-build structured decision failed")
        return {
            "decision_history": _log(state, "auto_build", None, error=str(exc)),
        }

    if not decision.performs_capability:
        closest = next(
            (c for c in candidates if c.get("process_id") == decision.process_id),
            candidates[0],
        )
        logger.info(
            "Auto-build refused: no candidate performs '%s' (closest %s, similarity %s).",
            capability, closest.get("process_id"), closest.get("similarity"),
        )
        return {
            "unmet_capabilities": _unmet(
                state, capability, closest.get("process_id"), closest.get("similarity"),
            ),
            "decision_history": _log(
                state, "auto_build", decision.model_dump(),
                error=(
                    f"No catalog process performs this capability; nothing added. "
                    f"Closest was '{closest.get('process_id')}' "
                    f"(similarity {closest.get('similarity')}), which does not do it."
                ),
            ),
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

    chosen = next(
        (c for c in candidates
         if c.get("process_id") == decision.process_id and c.get("server_url") == decision.server_url),
        {},
    )

    try:
        new_graph = apply_build_op(graph, "add_node", {
            "process_id": decision.process_id,
            "server_url": decision.server_url,
            "inputs": decision.inputs,
            "input_ports": list((chosen.get("inputs") or {}).keys()),
            "output_ports": list((chosen.get("outputs") or {}).keys()),
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
