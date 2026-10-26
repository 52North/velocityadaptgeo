# MCP vs. RAG Evaluation

Stress-tests the agentic workflow builder with many paraphrases of the same geospatial request, and compares how often it builds a correct workflow when it finds processes by catalog search (`pgvector`, RAG) or through every tool of the MCP server (`mcp`).

## Pipeline

Every step reads and writes the same run folder, `prompt_gen/out/<run_id>/` (git-ignored):

| Step | Where | Reads | Writes |
|---|---|---|---|
| 1. Generate paraphrases | [`prompt_gen`](prompt_gen/README.md) | `seeds/<id>/`, `config.yaml` | `candidates.jsonl`, `accepted.jsonl`, `embeddings.jsonl` |
| 2. Review them by hand | [`prompt_review`](prompt_review/README.md) | `candidates.jsonl`, `embeddings.jsonl` | `reviewed.jsonl` |
| 3. Build a workflow per prompt | `LangGraph/src/batch.py` | `reviewed.jsonl` | `workflows[.<variant>].jsonl`, `runs.jsonl` |
| 4. Execute the workflows | `LangGraph/src/batch.py --execute` | `workflows[.<variant>].jsonl` | `executed[.<variant>].jsonl`, `executions/` |
| 5. Grade the outputs | [`grading`](grading/README.md) | `executed[.<variant>].jsonl`, `outputs/reference.gpkg` | `grades[.<variant>].jsonl` |
| 6. Report | [`report`](report/README.md) | all of the above | `summary.md`, `detailed.html` |

```
# from the repository root
(cd metrics/prompt_gen    && uv run prompt-gen run)
(cd metrics/prompt_review && uv run prompt-review ../prompt_gen/out/<run_id>)
(cd LangGraph             && uv run python -m src.batch ../metrics/prompt_gen/out/<run_id> [--variant mcp])
(cd LangGraph             && uv run python -m src.batch ../metrics/prompt_gen/out/<run_id> [--variant mcp] --execute)
(cd metrics/grading       && uv run python grade.py ../prompt_gen/out/<run_id> [--variant mcp])
(cd metrics/report        && uv run quarto render)
```

Each folder is its own `uv` project (`uv sync` in the folder). Step 1 needs Ollama, steps 3 and 4 the LangGraph agent and pygeoapi; see the root `SETUP.md`. The commands and options of each step are in its README.

## Generating inputs

Paraphrases are generated per category of the ETPC paraphrase typology: morphological, lexical, syntactic, lexico-syntactic, discourse and other. A local LLM writes each paraphrase with a short plan first, from few-shot examples of its category.

The aim is wording that differs as much as possible while the request stays the same. Two embedding models measure this: a general sentence model for the semantic (wording) similarity to the seed, and an instruction-tuned model, told to compare geospatial requests by the analysis and output they ask for, for the pragmatic (intent) similarity. A loop generates, scores and filters candidates until each category has enough. Near-duplicates of paraphrases already accepted in the category are rejected, and an LLM judge rejects paraphrases that drop or blur one of the seed's constraints (place, distance, green-space type and size, output) or are ungrammatical. All candidates are then reviewed by hand.

## Scoring outputs

A workflow counts as correct when its executed output matches a reference solution (`grading/cool_spots.py`, computed from OSM) closely enough: area IoU with the reference answer, agreement of the distance bands, and the same largest distance. The thresholds are lenient, so that other plausible readings of the prompt (minimum park size, ring steps, whether woods count) still pass. Details in [`grading/README.md`](grading/README.md).

## Other files

- `runs.jsonl`: LangGraph's default metrics file (`METRICS_FILE`) for interactive runs; batch runs write theirs into the run folder.
- `.docs/`: plans and notes (git-ignored).
