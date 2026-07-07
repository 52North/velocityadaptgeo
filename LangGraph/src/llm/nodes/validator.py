# src/llm/nodes/validator.py
"""Deterministic workflow-graph validation.

Used by the manual "validate" action and by auto_builder.py's automatic build step.
"""

from src.llm.state.state import WorkflowState
from src.llm.nodes._helpers import _log


def validate_graph(graph: dict) -> dict:
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    errors = []

    node_ids = {n.get("id") for n in nodes if n.get("id")}
    if not node_ids:
        errors.append("Graph has no nodes.")

    for i, edge in enumerate(edges):
        src, tgt = edge.get("from_node"), edge.get("to_node")
        if src not in node_ids:
            errors.append(f"Edge {i}: unknown from_node '{src}'.")
        if tgt not in node_ids:
            errors.append(f"Edge {i}: unknown to_node '{tgt}'.")

    return {"valid": not errors, "errors": errors}


async def validator_node(state: WorkflowState) -> dict:
    graph = state.get("workflow_graph") or {"nodes": [], "edges": []}
    report = validate_graph(graph)

    return {
        "last_validation": report,
        "decision_history": _log(state, "validator", "validate", result=report),
    }
