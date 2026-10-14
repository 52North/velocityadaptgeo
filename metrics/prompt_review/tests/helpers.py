"""Small hand-made candidates and decisions shared by the tests."""

from prompt_review.data import candidate_key


def cand(category: str, attempt: int, accepted: bool = True, reason: str | None = None) -> dict:
    return {"category": category, "attempt": attempt, "prompt": f"{category} {attempt}", "accepted": accepted,
            "reject_reason": reason, "judge": {}}


CANDIDATES = [
    cand("lexical", 1),
    cand("lexical", 2, False, "near_duplicate"),
    cand("lexical", 3),
    cand("syntactic", 1, False, "relative:green_space"),
    cand("syntactic", 2),
]


def keys(cands):
    return [candidate_key(c) for c in cands]


def decision(decision, category):
    return {"decision": decision, "category": category, "note": "", "at": "2026-10-14T09:00:00"}


# Unit vectors for CANDIDATES, chosen so the similarities are easy to reason about:
# lexical#1 · lexical#2 ≈ 0.995, lexical#1 · syntactic#2 ≈ 0.981, lexical#1 · lexical#3 = 0.6.
VECTORS = {
    "lexical#1": [1, 0, 0],
    "lexical#2": [1, 0.1, 0],
    "lexical#3": [0.6, 0.8, 0],
    "syntactic#1": [0, 0, 1],
    "syntactic#2": [0.98, 0, 0.2],
}


def embedding_lines(candidates, vectors=VECTORS) -> str:
    """embeddings.jsonl content in the generator's format."""
    import base64
    import hashlib
    import json

    import numpy as np

    out = []
    for c in candidates:
        key = candidate_key(c)
        if key not in vectors:
            continue
        v = np.asarray(vectors[key], dtype="<f4")
        v = v / np.linalg.norm(v)
        out.append(json.dumps({"key": key, "text_sha1": hashlib.sha1(c["prompt"].encode()).hexdigest(), "model": "m",
                               "dim": len(v), "vector": base64.b64encode(v.astype("<f4").tobytes()).decode()}))
    return "".join(line + "\n" for line in out)


def embeddings_for(tmp_path, candidates=CANDIDATES, vectors=VECTORS):
    from prompt_review.similarity import load_embeddings
    (tmp_path / "embeddings.jsonl").write_text(embedding_lines(candidates, vectors))
    return load_embeddings(tmp_path, candidates)
