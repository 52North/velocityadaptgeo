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
