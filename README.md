# velocityadaptgeo

A geospatial assistant: a natural-language task ("find the cool spots in Münster within 300 m of
green space") becomes a **workflow graph of OGC API - Processes**, which the user can inspect, edit
and execute. Setup and operation: [SETUP.md](SETUP.md). How the approaches came to be modular, and
the decisions behind it: [docs/modular-variants.md](docs/modular-variants.md).

## How it works

```
 user request
      │
┌─────▼─────┐  one action per turn   ┌───────────┐   ┌────────────┐
│  manager  ├───────── search ──────►│ retriever ├──►│ auto_build │── picks and wires one
│ (LLM)     │◄────────────────────────────────────────┴────────────┘   candidate, validates
│           ├── build / validate ──► builder / validator (deterministic)
│           ├── done ──────────────► responder ──► reply + workflow graph
└───────────┘
                         workflow graph ──► execution/runner.py ──► OGC API - Processes servers
```

- **LangGraph** runs the agent loop above (`LangGraph/src/llm/`). The workflow graph it builds is a
  DAG of OGC processes (`nodes`, `edges` from a named output to a named input), not a LangGraph
  graph.
- **Execution** (`LangGraph/src/execution/runner.py`) posts the graph's processes in order to the
  allowlisted OGC servers: the local `pygeoapi_instance/` and remote servers in `OGC_SERVERS`.
- **Catalog**: `ogc_database/` crawls the servers into pgvector (Ollama embeddings); `mcp/` exposes
  the same processes as MCP tools.

## Workflow variants

The approaches the team is comparing are variants of what the agent is shown; the graph building,
validation and execution are shared. One registry lists them: `LangGraph/src/llm/variants.py`,
chosen with `WORKFLOW_VARIANT` (or `python -m src.batch --variant`).

| Variant | Candidate processes | Examples |
|---|---|---|
| `pgvector` | top 5 of a catalog search per step | – |
| `mcp` | every tool of the MCP server | – |
| `fewshot` | every process of the catalog | solved examples closest to the request (`fewshot_examples/`) |

Independent of the variant, `VALIDATE_IO_TYPES` adds a check of the data kinds an edge carries.

### Few-shot examples

1. Add `fewshot_examples/<id>.yaml` (copy `_template.yaml`): `id`, `request`, `solution.workflow_graph`,
   optional `notes`. Team remarks go in `#` comments — `notes` is shown to the agent.
2. Load: `docker compose run --rm ogc-database` (also runs on every `docker compose up`).
3. Use: `WORKFLOW_VARIANT=fewshot`; `FEWSHOT_K` examples per turn, `FEWSHOT_MIN_SIMILARITY` as cutoff.

Seed/paraphrase tasks (CoolSpots) leak the answer into the evaluation. The two `coolspots-*`
files are such oracle examples on purpose; rename them to `_coolspots-*.yaml` for a fair run.
Details: `fewshot_examples/README.md`.

## Evaluation

`metrics/` generates paraphrases of a seed task, runs every variant on them, executes and grades the
resulting graphs and builds the reports; see [metrics/README.md](metrics/README.md).

## Open questions (from the early design notes)

- Data sources as a node type: open endpoints (e.g. satellite data), Hypertegrity endpoints,
  S3-compatible storage. What does the graph do when it has to pass large data instead of small
  GeoJSON?
- Validation: which questions should the agent ask the user when inputs and outputs do not fit?
