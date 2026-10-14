"""Review state: candidates, decisions, filters and navigation, plus the per-category summary counts.
Pure: no file access and no drawing."""

from dataclasses import dataclass
from datetime import datetime

from prompt_review.data import candidate_key

BASE_FILTERS = ("all", "passed gates", "rejected by gates", "unreviewed")
DEFAULT_FILTER = "passed gates"


def reason_group(c: dict) -> str | None:
    """`relative:green_space,size` -> `relative`."""
    return c["reject_reason"].split(":")[0] if c.get("reject_reason") else None


class ReviewState:
    def __init__(self, candidates: list[dict], decisions: dict[str, dict] | None = None):
        self.candidates = candidates
        self.decisions = dict(decisions or {})
        self.pending_notes: dict[str, str] = {}  # notes typed before the candidate was decided
        self.by_key = {candidate_key(c): c for c in candidates}
        self.threshold: float | None = None  # the run's near-duplicate threshold, for the closest-match panel
        reasons = sorted({r for c in candidates if (r := reason_group(c))})
        self.filters = [*BASE_FILTERS, *(f"reason: {r}" for r in reasons)]
        self.filter = DEFAULT_FILTER
        self.index = 0  # position within visible()

    def _matches(self, c: dict) -> bool:
        f = self.filter
        if f == "all":
            return True
        if f == "passed gates":
            return c["accepted"]
        if f == "rejected by gates":
            return not c["accepted"]
        if f == "unreviewed":
            return candidate_key(c) not in self.decisions
        return reason_group(c) == f.removeprefix("reason: ")

    def visible(self) -> list[dict]:
        return [c for c in self.candidates if self._matches(c)]

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

    def cycle_filter(self) -> None:
        keep = self.current()
        self.filter = self.filters[(self.filters.index(self.filter) + 1) % len(self.filters)]
        keys = [candidate_key(c) for c in self.visible()]
        self.index = keys.index(candidate_key(keep)) if keep and candidate_key(keep) in keys else 0

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
