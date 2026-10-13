import json

from prompt_gen.review import ReviewState, candidate_key, load_decisions, save, word_diff


def _cand(category: str, attempt: int, accepted: bool = True, reason: str | None = None) -> dict:
    return {"category": category, "attempt": attempt, "prompt": f"{category} {attempt}", "accepted": accepted,
            "reject_reason": reason, "judge": {}}


CANDIDATES = [
    _cand("lexical", 1),
    _cand("lexical", 2, False, "near_duplicate"),
    _cand("lexical", 3),
    _cand("syntactic", 1, False, "relative:green_space"),
    _cand("syntactic", 2),
]


def keys(cands):
    return [candidate_key(c) for c in cands]


def test_default_filter_and_reason_filters():
    s = ReviewState(CANDIDATES)
    assert keys(s.visible()) == ["lexical#1", "lexical#3", "syntactic#2"]
    assert s.filters[4:] == ["reason: near_duplicate", "reason: relative"]
    s.filter = "reason: relative"
    assert keys(s.visible()) == ["syntactic#1"]


def test_navigation_clamps_at_both_ends():
    s = ReviewState(CANDIDATES)
    s.move(-1)
    assert candidate_key(s.current()) == "lexical#1"
    s.move(10)
    assert candidate_key(s.current()) == "syntactic#2"
    s.first()
    assert s.index == 0


def test_decide_advances_and_records():
    s = ReviewState(CANDIDATES)
    s.decide("accept")
    assert s.decisions["lexical#1"]["decision"] == "accept"
    assert s.decisions["lexical#1"]["category"] == "lexical"
    assert candidate_key(s.current()) == "lexical#3"
    s.decide("accept", "discourse")
    assert s.decisions["lexical#3"]["category"] == "discourse"


def test_decide_on_last_stays_on_last():
    s = ReviewState(CANDIDATES)
    s.last()
    s.decide("reject")
    assert candidate_key(s.current()) == "syntactic#2"


def test_decide_in_unreviewed_filter_lands_on_next():
    s = ReviewState(CANDIDATES)
    s.filter = "unreviewed"
    s.decide("accept")
    assert candidate_key(s.current()) == "lexical#2"
    assert "lexical#1" not in keys(s.visible())


def test_clear_and_next_unreviewed():
    s = ReviewState(CANDIDATES)
    s.decide("accept")
    s.move(-1)
    s.clear()
    assert "lexical#1" not in s.decisions
    s.decide("accept")  # auto-advances to lexical#3
    assert s.next_unreviewed()  # the next unreviewed after the current one
    assert candidate_key(s.current()) == "syntactic#2"


def test_note_before_and_after_decision():
    s = ReviewState(CANDIDATES)
    s.set_note("check grammar")
    s.decide("reject")
    assert s.decisions["lexical#1"]["note"] == "check grammar"
    s.move(-1)
    s.set_note("fixed")
    assert s.decisions["lexical#1"]["note"] == "fixed"
    s.decide("accept")  # changing the decision keeps the note
    assert s.decisions["lexical#1"]["note"] == "fixed"


def test_cycle_filter_keeps_current_when_possible():
    s = ReviewState(CANDIDATES)
    s.filter = "all"
    s.index = 2  # lexical#3
    s.cycle_filter()  # -> passed gates, which contains lexical#3
    assert s.filter == "passed gates" and candidate_key(s.current()) == "lexical#3"
    s.cycle_filter()  # -> rejected by gates, which doesn't
    assert s.filter == "rejected by gates" and s.index == 0
    for _ in range(len(s.filters) - 2):
        s.cycle_filter()
    assert s.filter == "all"  # wraps around


def test_counts():
    s = ReviewState(CANDIDATES)
    s.decide("accept")
    s.decide("reject")
    assert s.counts() == (1, 1, 3)
    assert s.counts("lexical") == (1, 1, 1)


def test_save_rewrites_and_leaves_candidates_untouched(tmp_path):
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text("".join(json.dumps(c) + "\n" for c in CANDIDATES))
    before = candidates_path.read_bytes()
    path = tmp_path / "reviewed.jsonl"

    s = ReviewState(CANDIDATES)
    s.decide("reject")
    save(path, s)
    s.move(-1)
    s.decide("accept")  # change the decision: the file is rewritten, not appended
    save(path, s)

    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(lines) == 1
    assert lines[0]["review"]["decision"] == "accept"
    assert {k: v for k, v in lines[0].items() if k != "review"} == CANDIDATES[0]
    assert candidates_path.read_bytes() == before
    assert not (tmp_path / "reviewed.jsonl.tmp").exists()
    assert load_decisions(path) == {"lexical#1": lines[0]["review"]}


def test_word_diff():
    t = word_diff("Identify all areas in Münster", "Locate every area in Münster")
    struck = "".join(t.plain[s.start:s.end] for s in t.spans if "strike" in str(s.style))
    added = "".join(t.plain[s.start:s.end] for s in t.spans if "green" in str(s.style))
    assert struck.split() == ["Identify", "all", "areas"]
    assert added.split() == ["Locate", "every", "area"]
    assert "in Münster" in t.plain
