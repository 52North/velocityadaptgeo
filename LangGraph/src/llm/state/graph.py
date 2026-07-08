"""Reusable workflow-graph node/edge data structures.

Canonical node shape produced by every build op (matches the process-graph
format expected downstream, e.g.):

    {
      "id": "n2",
      "type": "microclimate_sim",
      "position": {"x": 400, "y": 200},
      "config": {"timeout_seconds": 1800},
      "inputs": [],
      "outputs": []
    }
"""

import logging
from typing import TypedDict

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 300
NODE_X_SPACING = 200
NODE_Y = 200


class NodePosition(TypedDict):
    x: float
    y: float


class GraphNode(TypedDict):
    id: str
    type: str            # the OGC process_id this node represents
    position: NodePosition
    config: dict          # e.g. {"server_url": ..., "timeout_seconds": ...}
    inputs: list
    outputs: list


class GraphEdge(TypedDict):
    from_node: str
    to_node: str
    from_output: str | None
    to_input: str | None


class WorkflowGraph(TypedDict):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


def default_position(node_index: int) -> NodePosition:
    """Simple left-to-right auto-layout for newly added nodes."""
    return {"x": NODE_X_SPACING * node_index, "y": NODE_Y}


def new_graph_node(
    node_id: str,
    process_id: str,
    server_url: str,
    inputs: dict | None = None,
    position: NodePosition | None = None,
    config: dict | None = None,
    node_index: int = 0,
) -> GraphNode:
    """Build a GraphNode representing one OGC process instance in the graph."""
    resolved_config = {"server_url": server_url, "timeout_seconds": DEFAULT_TIMEOUT_SECONDS}
    resolved_config.update(config or {})

    node: GraphNode = {
        "id": node_id,
        "type": process_id,
        "position": position or default_position(node_index),
        "config": resolved_config,
        "inputs": [{"name": k, "value": v} for k, v in (inputs or {}).items()],
        "outputs": [],
    }

    logger.info("Graph-node produced: %s", node)

    return node
