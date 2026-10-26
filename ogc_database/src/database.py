"""Database operations for storing OGC process metadata."""

import json
import logging

import psycopg
from pgvector.psycopg import register_vector

from .config import DELETE_GONE_SQL, DELETE_UNCONFIGURED_SQL, UPSERT_SQL

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
    servers: list[str],
    listed: set[str],
) -> None:
    """Save all process records and remove the ones the servers no longer have.

    A server keeps its existing records unless its listing was complete: a server that
    is down or failed partway through would otherwise lose its whole catalog. Everything
    happens in one transaction.

    Args:
        dsn: PostgreSQL connection string
        results: List of (server, process_id, url, metadata) tuples
        embeddings: List of embedding vectors
        servers: Every configured server
        listed: The servers whose process listing was complete
    """
    log.info("Writing to database...")
    with connect(dsn) as conn:
        for (server, pid, url, meta), emb in zip(results, embeddings):
            upsert_process(conn, server, pid, url, meta, emb)
        with conn.cursor() as cur:
            for server in servers:
                if server not in listed:
                    log.warning("Kept the existing records of %s: its listing was incomplete.", server)
                    continue
                ids = [pid for s, pid, _, _ in results if s == server]
                cur.execute(DELETE_GONE_SQL, (server, ids))
                if cur.rowcount:
                    log.info("Removed %d processes %s no longer lists.", cur.rowcount, server)
            cur.execute(DELETE_UNCONFIGURED_SQL, (list(servers),))
            if cur.rowcount:
                log.info("Removed %d processes of servers no longer configured.", cur.rowcount)
        conn.commit()
    log.info("Stored %d records.", len(results))
