# src/llm/nodes/builder.py
from src.llm.state.state import WorkflowState
from src.llm.nodes._helpers import _log


def add_node(graph: dict, id: str, **attrs) -> dict:
    nodes = [n for n in graph.get("nodes", []) if n.get("id") != id]
    nodes.append({"id": id, **attrs})
    return {"nodes": nodes, "edges": graph.get("edges", [])}


def remove_node(graph: dict, id: str) -> dict:
    nodes = [n for n in graph.get("nodes", []) if n.get("id") != id]
    edges = [e for e in graph.get("edges", []) if e.get("source") != id and e.get("target") != id]
    return {"nodes": nodes, "edges": edges}


def connect(graph: dict, source: str, target: str, **attrs) -> dict:
    edges = list(graph.get("edges", []))
    if not any(e.get("source") == source and e.get("target") == target for e in edges):
        edges.append({"source": source, "target": target, **attrs})
    return {"nodes": graph.get("nodes", []), "edges": edges}


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
