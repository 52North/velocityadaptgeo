"""LangChain tools backed by the pgvector OGC process catalog."""

from functools import lru_cache
import os
import time
import logging
from typing import Any

import httpx
import psycopg
from langchain_core.tools import tool
from langchain_ollama import OllamaEmbeddings
from pgvector.psycopg import register_vector

# Assembled from the parts docker-compose shares with the postgres service; an explicit
# DB_DSN (host runs, external database) wins.
DB_DSN = os.environ.get("DB_DSN") or "postgresql://{}:{}@{}:{}/{}".format(
    os.environ.get("POSTGRES_USER", "postgres"),
    os.environ.get("POSTGRES_PASSWORD", "postgres"),
    os.environ.get("POSTGRES_HOST", "postgres-vector"),
    os.environ.get("POSTGRES_PORT", "5432"),
    os.environ.get("POSTGRES_DB", "velocityadaptgeo"),
)
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "nomic-embed-text")
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "30.0"))

logger = logging.getLogger(__name__)


def _get_embedding_dim(conn: psycopg.Connection) -> int | None:
        """Return declared dimension of ogc_processes.embedding, e.g. vector(384) -> 384."""
        row = conn.execute(
                """
                SELECT
                    NULLIF(
                        regexp_replace(
                            pg_catalog.format_type(a.atttypid, a.atttypmod),
                            '^vector\\((\\d+)\\)$',
                            '\\1'
                        ),
                        pg_catalog.format_type(a.atttypid, a.atttypmod)
                    )::int
                FROM pg_catalog.pg_attribute a
                JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = 'ogc_processes'
                    AND a.attname = 'embedding'
                    AND a.attnum > 0
                    AND NOT a.attisdropped
                LIMIT 1
                """
        ).fetchone()
        if row and row[0] is not None:
                return int(row[0])
        return None



@lru_cache(maxsize=1)
def _embedder() -> OllamaEmbeddings:
    logger.info("Using Ollama embeddings at %s with model %s", OLLAMA_BASE_URL, OLLAMA_MODEL)
    return OllamaEmbeddings(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL)

@tool
def search_ogc_processes(query: str, k: int = 5) -> list[dict]:
    """Search the catalog of OGC API processes by natural-language description.

    Use this whenever you need to find a geospatial process that can perform
    a requested operation (buffering, routing, raster ops, etc.). Returns a
    ranked list of candidate processes. To actually run one, call
    `execute_ogc_process` with the chosen `server_url` and `process_id`.

    Args:
        query: What you want to do, in plain language.
        k: Number of candidates to return (default 5, max 20).

    Returns:
        A list of dicts with keys: process_id, server_url, title, description,
        inputs (schema), outputs (schema), similarity. The port names in `inputs`
        and `outputs` are the only valid endpoints for wiring this process into a
        workflow graph.
    """
    k = max(1, min(k, 20))
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            vec = _embedder().embed_query(query)
            break
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2)
            else:
                raise

    vec = [float(v) for v in vec]

    sql = """
        SELECT server_url, process_id, title, description, metadata,
               1 - (embedding <=> %s::vector) AS similarity
        FROM ogc_processes
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """
    with psycopg.connect(DB_DSN) as conn:
        register_vector(conn)
        db_dim = _get_embedding_dim(conn)
        if db_dim is not None and db_dim != len(vec):
            # Another size means another model than the catalog was embedded with. Its vectors
            # are not comparable, so a resized query would rank the processes at random.
            raise ValueError(
                f"query embedding from {OLLAMA_MODEL} has {len(vec)} dimensions, but the catalog "
                f"stores {db_dim}: it was embedded with another model. Use the same OLLAMA_MODEL "
                "for the catalog crawler and LangGraph, or rebuild the catalog (SETUP.md)."
            )

        # Cast through text to pgvector so `<=>` compares VECTOR to VECTOR.
        vec_param = "[" + ",".join(str(v) for v in vec) + "]"
        rows = conn.execute(sql, (vec_param, vec_param, k)).fetchall()

    return [
        {
            "server_url": r[0],
            "process_id": r[1],
            "title": r[2] or "",
            "description": (r[3] or "")[:500],
            "inputs": (r[4] or {}).get("inputs", {}),
            "outputs": (r[4] or {}).get("outputs", {}),
            "similarity": round(float(r[5]), 3),
        }
        for r in rows
    ]

@tool
async def execute_ogc_process(
    server_url: str,
    process_id: str,
    inputs: dict[str, Any],
) -> dict:
    """Execute an OGC API process discovered via `search_ogc_processes`.

    Args:
        server_url: Base URL of the OGC API server (from the search result).
        process_id: ID of the process to run (from the search result).
        inputs: Dict matching the process's `inputs` schema.

    Returns:
        The process result as returned by the server (synchronous execution).
    """
    url = f"{server_url.rstrip('/')}/processes/{process_id}/execution"
    payload = {"inputs": inputs}

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            url,
            json=payload,
            headers={"Prefer": "respond-sync", "Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()

async def load_ogc_tools() -> list:
    """Return LangChain tools backed by the pgvector OGC catalog."""
    return [search_ogc_processes, execute_ogc_process]
