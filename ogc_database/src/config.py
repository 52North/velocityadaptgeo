"""Configuration and constants for OGC database crawler."""

import os

# OGC API servers to crawl
OGC_SERVERS = [
    "https://demo.pygeoapi.io/master/",
    "https://maps.ecere.com/ogcapi/",
    # Local pygeoapi instance (see ./pygeoapi_instance), exposed via docker-compose
    # on host port 5000 (pygeoapi:80 -> localhost:5000).
    os.environ.get("LOCAL_PYGEOAPI_URL", "http://localhost:5000/"),
]

DB_DSN = os.environ.get(
    "DB_DSN",
    "postgresql://postgres:postgres@localhost:5432/velocityadaptgeo",
)

# Embedding model configuration
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "nomic-embed-text")
EMBED_DIM = int(os.environ.get("EMBED_DIM", "768"))

# HTTP client configuration
HTTP_TIMEOUT = 30.0
CONCURRENT_REQUESTS = 5

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
