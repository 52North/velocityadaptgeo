# grading

Grades the output of the workflow graphs built by `LangGraph/src/batch.py` against a reference solution for the Münster green-space prompts. A result in the same ballpark as the reference counts as correct, since the agent may choose a different minimum park size or other ring steps. Plan and results: `metrics/.docs/output_grading_plan.md`.

## Usage

```
# Once, or with other parameters: the reference (OSM download ~4 min, then cached in cache/)
uv run python cool_spots.py [--min-area 4000] [--intervals 0,75,150,225,300] [--tags JSON] [--out outputs/reference.gpkg]

# Per run folder and variant: execute the graphs (in LangGraph, needs pygeoapi on localhost:5000), then grade
(cd ../../LangGraph && uv run python -m src.batch ../metrics/prompt_gen/out/<run_id> [--variant mcp] --execute)
uv run python grade.py ../prompt_gen/out/<run_id> [--variant mcp] [--target within|beyond]

# How far apart the plausible readings of the prompt lie (what the thresholds are set from)
uv run python grade.py --sensitivity

uv run pytest
```

## Files

- `cool_spots.py`: the reference. `outputs/reference.gpkg` (committed) holds both answers: `within` (the city within 300 m of a park or forest of at least 4000 m², for the green-300m prompt) and `beyond` (the rest of the city, for the CoolSpots prompt), plus the distance `rings`, the city and the green spaces. `outputs/reference.json` has the parameters and areas.
- `grade.py`: compares each executed graph with the reference (area IoU, distance-band agreement, largest distance) and writes `grades[.<variant>].jsonl` into the run folder. The target follows from the run's seed id.
- `tests/`: pytest for `grade.py`.

Thresholds (lenient: every minimum area from 1000 to 10000 m², any ring steps, with or without `natural=wood` passes): within ≥ 0.90, beyond ≥ 0.55, bands ≥ 0.78, largest distance 300 m.
