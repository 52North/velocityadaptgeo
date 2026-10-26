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
) -> tuple[list[tuple[str, str, str, dict]], bool]:
    """Crawl a single OGC server for all processes and their metadata.

    Args:
        client: Async HTTP client
        sem: Semaphore for rate limiting concurrent requests
        server: Server URL to crawl

    Returns:
        List of (server, process_id, resource_url, metadata) tuples, and whether the
        server's process listing was complete
    """
    log.info("Listing processes for %s", server)
    summaries, complete = await list_processes(client, server)
    log.info("  Found %d processes%s", len(summaries), "" if complete else " (listing incomplete)")

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
    return results, complete


async def crawl_all_servers(
    servers: list[str],
) -> tuple[list[tuple[str, str, str, dict]], set[str]]:
    """Crawl all configured OGC servers.

    Args:
        servers: List of server base URLs

    Returns:
        Combined list of (server, process_id, resource_url, metadata) from all servers,
        and the servers whose process listing was complete
    """
    all_results: list[tuple[str, str, str, dict]] = []
    listed: set[str] = set()

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        sem = asyncio.Semaphore(CONCURRENT_REQUESTS)
        for server in servers:
            try:
                results, complete = await crawl_server(client, sem, server)
            except Exception as e:
                log.error("Server %s failed: %s", server, e)
                continue
            all_results.extend(results)
            if complete:
                listed.add(server)

    return all_results, listed


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
    all_results, listed = await crawl_all_servers(servers)

    # Embed
    embeddings: list[list[float]] = []
    if all_results:
        log.info("Embedding %d process descriptions...", len(all_results))
        embedder = create_embedder(embed_model_name, embed_base_url)
        texts = [build_embedding_text(meta) for _, _, _, meta in all_results]
        embeddings = encode_texts(embedder, texts)
    else:
        log.warning("No processes collected.")

    # Store, and remove what the servers no longer have
    save_all(db_dsn, all_results, embeddings, servers, listed)

    log.info("Pipeline complete.")
