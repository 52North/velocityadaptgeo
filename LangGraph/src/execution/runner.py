"""Execute a built workflow graph against live OGC API - Processes servers.

The runner is deliberately independent of both the LLM that assembles the graph and the
transport that reports on it: it takes the graph dict held in `WorkflowState`, walks it in
dependency order, and yields plain progress events carrying full node results. Callers
decide what to do with them - the SSE endpoint summarises them for the browser, a script
can keep everything. Nothing here knows which processes exist; a node is executed purely
from its own `type`, `config` and the edges pointing at it, so any graph the builder can
produce is runnable without changes here.
"""

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
from urllib.parse import quote

import httpx

from src.llm.state.graph import CONFIG_KEYS

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 300.0
LOCAL_PYGEOAPI_HOST = os.environ.get("LOCAL_PYGEOAPI_HOST", "localhost:5000")
LOCAL_PYGEOAPI_INTERNAL = os.environ.get("LOCAL_PYGEOAPI_INTERNAL", "pygeoapi:80")
# The only servers a node may be executed against: the ones the catalog crawler and the MCP server
# read (same compose setting and default), plus the local pygeoapi under either address. A graph can
# come from a client (POST /api/execute, /api/graph/op), so its server_url is not trusted as given.
OGC_SERVERS = frozenset(
    url.strip().rstrip("/")
    for url in os.environ.get(
        "OGC_SERVERS", "https://demo.pygeoapi.io/master/,https://maps.ecere.com/ogcapi/"
    ).split(",")
    + [os.environ.get("LOCAL_PYGEOAPI_URL", ""), f"http://{LOCAL_PYGEOAPI_HOST}", f"http://{LOCAL_PYGEOAPI_INTERNAL}"]
    if url.strip()
)

GEOJSON_TYPES = frozenset({
    "Feature", "FeatureCollection", "Point", "MultiPoint", "LineString",
    "MultiLineString", "Polygon", "MultiPolygon", "GeometryCollection",
})


class ExecutionError(Exception):
    """Raised when a graph cannot be executed at all, before any node runs."""


def execution_order(graph: dict) -> list[str]:
    """Return node ids in dependency order (Kahn), raising on cycles.

    Independent nodes keep the order they were added, so a run reads the same way as the
    graph was built.
    """
    nodes = [n["id"] for n in graph.get("nodes", [])]
    known = set(nodes)
    edges = [
        e for e in graph.get("edges", [])
        if e.get("source") in known and e.get("target") in known
    ]

    remaining = {node: 0 for node in nodes}
    dependents: dict[str, list[str]] = {node: [] for node in nodes}
    for edge in edges:
        remaining[edge["target"]] += 1
        dependents[edge["source"]].append(edge["target"])

    ready = [node for node in nodes if remaining[node] == 0]
    ordered: list[str] = []
    while ready:
        node = ready.pop(0)
        ordered.append(node)
        for dependent in dependents[node]:
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                ready.append(dependent)

    if len(ordered) != len(nodes):
        stuck = sorted(set(nodes) - set(ordered))
        raise ExecutionError(f"graph contains a cycle involving: {', '.join(stuck)}")

    return ordered


def _static_inputs(node: dict) -> dict:
    """Input values held on the node itself, minus the reserved transport settings."""
    return {k: v for k, v in (node.get("config") or {}).items() if k not in CONFIG_KEYS}


def _pick_output(node_id: str, produced: dict, port: str) -> object:
    """Read one named output from a finished node's response body.

    Tolerates a process that answers with a single unnamed value rather than a map of
    named outputs, which OGC API - Processes permits for single-output processes.
    """
    if isinstance(produced, dict):
        if port in produced:
            return produced[port]
        if len(produced) == 1:
            only = next(iter(produced))
            logger.info("Node %s has no output '%s'; using its only output '%s'.",
                        node_id, port, only)
            return produced[only]
        raise ExecutionError(
            f"node '{node_id}' produced no output '{port}' "
            f"(available: {sorted(produced)})"
        )
    return produced


def _resolve_inputs(node: dict, incoming: list[dict], results: dict) -> dict:
    """Combine a node's static inputs with the values wired in from upstream nodes."""
    inputs = _static_inputs(node)
    for edge in incoming:
        source = edge["source"]
        if source not in results:
            raise ExecutionError(
                f"node '{node['id']}' expects input '{edge.get('target_input')}' from "
                f"'{source}', which did not produce a result"
            )
        inputs[edge.get("target_input") or "default"] = _pick_output(
            source, results[source], edge.get("source_output") or "default"
        )
    return inputs


def _summarise_value(value) -> str:
    """One-line description of an input or output value, never its full payload."""
    if isinstance(value, dict):
        kind = value.get("type")
        if kind == "FeatureCollection":
            return f"FeatureCollection[{len(value.get('features') or [])}]"
        if kind:
            return str(kind)
        return f"object({len(value)} keys)"
    if isinstance(value, list):
        return f"list[{len(value)}]"
    return str(value)[:80]


def summarise(payload: dict) -> dict:
    """Describe every entry of an input/output map without copying the geometry."""
    if not isinstance(payload, dict):
        return {"value": _summarise_value(payload)}
    return {key: _summarise_value(value) for key, value in payload.items()}


def geojson_kind(value) -> str | None:
    """Return the GeoJSON type of a value, or None when it is not drawable.

    This is what makes a result "interpretable" for the map: any output whose shape is
    recognisable GeoJSON can be rendered, whatever process produced it.
    """
    if isinstance(value, dict) and value.get("type") in GEOJSON_TYPES:
        return value["type"]
    return None


def as_feature_collection(value) -> dict:
    """Normalise any GeoJSON value into a FeatureCollection for uniform rendering."""
    kind = geojson_kind(value)
    if kind is None:
        raise ExecutionError("value is not GeoJSON and cannot be mapped")
    if kind == "FeatureCollection":
        return value
    if kind == "Feature":
        return {"type": "FeatureCollection", "features": [value]}
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": value, "properties": {}}],
    }


def mappable_outputs(payload: dict) -> dict:
    """Report which entries of an output map can be drawn, and how large they are."""
    if not isinstance(payload, dict):
        return {}
    found = {}
    for key, value in payload.items():
        kind = geojson_kind(value)
        if kind is None:
            continue
        count = len(value.get("features") or []) if kind == "FeatureCollection" else 1
        found[key] = {"kind": kind, "features": count}
    return found


def _resolve_server_url(url: str) -> str:
    """Prefer the compose service name inside Docker, and the published port outside it.

    The catalog is crawled from the host, so local processes are recorded against
    `localhost:5000`; inside a container that port belongs to the container itself.
    Graphs built in the container may carry the service name instead, which the host
    (e.g. a batch run with `uv run`) cannot resolve.
    """
    in_docker = os.path.exists("/.dockerenv")
    if in_docker and LOCAL_PYGEOAPI_HOST in url:
        return url.replace(LOCAL_PYGEOAPI_HOST, LOCAL_PYGEOAPI_INTERNAL)
    if not in_docker and LOCAL_PYGEOAPI_INTERNAL in url:
        return url.replace(LOCAL_PYGEOAPI_INTERNAL, LOCAL_PYGEOAPI_HOST)
    return url


async def _post_execution(client: httpx.AsyncClient, node: dict, inputs: dict) -> dict:
    """Run one node by calling its process's execution endpoint synchronously."""
    config = node.get("config") or {}
    server_url = config.get("server_url")
    if not server_url:
        raise ExecutionError(f"node '{node['id']}' has no server_url to execute against")

    server = _resolve_server_url(str(server_url)).rstrip("/")
    if server not in OGC_SERVERS:
        raise ExecutionError(f"node '{node['id']}': {server_url} is not one of the configured OGC servers")
    # One path segment, so a process id cannot reach another path or add a query.
    url = f"{server}/processes/{quote(str(node['type']), safe='')}/execution"
    timeout = float(config.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)

    response = await client.post(
        url,
        json={"inputs": inputs},
        headers={"Prefer": "respond-sync", "Accept": "application/json"},
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise ExecutionError(
            f"{node['type']} returned HTTP {response.status_code}: {response.text[:300]}"
        )
    return response.json()


async def run_graph(graph: dict) -> AsyncIterator[dict]:
    """Execute every node in dependency order, yielding progress events as they happen.

    Events carry full payloads under `outputs`/`inputs`; use `summarise()` before sending
    them anywhere size-sensitive. A failing node does not abort the run - its dependents
    are reported as skipped so a partial result is still useful for debugging.
    """
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    if not nodes:
        raise ExecutionError("graph has no nodes to execute")

    order = execution_order(graph)
    incoming: dict[str, list[dict]] = {node_id: [] for node_id in nodes}
    for edge in graph.get("edges", []):
        if edge.get("target") in incoming and edge.get("source") in nodes:
            incoming[edge["target"]].append(edge)

    yield {"event": "graph-start", "order": order,
           "processes": {node_id: nodes[node_id]["type"] for node_id in order}}

    results: dict[str, dict] = {}
    failed: set[str] = set()

    async with httpx.AsyncClient() as client:
        for node_id in order:
            node = nodes[node_id]

            blocked = sorted({e["source"] for e in incoming[node_id]} & failed)
            if blocked:
                failed.add(node_id)
                yield {"event": "node-skipped", "node": node_id, "process": node["type"],
                       "reason": f"depends on failed node(s): {', '.join(blocked)}"}
                continue

            try:
                inputs = _resolve_inputs(node, incoming[node_id], results)
            except ExecutionError as err:
                failed.add(node_id)
                yield {"event": "node-error", "node": node_id, "process": node["type"],
                       "ms": 0, "error": str(err)}
                continue

            yield {"event": "node-start", "node": node_id, "process": node["type"],
                   "inputs": inputs}

            started = time.monotonic()
            try:
                produced = await _post_execution(client, node, inputs)
            except (ExecutionError, httpx.HTTPError, ValueError) as err:
                failed.add(node_id)
                message = str(err) or type(err).__name__
                if isinstance(err, httpx.TimeoutException):
                    message = f"timed out after {node.get('config', {}).get('timeout_seconds', DEFAULT_TIMEOUT_SECONDS)}s"
                logger.warning("Node %s (%s) failed: %s", node_id, node["type"], message)
                yield {"event": "node-error", "node": node_id, "process": node["type"],
                       "ms": int((time.monotonic() - started) * 1000), "error": message}
                continue

            results[node_id] = produced
            yield {"event": "node-done", "node": node_id, "process": node["type"],
                   "ms": int((time.monotonic() - started) * 1000), "outputs": produced}

    terminal = [n for n in order if n in results and not any(
        e["source"] == n for e in graph.get("edges", []) if e.get("target") in nodes
    )]
    yield {"event": "graph-done", "ran": len(results), "failed": len(failed),
           "ok": not failed, "terminal": terminal,
           "results": {node_id: results[node_id] for node_id in terminal}}


async def execute_graph(graph: dict) -> dict:
    """Run a graph to completion and return every event plus the collected results."""
    events = []
    async for event in run_graph(graph):
        events.append(event)
    return {"events": events, "ok": events[-1].get("ok", False) if events else False}


async def _selftest() -> None:
    """Smoke-check ordering and cycle detection without touching the network."""
    graph = {
        "nodes": [{"id": "b", "type": "t", "config": {}}, {"id": "a", "type": "t", "config": {}}],
        "edges": [{"source": "a", "target": "b", "source_output": "o", "target_input": "i"}],
    }
    assert execution_order(graph) == ["a", "b"], execution_order(graph)
    try:
        execution_order({"nodes": [{"id": "a"}, {"id": "b"}],
                         "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]})
    except ExecutionError:
        pass
    else:
        raise AssertionError("cycle not detected")
    print("runner selftest ok")


if __name__ == "__main__":
    asyncio.run(_selftest())
