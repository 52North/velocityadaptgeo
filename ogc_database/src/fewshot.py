"""Few-shot examples: YAML files → embedded rows in the `fewshot_examples` table.

The `fewshot` workflow variant shows the agent the solved examples closest to a request. The
examples live as one YAML file each in FEWSHOT_DIR (format: fewshot_examples/README.md); every
crawler run syncs the table to the files. The table is derived data only: rows of deleted files are
removed, and the table is recreated when the embedding size changes.

Only the `request` is embedded, never the solution: the agent's query is a request too.
"""

import json
import logging
from pathlib import Path

import psycopg
import yaml

from .config import (
    CREATE_FEWSHOT_SQL,
    DELETE_FEWSHOT_GONE_SQL,
    EMBEDDING_DIM_SQL,
    FEWSHOT_DIM_SQL,
    UPSERT_FEWSHOT_SQL,
)
from .database import connect
from .embeddings import create_embedder, encode_texts

log = logging.getLogger("ogc-indexer")

EDGE_KEYS = ("source", "target", "source_output", "target_input")
# Used when neither the catalog column nor an embedding tells the size; init.sh's EMBED_DIM default.
FALLBACK_DIM = 768


class ExampleError(ValueError):
    """An example file that cannot be used, with the reason."""


def _check_graph(graph: object) -> None:
    """Raise ExampleError unless `graph` has the workflow graph shape of `workflows.jsonl`."""
    if not isinstance(graph, dict):
        raise ExampleError("solution.workflow_graph must be a mapping with nodes and edges")
    nodes, edges = graph.get("nodes"), graph.get("edges", [])
    if not isinstance(nodes, list) or not nodes:
        raise ExampleError("solution.workflow_graph.nodes must be a non-empty list")
    if not isinstance(edges, list):
        raise ExampleError("solution.workflow_graph.edges must be a list")
    ids = set()
    for i, node in enumerate(nodes):
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not isinstance(node.get("type"), str):
            raise ExampleError(f"node {i} needs a string id and a string type (the OGC process id)")
        ids.add(node["id"])
    for i, edge in enumerate(edges):
        if not isinstance(edge, dict) or not all(isinstance(edge.get(k), str) for k in EDGE_KEYS):
            raise ExampleError(f"edge {i} needs the strings {', '.join(EDGE_KEYS)}")
        if edge["source"] not in ids or edge["target"] not in ids:
            raise ExampleError(f"edge {i} connects a node id that is not in nodes")


def parse_example(path: Path) -> dict:
    """Read one example file; raise ExampleError if it is not a usable example."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ExampleError(f"not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ExampleError("the file must hold a mapping with id, request and solution")
    example_id, request, solution, notes = data.get("id"), data.get("request"), data.get("solution"), data.get("notes")
    if not isinstance(example_id, str) or not example_id.strip():
        raise ExampleError("id must be a non-empty string")
    if not isinstance(request, str) or not request.strip():
        raise ExampleError("request must be a non-empty string")
    if not isinstance(solution, dict):
        raise ExampleError("solution must be a mapping with workflow_graph")
    _check_graph(solution.get("workflow_graph"))
    if notes is not None and not isinstance(notes, str):
        raise ExampleError("notes must be a string if given")
    return {
        "id": example_id.strip(),
        "request": request.strip(),
        "solution": solution,
        "notes": notes,
        "source_file": path.name,
    }


def load_examples(directory: Path) -> list[dict]:
    """Every usable example in `directory`, by file name.

    Files starting with `_` (the template) are skipped. A broken file or a repeated id is logged as
    an error and left out, so one bad example does not stop the crawler and the services that wait
    for it.
    """
    examples: list[dict] = []
    seen: dict[str, str] = {}
    paths = sorted(p for p in directory.iterdir() if p.suffix in (".yaml", ".yml") and not p.name.startswith("_"))
    for path in paths:
        try:
            example = parse_example(path)
        except (ExampleError, OSError) as exc:
            log.error("Skipped few-shot example %s: %s", path.name, exc)
            continue
        if example["id"] in seen:
            log.error("Skipped few-shot example %s: id %r is already used by %s",
                      path.name, example["id"], seen[example["id"]])
            continue
        seen[example["id"]] = path.name
        examples.append(example)
    return examples


def _dim(conn: psycopg.Connection, sql: str) -> int:
    """The declared size of a vector column, or -1 when it is unknown."""
    try:
        row = conn.execute(sql).fetchone()
    except psycopg.errors.UndefinedTable:
        conn.rollback()
        return -1
    return row[0] if row and row[0] else -1


def sync_examples(directory: Path, embed_model_name: str, embed_base_url: str, dsn: str) -> None:
    """Make the `fewshot_examples` table hold exactly the usable examples in `directory`."""
    if not directory.is_dir():
        log.warning("No few-shot folder at %s; the examples in the database were left as they are.", directory)
        return
    examples = load_examples(directory)
    embeddings: list[list[float]] = []
    if examples:
        log.info("Embedding %d few-shot requests...", len(examples))
        embeddings = encode_texts(create_embedder(embed_model_name, embed_base_url),
                                  [e["request"] for e in examples])

    with connect(dsn) as conn:
        size = len(embeddings[0]) if embeddings else _dim(conn, EMBEDDING_DIM_SQL)
        size = size if size > 0 else FALLBACK_DIM
        existing = _dim(conn, FEWSHOT_DIM_SQL)
        if existing > 0 and existing != size:
            log.warning("Recreating fewshot_examples: its embeddings hold %d values, %s gives %d.",
                        existing, embed_model_name, size)
            conn.execute("DROP TABLE fewshot_examples;")
        conn.execute(CREATE_FEWSHOT_SQL.format(dim=int(size)))
        with conn.cursor() as cur:
            for example, embedding in zip(examples, embeddings):
                cur.execute(UPSERT_FEWSHOT_SQL, (
                    example["id"], example["request"], json.dumps(example["solution"]),
                    example["notes"], example["source_file"], embedding,
                ))
            cur.execute(DELETE_FEWSHOT_GONE_SQL, ([e["id"] for e in examples],))
            if cur.rowcount:
                log.info("Removed %d few-shot examples whose file is gone.", cur.rowcount)
        conn.commit()
    log.info("Stored %d few-shot examples.", len(examples))
