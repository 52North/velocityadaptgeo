import json

import pytest
from helpers import CANDIDATES, VECTORS, decision, embedding_lines, embeddings_for, keys

from prompt_review.similarity import load_embeddings
from prompt_review.state import (
    NEAR_DUPLICATE_FILTER,
    ReviewState,
    current_category,
    kept,
)


@pytest.fixture
def emb(tmp_path):
    return embeddings_for(tmp_path)


def _state(emb, decisions=None):
    return ReviewState(CANDIDATES, decisions, emb, threshold=0.97)


def _keys(live):
    return live["within"] and live["within"]["key"], live["any"] and live["any"]["key"]


# --- loading -------------------------------------------------------------------------------------


def test_load_embeddings_round_trip(emb):
    assert emb.keys == keys(CANDIDATES) and emb.warnings == [] and emb.model == "m"
    assert emb.sims[0, 0] == pytest.approx(1.0)
    assert emb.sims[emb.index["lexical#1"], emb.index["lexical#3"]] == pytest.approx(
        0.6
    )


def test_no_embeddings_file(tmp_path):
    assert load_embeddings(tmp_path, CANDIDATES) is None


def test_changed_text_and_missing_lines_get_no_vector(tmp_path):
    (tmp_path / "embeddings.jsonl").write_text(
        "".join(
            json.dumps({**json.loads(line), "text_sha1": "0" * 40}) + "\n"
            if '"lexical#3"' in line
            else line + "\n"
            for line in embedding_lines(CANDIDATES[:3]).splitlines()
        )
    )
    e = load_embeddings(tmp_path, CANDIDATES)
    assert e is not None
    assert e.keys == ["lexical#1", "lexical#2"]
    assert e.warnings == [
        "lexical#3: stored embedding is for a different text",
        "syntactic#1: no stored embedding",
        "syntactic#2: no stored embedding",
    ]
    s = ReviewState(CANDIDATES, None, e, 0.97)
    assert (
        s.live(CANDIDATES[2]) is None
    )  # lexical#3 has no vector: the panel falls back to the stored matches
    assert _keys(s.live(CANDIDATES[0])) == (
        None,
        None,
    )  # lexical#3 and syntactic#2 are kept but have no vector


# --- kept set ------------------------------------------------------------------------------------


def test_kept_follows_decisions_else_gates():
    assert kept(CANDIDATES, {}) == {
        "lexical#1": "lexical",
        "lexical#3": "lexical",
        "syntactic#2": "syntactic",
    }
    decisions = {
        "lexical#1": decision("reject", "lexical"),  # gate-accepted, rejected in review
        "lexical#2": decision("accept", "lexical"),  # gate-rejected, accepted in review
        "syntactic#2": decision("accept", "discourse"),  # moved
    }
    assert kept(CANDIDATES, decisions) == {
        "lexical#2": "lexical",
        "lexical#3": "lexical",
        "syntactic#2": "discourse",
    }
    assert current_category(CANDIDATES[4], decisions) == "discourse"
    assert current_category(CANDIDATES[3], decisions) == "syntactic"


# --- live closest matches ------------------------------------------------------------------------


def test_live_excludes_itself_and_considers_later_candidates(emb):
    s = _state(emb)
    live = s.live(
        CANDIDATES[0]
    )  # lexical#1: the only later kept ones are lexical#3 and syntactic#2
    assert _keys(live) == ("lexical#3", "syntactic#2")
    assert live is not None
    assert (
        live["within"]["sem"] == pytest.approx(0.6)
        and live["within"]["prompt"] == "lexical 3"
    )


def test_live_for_a_candidate_that_is_not_kept(emb):
    # lexical#2 was rejected by the gates: its matches answer "what would it duplicate if accepted?"
    assert _keys(_state(emb).live(CANDIDATES[1])) == ("lexical#1", "lexical#1")


def test_accepting_a_gate_rejected_candidate_makes_it_a_match(emb):
    s = _state(emb)
    s.decisions["lexical#2"] = decision("accept", "lexical")
    live = s.live(CANDIDATES[0])
    assert live is not None
    assert _keys(live) == ("lexical#2", "lexical#2") and live["within"][
        "sem"
    ] == pytest.approx(0.995, abs=1e-3)


def test_rejecting_the_match_lets_the_next_closest_take_over(emb):
    s = _state(emb)
    assert _keys(s.live(CANDIDATES[4])) == (
        None,
        "lexical#1",
    )  # syntactic#2: no other kept syntactic one
    s.decisions["lexical#1"] = decision("reject", "lexical")
    assert _keys(s.live(CANDIDATES[4])) == (None, "lexical#3")


def test_moving_changes_the_within_category_pool(emb):
    s = _state(emb, {"syntactic#2": decision("accept", "lexical")})
    assert _keys(s.live(CANDIDATES[4])) == ("lexical#1", "lexical#1")


def test_nothing_kept(emb):
    s = _state(emb, {k: decision("reject", k.split("#")[0]) for k in keys(CANDIDATES)})
    assert _keys(s.live(CANDIDATES[0])) == (None, None)


def test_no_live_values_without_embeddings():
    s = ReviewState(CANDIDATES, None, None, 0.97)
    assert s.live(CANDIDATES[0]) is None and s.near_duplicates() == {}
    assert NEAR_DUPLICATE_FILTER not in s.filters


# --- kept near-duplicates ------------------------------------------------------------------------


def test_near_duplicates_mark_both_members_and_go_away_on_reject(emb):
    s = _state(emb)
    assert (
        s.near_duplicates() == {}
    )  # lexical#1 and syntactic#2 are close, but in different categories
    s.decisions["lexical#2"] = decision("accept", "lexical")
    near = s.near_duplicates()
    assert (
        set(near) == {"lexical#1", "lexical#2"} and near["lexical#1"][0] == "lexical#2"
    )
    s.decisions["lexical#1"] = decision("reject", "lexical")
    assert s.near_duplicates() == {}


def test_near_duplicate_filter_lists_exactly_the_pairs(emb):
    s = _state(
        emb, {"syntactic#2": decision("accept", "lexical")}
    )  # moved next to lexical#1 (0.981)
    assert s.filters[4] == NEAR_DUPLICATE_FILTER
    s.filter = NEAR_DUPLICATE_FILTER
    assert keys(s.visible()) == ["lexical#1", "syntactic#2"]
    s.decide("reject")  # rejecting lexical#1 removes both from the filter
    assert s.visible() == []


def test_near_duplicates_ignore_candidates_without_vectors(tmp_path):
    vectors = {k: v for k, v in VECTORS.items() if k != "lexical#2"}
    e = embeddings_for(tmp_path, vectors=vectors)
    s = ReviewState(CANDIDATES, {"lexical#2": decision("accept", "lexical")}, e, 0.97)
    assert s.near_duplicates() == {}
