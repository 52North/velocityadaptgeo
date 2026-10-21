"""Main pipeline orchestrating the crawl, embed, and store workflow."""

import asyncio
import logging
from urllib.parse import urljoin

import httpx

from .client import fetch_process_detail, list_processes
from .config import CONCURRENT_REQUESTS, HTTP_TIMEOUT
from .database import save_all
from .embeddings import build_embedding_text, create_embedder, encode_texts

log = logging.getLogger("ogc-indexer")


async def crawl_server(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    server: str,
) -> list[tuple[str, str, str, dict]]:
    """Crawl a single OGC server for all processes and their metadata.

    Args:
        client: Async HTTP client
        sem: Semaphore for rate limiting concurrent requests
        server: Server URL to crawl

    Returns:
        List of (server, process_id, resource_url, metadata) tuples
    """
    log.info("Listing processes for %s", server)
    summaries = await list_processes(client, server)
    log.info("  Found %d processes", len(summaries))

    results: list[tuple[str, str, str, dict]] = []

    async def handle(summary: dict):
        pid = summary.get("id")
        if not pid:
            return
        async with sem:
            detail = await fetch_process_detail(client, server, pid)
        if not detail:
            # Fall back to summary if detail call failed
            detail = summary
        resource_url = urljoin(server.rstrip("/") + "/", f"processes/{pid}")
        results.append((server, pid, resource_url, detail))

    await asyncio.gather(*(handle(s) for s in summaries))
    return results


async def crawl_all_servers(
    servers: list[str],
) -> list[tuple[str, str, str, dict]]:
    """Crawl all configured OGC servers.

    Args:
        servers: List of server base URLs

    Returns:
        Combined list of (server, process_id, resource_url, metadata) from all servers
    """
    all_results: list[tuple[str, str, str, dict]] = []

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        sem = asyncio.Semaphore(CONCURRENT_REQUESTS)
        for server in servers:
            try:
                all_results.extend(await crawl_server(client, sem, server))
            except Exception as e:
                log.error("Server %s failed: %s", server, e)

    return all_results


async def run_pipeline(
    servers: list[str],
    embed_model_name: str,
    embed_base_url: str,
    db_dsn: str,
) -> None:
    """Execute the full pipeline: crawl → embed → store.

    Args:
        servers: List of OGC server URLs to crawl
        embed_model_name: Name of the Ollama embedding model to use
        embed_base_url: Base URL of the local Ollama server
        db_dsn: PostgreSQL connection string
    """
    log.info("Starting OGC crawl pipeline...")

    # Crawl
    all_results = await crawl_all_servers(servers)

    if not all_results:
        log.warning("No processes collected, exiting.")
        return

    # Embed
    log.info("Embedding %d process descriptions...", len(all_results))
    embedder = create_embedder(embed_model_name, embed_base_url)
    texts = [build_embedding_text(meta) for _, _, _, meta in all_results]
    embeddings = encode_texts(embedder, texts)

    # Store
    save_all(db_dsn, all_results, embeddings)

    log.info("Pipeline complete.")
