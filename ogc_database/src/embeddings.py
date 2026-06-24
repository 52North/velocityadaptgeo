"""Embedding generation for process metadata."""

import logging

from sentence_transformers import SentenceTransformer

log = logging.getLogger("ogc-indexer")


def build_embedding_text(meta: dict) -> str:
    """Build a concatenated text representation of process metadata for embedding.

    Combines title, description, keywords, and input/output descriptions
    into a single text that captures the semantic meaning of the process.

    Args:
        meta: Process metadata dict

    Returns:
        Concatenated text for embedding
    """
    parts = [
        meta.get("title", ""),
        meta.get("description", ""),
        " ".join(meta.get("keywords", []) or []),
    ]
    # Include input/output descriptions if present
    for io_key in ("inputs", "outputs"):
        io = meta.get(io_key) or {}
        if isinstance(io, dict):
            for k, v in io.items():
                if isinstance(v, dict):
                    parts.append(f"{k}: {v.get('title', '')} {v.get('description', '')}")
    return "\n".join(p for p in parts if p).strip()


def encode_texts(model: SentenceTransformer, texts: list[str]) -> list[list[float]]:
    """Encode a list of texts using the embedding model.

    Args:
        model: Loaded SentenceTransformer model
        texts: List of text strings to embed

    Returns:
        List of embedding vectors
    """
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=True)
    return embeddings.tolist()
