"""Review state: candidates, decisions, filters and navigation, plus the per-category summary counts.
Pure: no file access and no drawing."""

from dataclasses import dataclass
from datetime import datetime

from prompt_review.data import candidate_key
from prompt_review.similarity import Embeddings, closest_in_pool, closest_within_all

BASE_FILTERS = ("all", "passed gates", "rejected by gates", "unreviewed")
NEAR_DUPLICATE_FILTER = "kept near-duplicates"  # only offered when the run has embeddings
DEFAULT_FILTER = "passed gates"
SORTS = ("file order", "similarity", "category")


def reason_group(c: dict) -> str | None:
    """`relative:green_space,size` -> `relative`."""
    return c["reject_reason"].split(":")[0] if c.get("reject_reason") else None


def current_category(c: dict, decisions: dict[str, dict]) -> str:
    """The category of the candidate's manual decision (after a move) if it has one, else the generated one."""
    review = decisions.get(candidate_key(c))
    return review["category"] if review else c["category"]


def kept(candidates: list[dict], decisions: dict[str, dict]) -> dict[str, str]:
    """Kept paraphrases, key -> current category: manually accepted ones, plus unreviewed ones the gates
    accepted. Order follows candidates.jsonl."""
    out = {}
    for c in candidates:
        review = decisions.get(candidate_key(c))
        if (review["decision"] == "accept") if review else c["accepted"]:
            out[candidate_key(c)] = current_category(c, decisions)
    return out


class ReviewState:
    def __init__(self, candidates: list[dict], decisions: dict[str, dict] | None = None,
                 embeddings: Embeddings | None = None, threshold: float | None = None, categories: list[str] | None = None):
        self.candidates = candidates
        self.decisions = dict(decisions or {})
        self.pending_notes: dict[str, str] = {}  # notes typed before the candidate was decided
        self.by_key = {candidate_key(c): c for c in candidates}
        self.number = {candidate_key(c): i for i, c in enumerate(candidates, 1)}  # position in the run
        self.embeddings = embeddings  # None: no live similarities, only the stored closest_* fields
        self.threshold = threshold  # the run's near-duplicate threshold
        reasons = sorted({r for c in candidates if (r := reason_group(c))})
        live = [NEAR_DUPLICATE_FILTER] if embeddings is not None else []
        self.filters = [*BASE_FILTERS, *live, *(f"reason: {r}" for r in reasons)]
        self.filter = DEFAULT_FILTER
        self.sort = SORTS[0]
        # Category order for sorting; the run's typology order when given.
        self.categories = list(categories or dict.fromkeys(c["category"] for c in candidates))
        self.index = 0  # position within visible()
        self._cache: dict[str, tuple] = {}  # name -> (fingerprint, value)

    def _cached(self, name: str, fingerprint, compute):
        hit = self._cache.get(name)
        if hit is None or hit[0] != fingerprint:
            hit = self._cache[name] = (fingerprint, compute())
        return hit[1]

    def _decisions_fingerprint(self) -> tuple:
        """Changes whenever a decision or a category changes; notes don't matter here."""
        return tuple((k, d["decision"], d["category"]) for k, d in self.decisions.items())

    # --- live similarity (review_similarity_plan.md) ---

    def kept(self) -> dict[str, str]:
        return kept(self.candidates, self.decisions)

    def live(self, c: dict) -> dict | None:
        """Closest other kept paraphrase within the candidate's current category and in any category,
        given the decisions so far. None without embeddings or without a vector for this candidate."""
        if self.embeddings is None:
            return None
        return closest_in_pool(candidate_key(c), current_category(c, self.decisions), self.kept(), self.embeddings, self.by_key)

    def within_all(self) -> dict[str, tuple[str, float] | None]:
        """Live closest kept paraphrase in each candidate's current category: key -> (key, similarity) or
        None. Candidates without a vector are missing. Empty without embeddings. Cached until a decision changes."""
        def compute():
            if self.embeddings is None:
                return {}
            current = {candidate_key(c): current_category(c, self.decisions) for c in self.candidates}
            return closest_within_all(current, self.kept(), self.embeddings)
        return self._cached("within", self._decisions_fingerprint(), compute)

    def similarity(self, c: dict) -> tuple[str, float] | None:
        """The closest match in the candidate's category shown in the list: live with embeddings, else the
        one stored at generation."""
        if self.embeddings is not None:
            return self.within_all().get(candidate_key(c))
        m = c.get("closest_accepted")
        return (m["key"], m["sem"]) if m else None

    def near_duplicates(self) -> dict[str, tuple[str, float]]:
        """Kept paraphrases with a kept near-duplicate in their category: key -> (other key, similarity)."""
        if self.embeddings is None or self.threshold is None:
            return {}
        within = self.within_all()
        return {k: m for k in self.kept() if (m := within.get(k)) and m[1] > self.threshold}

    # --- filters and navigation ---

    def _matches(self, c: dict, near: dict | None = None) -> bool:
        f = self.filter
        if f == "all":
            return True
        if f == "passed gates":
            return c["accepted"]
        if f == "rejected by gates":
            return not c["accepted"]
        if f == "unreviewed":
            return candidate_key(c) not in self.decisions
        if f == NEAR_DUPLICATE_FILTER:
            return candidate_key(c) in near
        return reason_group(c) == f.removeprefix("reason: ")

    def visible(self) -> list[dict]:
        """The candidates in the current filter, in the current sort order. Cached; don't modify the list."""
        def compute():
            near = self.near_duplicates() if self.filter == NEAR_DUPLICATE_FILTER else None
            v = [c for c in self.candidates if self._matches(c, near)]
            if self.sort == "similarity":  # most similar first; no match last. Stable: ties keep file order
                v.sort(key=lambda c: -(m[1]) if (m := self.similarity(c)) else float("inf"))
            elif self.sort == "category":
                order = {k: i for i, k in enumerate(self.categories)}
                v.sort(key=lambda c: order.get(current_category(c, self.decisions), len(order)))
            return v
        return self._cached("visible", (self.filter, self.sort, self._decisions_fingerprint()), compute)

    def current(self) -> dict | None:
        v = self.visible()
        return v[self.index] if v else None

    def _clamp(self) -> None:
        self.index = max(0, min(self.index, len(self.visible()) - 1))

    def move(self, delta: int) -> None:
        self.index += delta
        self._clamp()

    def first(self) -> None:
        self.index = 0

    def last(self) -> None:
        self.index = len(self.visible()) - 1
        self._clamp()

    def next_unreviewed(self) -> bool:
        v = self.visible()
        n = len(v)
        for step in range(1, n + 1):
            i = (self.index + step) % n
            if candidate_key(v[i]) not in self.decisions:
                self.index = i
                return True
        return False

    def _change(self, apply, advance: bool) -> None:
        """Apply a change to the current candidate, then land on the right candidate even if the
        change removed the current one from the filter (e.g. deciding while filtering unreviewed)."""
        before = self.visible()
        if not before:
            return
        current = before[self.index]
        target = before[self.index + 1] if advance and self.index + 1 < len(before) else current
        apply(candidate_key(current))
        after = [candidate_key(c) for c in self.visible()]
        for wanted in (target, current):
            if candidate_key(wanted) in after:
                self.index = after.index(candidate_key(wanted))
                return
        self._clamp()

    def decide(self, decision: str, category: str | None = None) -> None:
        def apply(key: str) -> None:
            c = next(c for c in self.candidates if candidate_key(c) == key)
            note = self.pending_notes.pop(key, None) or self.decisions.get(key, {}).get("note", "")
            self.decisions[key] = {
                "decision": decision,
                "category": category or c["category"],
                "note": note,
                "at": datetime.now().isoformat(timespec="seconds"),
            }

        self._change(apply, advance=True)

    def set_note(self, note: str) -> None:
        """A note on an undecided candidate is kept and saved with the decision later."""
        c = self.current()
        if c is None:
            return
        key = candidate_key(c)
        if key in self.decisions:
            self.decisions[key]["note"] = note
        else:
            self.pending_notes[key] = note

    def clear(self) -> None:
        self._change(lambda key: self.decisions.pop(key, None), advance=False)

    def _keep_current(self, change) -> None:
        keep = self.current()
        change()
        keys = [candidate_key(c) for c in self.visible()]
        self.index = keys.index(candidate_key(keep)) if keep and candidate_key(keep) in keys else 0

    def cycle_filter(self) -> None:
        def change():
            self.filter = self.filters[(self.filters.index(self.filter) + 1) % len(self.filters)]
        self._keep_current(change)

    def cycle_sort(self) -> None:
        """Also the order of moving through candidates on the review page."""
        def change():
            self.sort = SORTS[(SORTS.index(self.sort) + 1) % len(SORTS)]
        self._keep_current(change)

    def go_to(self, key: str) -> bool:
        keys = [candidate_key(c) for c in self.visible()]
        if key not in keys:
            return False
        self.index = keys.index(key)
        return True

    def counts(self, category: str | None = None) -> tuple[int, int, int]:
        """(accepted, rejected, unreviewed) over all candidates, optionally of one category."""
        acc = rej = todo = 0
        for c in self.candidates:
            if category and c["category"] != category:
                continue
            d = self.decisions.get(candidate_key(c))
            if d is None:
                todo += 1
            elif d["decision"] == "accept":
                acc += 1
            else:
                rej += 1
        return acc, rej, todo


def match_status(key: str, by_key: dict[str, dict], decisions: dict[str, dict]) -> tuple[str, bool, str] | None:
    """(current category, moved, review status) of a matched candidate, or None if it isn't in the run.
    The current category is the one of its manual decision when that is an accept (it may have been moved),
    otherwise the category it was generated for."""
    c = by_key.get(key)
    if c is None:
        return None
    review = decisions.get(key)
    if review is None:
        return c["category"], False, "unreviewed"
    if review["decision"] == "accept":
        return review["category"], review["category"] != c["category"], "accept"
    return c["category"], False, "reject"


# --- summary -----------------------------------------------------------------------------------


@dataclass
class SummaryRow:
    category: str
    generated: int = 0
    gate_accepted: int = 0
    gate_rejected: int = 0
    review_accepted: int = 0  # counted under the category the candidate was generated for
    review_rejected: int = 0
    unreviewed: int = 0
    added: int = 0  # accepted in review and moved into this category
    subtracted: int = 0  # accepted in review and moved out of this category

    @property
    def final(self) -> int:
        return self.review_accepted - self.subtracted + self.added


@dataclass
class Overrules:
    gate_rejected_accepted: int = 0
    gate_accepted_rejected: int = 0


def summarize(candidates: list[dict], decisions: dict[str, dict], categories: list[str]) -> tuple[list[SummaryRow], Overrules]:
    """Per-category counts for `prompt-review --summary`. A move to another category counts as an
    accept, under the category the candidate was generated for, and as subtracted there / added there."""
    rows = {key: SummaryRow(key) for key in categories}
    overrules = Overrules()
    for c in candidates:
        row = rows[c["category"]]
        row.generated += 1
        if c["accepted"]:
            row.gate_accepted += 1
        else:
            row.gate_rejected += 1
        review = decisions.get(candidate_key(c))
        if review is None:
            row.unreviewed += 1
            continue
        if review["decision"] == "accept":
            row.review_accepted += 1
            if review["category"] != c["category"]:
                row.subtracted += 1
                rows[review["category"]].added += 1
            if not c["accepted"]:
                overrules.gate_rejected_accepted += 1
        else:
            row.review_rejected += 1
            if c["accepted"]:
                overrules.gate_accepted_rejected += 1
    return list(rows.values()), overrules
