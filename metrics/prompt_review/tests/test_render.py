import json

from helpers import CANDIDATES, cand, decision
from rich.console import Console

from prompt_review.render import closest_panel, print_summary, word_diff
from prompt_review.state import ReviewState


def test_word_diff():
    t = word_diff("Identify all areas in Münster", "Locate every area in Münster")
    struck = "".join(
        t.plain[s.start : s.end] for s in t.spans if "strike" in str(s.style)
    )
    added = "".join(
        t.plain[s.start : s.end] for s in t.spans if "green" in str(s.style)
    )
    assert struck.split() == ["Identify", "all", "areas"]
    assert added.split() == ["Locate", "every", "area"]
    assert "in Münster" in t.plain


def test_print_summary_on_a_run_folder(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "candidates.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in CANDIDATES)
        + json.dumps(
            {
                "category": "lexical",
                "attempt": 9,
                "prompt": None,
                "accepted": False,
                "reject_reason": "generation_error: x",
            }
        )
        + "\n"
    )
    (run / "config.json").write_text(
        json.dumps({"n_per_category": 30, "seed": {"id": "s"}})
    )
    (run / "config_20261014-090000.json").write_text(
        json.dumps({"n_per_category": 2, "seed": {"id": "s"}})
    )
    console = Console(record=True, width=150, color_system=None)
    print_summary(run, console)  # no reviewed.jsonl yet
    out = console.export_text()
    assert (
        "2 generation session(s)" in out and "target 2 per category" in out
    )  # latest session's config
    assert "1 generation error(s)" in out
    assert "overruled" not in out


# --- closest-match panel -------------------------------------------------------------------------


def _match(key, prompt, sem):
    return {"key": key, "prompt": prompt, "sem": sem}


def _panel_text(candidate, state):
    console = Console(record=True, width=200, color_system=None)
    console.print(closest_panel(candidate, state))
    return console.export_text()


def _with_matches(within, any_):
    return {**cand("syntactic", 2), "closest_accepted": within, "closest_any": any_}


def test_panel_shows_both_labeled_with_current_category_and_threshold():
    s = ReviewState(CANDIDATES, {"lexical#3": decision("accept", "discourse")})
    s.threshold = 0.97
    c = _with_matches(
        _match("syntactic#1", "syntactic 1", 0.95),
        _match("lexical#3", "lexical 3", 0.99),
    )
    text = _panel_text(c, s)
    assert (
        "Within the category" in text
        and "(syntactic)" in text
        and "Compared with all" in text
    )
    assert (
        "syntactic#1 · similarity 0.950 · review: unreviewed" in text
    )  # below threshold: no marker
    assert (
        "lexical#3 · now in discourse (moved) · similarity 0.990 ▲ over 0.970 · review: accept"
        in text
    )
    assert "same paraphrase" not in text


def test_panel_moving_the_match_updates_the_current_category():
    s = ReviewState(CANDIDATES)
    c = _with_matches(None, _match("lexical#1", "lexical 1", 0.9))
    assert "now in lexical ·" in _panel_text(c, s)
    s.decisions["lexical#1"] = decision(
        "accept", "discourse"
    )  # moved during the review session
    assert "now in discourse (moved)" in _panel_text(c, s)


def test_panel_same_match_is_shown_once_and_empty_matches_have_messages():
    s = ReviewState(CANDIDATES)
    m = _match("syntactic#1", "syntactic 1", 0.9)
    assert "same paraphrase as within the category" in _panel_text(
        _with_matches(m, m), s
    )
    text = _panel_text(_with_matches(None, None), s)
    assert (
        "no accepted paraphrase in this category yet" in text
        and "no accepted paraphrase yet" in text
    )


def test_panel_without_stored_fields_and_unknown_match():
    s = ReviewState(CANDIDATES)
    assert "prompt-gen backfill-closest" in _panel_text(cand("lexical", 1), s)
    assert "(not found in this run)" in _panel_text(
        _with_matches(_match("other#7", "x", 0.5), None), s
    )


# --- live similarities ---------------------------------------------------------------------------

from helpers import embedding_lines, embeddings_for  # noqa: E402

from prompt_review.render import _body  # noqa: E402


def _live_state(tmp_path, decisions=None):
    return ReviewState(CANDIDATES, decisions, embeddings_for(tmp_path), threshold=0.97)


def test_panel_shows_now_then_at_generation(tmp_path):
    s = _live_state(tmp_path, {"lexical#2": decision("accept", "lexical")})
    c = {
        **CANDIDATES[0],
        "closest_accepted": None,
        "closest_any": None,
    }  # lexical#1 was the first: nothing earlier
    text = _panel_text(c, s)
    assert text.index("Now · all other kept paraphrases") < text.index(
        "At generation · earlier gate-accepted"
    )
    assert "lexical#2 · similarity 0.995 ▲ over 0.970 · review: accept" in text
    assert (
        "no accepted paraphrase in this category yet" in text
    )  # the stored, generation-time section


def test_panel_same_matches_as_now_is_one_line(tmp_path):
    s = _live_state(tmp_path)
    m3, s2 = (
        _match("lexical#3", "lexical 3", 0.6),
        _match("syntactic#2", "syntactic 2", 0.981),
    )
    text = _panel_text({**CANDIDATES[0], "closest_accepted": m3, "closest_any": s2}, s)
    assert "same matches as now" in text and text.count("lexical#3 ·") == 1


def test_panel_without_embeddings_names_the_backfill(tmp_path):
    text = _panel_text(_with_matches(None, None), ReviewState(CANDIDATES))
    assert (
        "prompt-gen backfill-embeddings" in text
        and "no accepted paraphrase yet" in text
    )
    assert "Now ·" not in text


def test_header_marks_kept_near_duplicates(tmp_path):
    unjudged = [
        {**c, "judge": None, "operations_applied": []} for c in CANDIDATES
    ]  # enough fields for the body
    s = ReviewState(
        unjudged,
        {"lexical#2": decision("accept", "lexical")},
        embeddings_for(tmp_path),
        threshold=0.97,
    )
    s.filter = "all"
    console = Console(record=True, width=200, color_system=None)
    console.print(_body(s, "seed", details=False))
    assert "kept near-duplicate of lexical#2 (0.995)" in console.export_text()


def test_summary_counts_kept_near_duplicates(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "candidates.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in CANDIDATES)
    )
    (run / "config.json").write_text(
        json.dumps(
            {
                "n_per_category": 2,
                "seed": {"id": "s"},
                "config": {"thresholds": {"near_duplicate_sem": 0.97}},
            }
        )
    )
    (run / "reviewed.jsonl").write_text(
        json.dumps({**CANDIDATES[1], "review": decision("accept", "lexical")}) + "\n"
    )
    console = Console(record=True, width=150, color_system=None)
    print_summary(run, console)
    assert (
        "kept near-duplicate" not in console.export_text()
    )  # no embeddings.jsonl: no line
    (run / "embeddings.jsonl").write_text(embedding_lines(CANDIDATES))
    console = Console(record=True, width=150, color_system=None)
    print_summary(run, console)
    assert (
        "2 kept paraphrases have a kept near-duplicate in their category (> 0.970)."
        in console.export_text()
    )
