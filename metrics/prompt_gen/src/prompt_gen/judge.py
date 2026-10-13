"""LLM judge, in one call: hard-constraint check (a gate), category check (logged only), and
grammar check (a gate in strict mode).

Each constraint gets one of three verdicts (see seeds/*/constraints.yaml): kept, relative
(rejected in strict mode, otherwise accepted but tagged), or failed.
"""

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


class Judgement(BaseModel):
    # Field order matters: each reason comes before the decision it supports.
    verdicts: list[ConstraintVerdict]
    operations_found: list[str]
    main_change: str
    category_reason: str
    matches_category: bool
    grammar_reason: str
    grammatical: bool

    @property
    def passed(self) -> bool:
        return all(v.status != "failed" for v in self.verdicts)

    @property
    def failed_ids(self) -> list[str]:
        return [v.id for v in self.verdicts if v.status == "failed"]

    @property
    def relative_ids(self) -> list[str]:
        return [v.id for v in self.verdicts if v.status == "relative"]


def _constraints_block(seed: Seed) -> str:
    blocks = []
    for c in seed.constraints:
        allowed = "kept, relative or failed" if c.relative else "kept or failed (relative is not allowed here)"
        lines = [f"## {c.id}", c.requirement, f"Allowed statuses: {allowed}", f"kept, e.g.: {'; '.join(c.accept)}"]
        if c.relative:
            lines.append(f"relative, e.g.: {'; '.join(c.relative)}")
        lines.append(f"failed, e.g.: {'; '.join(c.reject)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


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
        return ("\nFact, checked by a word-stem comparison: every content word of the rewritten request is a form "
                "of a word in the original, and no word of the original is missing. Do not claim otherwise.\n")
    return ("\nFact, checked by a word-stem comparison: the rewritten request uses words that are not forms of "
            f"words in the original ({', '.join(result.new) or 'none'}), and drops words of the original "
            f"({', '.join(result.missing) or 'none'}).\n")


def system_prompt(seed: Seed, category: typology.Category, stem_result: StemCheck | None = None) -> str:
    return f"""You check rewritten requests for a geospatial analysis assistant. You do two things.

# 1. Constraints
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

Return one verdict per constraint id, in the order listed.

# 2. Paraphrase operations
The Extended Paraphrase Typology groups operations into categories:
{_typology_block()}

List the operations that turn the original into the rewritten request. Then name the main change: the \
operation that affects the most text (e.g. a whole clause added or moved counts far more than one word swapped). \
Ignore incidental edits such as capitalization, punctuation or a single article. Decide from the main change \
whether the rewrite was made MAINLY with operations from the {category.name} category: a rewrite whose main \
change belongs to {category.name} matches, even if it also has small changes from other categories.
{_stem_fact(stem_result)}
# 3. Grammar
Say whether the rewritten request is grammatical English a user could plausibly type. Informal or slightly \
awkward wording is acceptable. The following are grammatical errors and make the request ungrammatical: a wrong \
verb form (e.g. "Identified all areas ..." used as a request), wrong agreement (e.g. "a public parks"), or a \
sentence that doesn't parse. Give the reason first."""


class Judge:
    def __init__(self, config: JudgeConfig, host: str, num_ctx: int):
        self.config = config
        self.num_ctx = num_ctx
        self.client = ollama.Client(host=host)

    def check(self, seed: Seed, category: typology.Category, candidate: str, stem_result: StemCheck | None = None) -> Judgement:
        response = self.client.chat(
            model=self.config.model,
            messages=[
                {"role": "system", "content": system_prompt(seed, category, stem_result)},
                {"role": "user", "content": f"Rewritten request:\n{candidate}"},
            ],
            think=self.config.think,
            format=Judgement.model_json_schema(),
            options={"temperature": self.config.temperature, "seed": 0, "num_ctx": self.num_ctx},
        )
        judgement = Judgement.model_validate_json(response.message.content)
        expected = [c.id for c in seed.constraints]
        got = [v.id for v in judgement.verdicts]
        if got != expected:
            raise ValueError(f"judge returned constraint ids {got}, expected {expected}")
        # "relative" only exists for constraints that define relative phrasings; elsewhere it means kept.
        for verdict, constraint in zip(judgement.verdicts, seed.constraints):
            if verdict.status == "relative" and not constraint.relative:
                verdict.status = "kept"
                verdict.reason = f"[relative -> kept: not allowed for this constraint] {verdict.reason}"
        return judgement
