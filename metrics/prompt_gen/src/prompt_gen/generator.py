"""Chain-of-thought paraphrase generation with a local Ollama model."""

import time
from dataclasses import dataclass

import ollama
from pydantic import BaseModel, Field, ValidationError

from prompt_gen import typology
from prompt_gen.config import GeneratorConfig
from prompt_gen.examples import CategoryExamples
from prompt_gen.seeds import Seed


class GeneratorOutput(BaseModel):
    # Field order matters: the model writes its plan before the paraphrase (short-reasoning CoT).
    reasoning: str = Field(description="Plan written BEFORE the paraphrase, at most 150 words.")
    operations_applied: list[str]
    paraphrase: str


@dataclass
class Generation:
    paraphrase: str
    operations_applied: list[str]
    reasoning: str
    sampling_seed: int
    attempts: int
    duration_s: float
    eval_tokens: int


class GenerationError(RuntimeError):
    pass


def system_prompt(category: typology.Category, examples: CategoryExamples, seed: Seed, accept_relative: bool) -> str:
    types = "\n".join(f"- {t.name}: {t.description}" for t in category.types)
    type_names = {t.id: t.name for t in category.types}
    spans = "\n".join(
        f'- [{type_names[s.type_id]}] "{s.source}" -> "{s.target}"' + (f" ({s.note})" if s.note else "")
        for s in examples.spans
    )
    constraints = "\n".join(f"- {c.requirement}" for c in seed.constraints)
    if accept_relative:
        relative_rule = (
            'You may also state a value or a set of features more vaguely, as a real user might '
            '(e.g. "a short walk", "recreational green space").'
        )
    else:
        relative_rule = (
            "Keep every value and every set of features exactly as specific as in the seed: do not make "
            'them vaguer or broader (e.g. not "a short walk" for 300 metres, not "green space" for parks or forests).'
        )
    return f"""You rewrite requests for a geospatial analysis assistant. You produce one paraphrase of a seed request \
using only the paraphrase operations of one linguistic category, taken from the Extended Paraphrase Typology.

# Category: {category.name}
{category.definition}

Allowed operations:
{types}

Not allowed: {category.forbidden}

Examples of each operation, taken from news text:
{spans}

Full-sentence example on a different request:
Original: {examples.demo_source}
Paraphrase: {examples.demo_paraphrase}
Operations: {"; ".join(examples.demo_operations)}

# Hard constraints
The paraphrase must ask for the same analysis and output as the seed. Each of these must still hold. \
You may express them in a different form (other words, units or formats). {relative_rule} Never replace a \
value with a different specific value, and never drop a constraint:
{constraints}

# How to answer
Answer in JSON, filling the fields in this order:
1. `reasoning`: your plan, written before the paraphrase, at most 150 words. Go through the seed phrase \
by phrase and decide which allowed operations you will apply where. Apply as many as fit naturally: the \
paraphrase should differ from the seed as much as the category allows. Then name the words that carry each \
hard constraint in your planned version.
2. `operations_applied`: each operation with the edit it makes, e.g. "Same polarity substitution: identify -> locate".
3. `paraphrase`: the paraphrase only, as natural English that a real user could type."""


def user_prompt(seed: Seed, previous: list[str]) -> str:
    prompt = f"Seed request:\n{seed.text}"
    if previous:
        listed = "\n".join(f"- {p}" for p in previous)
        prompt += (
            "\n\nParaphrases already written for this category. Yours must be clearly different from all of them, "
            f"using other operations or applying them in other places:\n{listed}"
        )
    return prompt


class Generator:
    def __init__(self, config: GeneratorConfig, host: str, accept_relative: bool, num_ctx: int):
        self.config = config
        self.accept_relative = accept_relative
        self.num_ctx = num_ctx
        self.client = ollama.Client(host=host)

    def generate(
        self, category: typology.Category, examples: CategoryExamples, seed: Seed, previous: list[str], sampling_seed: int
    ) -> Generation:
        messages = [
            {"role": "system", "content": system_prompt(category, examples, seed, self.accept_relative)},
            {"role": "user", "content": user_prompt(seed, previous)},
        ]
        errors = []
        for attempt in range(1, self.config.max_retries + 1):
            started = time.monotonic()
            response = self.client.chat(
                model=self.config.model,
                messages=messages,
                think=self.config.think,
                format=GeneratorOutput.model_json_schema(),
                options={"temperature": self.config.temperature, "seed": sampling_seed + attempt - 1, "num_ctx": self.num_ctx},
            )
            try:
                output = GeneratorOutput.model_validate_json(response.message.content)
            except ValidationError as e:
                errors.append(f"invalid JSON: {e.errors()[0]['msg']}")
                continue
            paraphrase = " ".join(output.paraphrase.split())
            if not paraphrase:
                errors.append("empty paraphrase")
                continue
            if paraphrase.casefold() == seed.text.casefold():
                errors.append("copied the seed")
                continue
            return Generation(
                paraphrase=paraphrase,
                operations_applied=output.operations_applied,
                reasoning="\n\n".join(filter(None, [response.message.thinking, output.reasoning])),
                sampling_seed=sampling_seed + attempt - 1,
                attempts=attempt,
                duration_s=time.monotonic() - started,
                eval_tokens=response.eval_count or 0,
            )
        raise GenerationError(f"no valid paraphrase after {self.config.max_retries} attempts: {errors}")
