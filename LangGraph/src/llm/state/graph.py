"""Workflow-graph node/edge data structures.

Explicitly mirrors the VelocityAdapt `NodeGraph` JSON Schema
(https://velocityadapt.de/schemas/workflow-graph.schema.json):

    {
      "nodes": [
        {
          "id": "n2",
          "type": "microclimate_sim",
          "label": "",
          "position": {"x": 400, "y": 200},
          "config": {"timeout_seconds": 1800},
          "inputs": [],
          "outputs": []
        }
      ],
      "edges": [
        {"source": "n1", "target": "n2", "source_output": "default", "target_input": "default"}
      ]
    }

One deliberate deviation from the schema: `type` is kept as an open string
rather than the schema's fixed 9-value enum, since it holds a live
`process_id` discovered at runtime from the OGC process tools of the MCP
server (see src/llm/nodes/retriever.py) rather than a closed, hardcoded
set of node kinds.
"""

import logging

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 300

# Config keys that carry transport settings rather than a process parameter, so nothing
# should offer them for editing or resolve them as an input.
CONFIG_KEYS = ("server_url", "timeout_seconds")
NODE_X_SPACING = 200
NODE_Y = 200

NODE_ID_PATTERN = r"^[a-zA-Z0-9_\-]+$"


class NodePosition(BaseModel):
    """Canvas position for the frontend; auto-laid-out (per category column) when omitted."""

    model_config = ConfigDict(extra="forbid")

    x: float = 0
    y: float = 0


class NodeDefinition(BaseModel):
    """A node in the workflow DAG."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, pattern=NODE_ID_PATTERN)
    type: str  # live OGC process_id from the catalog - see module docstring
    label: str = ""
    position: NodePosition = Field(default_factory=NodePosition)
    config: dict = Field(default_factory=dict)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)


class EdgeDefinition(BaseModel):
    """A directed edge between two named ports. `source`/`target` reference node ids."""

    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    source_output: str = "default"
    target_input: str = "default"


class WorkflowGraph(BaseModel):
    """The full DAG, i.e. the `NodeGraph` per the schema linked above."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[NodeDefinition] = Field(default_factory=list)
    edges: list[EdgeDefinition] = Field(default_factory=list)


def find_cycle(graph: dict) -> list[str]:
    """The node ids left on a cycle, or [] when the graph is a DAG.

    Kahn's algorithm leaves exactly the cyclic nodes unresolved - the same way
    `src.execution.runner.execution_order` detects the problem at run time - so a graph
    that passes here is one the executor will accept. Edges pointing at unknown nodes are
    ignored: that is a dangling-edge error, reported separately by the validator.
    """
    pending = {
        n.get("id"): {e.get("source") for e in graph.get("edges", []) if e.get("target") == n.get("id")}
        for n in graph.get("nodes", [])
    }
    while (ready := [i for i, deps in pending.items() if not deps & pending.keys()]):
        for i in ready:
            del pending[i]
    return sorted(pending)


def default_position(node_index: int) -> NodePosition:
    """Simple left-to-right auto-layout for newly added nodes."""
    return NodePosition(x=NODE_X_SPACING * node_index, y=NODE_Y)


def new_graph_node(
    node_id: str,
    process_id: str,
    server_url: str,
    inputs: dict | None = None,
    position: NodePosition | dict | None = None,
    config: dict | None = None,
    node_index: int = 0,
    label: str = "",
    input_ports: list[str] | None = None,
    output_ports: list[str] | None = None,
) -> dict:
    """Build a node dict representing one OGC process instance in the graph.

    `inputs` holds concrete static parameter values (e.g. {"distance": 500}); these are
    folded into `config`. The node's `inputs`/`outputs` lists hold the process's declared
    port names, taken from the catalog, so an edge can be validated against the ports
    that actually exist. When the ports are unknown they fall back to the static keys.
    """
    resolved_config = {"server_url": server_url, "timeout_seconds": DEFAULT_TIMEOUT_SECONDS}
    resolved_config.update(inputs or {})
    resolved_config.update(config or {})

    node = NodeDefinition(
        id=node_id,
        type=process_id,
        label=label,
        position=position or default_position(node_index),
        config=resolved_config,
        inputs=list(input_ports if input_ports is not None else (inputs or {}).keys()),
        outputs=list(output_ports or []),
    )

    logger.info("Graph-node produced: %s", node.model_dump())

    return node.model_dump()
