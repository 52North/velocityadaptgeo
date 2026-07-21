# src/llm/nodes/validator.py
"""Deterministic workflow-graph validation.

Used by the manual "validate" action and by auto_builder.py's automatic build step.
"""

from pydantic import ValidationError

from src.llm.state.graph import WorkflowGraph
from src.llm.state.state import WorkflowState
from src.llm.nodes._helpers import _log


def validate_graph(graph: dict) -> dict:
    errors = []

    try:
        parsed = WorkflowGraph.model_validate(graph)
    except ValidationError as exc:
        for e in exc.errors():
            loc = ".".join(str(p) for p in e["loc"])
            errors.append(f"Schema error at '{loc}': {e['msg']}")
        return {"valid": False, "errors": errors}

    node_ids = {n.id for n in parsed.nodes}
    if not node_ids:
        errors.append("Graph has no nodes.")

    for i, edge in enumerate(parsed.edges):
        if edge.source not in node_ids:
            errors.append(f"Edge {i}: unknown source '{edge.source}'.")
        if edge.target not in node_ids:
            errors.append(f"Edge {i}: unknown target '{edge.target}'.")

    return {"valid": not errors, "errors": errors}


async def validator_node(state: WorkflowState) -> dict:
    graph = state.get("workflow_graph") or {"nodes": [], "edges": []}
    report = validate_graph(graph)

    return {
        "last_validation": report,
        "decision_history": _log(state, "validator", "validate", result=report),
    }
