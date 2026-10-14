# Run folder contract

What `prompt-review` reads from and writes to a `prompt_gen` run folder (`prompt_gen/out/<run_id>/`). The two packages can change independently as long as this holds.

## `candidates.jsonl` (generator, read only)

One JSON object per line, one per generation attempt, in generation order. The key of a candidate is `"<category>#<attempt>"` and must be unique within the run. Records without a `prompt` (generation errors) are counted in the summary but not reviewed.

| Field | Type | Used for |
|---|---|---|
| `category` | str | the category the candidate was generated for |
| `attempt` | int | key |
| `prompt` | str \| null | the paraphrase |
| `accepted` | bool | the automated gates' decision; filters, summary |
| `reject_reason` | str \| null | gates' reason, e.g. `near_duplicate`, `relative:green_space,size`; the part before `:` makes a filter |
| `operations_applied` | list[str] | shown |
| `reasoning` | str | details: generator plan |
| `discarded` | list[{`prompt`, `feedback`}] (optional) | details: discarded drafts |
| `stems` | {`new`, `missing`} (optional) | stem check row |
| `sem` | float (optional) | scores row |
| `prag`, `prag_no_instruction` | float | scores row, when judged |
| `max_sem_same_category` | float \| null (optional) | scores row |
| `judge` | object \| null | null when rejected before judging. Fields: `verdicts` [{`id`, `status` (kept/relative/failed), `reason`}], `matches_category`, `category_reason`, `operations_found`, optional `main_change`, `grammatical`, `corrected`, `grammar_reason` |
| `closest_accepted`, `closest_any` | {`key`, `prompt`, `sem`} \| null (optional) | details: closest matches |

## `config.json`, `config_<time>.json` (generator, read only)

`config.json` is the first generation session; each resumed session adds `config_<time>.json`. "Latest" is the last of these in time order.

| Field | From | Used for |
|---|---|---|
| `seed.text` | `config.json` | "Changes vs. seed" |
| `seed.id` | latest | summary header |
| `n_per_category` | latest | summary target |
| `config.thresholds.near_duplicate_sem` | latest | the closest-match marker |
| `typology` [{`key`, `name`}] | latest | all categories in order (moves, summary rows) |
| `categories` | all | fallback for runs without `typology`: the union, `config.json` first |

## `reviewed.jsonl` (reviewer, rewritten in full)

One line per reviewed candidate, in `candidates.jsonl` order: the full candidate record plus

```json
"review": {"decision": "accept" | "reject", "category": "<category after a move>", "note": "", "at": "2026-10-14T09:00:00"}
```

Written to `reviewed.jsonl.tmp`, then renamed, after every change.
