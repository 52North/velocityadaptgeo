from helpers import CANDIDATES, cand, current_key, decision, keys

from prompt_review.state import ReviewState, match_status, summarize


def test_default_filter_and_reason_filters():
    s = ReviewState(CANDIDATES)
    assert keys(s.visible()) == ["lexical#1", "lexical#3", "syntactic#2"]
    assert s.filters[4:] == ["reason: near_duplicate", "reason: relative"]
    s.filter = "reason: relative"
    assert keys(s.visible()) == ["syntactic#1"]


def test_navigation_clamps_at_both_ends():
    s = ReviewState(CANDIDATES)
    s.move(-1)
    assert current_key(s) == "lexical#1"
    s.move(10)
    assert current_key(s) == "syntactic#2"
    s.first()
    assert s.index == 0


def test_decide_advances_and_records():
    s = ReviewState(CANDIDATES)
    s.decide("accept")
    assert s.decisions["lexical#1"]["decision"] == "accept"
    assert s.decisions["lexical#1"]["category"] == "lexical"
    assert current_key(s) == "lexical#3"
    s.decide("accept", "discourse")
    assert s.decisions["lexical#3"]["category"] == "discourse"


def test_decide_on_last_stays_on_last():
    s = ReviewState(CANDIDATES)
    s.last()
    s.decide("reject")
    assert current_key(s) == "syntactic#2"


def test_decide_in_unreviewed_filter_lands_on_next():
    s = ReviewState(CANDIDATES)
    s.filter = "unreviewed"
    s.decide("accept")
    assert current_key(s) == "lexical#2"
    assert "lexical#1" not in keys(s.visible())


def test_clear_and_next_unreviewed():
    s = ReviewState(CANDIDATES)
    s.decide("accept")
    s.move(-1)
    s.clear()
    assert "lexical#1" not in s.decisions
    s.decide("accept")  # auto-advances to lexical#3
    assert s.next_unreviewed()  # the next unreviewed after the current one
    assert current_key(s) == "syntactic#2"


def test_note_before_and_afterdecision():
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
    assert s.filter == "passed gates" and current_key(s) == "lexical#3"
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


# --- summary -------------------------------------------------------------------------------------

CATS = ["lexical", "syntactic", "discourse"]


def test_summary_counts_and_moves():
    candidates = [
        cand("lexical", 1),  # gate accept, review accept
        cand(
            "lexical", 2, False, "near_duplicate"
        ),  # gate reject, review accept -> overrule
        cand("lexical", 3),  # gate accept, moved to syntactic
        cand("syntactic", 1),  # gate accept, review reject
        cand("syntactic", 2, False, "constraint:target"),  # unreviewed
        cand("discourse", 1),  # gate accept, moved to lexical
    ]
    decisions = {
        "lexical#1": decision("accept", "lexical"),
        "lexical#2": decision("accept", "lexical"),
        "lexical#3": decision("accept", "syntactic"),
        "syntactic#1": decision("reject", "syntactic"),
        "discourse#1": decision("accept", "lexical"),
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
    assert (overrules.gate_rejected_accepted, overrules.gate_accepted_rejected) == (
        1,
        1,
    )


def test_summary_rejected_with_other_category_is_not_a_move():
    rows, _ = summarize(
        [cand("lexical", 1)], {"lexical#1": decision("reject", "syntactic")}, CATS
    )
    assert [(r.added, r.subtracted) for r in rows] == [(0, 0), (0, 0), (0, 0)]


def test_summary_without_reviews():
    rows, overrules = summarize(CANDIDATES, {}, ["lexical", "syntactic"])
    assert [(r.generated, r.unreviewed, r.final) for r in rows] == [
        (3, 3, 0),
        (2, 2, 0),
    ]
    assert (overrules.gate_rejected_accepted, overrules.gate_accepted_rejected) == (
        0,
        0,
    )


def test_match_status():
    s = ReviewState(CANDIDATES)
    assert match_status("lexical#1", s.by_key, {}) == ("lexical", False, "unreviewed")
    assert match_status(
        "lexical#1", s.by_key, {"lexical#1": decision("accept", "lexical")}
    ) == ("lexical", False, "accept")
    assert match_status(
        "lexical#1", s.by_key, {"lexical#1": decision("accept", "discourse")}
    ) == ("discourse", True, "accept")
    assert match_status(
        "lexical#1", s.by_key, {"lexical#1": decision("reject", "lexical")}
    ) == ("lexical", False, "reject")
    assert match_status("lexical#99", s.by_key, {}) is None


# --- sorting (review_table_plan.md) --------------------------------------------------------------

from helpers import embeddings_for

from prompt_review.state import SORTS


def test_sort_by_similarity_and_category(tmp_path):
    s = ReviewState(
        CANDIDATES, None, embeddings_for(tmp_path), 0.97, ["syntactic", "lexical"]
    )
    s.filter = "all"
    assert s.sort == "file order" and keys(s.visible()) == keys(CANDIDATES)
    s.cycle_sort()
    # within category, live: lexical#2 -> lexical#1 0.995, lexical#1 -> lexical#3 0.6, lexical#3 -> lexical#1 0.6,
    # syntactic#1 -> syntactic#2 0.196, syntactic#2: no other kept syntactic one (last)
    assert s.sort == "similarity"
    assert keys(s.visible()) == [
        "lexical#2",
        "lexical#1",
        "lexical#3",
        "syntactic#1",
        "syntactic#2",
    ]
    s.cycle_sort()
    assert (
        s.sort == "category"
    )  # the given category order, file order within a category
    assert keys(s.visible()) == [
        "syntactic#1",
        "syntactic#2",
        "lexical#1",
        "lexical#2",
        "lexical#3",
    ]
    s.cycle_sort()
    assert s.sort == "seed similarity"
    s.cycle_sort()
    assert s.sort == SORTS[0]


def test_sort_keeps_the_current_candidate_and_sets_the_review_order(tmp_path):
    s = ReviewState(CANDIDATES, None, embeddings_for(tmp_path), 0.97)
    s.filter = "all"
    s.go_to("lexical#3")
    s.cycle_sort()  # similarity
    assert current_key(s) == "lexical#3"
    s.move(1)  # moving follows the sorted order
    assert current_key(s) == "syntactic#1"


def test_category_sort_follows_moves():
    s = ReviewState(
        CANDIDATES,
        {"syntactic#2": decision("accept", "lexical")},
        categories=["lexical", "syntactic"],
    )
    s.filter, s.sort = "all", "category"
    assert keys(s.visible()) == [
        "lexical#1",
        "lexical#2",
        "lexical#3",
        "syntactic#2",
        "syntactic#1",
    ]


def test_similarity_sort_without_embeddings_uses_the_stored_matches():
    stored = [
        {
            **c,
            "closest_accepted": {"key": "x", "prompt": "x", "sem": sem}
            if sem
            else None,
        }
        for c, sem in zip(CANDIDATES, [None, 0.9, 0.5, 0.99, None])
    ]
    s = ReviewState(stored)
    s.filter, s.sort = "all", "similarity"
    assert keys(s.visible()) == [
        "syntactic#1",
        "lexical#2",
        "lexical#3",
        "lexical#1",
        "syntactic#2",
    ]


def test_seed_similarity_sort():
    scored = [
        {**c, "sem": sem} if sem is not None else c
        for c, sem in zip(CANDIDATES, [0.8, None, 0.95, 0.7, 0.8])
    ]
    s = ReviewState(scored)
    s.filter, s.sort = "all", "seed similarity"
    # most similar to the seed first, ties in file order, no score last
    assert keys(s.visible()) == [
        "lexical#3",
        "lexical#1",
        "syntactic#2",
        "syntactic#1",
        "lexical#2",
    ]


def test_visible_cache_follows_direct_decision_changes():
    s = ReviewState(CANDIDATES)
    s.filter = "unreviewed"
    assert len(s.visible()) == 5
    s.decisions["lexical#1"] = decision("accept", "lexical")  # changed without decide()
    assert "lexical#1" not in keys(s.visible())


# --- accepted/rejected filter (review_accepted_filter_plan.md) ---


def test_status_follows_the_current_decision():
    s = ReviewState(
        CANDIDATES,
        {
            "lexical#1": decision("reject", "lexical"),  # gate-accepted, rejected
            "lexical#2": decision("accept", "lexical"),  # gate-rejected, accepted
            "syntactic#2": decision("accept", "lexical"),  # moved: counts as accept
        },
    )
    s.filter = "all"
    s.status = "currently accepted"
    accepted = keys(s.visible())
    assert accepted == ["lexical#2", "lexical#3", "syntactic#2"]
    s.status = "currently rejected"
    rejected = keys(s.visible())
    assert rejected == ["lexical#1", "syntactic#1"]
    assert sorted(accepted + rejected) == sorted(keys(CANDIDATES))  # a partition


def test_status_combines_with_the_filter():
    s = ReviewState(CANDIDATES, {"lexical#2": decision("accept", "lexical")})
    s.filter, s.status = "rejected by gates", "currently accepted"
    assert keys(s.visible()) == ["lexical#2"]  # gate rejections overruled in review
    assert s.filter_label() == "rejected by gates · currently accepted"
    s.status = "any"
    assert s.filter_label() == "rejected by gates"


def test_cycle_status_wraps_and_keeps_current_when_possible():
    s = ReviewState(CANDIDATES)
    s.filter = "all"
    s.move(2)  # lexical#3, gate-accepted
    s.cycle_status()
    assert s.status == "currently accepted" and current_key(s) == "lexical#3"
    s.cycle_status()
    assert s.status == "currently rejected" and s.index == 0
    s.cycle_status()
    assert s.status == "any"


def test_deciding_under_currently_accepted_removes_the_candidate():
    s = ReviewState(CANDIDATES)
    s.filter, s.status = "all", "currently accepted"
    s.decide("reject")  # lexical#1 leaves the filter, lands on the next
    assert "lexical#1" not in keys(s.visible()) and current_key(s) == "lexical#3"
    s.filter, s.status = "all", "currently accepted"
    s.decisions["lexical#2"] = decision("accept", "lexical")
    assert s.go_to("lexical#2")
    s.clear()  # undo the overrule: gate-rejected again
    assert "lexical#2" not in keys(s.visible())
