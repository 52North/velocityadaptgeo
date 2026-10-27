"""Few-shot examples from the pgvector database, for the `fewshot` workflow variant.

The `ogc-database` crawler fills the `fewshot_examples` table from `fewshot_examples/*.yaml`
(see that folder's README). Only an example's request is embedded, so the user's request is
compared with requests.
"""

import logging
import os

import psycopg

from src.llm.tools.ogc_client import DB_DSN, _embedder

logger = logging.getLogger(__name__)

FEWSHOT_K = int(os.environ.get("FEWSHOT_K", "2"))
FEWSHOT_MIN_SIMILARITY = float(os.environ.get("FEWSHOT_MIN_SIMILARITY", "0"))


def search_examples(goal: str, k: int = FEWSHOT_K, min_similarity: float = FEWSHOT_MIN_SIMILARITY) -> list[dict]:
    """The `k` examples whose request is closest to `goal`, at least `min_similarity` close.

    Returns dicts with id, request, solution, notes and similarity; none when the table does not
    exist yet (the crawler has not run since the variant was added) or holds no examples.
    """
    vec = "[" + ",".join(str(float(v)) for v in _embedder().embed_query(goal)) + "]"
    sql = """
        SELECT id, request, solution, notes, 1 - (embedding <=> %s::vector) AS similarity
        FROM fewshot_examples
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """
    try:
        with psycopg.connect(DB_DSN) as conn:
            rows = conn.execute(sql, (vec, vec, k)).fetchall()
    except psycopg.errors.UndefinedTable:
        logger.warning("No fewshot_examples table: run the ogc-database crawler to create it.")
        return []
    return [
        {"id": r[0], "request": r[1], "solution": r[2], "notes": r[3], "similarity": round(float(r[4]), 3)}
        for r in rows
        if float(r[4]) >= min_similarity
    ]
