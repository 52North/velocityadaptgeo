# src/llm/nodes/builder.py
"""Deterministic workflow-graph mutation helpers.

Used by the manual "build" action (see management.py's MANAGER_SYSTEM for the
{op, args} instruction format) and by auto_builder.py's automatic build step.
"""

from src.llm.state.state import WorkflowState
from src.llm.state.graph import new_graph_node, NodePosition
from src.llm.nodes._helpers import _log


def add_node(
    graph: dict,
    process_id: str,
    server_url: str,
    inputs: dict | None = None,
    node_id: str | None = None,
    position: NodePosition | None = None,
    config: dict | None = None,
    input_ports: list[str] | None = None,
    output_ports: list[str] | None = None,
) -> dict:
    nodes = list(graph.get("nodes", []))
    node_id = node_id or f"{process_id}_{len(nodes)}"
    nodes = [n for n in nodes if n.get("id") != node_id]
    nodes.append(new_graph_node(
        node_id, process_id, server_url,
        inputs=inputs, position=position, config=config,
        node_index=len(nodes),
        input_ports=input_ports, output_ports=output_ports,
    ))
    return {"nodes": nodes, "edges": graph.get("edges", [])}


def add_top_candidate(graph: dict, candidates: list[dict], node_id: str | None = None) -> dict:
    """Deterministically add the #1 ranked search result as a graph node.

    Unlike `add_node`, the process is not named by the caller - it is always
    `candidates[0]`, i.e. the top-searched process from the most recent
    `search_ogc_processes` ranking. No LLM selection involved.
    """
    if not candidates:
        raise ValueError("No candidate processes to build from.")

    top = candidates[0]
    process_id = top.get("process_id")
    server_url = top.get("server_url")
    if not process_id or not server_url:
        raise ValueError("Top candidate is missing process_id or server_url.")

    return add_node(graph, process_id, server_url, node_id=node_id)


def remove_node(graph: dict, node_id: str) -> dict:
    nodes = [n for n in graph.get("nodes", []) if n.get("id") != node_id]
    edges = [
        e for e in graph.get("edges", [])
        if e.get("source") != node_id and e.get("target") != node_id
    ]
    return {"nodes": nodes, "edges": edges}


def connect(graph: dict, source: str, target: str, source_output: str = "default", target_input: str = "default") -> dict:
    """Add an edge between two nodes that must both already exist.

    Unknown endpoints are rejected rather than written, since a dangling edge makes the
    whole graph invalid and the id is typically an LLM's near-miss on a real node id.
    """
    node_ids = {n.get("id") for n in graph.get("nodes", [])}
    for role, node_id in (("source", source), ("target", target)):
        if node_id not in node_ids:
            raise ValueError(
                f"Cannot connect: {role} '{node_id}' is not a node in the graph. "
                f"Known nodes: {sorted(i for i in node_ids if i)}"
            )

    edges = list(graph.get("edges", []))
    if not any(e.get("source") == source and e.get("target") == target for e in edges):
        edges.append({
            "source": source,
            "target": target,
            "source_output": source_output,
            "target_input": target_input,
        })
    return {"nodes": graph.get("nodes", []), "edges": edges}


_OPS = {
    "add_node": add_node,
    "remove_node": remove_node,
    "connect": connect,
    "add_top_candidate": add_top_candidate,
}


def apply_build_op(graph: dict, op: str, args: dict) -> dict:
    if op not in _OPS:
        raise ValueError(f"Unknown op '{op}'")
    return _OPS[op](graph, **args)


async def builder_node(state: WorkflowState) -> dict:
    """Manual build step: apply the exact {op, args} instruction the manager planned."""
    step = state.get("step") or {}
    instruction = step.get("instruction") or {}
    graph = state.get("workflow_graph") or {"nodes": [], "edges": []}

    op = instruction.get("op") if isinstance(instruction, dict) else None
    args = dict(instruction.get("args", {})) if isinstance(instruction, dict) else {}

    if op == "add_top_candidate":
        # Always use the actual ranked search results from state - never let
        # the LLM invent or reorder candidates for this deterministic op.
        args["candidates"] = state.get("candidate_processes") or []

    try:
        new_graph = apply_build_op(graph, op, args)
    except (ValueError, TypeError) as exc:
        return {
            "decision_history": _log(state, "builder", instruction, error=str(exc)),
        }

    return {
        "workflow_graph": new_graph,
        "decision_history": _log(state, "builder", instruction, result=new_graph),
    }
