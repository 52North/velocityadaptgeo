# src/llm/nodes/builder.py
"""Deterministic workflow-graph mutation helpers.

Used by the manual "build" action (see management.py's MANAGER_SYSTEM for the
{op, args} instruction format) and by auto_builder.py's automatic build step.
"""

from src.llm.state.state import WorkflowState
from src.llm.nodes._helpers import _log


def add_node(graph: dict, process_id: str, server_url: str, inputs: dict | None = None, node_id: str | None = None) -> dict:
    nodes = list(graph.get("nodes", []))
    node_id = node_id or f"{process_id}_{len(nodes)}"
    nodes = [n for n in nodes if n.get("id") != node_id]
    nodes.append({
        "id": node_id,
        "process_id": process_id,
        "server_url": server_url,
        "inputs": inputs or {},
    })
    return {"nodes": nodes, "edges": graph.get("edges", [])}


def remove_node(graph: dict, node_id: str) -> dict:
    nodes = [n for n in graph.get("nodes", []) if n.get("id") != node_id]
    edges = [
        e for e in graph.get("edges", [])
        if e.get("from_node") != node_id and e.get("to_node") != node_id
    ]
    return {"nodes": nodes, "edges": edges}


def connect(graph: dict, from_node: str, to_node: str, from_output: str | None = None, to_input: str | None = None) -> dict:
    edges = list(graph.get("edges", []))
    if not any(e.get("from_node") == from_node and e.get("to_node") == to_node for e in edges):
        edges.append({
            "from_node": from_node,
            "to_node": to_node,
            "from_output": from_output,
            "to_input": to_input,
        })
    return {"nodes": graph.get("nodes", []), "edges": edges}


_OPS = {"add_node": add_node, "remove_node": remove_node, "connect": connect}


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
    args = instruction.get("args", {}) if isinstance(instruction, dict) else {}

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
