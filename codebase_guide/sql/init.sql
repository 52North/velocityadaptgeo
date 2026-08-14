-- Schema for the codebase guide's index.
--
-- GENERATED FILE - do not edit by hand. Source of truth:
-- src/index.py:schema_statements(). Regenerate from the repository root with:
--
--   python -c "from pathlib import Path; \
--       from codebase_guide.src.index import render_init_sql; \
--       Path('codebase_guide/sql/init.sql').write_text( \
--           render_init_sql(), encoding='utf-8', newline='\n')"
--
-- `ensure_schema()` runs the same statements at index time and is the authoritative
-- creation path: this directory is *not* mounted by the repo's compose file (only
-- `ogc_database/sql` is), so Postgres never replays it. The file is here for a manual
-- `psql -f` against a database the guide has not indexed into yet.
--
-- The VECTOR width below is the default EMBED_DIM (768). If you set $EMBED_DIM to
-- anything else, regenerate this file with that width - `ensure_schema` uses CREATE
-- TABLE IF NOT EXISTS, which cannot widen a column that already exists, and
-- `write_index` refuses to embed into a mismatched one.
--
-- Deliberately mirrors ogc_processes (pgvector for search + JSONB for structure) and
-- lives in the same database, so the guide needs no new infrastructure.

CREATE EXTENSION IF NOT EXISTS vector;

-- One row per indexed repository, holding the pre-rendered architecture digest
-- so an agent can orient itself without a checkout of the code.
CREATE TABLE IF NOT EXISTS code_repos (
    repo            TEXT PRIMARY KEY,
    root            TEXT NOT NULL,
    commit_hash     TEXT,
    digest          TEXT,
    stats           JSONB NOT NULL DEFAULT '{}'::jsonb,
    notes           JSONB NOT NULL DEFAULT '[]'::jsonb,
    indexed_at      TIMESTAMPTZ DEFAULT now()
);

-- One row per documented symbol. `doc` holds the doc comment only, never source.
CREATE TABLE IF NOT EXISTS code_symbols (
    id              SERIAL PRIMARY KEY,
    repo            TEXT NOT NULL,
    qualname        TEXT NOT NULL,
    kind            TEXT NOT NULL,
    name            TEXT NOT NULL,
    file            TEXT,
    lineno          INTEGER,
    signature       TEXT,
    doc             TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding       VECTOR(768),
    indexed_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (repo, qualname)
);

-- The structural half of the index: what connects to what, and how.
CREATE TABLE IF NOT EXISTS code_edges (
    id              SERIAL PRIMARY KEY,
    repo            TEXT NOT NULL,
    src             TEXT NOT NULL,
    dst             TEXT NOT NULL,
    kind            TEXT NOT NULL,
    detail          TEXT NOT NULL DEFAULT '',
    UNIQUE (repo, src, dst, kind, detail)
);

CREATE INDEX IF NOT EXISTS code_symbols_embedding_idx
    ON code_symbols USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS code_symbols_metadata_idx
    ON code_symbols USING gin (metadata);

-- Lookup paths for the graph tools, which query by symbol rather than similarity.
CREATE INDEX IF NOT EXISTS code_symbols_repo_qualname_idx
    ON code_symbols (repo, qualname);

CREATE INDEX IF NOT EXISTS code_symbols_repo_name_idx
    ON code_symbols (repo, name);

CREATE INDEX IF NOT EXISTS code_edges_src_idx ON code_edges (repo, src, kind);

CREATE INDEX IF NOT EXISTS code_edges_dst_idx ON code_edges (repo, dst, kind);
