# Few-shot examples

Solved examples for the `fewshot` workflow variant (`LangGraph/src/llm/variants.py`). For each
user turn, the agent looks up the examples whose **request** is closest to the user's request and
shows them, with their solution graph, to the manager and auto_build.

`hamburg-water-bodies.yaml` is a **dummy** to start from: it is loaded and shown to the agent like
any other example, so replace or delete it before measuring.

## Adding an example

1. Copy `_template.yaml` to `<id>.yaml` and edit it (one example per file).
2. Load it into the database by re-running the crawler, which syncs this folder on every run:

   ```sh
   docker compose run --rm ogc-database
   ```

   No restart of `langgraph` is needed; the next user turn finds the new example.

Deleting a file removes its example on the next sync. Files starting with `_` are ignored.

## Format

| Key | Required | Meaning |
|---|---|---|
| `id` | yes | Unique name. Logged in `decision_history` of every run that used the example. |
| `request` | yes | The user request. The only part that is embedded and searched. |
| `solution.workflow_graph` | yes | The solution, in the `workflow_graph` format of `workflows.jsonl`: `nodes` (each with `id` and `type` = OGC process id, optionally `config`, `inputs`, `outputs`) and `edges` (`source`, `source_output`, `target`, `target_input`). |
| `notes` | no | Why the graph looks like this. Shown to the agent with the example. |

A graph the agent built can be copied from a batch result (`workflow_graph` in
`workflows[.<variant>].jsonl`) and then corrected by hand.

The sync checks the structure (required keys, edges between existing node ids). A file that fails
the check is logged as an error by the `ogc-database` service and skipped; the other examples are
still loaded. The sync does **not** check that process types or input/output names exist in the
catalog.

## Data leakage

Never add a task from the evaluation set — the seed prompt (`metrics/prompt_gen/seeds/`, e.g.
CoolSpots / green areas within 300 m in Münster) or any of its paraphrases — as an example. Seed and
paraphrases embed almost identically, so the retrieval would hand the agent the solution for every
test prompt and the scores would no longer say anything about the variant. This is not checked
automatically. To audit a run, look at the `examples` ids in the manager's `decision_history`
entries of `workflows.fewshot.jsonl`.

## Settings

- `FEWSHOT_K` (LangGraph, default 2): how many examples are shown per turn.
- `FEWSHOT_MIN_SIMILARITY` (LangGraph, default 0): examples below this cosine similarity are not
  shown; with none above it, the agent works without examples.
- `FEWSHOT_DIR` (ogc-database): where the crawler reads the files; compose mounts this folder there.
