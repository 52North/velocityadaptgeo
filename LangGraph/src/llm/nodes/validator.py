# src/llm/nodes/validator.py
from src.llm.state.state import WorkflowState
from src.llm.graph_ops import validate_graph
from src.llm.nodes._helpers import _log, _last_tool_result

async def validator_node(state: WorkflowState) -> dict:
    graph = state.get("workflow_graph", {"nodes": [], "edges": []})
    report = validate_graph(graph)

    return {
        "last_validation": report,
        "decision_history": _log(state, "validator", "validate", result=report),
    }
