"""LLM judge, in two calls per candidate.

Call A, constraints (a gate): each constraint gets one of three verdicts (see seeds/*/constraints.yaml):
kept, relative (rejected in strict mode, otherwise accepted but tagged), or failed.

Call B, category and grammar: the category check (logged only), and a grammar check by correction:
the model rewrites the request with only its grammatical errors fixed, and the code compares the
correction with the original. Any difference beyond case, whitespace and punctuation means
ungrammatical (a gate in strict mode).

The two jobs used to share one call; with both in one prompt, qwen3:8b got worse at the constraint
check (.docs/judge_split_plan.md. Call B always runs, also after a failed constraint, so that a
review that overrules the constraint verdict still has the category and grammar results.
"""

import re
import time
from typing import Literal

import ollama
from pydantic import BaseModel

from prompt_gen import typology
from prompt_gen.config import JudgeConfig
from prompt_gen.seeds import Seed
from prompt_gen.stems import StemCheck


class ConstraintVerdict(BaseModel):
    id: str
    reason: str  # before status, so the model reasons first
    status: Literal["kept", "relative", "failed"]


class ConstraintOutput(BaseModel):
    """What call A returns."""

    verdicts: list[ConstraintVerdict]


class CategoryGrammarOutput(BaseModel):
    """What call B returns. Field order matters: the reason comes before the decision it supports."""

    operations_found: list[str]
    main_change: str
    category_reason: str
    matches_category: bool
    corrected: str


class Judgement(BaseModel):
    """Both calls combined; this is what the pipeline stores and gates on."""

    verdicts: list[ConstraintVerdict]
    operations_found: list[str]
    main_change: str
    category_reason: str
    matches_category: bool
    corrected: str
    grammatical: bool
    durations_s: dict[str, float] = {}

    @property
    def passed(self) -> bool:
        return all(v.status != "failed" for v in self.verdicts)

    @property
    def failed_ids(self) -> list[str]:
        return [v.id for v in self.verdicts if v.status == "failed"]

    @property
    def relative_ids(self) -> list[str]:
        return [v.id for v in self.verdicts if v.status == "relative"]


_WORDS = re.compile(r"[^\W_]+")


def same_text(a: str, b: str) -> bool:
    """Equal apart from case, whitespace and punctuation."""
    return _WORDS.findall(a.casefold()) == _WORDS.findall(b.casefold())


# --- call A: constraints -----------------------------------------------------------------------


def _constraints_block(seed: Seed) -> str:
    blocks = []
    for c in seed.constraints:
        allowed = (
            "kept, relative or failed"
            if c.relative
            else "kept or failed (relative is not allowed here)"
        )
        lines = [
            f"## {c.id}",
            c.requirement,
            f"Allowed statuses: {allowed}",
            f"kept, e.g.: {'; '.join(c.accept)}",
        ]
        if c.relative:
            lines.append(f"relative, e.g.: {'; '.join(c.relative)}")
        lines.append(f"failed, e.g.: {'; '.join(c.reject)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def constraints_prompt(seed: Seed) -> str:
    # The constraint section of the prompt that scored 12/12 before the extended single-call prompt.
    return f"""You check rewritten requests for a geospatial analysis assistant.

# Constraints
Check whether the rewritten request still asks for the same analysis as the original. Give each constraint \
one status:
- kept: the same meaning and the same value, in any form (other words, units, formats).
- relative: a specific value or a specific set of features from the original is expressed more vaguely or \
more broadly, so that someone carrying out the request would have to choose the quantity themselves \
(e.g. "a short walk" for 300 metres, "recreational green space" for parks or forests). It keeps the direction \
and spirit of the original. Only where the constraint allows it.
- failed: a different specific value (500 m instead of 300 m), a changed meaning, or the constraint is missing.
Any change to what is measured or how it is measured fails, however small it seems.
The examples under each constraint are authoritative: a phrasing listed under kept is kept.
Check each constraint independently, and give the reason before the status.

## Original request
{seed.text}

{_constraints_block(seed)}

Return one verdict per constraint id, in the order listed."""


# --- call B: category and grammar --------------------------------------------------------------


def _typology_block() -> str:
    blocks = []
    for c in typology.CATEGORIES:
        types = "\n".join(f"  - {t.name}: {t.description}" for t in c.types)
        blocks.append(f"- {c.name}: {c.definition}\n{types}")
    return "\n".join(blocks)


def _stem_fact(result: StemCheck | None) -> str:
    if result is None:
        return ""
    if result.passed:
        return (
            "\nFact, checked by a word-stem comparison: every content word of the rewritten request is a form "
            "of a word in the original, and no word of the original is missing. Do not claim otherwise.\n"
        )
    return (
        "\nFact, checked by a word-stem comparison: the rewritten request uses words that are not forms of "
        f"words in the original ({', '.join(result.new) or 'none'}), and drops words of the original "
        f"({', '.join(result.missing) or 'none'}).\n"
    )


def category_grammar_prompt(
    seed: Seed, category: typology.Category, stem_result: StemCheck | None = None
) -> str:
    return f"""You analyze rewritten requests for a geospatial analysis assistant. You do two things.

# 1. Paraphrase operations
The Extended Paraphrase Typology groups operations into categories:
{_typology_block()}

List the operations that turn the original into the rewritten request. Then name the main change: the \
operation that affects the most text (e.g. a whole clause added or moved counts far more than one word swapped). \
Ignore incidental edits such as capitalization, punctuation or a single article. Decide from the main change \
whether the rewrite was made MAINLY with operations from the {category.name} category: a rewrite whose main \
change belongs to {category.name} matches, even if it also has small changes from other categories.
{_stem_fact(stem_result)}
## Original request
{seed.text}

# 2. Grammar
In `corrected`, write the rewritten request again with every grammatical error corrected: wrong verb forms \
(e.g. "Identified all areas ..." as a request needs "Identify"), wrong agreement (e.g. "a public parks"), \
missing or wrong words that keep a sentence from parsing. Change nothing else: keep the wording, word choice, \
style and meaning exactly as they are, even where you would phrase it differently. If there are no grammatical \
errors, copy the rewritten request unchanged."""


# --- both --------------------------------------------------------------------------------------


class Judge:
    def __init__(self, config: JudgeConfig, host: str, num_ctx: int):
        self.config = config
        self.num_ctx = num_ctx
        self.client = ollama.Client(host=host)

    def _ask(
        self, system: str, candidate: str, schema: type[BaseModel]
    ) -> tuple[BaseModel, dict[str, float]]:
        started = time.monotonic()
        response = self.client.chat(
            model=self.config.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Rewritten request:\n{candidate}"},
            ],
            think=self.config.think,
            format=schema.model_json_schema(),
            options={
                "temperature": self.config.temperature,
                "seed": 0,
                "num_ctx": self.num_ctx,
            },
        )
        timing = {
            "total": round(time.monotonic() - started, 1),
            "prompt": round(
                (response.prompt_eval_duration or 0) / 1e9, 1
            ),  # high = prompt cache miss
        }
        return schema.model_validate_json(response.message.content), timing

    def check_constraints(
        self, seed: Seed, candidate: str
    ) -> tuple[list[ConstraintVerdict], dict[str, float]]:
        output, timing = self._ask(
            constraints_prompt(seed), candidate, ConstraintOutput
        )
        expected = [c.id for c in seed.constraints]
        got = [v.id for v in output.verdicts]
        if got != expected:
            raise ValueError(
                f"judge returned constraint ids {got}, expected {expected}"
            )
        # "relative" only exists for constraints that define relative phrasings; elsewhere it means kept.
        for verdict, constraint in zip(output.verdicts, seed.constraints):
            if verdict.status == "relative" and not constraint.relative:
                verdict.status = "kept"
                verdict.reason = f"[relative -> kept: not allowed for this constraint] {verdict.reason}"
        return output.verdicts, timing

    def check_category_grammar(
        self,
        seed: Seed,
        category: typology.Category,
        candidate: str,
        stem_result: StemCheck | None = None,
    ) -> tuple[CategoryGrammarOutput, dict[str, float]]:
        output, timing = self._ask(
            category_grammar_prompt(seed, category, stem_result),
            candidate,
            CategoryGrammarOutput,
        )
        output.corrected = " ".join(output.corrected.split())
        return output, timing

    def check(
        self,
        seed: Seed,
        category: typology.Category,
        candidate: str,
        stem_result: StemCheck | None = None,
    ) -> Judgement:
        verdicts, timing_a = self.check_constraints(seed, candidate)
        # Always run, even after a failed constraint: review may overrule the constraint verdict.
        b, timing_b = self.check_category_grammar(
            seed, category, candidate, stem_result
        )
        return combine(verdicts, b, candidate, timing_a, timing_b)


def combine(
    verdicts: list[ConstraintVerdict],
    b: CategoryGrammarOutput,
    candidate: str,
    timing_a: dict[str, float] | None = None,
    timing_b: dict[str, float] | None = None,
) -> Judgement:
    durations = {f"constraints_{k}": v for k, v in (timing_a or {}).items()}
    durations |= {f"category_grammar_{k}": v for k, v in (timing_b or {}).items()}
    return Judgement(
        verdicts=verdicts,
        **b.model_dump(),
        grammatical=same_text(b.corrected, candidate),
        durations_s=durations,
    )
