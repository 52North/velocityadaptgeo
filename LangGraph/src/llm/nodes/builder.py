# src/llm/nodes/builder.py
from src.llm.state.state import WorkflowState
from src.llm.graph_ops import add_node, connect, remove_node
from src.llm.nodes._helpers import _log, _last_tool_result

async def builder_node(state: WorkflowState) -> dict:
    step = state.get("step") or {}
    instruction = step.get("instruction", {})

    op = instruction.get("op")
    args = instruction.get("args", {})
    graph = state.get("workflow_graph", {"nodes": [], "edges": []})

    ops = {"add_node": add_node, "connect": connect, "remove_node": remove_node}

    if op not in ops:
        return {
            "decision_history": _log(state, "builder", instruction, error=f"Unknown op '{op}'"),
        }

    new_graph = ops[op](graph, **args)

    return {
        "workflow_graph": new_graph,
        "decision_history": _log(state, "builder", instruction, result=new_graph),
    }
