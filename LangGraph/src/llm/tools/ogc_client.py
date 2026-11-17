"""LangChain tools backed by the pgvector OGC process catalog."""

from functools import lru_cache
import os
import time
import logging
import unicodedata

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



def clean_catalog_text(value):
    """`value` with control and invisible formatting characters removed from every string in it.

    Titles, descriptions and schemas come verbatim from remote OGC servers and go into the LLM
    prompts. Zero-width characters, bidi overrides and Unicode tag characters (categories Cc, Cf)
    hide text from a reviewer that the model still reads. Dict keys are left as they are: they
    are input/output names that edges must match exactly.
    """
    if isinstance(value, str):
        return "".join(ch for ch in value if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf"))
    if isinstance(value, dict):
        return {k: clean_catalog_text(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_catalog_text(v) for v in value]
    return value


def _candidate(row: tuple) -> dict:
    """A catalog row (server_url, process_id, title, description, metadata, ...) as a candidate process."""
    return {
        "server_url": row[0],
        "process_id": row[1],
        "title": clean_catalog_text(row[2] or ""),
        "description": clean_catalog_text(row[3] or "")[:500],
        "inputs": clean_catalog_text((row[4] or {}).get("inputs", {})),
        "outputs": clean_catalog_text((row[4] or {}).get("outputs", {})),
    }


@lru_cache(maxsize=1)
def _embedder() -> OllamaEmbeddings:
    logger.info("Using Ollama embeddings at %s with model %s", OLLAMA_BASE_URL, OLLAMA_MODEL)
    return OllamaEmbeddings(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL)

@tool
def search_ogc_processes(query: str, k: int = 5) -> list[dict]:
    """Search the catalog of OGC API processes by natural-language description.

    Use this whenever you need to find a geospatial process that can perform
    a requested operation (buffering, routing, raster ops, etc.). Returns a
    ranked list of candidate processes.

    Args:
        query: What you want to do, in plain language.
        k: Number of candidates to return (default 5, max 20).

    Returns:
        A list of dicts with keys: process_id, server_url, title, description,
        inputs (schema), outputs (schema), similarity. The input/output names in `inputs`
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

    return [{**_candidate(r), "similarity": round(float(r[5]), 3)} for r in rows]


def list_ogc_processes() -> list[dict]:
    """Every process in the catalog, as candidates in the same shape as `search_ogc_processes` returns.

    No query and no ranking: the `fewshot` variant shows the whole catalog to the agent.
    """
    sql = """
        SELECT server_url, process_id, title, description, metadata
        FROM ogc_processes
        ORDER BY server_url, process_id;
    """
    with psycopg.connect(DB_DSN) as conn:
        rows = conn.execute(sql).fetchall()
    return [_candidate(r) for r in rows]


def fetch_io_specs(processes) -> dict[tuple[str, str], dict]:
    """Look up the declared input/output descriptions of catalogued processes.

    `processes` is an iterable of (process_id, server_url) pairs, as a graph node stores
    them in `type` and `config.server_url`. Returns {(process_id, server_url): {"inputs":
    {...}, "outputs": {...}}} for every pair the catalog knows. An unreachable catalog
    yields {} rather than an error: callers treat missing descriptions as "unknown type",
    which validation lets through.
    """
    wanted = sorted({(p, s) for p, s in processes if p and s})
    if not wanted:
        return {}

    sql = """
        SELECT process_id, server_url, metadata
        FROM ogc_processes
        WHERE (process_id, server_url) IN (SELECT * FROM unnest(%s::text[], %s::text[]));
    """
    try:
        with psycopg.connect(DB_DSN) as conn:
            rows = conn.execute(sql, ([p for p, _ in wanted], [s for _, s in wanted])).fetchall()
    except psycopg.Error as exc:
        logger.warning("Input/output lookup failed, skipping type checks: %s", exc)
        return {}

    return {
        (r[0], r[1]): {
            "inputs": (r[2] or {}).get("inputs", {}),
            "outputs": (r[2] or {}).get("outputs", {}),
        }
        for r in rows
    }
