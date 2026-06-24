"""Configuration and constants for OGC database crawler."""

import os

# OGC API servers to crawl
OGC_SERVERS = [
    "https://demo.pygeoapi.io/master/",
    "https://maps.ecere.com/ogcapi/",
]

DB_DSN = os.environ.get(
    "DB_DSN",
    "postgresql://postgres:postgres@localhost:5432/velocityadaptgeo",
)

# Embedding model configuration
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # 384-dimensional

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
