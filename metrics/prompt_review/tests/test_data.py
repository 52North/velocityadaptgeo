import json

import pytest
from helpers import CANDIDATES, cand

from prompt_review.data import categories, load_candidates, load_decisions, save
from prompt_review.state import ReviewState


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


def _run(tmp_path, records, *configs):
    """configs: config.json first, then the resumed sessions' snapshots."""
    run = tmp_path / "run"
    run.mkdir()
    (run / "candidates.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in records)
    )
    for i, cfg in enumerate(configs):
        name = "config.json" if i == 0 else f"config_20261014-09000{i}.json"
        (run / name).write_text(json.dumps(cfg))
    return run


def test_categories_from_typology_in_the_latest_config(tmp_path):
    typology = [
        {"key": k, "name": k.title()} for k in ("lexical", "syntactic", "discourse")
    ]
    run = _run(
        tmp_path,
        CANDIDATES,
        {"categories": ["syntactic"]},
        {"categories": ["syntactic"], "typology": typology},
    )
    assert categories(run) == ["lexical", "syntactic", "discourse"]


def test_categories_fallback_is_the_union_of_sessions_config_json_first(tmp_path):
    run = _run(
        tmp_path,
        CANDIDATES,
        {"categories": ["lexical", "syntactic"]},
        {"categories": ["discourse", "lexical"]},
    )
    assert categories(run) == ["lexical", "syntactic", "discourse"]
    # a category that only appears in the candidates is added at the end
    assert categories(run, [cand("other", 1)]) == [
        "lexical",
        "syntactic",
        "discourse",
        "other",
    ]


def test_duplicate_key_raises(tmp_path):
    run = _run(tmp_path, [cand("lexical", 1), cand("lexical", 1)], {})
    with pytest.raises(ValueError, match="duplicate candidate key lexical#1"):
        load_candidates(run)


def test_load_candidates_leaves_out_generation_errors(tmp_path):
    error = {
        "category": "lexical",
        "attempt": 9,
        "prompt": None,
        "accepted": False,
        "reject_reason": "generation_error: x",
    }
    run = _run(tmp_path, [*CANDIDATES, error], {})
    assert len(load_candidates(run)) == len(CANDIDATES)
