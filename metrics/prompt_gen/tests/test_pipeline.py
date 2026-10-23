import json
from typing import Literal

import pytest

from prompt_gen import config, examples, seeds, stems, typology
from prompt_gen.judge import ConstraintVerdict, Judgement
from prompt_gen.run import EXAMPLES_PATH, gate, read_jsonl, stem_reason


def test_every_type_maps_to_exactly_one_category():
    ids = [t.id for c in typology.CATEGORIES for t in c.types]
    assert len(ids) == len(set(ids))
    assert {c.key for c in typology.CATEGORIES} == {
        "morphological",
        "lexical",
        "lexico_syntactic",
        "syntactic",
        "discourse",
        "other",
    }
    assert typology.IDENTITY_TYPE_ID not in typology.BY_TYPE_ID


def test_examples_cover_every_type():
    ex = examples.load(EXAMPLES_PATH)
    for c in typology.CATEGORIES:
        assert {s.type_id for s in ex[c.key].spans} == c.type_ids


def test_seed_loads_with_trap_set():
    seed = seeds.load("muenster_green_300m")
    assert "Münster" in seed.text
    assert [c.id for c in seed.constraints][:4] == [
        "location",
        "target",
        "distance",
        "walking",
    ]
    assert any(t.passes for t in seed.trap_set) and any(
        not t.passes for t in seed.trap_set
    )
    assert any(t.relative for t in seed.trap_set)


def _judgement(
    *statuses: Literal["kept", "relative", "failed"], grammatical: bool = True
) -> Judgement:
    return Judgement(
        verdicts=[
            ConstraintVerdict(id=f"c{i}", reason="", status=s)
            for i, s in enumerate(statuses)
        ],
        operations_found=[],
        main_change="",
        category_reason="",
        matches_category=True,
        corrected="",
        grammatical=grammatical,
    )


SCORES = {"sem": 0.8, "prag": 0.95, "max_sem_same_category": 0.5}


@pytest.fixture
def cfg():
    return config.load()


def test_relative_passes_failed_rejects():
    assert _judgement("kept", "relative").passed
    assert _judgement("kept", "relative").relative_ids == ["c1"]
    assert _judgement("kept", "failed").failed_ids == ["c1"]


def test_gate(cfg):
    assert gate(cfg, "lexical", SCORES, _judgement("kept", "relative")) == "relative:c1"
    cfg.thresholds.strict = False
    assert gate(cfg, "lexical", SCORES, _judgement("kept", "relative")) is None
    assert (
        gate(cfg, "lexical", SCORES, _judgement("failed", "kept", "failed"))
        == "constraint:c0,c2"
    )
    assert (
        gate(
            cfg,
            "lexical",
            {**SCORES, "max_sem_same_category": 0.99},
            _judgement("kept"),
        )
        == "near_duplicate"
    )
    assert (
        gate(
            cfg,
            "lexical",
            {**SCORES, "max_sem_same_category": None},
            _judgement("kept"),
        )
        is None
    )


def test_gate_thresholds(cfg):
    cfg.thresholds.sem_max = {"lexical": 0.7}
    cfg.thresholds.prag_min = 0.97
    assert gate(cfg, "lexical", SCORES, _judgement("kept")) == "too_similar_to_seed"
    assert gate(cfg, "syntactic", SCORES, _judgement("kept")) == "intent_drift"


def test_read_jsonl_skips_blank_lines(tmp_path):
    path = tmp_path / "c.jsonl"
    path.write_text(json.dumps({"a": 1}) + "\n\n" + json.dumps({"a": 2}) + "\n")
    assert read_jsonl(path) == [{"a": 1}, {"a": 2}]
    assert read_jsonl(tmp_path / "missing.jsonl") == []


def test_gate_grammar_follows_strict_mode(cfg):
    assert (
        gate(cfg, "lexical", SCORES, _judgement("kept", grammatical=False))
        == "ungrammatical"
    )
    # a failed constraint is the more important reason
    assert (
        gate(cfg, "lexical", SCORES, _judgement("failed", grammatical=False))
        == "constraint:c0"
    )
    cfg.thresholds.strict = False
    assert gate(cfg, "lexical", SCORES, _judgement("kept", grammatical=False)) is None


def test_stem_check_configured_for_morphological_only(cfg):
    assert cfg.thresholds.stem_check == ["morphological"]


def test_stem_reason():
    assert stem_reason(stems.StemCheck((), ())) is None
    assert (
        stem_reason(stems.StemCheck(("generate", "routes"), ()))
        == "stem:generate,routes"
    )
    assert (
        stem_reason(stems.StemCheck(("generate",), ("identify",)))
        == "stem:generate|missing:identify"
    )


def test_config_snapshot_lists_the_whole_typology(cfg, tmp_path, monkeypatch):
    """prompt-review reads the categories from the snapshot instead of importing typology."""
    from prompt_gen import run

    monkeypatch.setattr(run, "_model_digest", lambda host, model: None)
    monkeypatch.setattr(run.shutil, "copytree", lambda *a, **k: None)
    r = run.Run.__new__(run.Run)
    r.cfg, r.seed, r.run_id, r.dir = (
        cfg,
        seeds.load("muenster_green_300m"),
        "test",
        tmp_path,
    )
    r._write_config(["syntactic"], 30)
    snapshot = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert snapshot["categories"] == ["syntactic"]
    assert snapshot["typology"] == [
        {"key": c.key, "name": c.name} for c in typology.CATEGORIES
    ]


def test_judge_error_is_stored_and_resume_moves_on(cfg, tmp_path, monkeypatch):
    """A judge error must not abort the run, and must count as an attempt: the judge is deterministic,
    so a resume that retried the same sampling seed would fail on the same candidate again."""
    from types import SimpleNamespace

    from prompt_gen import run
    from prompt_gen.judge import JudgeError

    seeds_used = []

    class FakeGenerator:
        def __init__(self, *a, **k):
            pass

        def generate(
            self, category, examples, seed, entries, sampling_seed, target, feedback
        ):
            seeds_used.append(sampling_seed)
            return SimpleNamespace(
                paraphrase=f"Find the green areas, take {sampling_seed}",
                operations_applied=[],
                reasoning="",
                sampling_seed=sampling_seed,
                attempts=1,
                eval_tokens=0,
                discarded=[],
            )

    class FakeJudge:
        def __init__(self, *a, **k):
            pass

        def check(self, *a, **k):
            raise JudgeError(
                "judge returned constraint ids ['b', 'a'], expected ['a', 'b']"
            )

    class FakeScorer:
        def __init__(self, *a, **k):
            self.semantic = SimpleNamespace(embed=lambda texts: [[1.0, 0.0]])

        def semantic_similarities(self, text, others):
            return [0.0] * len(others)

        def score(self, candidate, seed, same_category, other_categories):
            return {
                "sem": 0.9,
                "prag": 0.9,
                "prag_no_instruction": 0.9,
                "max_sem_same_category": None,
                "max_sem_other_categories": None,
            }

    monkeypatch.setattr(run, "Generator", FakeGenerator)
    monkeypatch.setattr(run, "Judge", FakeJudge)
    monkeypatch.setattr(run, "Scorer", FakeScorer)
    monkeypatch.setattr(run, "_model_digest", lambda host, model: None)
    monkeypatch.setattr(run.shutil, "copytree", lambda *a, **k: None)
    monkeypatch.setattr(run, "OUT_DIR", tmp_path)
    cfg = cfg.model_copy(
        update={
            "loop": cfg.loop.model_copy(
                update={"max_attempts_factor": 10, "max_consecutive_rejects": 2}
            )
        }
    )
    seed = seeds.load("muenster_green_300m")

    run.Run(cfg, seed, "test").execute(["lexical"], 1)
    run.Run(cfg, seed, "test").execute(["lexical"], 1)  # resume

    records = read_jsonl(tmp_path / "test" / "candidates.jsonl")
    assert [r["attempt"] for r in records] == [1, 2, 3, 4]
    assert all(r["reject_reason"].startswith("judge_error: ") for r in records)
    assert all(r["prompt"] and "sem" in r for r in records)
    assert len(set(seeds_used)) == 4
