"""Database operations for storing OGC process metadata."""

import json
import logging

import psycopg
from pgvector.psycopg import register_vector

from .config import UPSERT_SQL

log = logging.getLogger("ogc-indexer")


def connect(dsn: str) -> psycopg.Connection:
    """Create and register pgvector support for a database connection.

    Args:
        dsn: PostgreSQL connection string

    Returns:
        Database connection object
    """
    conn = psycopg.connect(dsn)
    register_vector(conn)
    return conn


def upsert_process(
    conn: psycopg.Connection,
    server: str,
    process_id: str,
    resource_url: str,
    meta: dict,
    embedding: list[float],
) -> None:
    """Insert or update a process record in the database.

    Args:
        conn: Database connection
        server: Server URL
        process_id: The process ID
        resource_url: Full URL to the process resource
        meta: Process metadata dict
        embedding: Vector embedding of the process
    """
    with conn.cursor() as cur:
        cur.execute(
            UPSERT_SQL,
            (
                server,
                process_id,
                resource_url,
                meta.get("title"),
                meta.get("description"),
                json.dumps(meta),
                embedding,
            ),
        )


def save_all(
    dsn: str,
    results: list[tuple[str, str, str, dict]],
    embeddings: list[list[float]],
) -> None:
    """Save all process records to the database.

    Args:
        dsn: PostgreSQL connection string
        results: List of (server, process_id, url, metadata) tuples
        embeddings: List of embedding vectors
    """
    log.info("Writing to database...")
    with connect(dsn) as conn:
        for (server, pid, url, meta), emb in zip(results, embeddings):
            upsert_process(conn, server, pid, url, meta, emb)
        conn.commit()
    log.info("Stored %d records.", len(results))
