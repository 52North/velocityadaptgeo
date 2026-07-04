CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS ogc_processes (
    id              SERIAL PRIMARY KEY,
    server_url      TEXT NOT NULL,
    process_id      TEXT NOT NULL,
    resource_url    TEXT NOT NULL,
    title           TEXT,
    description     TEXT,
    metadata        JSONB NOT NULL,
    embedding       VECTOR(768),
    fetched_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (server_url, process_id)
);

CREATE INDEX IF NOT EXISTS ogc_processes_embedding_idx
    ON ogc_processes USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS ogc_processes_metadata_idx
    ON ogc_processes USING gin (metadata);
