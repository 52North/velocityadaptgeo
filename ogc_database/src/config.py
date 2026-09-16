"""Configuration and constants for OGC database crawler."""

import os

# Comma-separated OGC API servers to crawl. The local pygeoapi instance is appended,
# addressed via LOCAL_PYGEOAPI_INTERNAL so it can move without touching this list.
LOCAL_PYGEOAPI_URL = os.environ.get("LOCAL_PYGEOAPI_URL") or "http://{}/".format(
    os.environ.get("LOCAL_PYGEOAPI_INTERNAL", "pygeoapi:80")
)
OGC_SERVERS = [
    url.strip()
    for url in os.environ.get(
        "OGC_SERVERS",
        "https://demo.pygeoapi.io/master/,https://maps.ecere.com/ogcapi/",
    ).split(",")
    + [LOCAL_PYGEOAPI_URL]
    if url.strip()
]

# Assembled from the parts docker-compose shares with the postgres service; an explicit
# DB_DSN (host runs, external database) wins.
DB_DSN = os.environ.get("DB_DSN") or "postgresql://{}:{}@{}:{}/{}".format(
    os.environ.get("POSTGRES_USER", "postgres"),
    os.environ.get("POSTGRES_PASSWORD", "postgres"),
    os.environ.get("POSTGRES_HOST", "postgres-vector"),
    os.environ.get("POSTGRES_PORT", "5432"),
    os.environ.get("POSTGRES_DB", "velocityadaptgeo"),
)

# Embedding model configuration
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "nomic-embed-text")

# HTTP client configuration
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "30.0"))
CONCURRENT_REQUESTS = int(os.environ.get("CONCURRENT_REQUESTS", "5"))

# Database upsert SQL statement
UPSERT_SQL = """
INSERT INTO ogc_processes
    (server_url, process_id, resource_url, title, description, metadata, embedding)
VALUES
    (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (server_url, process_id) DO UPDATE SET
    resource_url = EXCLUDED.resource_url,
    title        = EXCLUDED.title,
    description  = EXCLUDED.description,
    metadata     = EXCLUDED.metadata,
    embedding    = EXCLUDED.embedding,
    fetched_at   = now();
"""
