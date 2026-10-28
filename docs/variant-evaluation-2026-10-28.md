# Variant evaluation, 2026-10-28: pgvector vs mcp vs fewshot

All three workflow variants (`LangGraph/src/llm/variants.py`), run on the same 58 prompts: 53
paraphrases of the Münster seed and 5 runs of the seed itself. `fewshot` ran twice: with the full
example set, which includes the two CoolSpots examples, and without them.

## Summary

- **The catalog search (`pgvector`) is the cheapest but builds the right chain least often.**
  It costs about half as much per request as `mcp` (1.1 vs 2.1 cent), but only 18 of 58 graphs are
  exactly the expected chain (31%), against 52 of 58 (90%) for `mcp`. The usual reason is a
  redundant 300 m `buffer` next to the distance bands (33 of 58 graphs).
- **`fewshot` is not measurably better than `mcp`.** Without the CoolSpots examples it builds the
  exact chain in 55 of 58 graphs (95%, `mcp` 90%, p = 0.49); its outputs match the reference in
  55 of 58 (`mcp` 58 of 58, p = 0.24). With 58 prompts per variant, differences of this size can
  be chance.
- **The CoolSpots examples hand the agent the reference parameters.** With them, `fewshot` uses
  `minArea` 4000 (the grading reference's value) in every graph and reaches the highest accuracy;
  without them it picks 5000–20000 itself and is the least precise variant. Once the agent also
  copied the example's `geometry-difference` step and returned the opposite of what was asked.
- **The outputs are right almost everywhere (95–100%),** because grading is lenient by design
  and because the scripted user fills in a missing minimum area with the reference value
  (`mcp` 23 times, `pgvector` 24 times, `fewshot` never).

## Results

| | `pgvector` | `mcp` | `fewshot` with CoolSpots | `fewshot` without CoolSpots |
|---|---|---|---|---|
| Strict: exactly the expected chain | 18/58 = 31% [21–44%] | 52/58 = 90% [79–95%] | 56/58 = 97% [88–99%] | 55/58 = 95% [86–98%] |
| Lenient: expected chain present | 46/58 = 79% [67–88%] | 52/58 = 90% [79–95%] | 57/58 = 98% [91–100%] | 55/58 = 95% [86–98%] |
| Output matches the reference | 56/58 = 97% [88–99%] | 58/58 = 100% [94–100%] | 57/58 = 98% [91–100%] | 55/58 = 95% [86–98%] |
| Area agreement with the reference, median | 0.963 | 0.975 | 0.996 | 0.927 |
| Distance-band agreement, median | 0.926 | 0.942 | 0.993 | 0.861 |
| Minimum area filled in by the scripted user | 24 | 23 | 0 | 0 |
| Input / output tokens per request | 84k / 6.1k | 187k / 5.1k | 203k / 4.8k | 208k / 5.3k |
| Cost per request | 1.14 cent | 2.13 cent | 2.27 cent | 2.35 cent |
| Cost of the run (58 prompts) | $0.66 | $1.23 | $1.31 | $1.36 |
| Wall time per request, median | 40 s | 34 s | 32 s | 35 s |

The expected chain is `city-boundary → osm-green-areas → min-area-filter → multi-ring-buffer`
(`LangGraph/src/batch_summary.py`: lenient = present and wired in order, strict = exactly that
chain). The brackets are 95% Wilson intervals: with 58 prompts, "55/58" means the true rate lies
between 86% and 98% with 95% confidence.

Two-sided Fisher tests against `mcp`:

| | lenient | strict | output |
|---|---|---|---|
| `pgvector` | p = 0.20 | **p < 0.0001** | p = 0.50 |
| `fewshot` with CoolSpots | p = 0.11 | p = 0.27 | p = 1.0 |
| `fewshot` without CoolSpots | p = 0.49 | p = 0.49 | p = 0.24 |

Only the strict gap between `pgvector` and `mcp` is significant.

### Per category (strict / output)

| Category | n | `pgvector` | `mcp` | `fewshot` with CoolSpots | `fewshot` without CoolSpots |
|---|---|---|---|---|---|
| seed | 5 | 1 / 5 | 5 / 5 | 5 / 5 | 5 / 5 |
| morphological | 3 | 0 / 3 | 2 / 3 | 3 / 3 | 3 / 3 |
| lexical | 10 | 3 / 10 | 7 / 10 | 8 / 9 | 9 / 9 |
| lexico_syntactic | 10 | 4 / 9 | 10 / 10 | 10 / 10 | 10 / 9 |
| syntactic | 10 | 5 / 10 | 9 / 10 | 10 / 10 | 9 / 10 |
| discourse | 10 | 1 / 9 | 9 / 10 | 10 / 10 | 10 / 10 |
| other | 10 | 4 / 10 | 10 / 10 | 10 / 10 | 9 / 9 |

### What the agent built

- **`pgvector`**: 30 distinct graphs. 33 of 58 add a redundant `buffer` of 300 m beside the
  distance bands; 8 leave out `min-area-filter`; `minArea` is unset or a placeholder in 23. One
  graph (lexico_syntactic#19) subtracts the bands from the city and so returns the areas that are
  too far away.
- **`mcp`**: 18 distinct graphs. The only structural error is a missing `min-area-filter` (6 of
  58). `minArea` is left unset 23 times; otherwise 10000 or 5000.
- **`fewshot` with CoolSpots**: 12 distinct graphs. Every request retrieved `coolspots-muenster`
  (similarity ≈ 0.75), almost always with `stuttgart-forest-core-distance-bands`. All 57 graphs
  with a size filter use `minArea` 4000, the example's (and the reference's) value. The one wrong
  output (lexical#5) copied the example's final `geometry-difference` step: the CoolSpots task
  asks for the areas *too far* from green, this seed for the areas *within* 300 m.
- **`fewshot` without CoolSpots**: 22 distinct graphs. Mostly Stuttgart and Duisburg are
  retrieved. `minArea` 10000 (29), 5000 (23), 20000 (3); rings mostly `[100, 200, 300]`, as in the
  Stuttgart example. The three wrong outputs all use `minArea` 20000, which drops too many
  parks. The three strict failures lack `min-area-filter` but still pass the output grading.

## Setup

- Stack from `docker-compose.yml`, batch on the host. Model `claude-haiku-5-5`, effort medium,
  `MAX_WORKFLOW_ITERATIONS` 16, `VALIDATE_IO_TYPES` off, `FEWSHOT_K` 2,
  `FEWSHOT_MIN_SIMILARITY` 0.
- Catalog: 25 processes (19 local, 6 from demo.pygeoapi.io; maps.ecere.com answered 401).
- Few-shot examples: the 18 files in `fewshot_examples/`. For the run without CoolSpots, the two
  `coolspots-*.yaml` files were renamed to `_coolspots-*.yaml` and the crawler was re-run (16
  examples in the database).
- Run folders, committed without `executions/` (730 MB of GeoJSON outputs, git-ignored; re-create
  them with `--execute`): `metrics/prompt_gen/out/20261028-claude_muenster_green_300m/` (pgvector,
  mcp, fewshot with CoolSpots) and `…_no-coolspots/` (fewshot without CoolSpots; same
  `config.json`, `candidates.jsonl` and `reviewed.jsonl`).
- Per variant: `python -m src.batch <run_dir> --variant V --seed-runs 5 --concurrency 4`, then
  `--execute`, then `metrics/grading/grade.py <run_dir> --variant V` (target `within`), then
  `--summary --expect city-boundary,osm-green-areas,min-area-filter,multi-ring-buffer`.
- `--execute` was called twice per variant: some graphs failed on overloaded public Overpass
  servers ("every Overpass mirror failed"); the second call only re-runs graphs that did not finish
  cleanly, and then all of them ran.

## How the paraphrases were made

These paraphrases do **not** come from `prompt-gen run`. qwen3:8b on this machine's CPU needed
1–5 minutes per attempt (5–10 hours for a run), so the generation was done by Claude Code
subagents, keeping the gates of `metrics/prompt_gen`:

1. **Generator**: one Claude Haiku subagent per category, given the seed, the category definition,
   ETPC types and forbidden operations (`src/prompt_gen/typology.py`), the examples
   (`data/examples.yaml`) and the hard constraints (`seeds/muenster_green_300m/constraints.yaml`),
   strict mode (no vague restatements). 14 candidates per category, then a second round for the
   categories still short, with the accepted and near-duplicate candidates fed back (145
   candidates in all).
2. **Deterministic gates**, using the package's own code: the word-family check
   (`stems.check`, morphological only), semantic and pragmatic similarity (`Scorer`), and the
   near-duplicate threshold `near_duplicate_sem` 0.97 against the accepted paraphrases of the
   same category.
3. **Judge**: Claude Sonnet subagents (a different model than the generator) gave each
   constraint a kept/relative/failed verdict and checked grammar and category fit. A candidate is
   accepted only if every constraint is kept. Before judging, the judge was checked on the seed's
   `trap_set` and got all 13 cases right, including the two vague phrasings strict mode must reject.
4. At most 10 per category were accepted: **53 paraphrases**, 10 in each category except
   morphological (3). Pure word-form changes almost always stay above the 0.97 near-duplicate
   threshold (13 of 27 morphological candidates were rejected for it).
5. `reviewed.jsonl` takes the gates' decision as the review decision, with the note "auto: Claude
   Code gates, not reviewed by hand". **No human reviewed these paraphrases.**

`config.json` of the run folder records this (`generated_by`). The scripts for steps 2–5 were
scratch files and are not in the repository.

## Caveats

- **Not comparable with the earlier report** (`metrics/report/summary.md`, run
  `20261012-174604_muenster_green_300m`): other paraphrases (generated by Claude instead of
  qwen, not reviewed by hand), prompts changed since then (step 6 of `docs/modular-variants.md`),
  and 5 seed runs instead of 200. The overall picture matches: `pgvector` strict about 30%,
  `mcp` about 90%, `pgvector` at about half the cost.
- **Small sample**: 58 prompts per variant, and only 3 morphological paraphrases. Differences of
  a few points between `mcp` and `fewshot` cannot be told apart from chance.
- **Possible self-bias**: the paraphrases were written by Claude Haiku, the model the agent runs
  on.
- **The CoolSpots examples are oracle examples** (see `fewshot_examples/README.md`): with them
  loaded, a `fewshot` score is an upper bound, not a fair measurement.
- **The scripted user helps `pgvector` and `mcp`**: when the agent leaves `minArea` unset, the
  executor answers 4000, the reference value (`ANSWERS` in `LangGraph/src/batch_execute.py`).
  This lifts their output scores; `fewshot` always set the value itself.

## Next steps

- More prompts (or a second seed) to separate `mcp` from `fewshot`; a difference of 5 points
  needs several hundred prompts per variant.
- A human review of the 53 paraphrases in `prompt-review`, then the same runs again.
- Measure `fewshot` with a calibrated `FEWSHOT_MIN_SIMILARITY`: every request currently retrieves
  two examples, even when no example is a close match (all similarities lie between 0.60 and 0.75).
