"""Execute the workflow graphs of a batch run, each distinct graph once, for grading.

    python -m src.batch <run_dir> [--variant V] --execute

Reads the results through `load_results`, so only the currently accepted paraphrases and the seed runs
run. The agent is not loaded; the graphs go to the OGC servers through the runner's helpers.

Unset values: the manager leaves a required input unset when the prompt does not give it ("let it be
resolved at execution time"), as `null`, a placeholder such as `"<UNKNOWN>"`, or no key at all. In the
app the user would be asked; here the scripted `ANSWERS` reply for them. A required input with no
scripted answer stays unset and its node fails. An optional input holding a placeholder is dropped, so
the process default applies. Every result records what was answered (`asked`) and dropped (`defaulted`).

A graph's signature covers its process types, static inputs (after the answers) and edges by port, not
node ids or positions, so the many results that built the same graph run once. Each node's output is
cached by process and inputs under `<run_dir>/executions/nodes/<sha1>.json`, so a node shared by many
graphs (the city boundary, the OSM download) runs once per run folder, for every variant.

Writes `<run_dir>/executions/<signature>.json` (the graph as run, and per node its output's cache key or
its error) and rewrites `<run_dir>/executed[.<variant>].jsonl` (one line per result: key, category,
signature, asked, defaulted). Signatures that did not run cleanly are run again on the next call; nodes
that succeeded come from the cache.
"""

import hashlib
import json
import logging
import re
import time
from pathlib import Path

import httpx

from src.batch import DEFAULT_VARIANT, load_results
from src.execution.runner import (
    ExecutionError,
    _post_execution,
    _resolve_inputs,
    _resolve_server_url,
    execution_order,
)
from src.llm.state.graph import CONFIG_KEYS

logger = logging.getLogger("src.batch")

EXECUTIONS_DIR = "executions"
# The scripted user: what they answer when an input is left unset, by input name.
ANSWERS = {"minArea": 4000}  # m², as in metrics/grading/cool_spots.py
PLACEHOLDER = re.compile(r"^\s*<.*>\s*$")


def executed_file(variant: str = DEFAULT_VARIANT) -> str:
    return (
        "executed.jsonl" if variant == DEFAULT_VARIANT else f"executed.{variant}.jsonl"
    )


def _sha1(value) -> str:
    return hashlib.sha1(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _unset(value) -> bool:
    return (
        value is None
        or value == ""
        or (isinstance(value, str) and bool(PLACEHOLDER.match(value)))
    )


async def _describe(client: httpx.AsyncClient, cache: dict, node: dict) -> dict:
    """The process description's inputs, fetched once per server and process."""
    if not (node.get("config") or {}).get("server_url"):
        return {}  # the runner fails this node anyway
    server = _resolve_server_url(str(node["config"]["server_url"])).rstrip("/")
    key = (server, node["type"])
    if key not in cache:
        response = await client.get(f"{server}/processes/{node['type']}", timeout=30)
        response.raise_for_status()
        cache[key] = response.json().get("inputs") or {}
    return cache[key]


def _required(spec: dict) -> bool:
    return bool(spec.get("required")) or (spec.get("minOccurs") or 0) >= 1


async def answer_unset(
    graph: dict, client: httpx.AsyncClient, cache: dict
) -> tuple[dict, list[str], list[str]]:
    """The graph with unset inputs answered or dropped, plus what was asked and what was dropped."""
    wired = {(e["target"], e.get("target_input")) for e in graph.get("edges", [])}
    nodes, asked, defaulted = [], [], []
    for node in graph["nodes"]:
        config = dict(node.get("config") or {})
        for name, spec in (await _describe(client, cache, node)).items():
            if (node["id"], name) in wired or not _unset(config.get(name)):
                continue
            if _required(spec) and name in ANSWERS:
                config[name] = ANSWERS[name]
                asked.append(f"{node['type']}.{name}")
            elif name in config:
                del config[name]
                defaulted.append(f"{node['type']}.{name}")
        nodes.append({**node, "config": config})
    return {**graph, "nodes": nodes}, asked, defaulted


def signature(graph: dict) -> str:
    """Process types, static inputs and edges by port; independent of node ids and positions."""
    desc = {
        n["id"]: json.dumps(
            [n["type"], {k: v for k, v in n["config"].items() if k not in CONFIG_KEYS}],
            sort_keys=True,
        )
        for n in graph["nodes"]
    }
    # Identical nodes get an occurrence index, so two of them still give two labels.
    label, seen = {}, {}
    for node_id in sorted(desc, key=desc.get):
        seen[desc[node_id]] = seen.get(desc[node_id], 0) + 1
        label[node_id] = f"{desc[node_id]}#{seen[desc[node_id]]}"
    edges = sorted(
        [
            label[e["source"]],
            e.get("source_output"),
            label[e["target"]],
            e.get("target_input"),
        ]
        for e in graph.get("edges", [])
        if e["source"] in label and e["target"] in label
    )
    return _sha1([sorted(label.values()), edges])[:16]


async def execute(graph: dict, client: httpx.AsyncClient, node_dir: Path) -> dict:
    """Run a graph node by node, every output through the cache; never raises for a node."""
    nodes = {n["id"]: n for n in graph["nodes"]}
    incoming = {node_id: [] for node_id in nodes}
    for edge in graph.get("edges", []):
        if edge.get("target") in nodes and edge.get("source") in nodes:
            incoming[edge["target"]].append(edge)

    results, record = {}, {}
    for node_id in execution_order(graph):
        node = nodes[node_id]
        entry = record[node_id] = {
            "type": node["type"],
            "output": None,
            "error": None,
            "ms": 0,
        }
        failed = sorted(
            e["source"] for e in incoming[node_id] if e["source"] not in results
        )
        if failed:
            entry["error"] = f"skipped: depends on failed node(s) {', '.join(failed)}"
            continue
        try:
            inputs = _resolve_inputs(node, incoming[node_id], results)
        except ExecutionError as err:
            entry["error"] = str(err)
            continue
        key = _sha1(
            {
                "process": node["type"],
                "server": _resolve_server_url(node["config"]["server_url"]),
                "inputs": inputs,
            }
        )
        path = node_dir / f"{key}.json"
        if path.exists():
            results[node_id] = json.loads(path.read_text(encoding="utf-8"))
        else:
            started = time.monotonic()
            try:
                results[node_id] = await _post_execution(client, node, inputs)
            except (ExecutionError, httpx.HTTPError, ValueError) as err:
                entry["error"] = str(err) or type(err).__name__
                entry["ms"] = round((time.monotonic() - started) * 1000)
                logger.warning("%s failed: %s", node["type"], entry["error"])
                continue
            entry["ms"] = round((time.monotonic() - started) * 1000)
            path.write_text(
                json.dumps(results[node_id], ensure_ascii=False), encoding="utf-8"
            )
        entry["output"] = key
    return {"ok": all(e["error"] is None for e in record.values()), "nodes": record}


async def execute_all(run_dir: Path, variant: str = DEFAULT_VARIANT) -> None:
    """Execute every distinct graph of the run's results that has not run cleanly yet."""
    out_dir = run_dir / EXECUTIONS_DIR
    node_dir = out_dir / "nodes"
    node_dir.mkdir(parents=True, exist_ok=True)

    results = [
        r
        for r in load_results(run_dir, variant)
        if not r.get("error") and r["workflow_graph"]["nodes"]
    ]
    describe_cache: dict = {}
    lines, graphs = [], {}
    async with httpx.AsyncClient() as client:
        for r in results:
            graph, asked, defaulted = await answer_unset(
                r["workflow_graph"], client, describe_cache
            )
            sig = signature(graph)
            graphs.setdefault(sig, graph)
            lines.append(
                {
                    "key": r["key"],
                    "category": r["category"],
                    "thread_id": r["thread_id"],
                    "text_sha1": r["text_sha1"],
                    "signature": sig,
                    "asked": asked,
                    "defaulted": defaulted,
                }
            )

        todo = [s for s in graphs if not _clean(out_dir / f"{s}.json")]
        logger.info(
            "%s: %d results, %d distinct graphs, %d to execute",
            variant,
            len(lines),
            len(graphs),
            len(todo),
        )
        for i, sig in enumerate(todo, 1):
            started = time.time()
            try:
                run = await execute(graphs[sig], client, node_dir)
            except ExecutionError as err:  # a cycle: the graph cannot run at all
                run = {"ok": False, "error": str(err), "nodes": {}}
            record = {
                "signature": sig,
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "wall_ms": round((time.time() - started) * 1000),
                "graph": graphs[sig],
                **run,
            }
            (out_dir / f"{sig}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            errors = [
                f"{n['type']}: {n['error']}"
                for n in run["nodes"].values()
                if n["error"]
            ]
            logger.info(
                "%d/%d %s: %s",
                i,
                len(todo),
                sig,
                "ok" if run["ok"] else "; ".join(errors)[:300],
            )

    with (run_dir / executed_file(variant)).open("w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


def _clean(path: Path) -> bool:
    return path.exists() and json.loads(path.read_text(encoding="utf-8")).get(
        "ok", False
    )
