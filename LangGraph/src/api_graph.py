"""The workflow graph as the HTTP API sends and receives it: process input values in `config.values`.

Inside the service a node's `config` is flat. The service's own settings (`server_url`,
`timeout_seconds`: CONFIG_KEYS in src/llm/state/graph.py) sit next to the OGC process's input
values:

    internal:  {"server_url": "http://pygeoapi:80/", "timeout_seconds": 300, "distance": 500}
    API:       {"server_url": "http://pygeoapi:80/", "timeout_seconds": 300, "values": {"distance": 500}}

The API nests the values instead, because in the flat layout the service's setting names and the
input names of third-party OGC processes share one set of keys (a namespace collision). That has
three consequences a caller would have to live with:

1. Settings told apart by name: to separate settings from values (e.g. to edit only the values),
   a caller has to keep its own copy of the list of setting names.
2. Lossy translation: a caller that keeps values apart, as velocityadapt-stack's `ogc_process`
   node does, needs special cases in both directions.
3. New settings break callers silently: making a third name a setting reclassifies a key that
   existing callers treat as a process input, so they would pass it to the OGC server. Under the
   API's v1 promise (additive changes only) that is a breaking change.

Nested, a caller tells settings and values apart by where they are, callers and the service share
one layout, and a new setting is a new optional field of ApiNodeConfig, outside `values`: it never
takes a name an input already uses, and old callers can ignore it (additive). Do not flatten the
API format again.

What nesting does not change: `server_url` and `timeout_seconds` stay refused as names inside
`values` (ApiNodeConfig), because the internal layout puts the values next to the settings again.
That list stays at these two names; later settings do not extend it.

Security: values come from untrusted sources (the LLM, which reads remote process descriptions,
and API callers), settings decide where and how long the service makes outbound requests. Kept in
one set of keys, a value can pose as a setting:
- a value named `server_url` would redirect the process call, and the input data sent with it, to
  another server (SSRF, data leaving the allowed servers);
- a value named `timeout_seconds` would let one node hold a request open for as long as it likes;
- in the other direction, a future setting holding a secret (e.g. a credential) would be read by
  a client that only knows the old setting names as a process input, and forwarded to a
  third-party OGC server.
Nesting at the API, and refusing setting names inside `values`, keeps API input from crossing
into settings. Inside the flat layout the same rule is enforced where values enter a node:
`new_graph_node` takes `server_url` and `timeout_seconds` only from their own sources and drops
values named like them, and `node_timeout` caps the timeout (MAX_NODE_TIMEOUT_SECONDS) wherever it
is used, the runner included. The OGC server allowlist (src/ogc_servers.py, checked by the
validator and the runner) stays the last line for `server_url` whatever produced it.

The internal layout stays flat on purpose: the agent, the builder ops, the runner, the batch scripts
and the LLM prompts use it, and changing it would change what the LLM sees and invalidate the
workflow variants' measurements. This module is the only place the two layouts meet: src/app.py
converts every graph that crosses the API with `from_api` (requests) and `to_api` (responses and
stream events).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.llm.state.graph import (
    CONFIG_KEYS,
    MAX_NODE_TIMEOUT_SECONDS,
    NodeDefinition,
    WorkflowGraph,
)


class ApiNodeConfig(BaseModel):
    """A node's `config` at the API: the service's settings, and the process's input values apart.

    `extra="forbid"`: a value placed directly in `config`, as in the internal layout, is rejected
    instead of being taken for a setting. A new setting is added here as a new optional field.
    """

    model_config = ConfigDict(extra="forbid")

    # Optional so that a graph missing it is still accepted as incomplete; the validator reports it.
    server_url: str | None = None
    # Bounded: it decides how long an outbound process call may stay open (MAX_NODE_TIMEOUT_SECONDS).
    timeout_seconds: int | float | None = Field(None, gt=0, le=MAX_NODE_TIMEOUT_SECONDS)
    values: dict[str, Any] = Field(default_factory=dict)

    @field_validator("values")
    @classmethod
    def _no_setting_names(cls, values: dict[str, Any]) -> dict[str, Any]:
        # Internally the values sit next to the settings again, where these names would overwrite
        # them. Refused here with the reason, rather than lost in the conversion.
        if clash := sorted(set(values) & set(CONFIG_KEYS)):
            raise ValueError(
                f"'values' cannot contain {', '.join(clash)}: the service uses these names for its "
                "own settings, so no process input value can have them"
            )
        return values


class ApiNode(NodeDefinition):
    """A graph node at the API: like the internal node, with ApiNodeConfig as its `config`."""

    config: ApiNodeConfig = Field(default_factory=ApiNodeConfig)


class ApiGraph(WorkflowGraph):
    """A workflow graph at the API (see the module docstring for how it differs internally)."""

    nodes: list[ApiNode] = Field(default_factory=list)


def to_api(graph: dict | None) -> dict:
    """An internal graph in the API layout: every non-setting `config` key moves into `values`."""
    graph = graph or {"nodes": [], "edges": []}
    nodes = []
    for node in graph.get("nodes", []):
        config = dict(node.get("config") or {})
        settings = {key: config.pop(key) for key in CONFIG_KEYS if key in config}
        nodes.append({**node, "config": {**settings, "values": config}})
    return {**graph, "nodes": nodes, "edges": list(graph.get("edges", []))}


def from_api(graph: dict) -> dict:
    """An API graph, as validated by ApiGraph and dumped, in the internal flat layout.

    Unset settings are left out rather than set to None, as an internal node would not have them.
    ApiNodeConfig has already refused values named like a setting, so nothing is overwritten.
    """
    nodes = []
    for node in graph.get("nodes", []):
        config = dict(node.get("config") or {})
        values = config.pop("values", None) or {}
        settings = {key: value for key, value in config.items() if value is not None}
        nodes.append({**node, "config": {**settings, **values}})
    return {**graph, "nodes": nodes}
