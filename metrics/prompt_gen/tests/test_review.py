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


# --- summary -------------------------------------------------------------------------------------

from prompt_gen.review import print_summary, summarize  # noqa: E402

CATS = ["lexical", "syntactic", "discourse"]


def _decision(decision, category):
    return {"decision": decision, "category": category, "note": "", "at": "2026-10-14T09:00:00"}


def test_summary_counts_and_moves():
    candidates = [
        _cand("lexical", 1),                          # gate accept, review accept
        _cand("lexical", 2, False, "near_duplicate"),  # gate reject, review accept -> overrule
        _cand("lexical", 3),                          # gate accept, moved to syntactic
        _cand("syntactic", 1),                        # gate accept, review reject
        _cand("syntactic", 2, False, "constraint:target"),  # unreviewed
        _cand("discourse", 1),                        # gate accept, moved to lexical
    ]
    decisions = {
        "lexical#1": _decision("accept", "lexical"),
        "lexical#2": _decision("accept", "lexical"),
        "lexical#3": _decision("accept", "syntactic"),
        "syntactic#1": _decision("reject", "syntactic"),
        "discourse#1": _decision("accept", "lexical"),
    }
    rows, overrules = summarize(candidates, decisions, CATS)
    lex, syn, dis = rows
    assert (lex.generated, lex.gate_accepted, lex.gate_rejected) == (3, 2, 1)
    assert (lex.review_accepted, lex.review_rejected, lex.unreviewed) == (3, 0, 0)
    assert (lex.added, lex.subtracted, lex.final) == (1, 1, 3)
    assert (syn.review_accepted, syn.review_rejected, syn.unreviewed) == (0, 1, 1)
    assert (syn.added, syn.subtracted, syn.final) == (1, 0, 1)
    assert (dis.review_accepted, dis.added, dis.subtracted, dis.final) == (1, 0, 1, 0)
    assert sum(r.added for r in rows) == sum(r.subtracted for r in rows) == 2
    assert sum(r.final for r in rows) == sum(r.review_accepted for r in rows)
    assert (overrules.gate_rejected_accepted, overrules.gate_accepted_rejected) == (1, 1)


def test_summary_rejected_with_other_category_is_not_a_move():
    rows, _ = summarize([_cand("lexical", 1)], {"lexical#1": _decision("reject", "syntactic")}, CATS)
    assert [(r.added, r.subtracted) for r in rows] == [(0, 0), (0, 0), (0, 0)]


def test_summary_without_reviews():
    rows, overrules = summarize(CANDIDATES, {}, ["lexical", "syntactic"])
    assert [(r.generated, r.unreviewed, r.final) for r in rows] == [(3, 3, 0), (2, 2, 0)]
    assert (overrules.gate_rejected_accepted, overrules.gate_accepted_rejected) == (0, 0)


def test_print_summary_on_a_run_folder(tmp_path):
    from rich.console import Console
    run = tmp_path / "run"
    run.mkdir()
    (run / "candidates.jsonl").write_text("".join(json.dumps(c) + "\n" for c in CANDIDATES) + json.dumps(
        {"category": "lexical", "attempt": 9, "prompt": None, "accepted": False, "reject_reason": "generation_error: x"}) + "\n")
    (run / "config.json").write_text(json.dumps({"n_per_category": 30, "seed": {"id": "s"}}))
    (run / "config_20261014-090000.json").write_text(json.dumps({"n_per_category": 2, "seed": {"id": "s"}}))
    console = Console(record=True, width=150, color_system=None)
    print_summary(run, console)  # no reviewed.jsonl yet
    out = console.export_text()
    assert "2 generation session(s)" in out and "target 2 per category" in out  # latest session's config
    assert "1 generation error(s)" in out
    assert "overruled" not in out
