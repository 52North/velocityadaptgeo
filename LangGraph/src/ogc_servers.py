"""The OGC API - Processes servers a workflow graph may use.

Shared by the validator, which rejects other servers while a graph is built, and the runner,
which refuses to execute against them. Standard library only, so neither pulls in the other.
"""

import os

LOCAL_PYGEOAPI_HOST = os.environ.get("LOCAL_PYGEOAPI_HOST", "localhost:5000")
LOCAL_PYGEOAPI_INTERNAL = os.environ.get("LOCAL_PYGEOAPI_INTERNAL", "pygeoapi:80")
# The ones the catalog crawler and the MCP server read (same compose setting and default), plus
# the local pygeoapi under either address. A graph can come from a client (POST /api/chat with
# `graph`, POST /api/execute, /api/graph/op) or from the LLM, so its server_url is not trusted.
OGC_SERVERS = frozenset(
    url.strip().rstrip("/")
    for url in os.environ.get(
        "OGC_SERVERS", "https://demo.pygeoapi.io/master/,https://maps.ecere.com/ogcapi/"
    ).split(",")
    + [os.environ.get("LOCAL_PYGEOAPI_URL", ""), f"http://{LOCAL_PYGEOAPI_HOST}", f"http://{LOCAL_PYGEOAPI_INTERNAL}"]
    if url.strip()
)


def is_allowed_server(server_url) -> bool:
    """Whether `server_url` is one of OGC_SERVERS, ignoring a trailing slash."""
    return isinstance(server_url, str) and server_url.strip().rstrip("/") in OGC_SERVERS
