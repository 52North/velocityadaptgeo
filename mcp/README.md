# MCP server for the `mcp` workflow variant

Crawls the OGC API - Processes servers at startup and exposes every process as an MCP tool (`<host>__<process_id>`), with its input schema, and its `process_id`, `server_url`, title and outputs in the tool's `_meta.ogc`. LangGraph's `mcp` variant (`WORKFLOW_VARIANT=mcp`) lists these tools as candidates instead of searching the pgvector catalog.

The servers are `OGC_SERVERS` plus the local pygeoapi (`LOCAL_PYGEOAPI_URL`, or `http://<LOCAL_PYGEOAPI_INTERNAL>/`), read the same way as the catalog crawler in `ogc_database/`, so both variants see the same processes under the same `server_url`. The tool list is fixed at startup: restart the server after changing a process.

```sh
docker compose up -d mcp                                   # port 8001, http://localhost:8001/mcp
uv run python app.py                                       # outside docker
```
