#!/bin/sh
# Runs once on first database start. A .sh (not .sql) so EMBED_DIM reaches the schema:
# the vector column's dimension must match whatever OLLAMA_MODEL produces.
set -e
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS ogc_processes (
    id              SERIAL PRIMARY KEY,
    server_url      TEXT NOT NULL,
    process_id      TEXT NOT NULL,
    resource_url    TEXT NOT NULL,
    title           TEXT,
    description     TEXT,
    metadata        JSONB NOT NULL,
    embedding       VECTOR(${EMBED_DIM:-768}),
    fetched_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (server_url, process_id)
);

CREATE INDEX IF NOT EXISTS ogc_processes_embedding_idx
    ON ogc_processes USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS ogc_processes_metadata_idx
    ON ogc_processes USING gin (metadata);
SQL
