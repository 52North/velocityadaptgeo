# prompt-gen

Generates paraphrases of a seed prompt, a fixed number per paraphrase category, for testing the agent with many wordings of the same request. Each candidate is scored with two embedding models (semantic: how different the wording is; pragmatic: whether the intent is the same) and passes a set of gates: near-duplicate check, a word-family check for morphological paraphrases, and an LLM judge for the seed's hard constraints and grammar. The candidates are then reviewed by hand in [`prompt_review`](../prompt_review).

## Requirements

- Ollama on `localhost:11434` with `qwen3:8b` (the root stack's Ollama; see `config.yaml`).
- The embedding models (`all-mpnet-base-v2`, `multilingual-e5-large-instruct`) are downloaded into `models/` (git-ignored) on first use.

## Usage

```
uv sync
uv run prompt-gen run [--seed muenster_green_300m] [--categories lexical ...] [--n 10] [--hours H]
uv run prompt-gen run --resume <run_id>          # continue an interrupted run
uv run prompt-gen check-judge [--seed ID]        # judge the seed's trap and grammar sets before a run
uv run prompt-gen rejudge <run_id> --category C [--limit N] [--contains TEXT]
uv run prompt-gen backfill-closest <run_id>      # older runs: closest matches per candidate
uv run prompt-gen backfill-embeddings <run_id>   # older runs: embeddings.jsonl for prompt-review
uv run pytest
```

Settings (models, loop limits, thresholds, strict mode) are in `config.yaml`, explained in its comments.

## Inputs

- `seeds/<seed_id>/`: `prompt.txt` (the seed prompt) and `constraints.yaml` (the hard constraints a paraphrase must keep, plus the judge's trap and grammar test sets).
- `data/examples.yaml`: few-shot examples per category, picked by hand from the ETPC corpus (and hand-written where ETPC has none).

## Output

One folder per run, `out/<run_id>/` (git-ignored):

- `candidates.jsonl`: every attempt with its scores, gate results and judge output; the run's state, appended as it goes.
- `accepted.jsonl`: the gate-accepted paraphrases, rebuilt at the end.
- `embeddings.jsonl`: each paraphrase's semantic embedding.
- `config.json`, `code/`: the config and code of the first session; each resumed session adds `config_<time>.json` and `code_<time>/`.

`prompt_review` adds `reviewed.jsonl`, LangGraph's batch and grading add their results to the same folder. What the reviewer relies on is listed in [`prompt_review/FORMAT.md`](../prompt_review/FORMAT.md).

## Files

`src/prompt_gen/`:

- `cli.py`: the `prompt-gen` commands.
- `config.py`: `config.yaml` as pydantic models.
- `run.py`: the generate → score → filter loop per category, resuming, the run folder's files and the backfills.
- `generator.py`: chain-of-thought paraphrase generation with Ollama, with retries and feedback on rejected drafts.
- `judge.py`: the LLM judge, two calls per candidate: constraints (kept / relative / failed), then category and grammar.
- `scoring.py`: semantic and pragmatic similarity from the two embedding models.
- `stems.py`: the deterministic word-family check for morphological paraphrases.
- `seeds.py`: loads a seed folder (prompt, constraints, trap and grammar sets).
- `typology.py`: the six paraphrase categories and their ETPC types; the single source of the category mapping.
- `examples.py`: loads `data/examples.yaml`.
- `etpc.py`: reads the ETPC corpus (`data/raw/etpc/`), for picking new examples by hand; not used by a run.

`tests/`: pytest; no Ollama or embedding models needed.
