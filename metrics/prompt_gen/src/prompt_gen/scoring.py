"""Semantic (wording) and pragmatic (intent) similarity from two local embedding models."""

import hashlib

import numpy as np
from sentence_transformers import SentenceTransformer

from prompt_gen.config import EmbeddingConfig


class Embedder:
    """Normalized embeddings, cached by text hash."""

    def __init__(self, model: SentenceTransformer, prefix: str = ""):
        self.model = model
        self.prefix = prefix
        self._cache: dict[str, np.ndarray] = {}

    def embed(self, texts: list[str]) -> np.ndarray:
        keys = [hashlib.sha1(t.encode()).hexdigest() for t in texts]
        todo = [(k, t) for k, t in zip(keys, texts) if k not in self._cache]
        if todo:
            vectors = self.model.encode(
                [self.prefix + t for _, t in todo], normalize_embeddings=True
            )
            for (k, _), v in zip(todo, vectors):
                self._cache[k] = v
        return np.stack([self._cache[k] for k in keys])


class Scorer:
    def __init__(self, config: EmbeddingConfig):
        self.semantic = Embedder(SentenceTransformer(config.semantic, device="cpu"))
        e5 = SentenceTransformer(config.pragmatic, device="cpu")
        # E5 instruct format, applied to both texts of a symmetric comparison.
        self.pragmatic = Embedder(
            e5, f"Instruct: {config.pragmatic_instruction}\nQuery: "
        )
        # Same model without the instruction, to test whether the instruction helps.
        self.pragmatic_plain = Embedder(e5)

    @staticmethod
    def _sim(embedder: Embedder, text: str, others: list[str]) -> np.ndarray:
        vectors = embedder.embed([text, *others])
        return vectors[1:] @ vectors[0]

    def semantic_similarities(self, text: str, others: list[str]) -> list[float]:
        return (
            [float(x) for x in self._sim(self.semantic, text, others)] if others else []
        )

    def score(
        self,
        candidate: str,
        seed: str,
        same_category: list[str],
        other_categories: list[str],
    ) -> dict:
        sem_seed, *sem_same = self._sim(
            self.semantic, candidate, [seed, *same_category]
        )
        prag, prag_plain = (
            float(self._sim(e, candidate, [seed])[0])
            for e in (self.pragmatic, self.pragmatic_plain)
        )
        sem_other = (
            self._sim(self.semantic, candidate, other_categories)
            if other_categories
            else []
        )
        return {
            "sem": float(sem_seed),
            "prag": prag,
            "prag_no_instruction": prag_plain,
            "max_sem_same_category": float(max(sem_same)) if sem_same else None,
            "max_sem_other_categories": float(max(sem_other))
            if len(sem_other)
            else None,
        }
