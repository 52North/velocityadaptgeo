"""OGC API client for fetching processes and metadata."""

import logging
from typing import Any
from urllib.parse import urljoin

import httpx

log = logging.getLogger("ogc-indexer")


async def fetch_json(client: httpx.AsyncClient, url: str) -> dict[str, Any] | None:
    """Fetch and parse JSON from URL, with error handling.

    Args:
        client: Async HTTP client
        url: URL to fetch

    Returns:
        Parsed JSON dict or None if fetch failed
    """
    try:
        r = await client.get(url, headers={"Accept": "application/json"})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("Failed to fetch %s: %s", url, e)
        return None


async def list_processes(client: httpx.AsyncClient, server: str) -> tuple[list[dict], bool]:
    """Fetch list of processes from OGC server, handling pagination.

    Retrieves {server}/processes and follows 'next' links for pagination.

    Args:
        client: Async HTTP client
        server: Base server URL

    Returns:
        List of process summaries, and whether every page was fetched: only a complete
        listing shows which processes the server no longer has
    """
    server = server.rstrip("/") + "/"
    url = urljoin(server, "processes")
    processes: list[dict] = []

    while url:
        data = await fetch_json(client, url)
        if data is None:
            return processes, False
        processes.extend(data.get("processes", []))

        next_url = None
        for link in data.get("links", []):
            if link.get("rel") == "next":
                next_url = link.get("href")
                break
        url = next_url

    return processes, True


async def fetch_process_detail(
    client: httpx.AsyncClient, server: str, process_id: str
) -> dict | None:
    """Fetch detailed metadata for a specific process.

    Args:
        client: Async HTTP client
        server: Base server URL
        process_id: ID of the process to fetch

    Returns:
        Process detail dict or None if fetch failed
    """
    server = server.rstrip("/") + "/"
    url = urljoin(server, f"processes/{process_id}")
    return await fetch_json(client, url)
