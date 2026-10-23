import pytest

from prompt_gen import seeds, typology
from prompt_gen.judge import (
    CategoryGrammarOutput,
    ConstraintVerdict,
    Judge,
    JudgeError,
    combine,
    same_text,
)

SEED = seeds.load("muenster_green_300m")


def test_same_text_ignores_case_whitespace_and_punctuation():
    assert same_text(
        "Identify all areas, then  map them.", "identify all areas then map them"
    )
    assert same_text("300-meter limit", "300 meter limit")
    assert not same_text("Identified all areas", "Identify all areas")
    assert not same_text("a public parks", "public parks")


def _b(corrected: str) -> CategoryGrammarOutput:
    return CategoryGrammarOutput(
        operations_found=["x"],
        main_change="x",
        category_reason="r",
        matches_category=True,
        corrected=corrected,
    )


def test_combine_computes_grammatical_from_the_correction():
    verdicts = [ConstraintVerdict(id="location", reason="", status="kept")]
    assert combine(
        verdicts, _b("Identify all areas."), "Identify all areas"
    ).grammatical
    j = combine(
        verdicts,
        _b("Identify all areas."),
        "Identified all areas",
        {"total": 40.0},
        {"total": 35.0},
    )
    assert not j.grammatical
    assert j.durations_s == {"constraints_total": 40.0, "category_grammar_total": 35.0}


class FakeResponse:
    def __init__(self, content: str):
        self.message = type("M", (), {"content": content})()
        self.prompt_eval_duration = 0


class FakeClient:
    """Answers call A with a failed constraint, call B with a correction; records what was asked."""

    def __init__(self):
        self.calls = []

    def chat(self, model, messages, think, format, options):
        self.calls.append(messages[0]["content"])
        if "verdicts" in format["properties"]:
            verdicts = [
                {
                    "id": c.id,
                    "reason": "",
                    "status": "failed" if c.id == "target" else "kept",
                }
                for c in SEED.constraints
            ]
            return FakeResponse(__import__("json").dumps({"verdicts": verdicts}))
        return FakeResponse(_b("Identify all areas in Münster.").model_dump_json())


def test_call_b_runs_even_when_a_constraint_fails():
    judge = Judge.__new__(Judge)
    judge.config = type(  # type: ignore[assignment]
        "C", (), {"model": "m", "think": False, "temperature": 0.0}
    )()
    judge.num_ctx = 8192
    judge.client = client = FakeClient()  # type: ignore[assignment]
    j = judge.check(SEED, typology.get("lexical"), "Identified all areas in Münster")
    assert j.failed_ids == ["target"]
    assert len(client.calls) == 2
    assert (
        "# Constraints" in client.calls[0]
        and "Paraphrase operations" not in client.calls[0]
    )
    assert (
        "Paraphrase operations" in client.calls[1]
        and "# Constraints" not in client.calls[1]
    )
    assert not j.grammatical
    assert j.corrected == "Identify all areas in Münster."


def _judge(client) -> Judge:
    judge = Judge.__new__(Judge)
    judge.config = type(  # type: ignore[assignment]
        "C", (), {"model": "m", "think": False, "temperature": 0.0}
    )()
    judge.num_ctx = 8192
    judge.client = client  # type: ignore[assignment]
    return judge


class WrongIdsClient(FakeClient):
    """Answers call A with the verdicts out of order."""

    def chat(self, model, messages, think, format, options):
        response = super().chat(model, messages, think, format, options)
        if "verdicts" in format["properties"]:
            data = __import__("json").loads(response.message.content)
            data["verdicts"].reverse()
            return FakeResponse(__import__("json").dumps(data))
        return response


class BadJsonClient(FakeClient):
    def chat(self, model, messages, think, format, options):
        return FakeResponse("{not json")


@pytest.mark.parametrize("client", [WrongIdsClient(), BadJsonClient()])
def test_unusable_judge_answers_raise_judge_error(client):
    with pytest.raises(JudgeError):
        _judge(client).check(SEED, typology.get("lexical"), "Identify all areas")
