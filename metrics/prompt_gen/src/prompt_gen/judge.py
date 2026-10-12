"""LLM judge: hard-constraint check (a gate) and category check (logged only), in one call.

Each constraint gets one of three verdicts (see seeds/*/constraints.yaml): kept, relative
(accepted but tagged), or failed.
"""

from typing import Literal

import ollama
from pydantic import BaseModel

from prompt_gen import typology
from prompt_gen.config import JudgeConfig
from prompt_gen.seeds import Seed


class ConstraintVerdict(BaseModel):
    id: str
    reason: str  # before status, so the model reasons first
    status: Literal["kept", "relative", "failed"]


class Judgement(BaseModel):
    verdicts: list[ConstraintVerdict]
    operations_found: list[str]
    matches_category: bool
    category_reason: str

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


def system_prompt(seed: Seed, category: typology.Category) -> str:
    all_types = "\n".join(f"- {c.name}: " + "; ".join(t.name for t in c.types) for c in typology.CATEGORIES)
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
{all_types}

List the operations that turn the original into the rewritten request. Then say whether it was made MAINLY \
with operations from the {category.name} category. Small incidental changes from other categories are fine; \
a rewrite that mostly relies on other categories does not match."""


class Judge:
    def __init__(self, config: JudgeConfig, host: str, num_ctx: int):
        self.config = config
        self.num_ctx = num_ctx
        self.client = ollama.Client(host=host)

    def check(self, seed: Seed, category: typology.Category, candidate: str) -> Judgement:
        response = self.client.chat(
            model=self.config.model,
            messages=[
                {"role": "system", "content": system_prompt(seed, category)},
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
