"""Chain-of-thought paraphrase generation with a local Ollama model."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

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
    discarded: list[dict] = field(default_factory=list)  # drafts rejected by the feedback check, with the feedback


class GenerationError(RuntimeError):
    pass


def system_prompt(category: typology.Category, examples: CategoryExamples, seed: Seed, strict: bool) -> str:
    types = "\n".join(f"- {t.name}: {t.description}" for t in category.types)
    type_names = {t.id: t.name for t in category.types}
    spans = "\n".join(
        f'- [{type_names[s.type_id]}] "{s.source}" -> "{s.target}"' + (f" ({s.note})" if s.note else "")
        for s in examples.spans
    )
    constraints = "\n".join(f"- {c.requirement}" for c in seed.constraints)
    if not strict:
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


TAG_TEXT = {"accepted": "accepted", "rejected": "rejected: too similar to an accepted one"}


def user_prompt(seed: Seed, written: list[tuple[str, str]], target: typology.ParaphraseType | None = None) -> str:
    """`written`: (paraphrase, "accepted" | "rejected") in the order written. New entries only ever go at
    the end, and the target operation comes last, so Ollama can reuse the processed prompt prefix."""
    prompt = f"Seed request:\n{seed.text}"
    if written:
        listed = "\n".join(f"- [{TAG_TEXT[tag]}] {text}" for text, tag in written)
        prompt += (
            "\n\nParaphrases already written for this category, in the order they were written. Yours must be "
            f"clearly different from all of them, using other operations or applying them in other places:\n{listed}"
        )
    openings = used_openings(written)
    if openings:
        listed = "; ".join(f'"{o} ..."' for o in openings)
        prompt += f"\n\nOpenings already used, do not start your paraphrase with any of these: {listed}"
    if target is not None:
        prompt += (
            f"\n\nStarting from the seed request, apply only this operation: {target.name}: {target.description}. "
            "Do not carry over the sentence structure of the paraphrases listed above."
        )
    return prompt


def used_openings(written: list[tuple[str, str]], words: int = 4) -> list[str]:
    """First words of each written paraphrase, without repeats, in order of first use."""
    openings: list[str] = []
    for text, _ in written:
        opening = " ".join(text.split()[:words]).rstrip(",.:;")
        if opening not in openings:
            openings.append(opening)
    return openings


class Generator:
    def __init__(self, config: GeneratorConfig, host: str, strict: bool, num_ctx: int):
        self.config = config
        self.strict = strict
        self.num_ctx = num_ctx
        self.client = ollama.Client(host=host)

    def generate(
        self,
        category: typology.Category,
        examples: CategoryExamples,
        seed: Seed,
        written: list[tuple[str, str]],
        sampling_seed: int,
        target: typology.ParaphraseType | None = None,
        feedback: Callable[[str], str | None] | None = None,
    ) -> Generation:
        """`feedback(paraphrase)` returns a correction message, or None if the draft is fine. A draft with
        feedback is sent back in the same conversation, up to `feedback_retries` times; the last draft is
        returned even if it still has feedback, and the caller decides what to do with it."""
        messages = [
            {"role": "system", "content": system_prompt(category, examples, seed, self.strict)},
            {"role": "user", "content": user_prompt(seed, written, target)},
        ]
        started = time.monotonic()
        errors: list[str] = []
        discarded: list[dict] = []
        tokens = 0
        call = 0
        while True:
            call += 1
            response = self.client.chat(
                model=self.config.model,
                messages=messages,
                think=self.config.think,
                format=GeneratorOutput.model_json_schema(),
                options={"temperature": self.config.temperature, "seed": sampling_seed + call - 1, "num_ctx": self.num_ctx},
            )
            tokens += response.eval_count or 0
            try:
                output = GeneratorOutput.model_validate_json(response.message.content)
                paraphrase = " ".join(output.paraphrase.split())
                if not paraphrase:
                    raise ValueError("empty paraphrase")
                if paraphrase.casefold() == seed.text.casefold():
                    raise ValueError("copied the seed")
            except (ValidationError, ValueError) as e:
                errors.append(f"invalid JSON: {e.errors()[0]['msg']}" if isinstance(e, ValidationError) else str(e))
                if len(errors) >= self.config.max_retries:
                    raise GenerationError(f"no valid paraphrase after {len(errors)} invalid outputs: {errors}") from None
                continue
            message = feedback(paraphrase) if feedback else None
            if message and len(discarded) < self.config.feedback_retries:
                discarded.append({"prompt": paraphrase, "feedback": message})
                messages += [
                    {"role": "assistant", "content": response.message.content},
                    {"role": "user", "content": message},
                ]
                continue
            return Generation(
                paraphrase=paraphrase,
                operations_applied=output.operations_applied,
                reasoning="\n\n".join(filter(None, [response.message.thinking, output.reasoning])),
                sampling_seed=sampling_seed + call - 1,
                attempts=call,
                duration_s=time.monotonic() - started,
                eval_tokens=tokens,
                discarded=discarded,
            )
