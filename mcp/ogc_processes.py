"""Crawl OGC API - Processes servers at startup and expose every process as an MCP tool."""

import asyncio
import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools.tool import Tool, ToolResult

log = logging.getLogger("ogc-processes")

# The same servers as the pgvector catalog crawler (ogc_database/src/config.py), from the same
# compose settings, so both workflow variants see the same processes under the same server_url.
LOCAL_PYGEOAPI_URL = os.environ.get("LOCAL_PYGEOAPI_URL") or "http://{}/".format(
    os.environ.get("LOCAL_PYGEOAPI_INTERNAL", "pygeoapi:80")
)
OGC_SERVERS = [
    url.strip()
    for url in os.environ.get(
        "OGC_SERVERS", "https://demo.pygeoapi.io/master/,https://maps.ecere.com/ogcapi/"
    ).split(",")
    + [LOCAL_PYGEOAPI_URL]
    if url.strip()
]
EXECUTE_TIMEOUT = float(os.environ.get("OGC_EXECUTE_TIMEOUT", "300"))


class OGCProcessTool(Tool):
    """MCP tool that forwards its arguments as `inputs` to one OGC process's execution endpoint."""

    server_url: str
    process_id: str

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        """Execute the process synchronously and return the server's JSON response."""
        async with httpx.AsyncClient(
            timeout=EXECUTE_TIMEOUT, follow_redirects=True
        ) as client:
            r = await client.post(
                f"{self.server_url.rstrip('/')}/processes/{self.process_id}/execution",
                json={"inputs": arguments},
                headers={"Prefer": "respond-sync", "Accept": "application/json"},
            )
        if r.is_error:
            raise ToolError(
                f"{self.process_id} returned HTTP {r.status_code}: {r.text[:300]}"
            )
        return self.convert_result(r.json())


def input_schema(inputs: dict) -> dict:
    """Map an OGC process `inputs` description to one JSON Schema object usable as MCP `inputSchema`.

    Honours both the standard `minOccurs`/`maxOccurs` and the `required` flag used by the local
    pygeoapi processes.
    """
    properties, required = {}, []
    for name, spec in inputs.items():
        schema = spec.get("schema") or {}
        if spec.get("maxOccurs", 1) != 1:
            schema = {"anyOf": [schema, {"type": "array", "items": schema}]}
        properties[name] = {
            k: spec[k] for k in ("title", "description") if spec.get(k)
        } | schema
        if spec.get("required", spec.get("minOccurs", 1) > 0):
            required.append(name)
    return {"type": "object", "properties": properties, "required": required}


async def fetch_json(client: httpx.AsyncClient, url: str) -> dict | None:
    """GET a JSON document, returning None (and logging) on any failure."""
    try:
        r = await client.get(url, headers={"Accept": "application/json"})
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("Failed to fetch %s: %s", url, e)
        return None


async def list_processes(client: httpx.AsyncClient, base: str) -> list[dict]:
    """Return every process summary of a server, following `next` links."""
    url, processes = f"{base}/processes", []
    while url and (data := await fetch_json(client, url)):
        processes += [p for p in data.get("processes", []) if p.get("id")]
        url = next(
            (l["href"] for l in data.get("links", []) if l.get("rel") == "next"), None
        )
    return processes


async def register_ogc_tools(mcp: FastMCP, servers: list[str] = OGC_SERVERS) -> None:
    """Crawl each server and add one tool per process, named `<host>__<process_id>`.

    `server_url` is kept exactly as configured, as the catalog crawler stores it.
    """
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for server_url in servers:
            base = server_url.rstrip("/")
            summaries = await list_processes(client, base)
            details = await asyncio.gather(
                *(fetch_json(client, f"{base}/processes/{s['id']}") for s in summaries)
            )
            for summary, detail in zip(summaries, details):
                detail = detail or summary
                mcp.add_tool(
                    OGCProcessTool(
                        name=re.sub(
                            r"[^A-Za-z0-9._-]",
                            "_",
                            f"{urlparse(base).hostname}__{summary['id']}",
                        ),
                        title=detail.get("title"),
                        description=detail.get("description"),
                        parameters=input_schema(detail.get("inputs") or {}),
                        server_url=server_url,
                        process_id=summary["id"],
                        meta={
                            "ogc": {
                                "server_url": server_url,
                                "process_id": summary["id"],
                                "title": detail.get("title"),
                                "outputs": detail.get("outputs") or {},
                            }
                        },
                    )
                )
            log.info("Registered %d OGC processes from %s", len(summaries), server_url)
