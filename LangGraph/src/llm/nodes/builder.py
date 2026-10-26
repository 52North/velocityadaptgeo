# src/llm/nodes/builder.py
"""Deterministic workflow-graph mutation helpers.

Used by the manual "build" action (see management.py's MANAGER_SYSTEM for the
{op, args} instruction format) and by auto_builder.py's automatic build step.
"""

from src.llm.state.state import WorkflowState
from src.llm.state.graph import CONFIG_KEYS, find_cycle, new_graph_node, NodePosition
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

    if source == target:
        raise ValueError(f"Cannot connect: '{source}' cannot feed itself.")

    # An input carries exactly one value, so a second edge into it replaces the first
    # rather than joining it: `src.execution.runner._resolve_inputs` would otherwise
    # silently keep whichever of the two happened to be listed last.
    edges = [
        e for e in graph.get("edges", [])
        if not (e.get("target") == target and (e.get("target_input") or "default") == target_input)
    ]
    edges.append({
        "source": source,
        "target": target,
        "source_output": source_output,
        "target_input": target_input,
    })

    wired = {"nodes": graph.get("nodes", []), "edges": edges}
    if cycle := find_cycle(wired):
        raise ValueError(f"Cannot connect: that would create a cycle through {', '.join(cycle)}.")
    return wired


def disconnect(graph: dict, source: str, target: str, source_output: str = "default", target_input: str = "default") -> dict:
    """Remove one edge, identified by both of its ports.

    Matched on all four fields rather than just the endpoints, so removing one of two
    connections between the same pair of nodes leaves the other one in place.
    """
    edges = [
        e for e in graph.get("edges", [])
        if not (e.get("source") == source and e.get("target") == target
                and (e.get("source_output") or "default") == source_output
                and (e.get("target_input") or "default") == target_input)
    ]
    return {"nodes": graph.get("nodes", []), "edges": edges}


def swap_nodes(graph: dict, node_a: str, node_b: str) -> dict:
    """Exchange two nodes' places in the pipeline: each takes over the other's edges.

    Reordering a chain by hand would otherwise mean deleting and redrawing every edge on
    both nodes. An edge only carries over when the receiving node declares a port of the
    same name: the two processes have different signatures, so a `geometry` input has no
    counterpart on a node that never declared one, and re-attaching it to an invented port
    would produce a graph the executor cannot run. Those edges are dropped rather than
    guessed at - the swap is still the edit that was asked for, minus what cannot exist.

    No cycle check is needed: exchanging two ids is a relabeling, so the result is the
    same graph under different names - minus any dropped edge - and a DAG stays a DAG.
    """
    nodes = graph.get("nodes", [])
    ports = {
        n.get("id"): {"in": set(n.get("inputs") or []), "out": set(n.get("outputs") or [])}
        for n in nodes
    }
    if node_a == node_b or {node_a, node_b} - ports.keys():
        raise ValueError("Cannot swap: needs two different nodes, both present in the graph.")

    other = {node_a: node_b, node_b: node_a}
    edges = []
    for edge in graph.get("edges", []):
        moved = dict(edge)
        for side, end, port_key in (("out", "source", "source_output"), ("in", "target", "target_input")):
            if (to := other.get(moved.get(end))) is None:
                continue
            port = moved.get(port_key) or "default"
            if port not in ports[to][side]:
                break
            moved[end], moved[port_key] = to, port
        else:
            edges.append(moved)

    return {"nodes": nodes, "edges": edges}


def set_input(graph: dict, node_id: str, port: str, value=None) -> dict:
    """Set a literal value for one input port, or clear it with `value=None`.

    Static values live in the node's `config`, which is exactly where
    `src.execution.runner._resolve_inputs` looks for an input no edge feeds - so this
    writes nothing new into the schema. An edge into the same port still wins at run time.
    """
    nodes = [dict(n) for n in graph.get("nodes", [])]
    node = next((n for n in nodes if n.get("id") == node_id), None)
    if node is None:
        raise ValueError(f"Cannot set input: '{node_id}' is not a node in the graph.")
    if port in CONFIG_KEYS:
        raise ValueError(f"Cannot set input: '{port}' is a transport setting, not a parameter.")

    config = {k: v for k, v in (node.get("config") or {}).items() if k != port}
    if value is not None:
        config[port] = value
    node["config"] = config
    return {"nodes": nodes, "edges": graph.get("edges", [])}


_OPS = {
    "add_node": add_node,
    "remove_node": remove_node,
    "connect": connect,
    "disconnect": disconnect,
    "set_input": set_input,
    "swap_nodes": swap_nodes,
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
    args = instruction.get("args") if isinstance(instruction, dict) else None
    # `args: null` or a non-object leaves the op without its arguments, which apply_build_op reports.
    args = dict(args) if isinstance(args, dict) else {}

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
