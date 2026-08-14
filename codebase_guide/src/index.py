"""The retrieval layer: semantic search over doc comments, structure from the map.

Two stores, because the two questions are different in kind:

* "which part of this codebase deals with X" is a similarity question over prose, and
  belongs in pgvector.
* "what calls this / what runs next / how does A reach B" is a graph question. It is
  answered from the `CodeMap` held in memory, not from SQL. The whole edge set for a
  large repo is a few hundred kilobytes, and traversal in Python is both faster and
  far simpler than recursive CTEs.

Both are persisted so the guide can run against a repo it has no checkout of, and the
index degrades rather than fails: with no database reachable it falls back to lexical
scoring over the same map, which is worse at synonyms but always available.
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from .config import (
    DEFAULT_EMBED_DIM,
    GuideConfig,
    db_connect_timeout,
    embed_dim,
    ollama_base_url,
    ollama_model,
    ollama_timeout,
)
from .model import CodeMap, Edge, Symbol

logger = logging.getLogger("codebase-guide")

_WORD = re.compile(r"[A-Za-z0-9_]+")


def _connect(dsn: str):
    """Open a Postgres connection that fails fast when nothing is listening."""
    import psycopg

    return psycopg.connect(dsn, connect_timeout=db_connect_timeout())


# ----------------------------------------------------------------- embeddings

def _resolve_ollama_base_url() -> str:
    """Prefer the compose service name when running inside Docker.

    Mirrors `LangGraph/src/llm/tools/ogc_client.py`: a `localhost` default is right on
    a developer machine and wrong in a container, where Ollama is a sibling service.
    """
    configured = ollama_base_url()
    if configured.startswith("http://localhost") and os.path.exists("/.dockerenv"):
        return "http://ollama:11434"
    return configured


@lru_cache(maxsize=4)
def _embedder(base_url: str, model: str, timeout: float):
    """Cached Ollama embedding client, keyed on its settings.

    Keyed rather than a bare singleton so that a process which reconfigures the
    environment - tests, or a host app switching endpoints - is not stuck with the
    client built for the first call.
    """
    from langchain_ollama import OllamaEmbeddings

    logger.info("Embedding with %s at %s", model, base_url)
    return OllamaEmbeddings(
        model=model, base_url=base_url, client_kwargs={"timeout": timeout}
    )


def _embeddings():
    """The embedding client for the current environment."""
    return _embedder(_resolve_ollama_base_url(), ollama_model(), ollama_timeout())


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed indexable texts. Batched by the client."""
    return _embeddings().embed_documents(texts)


def embed_query(text: str) -> list[float]:
    """Embed a single search query."""
    return _embeddings().embed_query(text)


def _vector_literal(values: list[float]) -> str:
    """Render an embedding in pgvector's text form, for use with an explicit `::vector`.

    Chosen over `register_vector`, whose psycopg dumpers cover `numpy.ndarray` and
    `pgvector.Vector` but not plain lists - those only reach a vector column through
    pgvector's implicit array cast, which is a lot of behaviour to depend on when a
    literal and a cast are unambiguous.
    """
    return "[" + ",".join(str(float(v)) for v in values) + "]"


# --------------------------------------------------------------------- search

@dataclass
class Hit:
    """One search result: the symbol, its score, and why it was returned."""

    symbol: Symbol
    score: float
    matched_on: str = "semantic"

    def to_dict(self) -> dict:
        """Flatten to the shape handed to the LLM."""
        return {
            "qualname": self.symbol.qualname,
            "kind": self.symbol.kind,
            "location": self.symbol.location,
            "signature": self.symbol.signature,
            "doc": self.symbol.doc,
            "tags": self.symbol.tags,
            "score": round(self.score, 3),
            "matched_on": self.matched_on,
        }


class Searcher(Protocol):
    """Contract for the semantic-search half of the index."""

    backend: str

    def search(self, query: str, k: int, kinds: tuple[str, ...] | None) -> list[Hit]:
        """Return the `k` best-matching symbols for a natural-language query."""
        ...


class LexicalSearcher:
    """Token-overlap search over the in-memory map, for when no database is reachable.

    Not a substitute for embeddings - it cannot connect "how do I add a step" to a
    docstring about "workflow node registration" - but it keeps the guide usable
    offline and makes the module runnable with no infrastructure at all.
    """

    backend = "lexical"

    def __init__(self, code_map: CodeMap) -> None:
        self.code_map = code_map

    def search(self, query: str, k: int, kinds: tuple[str, ...] | None = None) -> list[Hit]:
        """Score symbols by weighted token overlap. See `Searcher.search`."""
        tokens = {t.lower() for t in _WORD.findall(query)}
        if not tokens:
            return []

        phrase = query.strip().lower()
        hits: list[Hit] = []
        for symbol in self.code_map.symbols.values():
            if kinds and symbol.kind not in kinds:
                continue
            score = 0.0
            score += 3.0 * self._overlap(tokens, symbol.name)
            score += 2.0 * self._overlap(tokens, symbol.qualname)
            score += 1.0 * self._overlap(tokens, symbol.doc)
            score += 0.5 * self._overlap(tokens, symbol.signature)
            if phrase and phrase in symbol.doc.lower():
                score += 4.0
            if score > 0:
                hits.append(Hit(symbol=symbol, score=score, matched_on="lexical"))

        hits.sort(key=lambda h: (-h.score, h.symbol.qualname))
        return hits[:k]

    def _overlap(self, tokens: set[str], text: str) -> float:
        """Fraction of query tokens present in `text`, snake/camel case split apart."""
        if not text:
            return 0.0
        words = {w.lower() for w in _WORD.findall(text)}
        words |= {
            part.lower()
            for word in list(words)
            for part in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", word)
        }
        return len(tokens & words) / len(tokens)


class VectorSearcher:
    """pgvector search over doc-comment embeddings."""

    backend = "pgvector"

    def __init__(self, dsn: str, repo: str, code_map: CodeMap) -> None:
        self.dsn = dsn
        self.repo = repo
        self.code_map = code_map

    def search(self, query: str, k: int, kinds: tuple[str, ...] | None = None) -> list[Hit]:
        """Embed the query and rank symbols by cosine similarity. See `Searcher.search`."""
        literal = _vector_literal(embed_query(query))

        sql = """
            SELECT qualname, 1 - (embedding <=> %s::vector) AS similarity
            FROM code_symbols
            WHERE repo = %s AND embedding IS NOT NULL
        """
        params: list = [literal, self.repo]
        if kinds:
            sql += " AND kind = ANY(%s)"
            params.append(list(kinds))
        sql += " ORDER BY embedding <=> %s::vector LIMIT %s"
        params.extend([literal, k])

        with _connect(self.dsn) as conn:
            rows = conn.execute(sql, params).fetchall()

        hits: list[Hit] = []
        for qualname, similarity in rows:
            symbol = self.code_map.symbols.get(qualname)
            if symbol is not None:
                hits.append(Hit(symbol=symbol, score=float(similarity)))
        return hits


# ---------------------------------------------------------------------- index

@dataclass
class GuideIndex:
    """Everything the agent's tools query: the map, the digest, and a searcher.

    Attributes:
        repo_name: Which repository this index describes.
        code_map: Symbols and edges, used for every structural question.
        digest: Pre-rendered architecture briefing.
        searcher: Semantic (or lexical) search backend.
        degraded: Whether a query-time failure has forced a fallback to lexical search.
            Sticky once set, and reflected in `backend`.
    """

    repo_name: str
    code_map: CodeMap
    digest: str = ""
    searcher: Searcher | None = None
    degraded: bool = False

    @property
    def backend(self) -> str:
        """Name of the active search backend, for reporting to the user.

        Reports the *effective* backend, not the configured one. This string is what
        `/guide/search` returns and what the tool output puts in front of the model, and
        the module promises a weak answer has a visible cause - so a `pgvector` searcher
        that has fallen back must stop reporting itself as one.
        """
        if self.searcher is None:
            return "none"
        if self.degraded:
            return f"lexical ({self.searcher.backend} failed at query time)"
        return self.searcher.backend

    def search(self, query: str, k: int = 8, kinds: tuple[str, ...] | None = None) -> list[Hit]:
        """Semantic search, falling back to lexical if the backend fails at query time.

        A vector search can fail long after startup - Ollama restarts, the DB drops the
        connection. Returning nothing would make the guide look like the codebase has
        no answer, which is a worse failure than a weaker result, so it degrades.

        The backend is still retried on every query, in case the failure was transient,
        but `degraded` stays set: it records that answers in this session came from a
        weaker index, which remains true whether or not the service came back.
        """
        if self.searcher is None:
            return []
        try:
            return self.searcher.search(query, k, kinds)
        except Exception as exc:
            logger.warning(
                "Search backend %s failed (%s); using lexical", self.searcher.backend, exc
            )
            self.degraded = True
            return LexicalSearcher(self.code_map).search(query, k, kinds)


# ------------------------------------------------------------------- writing

def schema_statements(dim: int) -> tuple[str, ...]:
    """The guide's DDL, as statements ready to execute or to concatenate into a file.

    The single source of truth for the schema. `ensure_schema` executes these against a
    live database and `render_init_sql` writes them out as `sql/init.sql`; the two used
    to be maintained separately, and had already drifted - the file declared a hardcoded
    `VECTOR(768)` and carried an index `ensure_schema` never created.

    Args:
        dim: Embedding width for the `VECTOR(n)` column.

    Returns:
        Statements in dependency order. Each is individually re-runnable. Explanatory
        comments are `--` prefixes inside the statements rather than Python comments, so
        that the generated file keeps them; Postgres ignores them either way.
    """
    return (
        "CREATE EXTENSION IF NOT EXISTS vector;",
        """-- One row per indexed repository, holding the pre-rendered architecture digest
-- so an agent can orient itself without a checkout of the code.
CREATE TABLE IF NOT EXISTS code_repos (
    repo            TEXT PRIMARY KEY,
    root            TEXT NOT NULL,
    commit_hash     TEXT,
    digest          TEXT,
    stats           JSONB NOT NULL DEFAULT '{}'::jsonb,
    notes           JSONB NOT NULL DEFAULT '[]'::jsonb,
    indexed_at      TIMESTAMPTZ DEFAULT now()
);""",
        f"""-- One row per documented symbol. `doc` holds the doc comment only, never source.
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
    metadata        JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    embedding       VECTOR({dim}),
    indexed_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (repo, qualname)
);""",
        """-- The structural half of the index: what connects to what, and how.
CREATE TABLE IF NOT EXISTS code_edges (
    id              SERIAL PRIMARY KEY,
    repo            TEXT NOT NULL,
    src             TEXT NOT NULL,
    dst             TEXT NOT NULL,
    kind            TEXT NOT NULL,
    detail          TEXT NOT NULL DEFAULT '',
    UNIQUE (repo, src, dst, kind, detail)
);""",
        """CREATE INDEX IF NOT EXISTS code_symbols_embedding_idx
    ON code_symbols USING hnsw (embedding vector_cosine_ops);""",
        """CREATE INDEX IF NOT EXISTS code_symbols_metadata_idx
    ON code_symbols USING gin (metadata);""",
        """-- Lookup paths for the graph tools, which query by symbol rather than similarity.
CREATE INDEX IF NOT EXISTS code_symbols_repo_qualname_idx
    ON code_symbols (repo, qualname);""",
        """CREATE INDEX IF NOT EXISTS code_symbols_repo_name_idx
    ON code_symbols (repo, name);""",
        "CREATE INDEX IF NOT EXISTS code_edges_src_idx ON code_edges (repo, src, kind);",
        "CREATE INDEX IF NOT EXISTS code_edges_dst_idx ON code_edges (repo, dst, kind);",
    )


def render_init_sql(dim: int = DEFAULT_EMBED_DIM) -> str:
    """Render `schema_statements` as the standalone `sql/init.sql` file.

    `sql/init.sql` exists for a manual `psql -f` - this repo's compose file mounts only
    `ogc_database/sql`, so it is never replayed automatically and `ensure_schema` is the
    real creation path. Generating it keeps a plain, runnable `.sql` file (no templating)
    that still cannot drift: `tests/test_config_and_index.py` fails when the checked-in
    file stops matching this output.

    Args:
        dim: Embedding width to bake in. The default is what a reader of the file gets
            unless they change `$EMBED_DIM` too, which the header says.

    Returns:
        The complete file contents, newline-terminated.
    """
    header = f"""-- Schema for the codebase guide's index.
--
-- GENERATED FILE - do not edit by hand. Source of truth:
-- src/index.py:schema_statements(). Regenerate from the repository root with:
--
--   python -c "from pathlib import Path; \\
--       from codebase_guide.src.index import render_init_sql; \\
--       Path('codebase_guide/sql/init.sql').write_text( \\
--           render_init_sql(), encoding='utf-8', newline='\\n')"
--
-- `ensure_schema()` runs the same statements at index time and is the authoritative
-- creation path: this directory is *not* mounted by the repo's compose file (only
-- `ogc_database/sql` is), so Postgres never replays it. The file is here for a manual
-- `psql -f` against a database the guide has not indexed into yet.
--
-- The VECTOR width below is the default EMBED_DIM ({dim}). If you set $EMBED_DIM to
-- anything else, regenerate this file with that width - `ensure_schema` uses CREATE
-- TABLE IF NOT EXISTS, which cannot widen a column that already exists, and
-- `write_index` refuses to embed into a mismatched one.
--
-- Deliberately mirrors ogc_processes (pgvector for search + JSONB for structure) and
-- lives in the same database, so the guide needs no new infrastructure.
"""
    return header + "\n" + "\n\n".join(schema_statements(dim)) + "\n"


def ensure_schema(dsn: str) -> None:
    """Create the guide's tables if they are missing.

    Run on every index, not just at first install: `sql/init.sql` is not mounted by this
    repo's compose file at all, and a mounted init script is replayed by Postgres only
    for a fresh data volume - so an existing deployment would never otherwise acquire
    these tables.

    Args:
        dsn: Postgres connection string.
    """
    with _connect(dsn) as conn:
        for statement in schema_statements(embed_dim()):
            conn.execute(statement)
        conn.commit()


def embedding_column_dim(dsn: str) -> int | None:
    """Declared width of `code_symbols.embedding`, or None when there is none to read.

    Read through `format_type`, which renders the column as `vector(768)`, rather than
    interpreting `atttypmod` directly: the encoding of a typmod is the extension's
    business, and `information_schema.columns` reports no length at all for an
    extension type.

    Args:
        dsn: Postgres connection string.

    Returns:
        The column's width, or None when the table does not exist yet or the column was
        declared without one (an unconstrained `vector` accepts any width).
    """
    with _connect(dsn) as conn:
        row = conn.execute(
            """SELECT format_type(a.atttypid, a.atttypmod)
               FROM pg_attribute a
               JOIN pg_class c ON c.oid = a.attrelid
               WHERE c.relname = 'code_symbols' AND a.attname = 'embedding'
                 AND a.attnum > 0 AND NOT a.attisdropped"""
        ).fetchone()

    if row is None or not row[0]:
        return None
    match = re.search(r"\((\d+)\)", row[0])
    return int(match.group(1)) if match else None


def write_index(config: GuideConfig, code_map: CodeMap, digest: str) -> int:
    """Embed every symbol's doc comment and store the map in Postgres.

    Symbols and edges are replaced wholesale for this repo rather than merged: a
    deleted function must disappear from the index, and an incremental upsert would
    leave it behind to be cited in a future answer.

    Args:
        config: Target repo configuration, supplying the DSN and repo name.
        code_map: The map to store.
        digest: Pre-rendered architecture briefing.

    Returns:
        Number of symbols written.
    """
    # Before embedding, not after: connecting first means an unreachable database costs
    # a timeout instead of the whole embedding run.
    ensure_schema(config.db_dsn)

    # Same reasoning, for the other way this run can be wasted. `ensure_schema` uses
    # CREATE TABLE IF NOT EXISTS, which leaves an existing VECTOR(n) at its old n, so a
    # changed EMBED_DIM would only surface at INSERT - after every symbol was embedded.
    column_dim = embedding_column_dim(config.db_dsn)
    if column_dim is not None and column_dim != embed_dim():
        raise ValueError(
            f"code_symbols.embedding is VECTOR({column_dim}) but EMBED_DIM is "
            f"{embed_dim()}. CREATE TABLE IF NOT EXISTS cannot change the width of an "
            f"existing column: either set EMBED_DIM={column_dim} to match the table, or "
            f"drop it (DROP TABLE code_symbols) and re-run `index` so it is recreated "
            f"at {embed_dim()} - which discards the embeddings of every repo in this "
            f"database, not just '{config.repo_name}'."
        )

    symbols = list(code_map.symbols.values())
    parent_summaries = _parent_summaries(code_map)
    texts = [s.embedding_text(parent_summaries.get(s.qualname, "")) for s in symbols]

    logger.info("Embedding %d symbols with %s", len(texts), ollama_model())
    vectors = embed_documents(texts)
    # The column now agrees with EMBED_DIM; this catches the remaining pair, where the
    # model itself disagrees with both (a different Ollama model than the one indexed with).
    if vectors and len(vectors[0]) != embed_dim():
        raise ValueError(
            f"Embedding model returned {len(vectors[0])} dimensions but the schema "
            f"declares {embed_dim()}. Set EMBED_DIM to match, or index into a fresh table."
        )

    with _connect(config.db_dsn) as conn:
        conn.execute("DELETE FROM code_symbols WHERE repo = %s", (config.repo_name,))
        conn.execute("DELETE FROM code_edges WHERE repo = %s", (config.repo_name,))

        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO code_symbols
                   (repo, qualname, kind, name, file, lineno, signature, doc,
                    metadata, embedding)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)""",
                [
                    (
                        config.repo_name, symbol.qualname, symbol.kind, symbol.name,
                        symbol.file, symbol.lineno, symbol.signature, symbol.doc,
                        json.dumps({
                            "decorators": symbol.decorators,
                            "tags": symbol.tags,
                            "extra": symbol.extra,
                        }),
                        _vector_literal(vector),
                    )
                    for symbol, vector in zip(symbols, vectors)
                ],
            )
            cur.executemany(
                """INSERT INTO code_edges (repo, src, dst, kind, detail)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (repo, src, dst, kind, detail) DO NOTHING""",
                [
                    (config.repo_name, e.src, e.dst, e.kind, e.detail)
                    for e in code_map.edges
                ],
            )
            cur.execute(
                """INSERT INTO code_repos (repo, root, commit_hash, digest, stats, notes)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (repo) DO UPDATE SET
                       root = EXCLUDED.root, commit_hash = EXCLUDED.commit_hash,
                       digest = EXCLUDED.digest, stats = EXCLUDED.stats,
                       notes = EXCLUDED.notes, indexed_at = now()""",
                (
                    config.repo_name, str(config.repo_root), code_map.commit, digest,
                    json.dumps(code_map.stats()), json.dumps(code_map.notes),
                ),
            )
        conn.commit()

    logger.info("Indexed %d symbols and %d edges as repo '%s'",
                len(symbols), len(code_map.edges), config.repo_name)
    return len(symbols)


def _parent_summaries(code_map: CodeMap) -> dict[str, str]:
    """Map each symbol to its container's one-line summary, for embedding context."""
    summaries: dict[str, str] = {}
    for edge in code_map.edges:
        if edge.kind == "contains" and edge.src in code_map.symbols:
            parent = code_map.symbols[edge.src]
            if parent.doc:
                summaries[edge.dst] = parent.summary
    return summaries


# ------------------------------------------------------------------- reading

def load_code_map_from_db(dsn: str, repo: str) -> tuple[CodeMap, str]:
    """Reconstruct a map and its digest from Postgres, with no repo checkout needed.

    Args:
        dsn: Postgres connection string.
        repo: Repo name used when indexing.

    Returns:
        (code map, digest). Raises `LookupError` when the repo was never indexed.
    """
    with _connect(dsn) as conn:
        repo_row = conn.execute(
            "SELECT commit_hash, digest, notes FROM code_repos WHERE repo = %s", (repo,)
        ).fetchone()
        if repo_row is None:
            raise LookupError(f"Repo '{repo}' is not indexed. Run `index` first.")

        symbol_rows = conn.execute(
            """SELECT qualname, kind, name, file, lineno, signature, doc, metadata
               FROM code_symbols WHERE repo = %s""",
            (repo,),
        ).fetchall()
        edge_rows = conn.execute(
            "SELECT src, dst, kind, detail FROM code_edges WHERE repo = %s", (repo,)
        ).fetchall()

    commit, digest, notes = repo_row
    code_map = CodeMap(repo_name=repo, commit=commit or "", notes=list(notes or []))
    for qualname, kind, name, file, lineno, signature, doc, metadata in symbol_rows:
        meta = metadata or {}
        code_map.symbols[qualname] = Symbol(
            qualname=qualname, kind=kind, name=name, file=file or "", lineno=lineno or 0,
            doc=doc or "", signature=signature or "",
            decorators=meta.get("decorators", []), tags=meta.get("tags", []),
            extra=meta.get("extra", {}),
        )
    code_map.edges = [Edge(src=s, dst=d, kind=k, detail=t) for s, d, k, t in edge_rows]
    code_map.dedupe()
    return code_map, digest or ""


def open_index(config: GuideConfig) -> GuideIndex:
    """Open the best index available for a repo.

    Tries Postgres first, then the on-disk map, then builds from source. Each fallback
    is logged so the answer's provenance is never a mystery: an unexpectedly weak
    reply is usually a lexical fallback, and that should be visible.

    Args:
        config: Target repo configuration.

    Returns:
        A ready `GuideIndex`.
    """
    from .build import build_code_map
    from .config import digest_max_chars
    from .digest import architecture_digest

    if config.use_db:
        try:
            code_map, digest = load_code_map_from_db(config.db_dsn, config.repo_name)
            logger.info("Loaded index for '%s' from Postgres", config.repo_name)
            return GuideIndex(
                repo_name=config.repo_name,
                code_map=code_map,
                digest=digest or architecture_digest(code_map, digest_max_chars()),
                searcher=VectorSearcher(config.db_dsn, config.repo_name, code_map),
            )
        except LookupError as exc:
            logger.warning("%s", exc)
        except Exception as exc:
            # The detail stays in the server log: a psycopg failure names the host, port
            # and user, which is exactly what an operator needs and exactly what an HTTP
            # caller must not be handed - see `api.py`, which reports a log reference.
            logger.warning("Postgres index unavailable (%s); falling back", exc)

    stored_map = None
    if config.map_path and config.map_path.exists():
        try:
            stored_map = CodeMap.load(config.map_path)
            logger.info("Loaded map from %s (lexical search only)", config.map_path)
        except (OSError, ValueError) as exc:
            # A map truncated by an interrupted `index` used to take down every entry
            # point with a raw JSONDecodeError. Rebuilding is the next rung of the same
            # ladder the two neighbouring branches already climb.
            logger.warning(
                "Stored map at %s is unusable (%s); rebuilding from source",
                config.map_path, exc,
            )

    if stored_map is None:
        logger.info("No usable stored index; building the map from source")
    code_map = stored_map if stored_map is not None else build_code_map(config)

    return GuideIndex(
        repo_name=config.repo_name,
        code_map=code_map,
        digest=architecture_digest(code_map, digest_max_chars()),
        searcher=LexicalSearcher(code_map),
    )
