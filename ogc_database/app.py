"""
Entry point for the OGC database crawler.

Processes OGC API endpoints, generates embeddings for metadata, and stores in PostgreSQL.
Then syncs the few-shot examples (src/fewshot.py).
"""

import asyncio
import logging

from src.config import DB_DSN, FEWSHOT_DIR, OLLAMA_BASE_URL, OLLAMA_MODEL, OGC_SERVERS
from src.fewshot import sync_examples
from src.pipeline import run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def main() -> None:
    """Run the OGC crawl pipeline with configured servers and settings, then sync the few-shot examples."""
    await run_pipeline(OGC_SERVERS, OLLAMA_MODEL, OLLAMA_BASE_URL, DB_DSN)
    sync_examples(FEWSHOT_DIR, OLLAMA_MODEL, OLLAMA_BASE_URL, DB_DSN)

 
if __name__ == "__main__":
    asyncio.run(main())
