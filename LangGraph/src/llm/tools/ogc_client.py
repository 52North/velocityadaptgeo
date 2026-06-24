"""LangChain tools backed by the pgvector OGC process catalog."""

from functools import lru_cache
import os
from typing import Any

import httpx
import psycopg
from langchain_core.tools import tool
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

DB_DSN = os.environ.get(
    "DB_DSN",
    "postgresql://postgres-vector:postgres@localhost:5432/velocityadaptgeo",
)
EMBED_MODEL = os.environ.get(
    "EMBED_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2",
)
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "30.0"))



@lru_cache(maxsize=1)
def _embedder() -> SentenceTransformer:
    return SentenceTransformer(EMBED_MODEL)

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
        inputs (schema), similarity.
    """
    k = max(1, min(k, 20))
    vec = _embedder().encode(query, normalize_embeddings=True)

    sql = """
        SELECT server_url, process_id, title, description, metadata,
               1 - (embedding <=> %s) AS similarity
        FROM ogc_processes
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s
        LIMIT %s;
    """
    with psycopg.connect(DB_DSN) as conn:
        register_vector(conn)
        rows = conn.execute(sql, (vec, vec, k)).fetchall()

    return [
        {
            "server_url": r[0],
            "process_id": r[1],
            "title": r[2] or "",
            "description": (r[3] or "")[:500],
            "inputs": (r[4] or {}).get("inputs", {}),
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
    """Return LangChain tools backed by the pgvector OGC catalog.

    Drop-in replacement for the previous MCP-based `load_mcp_tools()`.
    """
    return [search_ogc_processes, execute_ogc_process]
