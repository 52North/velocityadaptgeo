"""Live similarities from the generator's stored embeddings (embeddings.jsonl).

Review never changes a paraphrase's text, only which paraphrases are kept and in which category, so
the stored vectors stay valid: the similarity matrix is computed once, and each lookup is a masked
argmax over one row of it.
"""

import base64
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from prompt_review.data import candidate_key, read_jsonl


@dataclass
class Embeddings:
    keys: list[str]  # candidates with a usable vector, in candidates.jsonl order
    sims: np.ndarray  # cosine similarities, len(keys) x len(keys)
    model: str | None = None
    warnings: list[str] = field(
        default_factory=list
    )  # candidates without a usable vector

    def __post_init__(self) -> None:
        self.index = {k: i for i, k in enumerate(self.keys)}


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def load_embeddings(run_dir: Path, candidates: list[dict]) -> Embeddings | None:
    """None when the run has no embeddings.jsonl. A candidate without a line, or whose text no longer
    matches the line's hash, gets no vector and a warning."""
    path = run_dir / "embeddings.jsonl"
    if not path.exists():
        return None
    lines = {line["key"]: line for line in read_jsonl(path)}
    keys, vectors, warnings, model = [], [], [], None
    for c in candidates:
        key = candidate_key(c)
        line = lines.get(key)
        if line is None:
            warnings.append(f"{key}: no stored embedding")
        elif line["text_sha1"] != _sha1(c["prompt"]):
            warnings.append(f"{key}: stored embedding is for a different text")
        else:
            keys.append(key)
            vectors.append(np.frombuffer(base64.b64decode(line["vector"]), dtype="<f4"))
            model = model or line.get("model")
    matrix = np.stack(vectors) if vectors else np.zeros((0, 0), dtype=np.float32)
    return Embeddings(keys, matrix @ matrix.T, model, warnings)


def closest_in_pool(
    key: str,
    category: str,
    pool: dict[str, str],
    emb: Embeddings,
    by_key: dict[str, dict],
) -> dict | None:
    """The closest other paraphrase of `pool` (key -> current category) to `key`, within `category` and
    in any category, as {"within": match, "any": match}, each {"key", "prompt", "sem"} or None.
    None when `key` itself has no vector. Ties go to the earlier candidate, as in the generator."""
    i = emb.index.get(key)
    if i is None:
        return None
    others = [
        (emb.index[k], k, cat) for k, cat in pool.items() if k != key and k in emb.index
    ]
    others.sort()  # candidates.jsonl order
    row = emb.sims[i]

    def best(entries) -> dict | None:
        if not entries:
            return None
        j = int(np.argmax(row[[e[0] for e in entries]]))
        k = entries[j][1]
        return {
            "key": k,
            "prompt": by_key[k]["prompt"],
            "sem": float(row[entries[j][0]]),
        }

    return {
        "within": best([e for e in others if e[2] == category]),
        "any": best(others),
    }


def closest_within_all(
    current: dict[str, str], pool: dict[str, str], emb: Embeddings
) -> dict[str, tuple[str, float] | None]:
    """For every candidate in `current` (key -> current category) that has a vector: the closest other
    paraphrase of `pool` (key -> current category) in the same category, as (key, similarity), or None.
    One matrix operation for all candidates, for the list view. Ties go to the earlier candidate."""
    q = [(k, c) for k, c in current.items() if k in emb.index]
    p = sorted((emb.index[k], k, c) for k, c in pool.items() if k in emb.index)
    if not q:
        return {}
    if not p:
        return {k: None for k, _ in q}
    qi = np.array([emb.index[k] for k, _ in q])
    pi = np.array([e[0] for e in p])
    sub = emb.sims[np.ix_(qi, pi)].copy()
    qc = np.array([c for _, c in q])
    pc = np.array([e[2] for e in p])
    sub[(qc[:, None] != pc[None, :]) | (qi[:, None] == pi[None, :])] = -np.inf
    best = sub.argmax(axis=1)
    out = {}
    for a, (k, _) in enumerate(q):
        b = best[a]
        out[k] = None if np.isneginf(sub[a, b]) else (p[b][1], float(sub[a, b]))
    return out


def kept_near_duplicates(
    kept: dict[str, str], emb: Embeddings, threshold: float
) -> dict[str, tuple[str, float]]:
    """Kept paraphrases whose closest other kept paraphrase in the same category is above the threshold:
    key -> (that paraphrase's key, similarity). Both members of a pair are listed."""
    return {
        k: m
        for k, m in closest_within_all(kept, kept, emb).items()
        if m and m[1] > threshold
    }
