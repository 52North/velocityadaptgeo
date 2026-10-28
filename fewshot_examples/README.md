# Few-shot examples

Solved examples for the `fewshot` workflow variant (`LangGraph/src/llm/variants.py`). For each
user turn, the agent looks up the examples whose **request** is closest to the user's request and
shows them, with their solution graph, to the manager and auto_build.

Every example uses only the nine processes of the local pygeoapi that execute (`city-boundary`,
`osm-green-areas`, `osm-water-bodies`, `min-area-filter`, `buffer`, `multi-ring-buffer`,
`geometry-difference`, `feature-merge`, `core-area-metrics`); the metadata-only stubs and the
demo.pygeoapi.io processes appear in none.

| Example | Nodes | Shows |
|---|---|---|
| `berlin-kreuzberg-buffer-1km` | 2 | the simplest buffer; a district as the place |
| `hamburg-water-bodies` | 2 | extraction inside a boundary |
| `cologne-water-setback-50m` | 3 | buffer on a whole feature collection |
| `leipzig-forests-over-10ha` | 3 | narrowed tags; hectares to square metres |
| `dresden-allotments-core-area` | 3 | `osm-green-areas` for any OSM tag; interior and compactness |
| `duisburg-industrial-distance-zones` | 3 | several distances = `multi-ring-buffer` |
| `bremen-dry-land-share` | 3 | difference with area and share |
| `nuremberg-pitches-and-playgrounds` | 4 | one process twice in parallel branches, merged |
| `hanover-large-parks-interior` | 4 | filter, then interior |
| `bonn-far-from-water-500m` | 4 | gap analysis: buffer, then subtract from the boundary |
| `stuttgart-forest-core-distance-bands` | 5 | chain of four; `cores` passed on instead of `features` |
| `mannheim-sports-ground-gaps-800m` | 5 | filter before buffer, then gap analysis |
| `munich-industrial-zone-without-water` | 5 | a buffer as the subject of the difference |
| `freiburg-vineyards-orchards-interior` | 6 | merge before filter |
| `kiel-park-and-water-gaps-400m` | 6 | merged destinations, one buffer, gap analysis |
| `potsdam-lakeshore-without-parks` | 6 | one output feeding two nodes; merged subtrahend |
| `coolspots-muenster`, `coolspots-muenster-parallel` | 5, 8 | **oracle**: the evaluation tasks themselves (below) |

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

### Oracle examples

`coolspots-muenster.yaml` and `coolspots-muenster-parallel.yaml` break this rule on purpose: they
are the two CoolSpots prompts of `prompts.jsonl` with their solution, using the parameters of the
grading reference (`metrics/grading/cool_spots.py`). With them loaded, a `fewshot` run measures an
upper bound (the agent is shown the answer), not how well the variant generalises.

- Fair run: rename both to `_coolspots-*.yaml` and re-run the crawler, which removes them.
- The batch skips prompts that already have a result, so run the oracle and the fair measurement
  in separate copies of the run folder.
- Always report whether the oracle examples were loaded.

## Settings

- `FEWSHOT_K` (LangGraph, default 2): how many examples are shown per turn.
- `FEWSHOT_MIN_SIMILARITY` (LangGraph, default 0): examples below this cosine similarity are not
  shown; with none above it, the agent works without examples.
- `FEWSHOT_DIR` (ogc-database): where the crawler reads the files; compose mounts this folder there.
