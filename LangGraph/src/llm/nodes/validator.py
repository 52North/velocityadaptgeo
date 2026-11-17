# src/llm/nodes/validator.py
"""Deterministic workflow-graph validation.

Used by the manual "validate" action and by auto_builder.py's automatic build step.

The I/O type check is a switch independent of the workflow variant: with VALIDATE_IO_TYPES unset
(the default) a graph is checked by schema, input/output names and cycles only, as the variants
were measured; set it to check the data kinds an edge carries as well (docs/modular-variants.md).
"""

import os

from pydantic import ValidationError

from src.llm.state.graph import WorkflowGraph, find_cycle
from src.llm.state.state import WorkflowState
from src.llm.nodes._helpers import _log
from src.llm.tools.ogc_client import fetch_io_specs
from src.ogc_servers import is_allowed_server

VALIDATE_IO_TYPES = os.environ.get("VALIDATE_IO_TYPES", "").strip().lower() in ("1", "true", "yes", "on")

# Kinds a bare `{"type": "object"}` may stand for. Most services describe every geodata
# input/output that loosely, so a generic object is accepted on either side of any of them.
_OBJECT_LIKE = frozenset({"geojson", "raster", "bbox"})


def io_kinds(spec) -> frozenset[str]:
    """Classify an OGC input/output description into coarse data kinds.

    Understands the OGC vocabulary where it is present (`format` such as
    "geojson-feature-collection" or "ogc-bbox", `contentMediaType`, `$ref`, `oneOf`/
    `anyOf`) and otherwise falls back to the JSON type. An empty set means "unknown",
    which is compatible with everything.
    """
    if not isinstance(spec, dict):
        return frozenset()
    schema = spec.get("schema", spec)
    if not isinstance(schema, dict) or not schema:
        return frozenset()

    for key in ("oneOf", "anyOf"):
        if isinstance(schema.get(key), list):
            members = [io_kinds({"schema": s}) for s in schema[key]]
            # One open-ended alternative makes the whole union open-ended.
            return frozenset() if any(not m for m in members) else frozenset().union(*members)
    if isinstance(schema.get("allOf"), list):
        # Every part constrains the same value; whichever parts are classifiable say what it is.
        return frozenset().union(*(io_kinds({"schema": s}) for s in schema["allOf"]))

    media = str(schema.get("contentMediaType", "")).lower()
    hints = f"{schema.get('format', '')} {schema.get('$ref', '')}".lower()
    if "geo+json" in media or "geojson" in hints:
        return frozenset({"geojson"})
    if "bbox" in hints:
        return frozenset({"bbox"})
    if media.startswith("image/") or "tiff" in media or "netcdf" in media or any(
        word in hints for word in ("raster", "coverage", "tiff")
    ):
        return frozenset({"raster"})

    types = schema.get("type")
    types = types if isinstance(types, list) else [types] if types else []
    return frozenset("number" if t == "integer" else str(t) for t in types)


def _kind_fits(produced: str, accepted: str) -> bool:
    if produced == accepted:
        return True
    pair = {produced, accepted}
    # An OGC bbox is an object, but plenty of services pass a bbox as a bare number array.
    return pair == {"bbox", "array"} or ("object" in pair and bool(pair & _OBJECT_LIKE))


def io_compatible(output_spec, input_spec) -> bool:
    """Whether an output can feed an input. Unknown kinds on either side always pass."""
    produced, accepted = io_kinds(output_spec), io_kinds(input_spec)
    if not produced or not accepted:
        return True
    return any(_kind_fits(p, a) for p in produced for a in accepted)


def validate_graph(graph: dict, io_specs: dict | None = None, check_types: bool | None = None) -> dict:
    """Check the graph's schema, wiring, acyclicity and - with the type check on - input/output types.

    `check_types` defaults to VALIDATE_IO_TYPES. With it on, `io_specs` maps (process_id,
    server_url) to the process's declared inputs/outputs and is looked up in the catalog when
    omitted; a node without declared input/output names is then checked against the catalog's,
    and a process the catalog does not describe only by name, not by type.
    """
    check_types = VALIDATE_IO_TYPES if check_types is None else check_types
    errors = []

    try:
        parsed = WorkflowGraph.model_validate(graph)
    except ValidationError as exc:
        for e in exc.errors():
            loc = ".".join(str(p) for p in e["loc"])
            errors.append(f"Schema error at '{loc}': {e['msg']}")
        return {"valid": False, "errors": errors}

    def process_key(node):
        return node.type, node.config.get("server_url")

    if check_types and io_specs is None:
        io_specs = fetch_io_specs(process_key(n) for n in parsed.nodes)
    specs = {n.id: (io_specs or {}).get(process_key(n)) or {} for n in parsed.nodes} if check_types else {}

    # The declared input and output names per node. With the type check on, a node added without
    # them (e.g. a manual add_node) is checked against the catalog's instead of being waved through.
    io_names = {
        n.id: (
            set(n.inputs) or set(specs.get(n.id, {}).get("inputs", {})),
            set(n.outputs) or set(specs.get(n.id, {}).get("outputs", {})),
        )
        for n in parsed.nodes
    }
    if not io_names:
        errors.append("Graph has no nodes.")

    # Always checked, unlike types: a graph a host stores is then already known to run only
    # against allowed servers, whoever produced it (the LLM or a client).
    for node in parsed.nodes:
        server_url = node.config.get("server_url")
        if not server_url:
            errors.append(f"Node '{node.id}' has no server_url.")
        elif not is_allowed_server(server_url):
            errors.append(f"Node '{node.id}': server '{server_url}' is not one of the allowed OGC servers.")

    for i, edge in enumerate(parsed.edges):
        wired = True
        if edge.source not in io_names:
            errors.append(f"Edge {i}: unknown source '{edge.source}'.")
            wired = False
        elif (declared := io_names[edge.source][1]) and edge.source_output not in declared:
            errors.append(
                f"Edge {i}: '{edge.source}' has no output '{edge.source_output}' "
                f"(declared outputs: {sorted(declared)})."
            )
            wired = False

        if edge.target not in io_names:
            errors.append(f"Edge {i}: unknown target '{edge.target}'.")
            wired = False
        elif (declared := io_names[edge.target][0]) and edge.target_input not in declared:
            errors.append(
                f"Edge {i}: '{edge.target}' has no input '{edge.target_input}' "
                f"(declared inputs: {sorted(declared)})."
            )
            wired = False

        if not (wired and check_types):
            continue
        output_spec = specs[edge.source].get("outputs", {}).get(edge.source_output)
        input_spec = specs[edge.target].get("inputs", {}).get(edge.target_input)
        if not io_compatible(output_spec, input_spec):
            errors.append(
                f"Edge {i}: type mismatch - '{edge.source}.{edge.source_output}' produces "
                f"{sorted(io_kinds(output_spec))} but '{edge.target}.{edge.target_input}' "
                f"expects {sorted(io_kinds(input_spec))}."
            )

    if cycle := find_cycle(graph):
        errors.append(f"Graph contains a cycle through: {', '.join(cycle)}.")

    return {"valid": not errors, "errors": errors}


async def validator_node(state: WorkflowState) -> dict:
    graph = state.get("workflow_graph") or {"nodes": [], "edges": []}
    report = validate_graph(graph)

    return {
        "last_validation": report,
        "decision_history": _log(state, "validator", "validate", result=report),
    }
