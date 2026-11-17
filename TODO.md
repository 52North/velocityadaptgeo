# TODO

Originally written 2026-10-01 on branch `feature/port-type-checks`; translated and updated
2026-10-27 on `feature/modular-variants` (see docs/modular-variants.md).

## Input/output type check

Done: lenient type check in the validator (`LangGraph/src/llm/nodes/validator.py`). The input/output
descriptions are fetched from the catalog at check time with `fetch_io_specs()`. `object` matches
GeoJSON/raster/bbox; an error is raised only for clear conflicts (e.g. `number` → `object`,
GeoJSON → raster). Since `feature/modular-variants` it is a switch, `VALIDATE_IO_TYPES` (default
off, so the variants behave as measured).

- [x] Review the diff, decide whether to merge (adopted as a switch on `feature/modular-variants`)
- [ ] Enrich the process definitions in `pygeoapi_instance/processes/` with OGC vocabulary
  (`"format": "geojson-feature-collection"`, `"contentMediaType": "image/tiff"` …) and re-crawl the
  catalog – only then can the check tell raster from vector
- [x] Unit tests in the repo; `validate_graph(graph, io_specs=..., check_types=True)` is testable
  without a database (`LangGraph/tests/test_validator.py`)
- [ ] Check required inputs (`required: True` / `minOccurs ≥ 1`, neither an edge nor a value in
  `config`) – conflicts with the manager rule "leave unknown values open", so decide first: error
  or only a warning?
- [ ] The manager prompt (`management.py`) claims the validator checks "type mismatches, dangling
  inputs" – types are checked only with `VALIDATE_IO_TYPES` on, dangling inputs never; align the
  prompt or the validator
- [ ] Manually added nodes (`add_node`, `add_top_candidate`) get no input/output names – with the
  type check on, the validator takes them from the catalog, but the frontend still shows none on
  the node
- [ ] With the type check on, the validator queries the database on every call – cache if needed

## Saving / reusing workflows

- [ ] Save finished graphs and let the user edit them by hand (the edit endpoint in `app.py`
  already exists)
- [ ] Alternatively/additionally: recipes as numbered lists with step references, e.g.
  "(1) minus (4)"; the planner fetches the top-k recipes as a template and writes its own plan
  from them (`plan`, `plan_cursor`, `step_nodes` in the state, `origin` per step). Related: the
  `fewshot` variant now retrieves solved example graphs (`fewshot_examples/`)
- [ ] `GraphBuildDecision` in `auto_builder.py` allows only one incoming edge per new node → allow
  a list of connections (needed e.g. for `geometry-difference` with `subject` + `subtrahend`)

## Evaluation

- [ ] Cool Spots prompts with Haiku vs. a larger model, each with/without recipe (2×2) – separates
  the workflow abstraction from discovery + wiring
- [ ] Compare the built graphs with the chain of `metrics/grading/cool_spots.py` (formerly
  `pygeoapi_instance/CoolSpots/cool_spots.py`)
- [ ] Test anchoring: prompts "almost like Cool Spots, but …" – does the difference show up in the
  plan?
