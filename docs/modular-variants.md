# Modular workflow variants: how we got here

Status: 2026-10-27, branch `feature/modular-variants` (based on `main` a51bb43).

This document records the analysis, the decisions taken with the team (human in the loop) and the
implementation plan for making the competing approaches of this project switchable. It is the
reference for this branch. **Code + this document are the source of truth** until the team says
otherwise; older notes (e.g. `workflow-migration.md`, a local, untracked file) are a collection of
ideas, nothing from them is adopted blindly.

## 1. Why

The project evaluated several ways of turning a natural-language geo task into an executable
workflow, and the team does not agree yet which one to pursue. Instead of committing to one, the
approaches are built **modularly and switchable**, so that they can be compared and swapped quickly.

## 2. Terminology

- **Inputs/outputs**: the named inputs and outputs of a process node in the workflow graph
  (`source_output` → `target_input` on an edge). They are **never** called "ports" — a port is a
  network port. Older code used "port"; it is renamed on this branch, including the LLM prompts.
- **Workflow graph**: the OGC process DAG the agent builds (JSON `nodes`/`edges`). It is *not* a
  LangGraph graph — LangGraph only runs the agent loop that builds it.
- **Variant**: one way of providing tools (and examples) to the agent. Variants share the graph
  building loop and the executor.

## 3. What the system is (state of `main` a51bb43)

- Natural-language geo task → **OGC process DAG** → executed by `LangGraph/src/execution/runner.py`
  against OGC API Processes servers (local pygeoapi + allowlisted remote servers).
- Services (`docker-compose.yml`): `langgraph` (FastAPI, agent, runner, vanilla JS frontend),
  `pygeoapi` (19 processes: 9 real, 10 metadata-only stubs used as decoys), `ogc-database`
  (one-shot crawler → pgvector, Ollama `nomic-embed-text`), `postgres-vector`, `ollama`, `mcp`
  (FastMCP, one tool per OGC process; used only as a catalog), `laya` (optional shadow decision
  model).
- Agent loop (`LangGraph/src/llm/workflow.py`): `manager` (Claude Haiku 5.5, one action per turn) →
  `retriever` → `auto_build` (structured output: picks **and wires** one candidate, then validates)
  → `manager` … → `responder`. Plus `builder` (deterministic graph ops), `validator`, `chat`.
- The LLM sees, per candidate, name, title, description **and** the full input/output schemas
  (manager and auto_build prompts) — it needs input/output names to wire edges.
- The validator checks schema, input/output names and cycles — **no types**.
- Existing variant axis: `RETRIEVERS = {"pgvector", "mcp"}`, chosen at import time by
  `WORKFLOW_VARIANT`. Only the retriever node and one prompt fragment differ. The variant list was
  hard-coded in `workflow.py`, `batch.py`, `metrics.py` and `metrics/report/analysis.py`.
- The original approach (commit 173a963: a ReAct agent calling MCP tools directly, no graph) no
  longer exists on `main`.

### Evaluation harness

`metrics/prompt_gen` (seed `muenster_green_300m` + ETPC paraphrases) → `metrics/prompt_review` →
`python -m src.batch <run_dir> --variant …` → `--execute` → `metrics/grading/grade.py` (IoU against
an OSM reference) → `metrics/report` (Quarto). Results contract: `workflows[.<variant>].jsonl` and
`runs.jsonl` (pgvector is the default and has no file suffix).

- **Strict** = the graph's edge set is exactly `city-boundary → osm-green-areas → min-area-filter →
  multi-ring-buffer`. **Lenient** = that chain is present and wired in order, extra nodes allowed.
  Both are structural; parameters are not compared.
- Results on paraphrases (structural): MCP 96 % lenient / 91 % strict, pgvector 81.5 % / 27 %. The
  pgvector strict drop comes mostly from an extra, redundant 300 m `buffer` node (`summary.md`).
- About 13–14 LLM calls per CoolSpots request (local `runs.jsonl`); the candidate list is sent with
  every manager and auto_build call, no prompt caching.

## 4. Other branches

| Branch | Content | Verdict |
|---|---|---|
| `feature/mcp-comparison` | MCP *replaces* pgvector | superseded by PR #3 (variant switch) |
| `refactor/multi-agent-system` | Claude Code developer agents + `codebase_guide/` | developer tooling, not a runtime variant; stale |
| `provence`, `provenance-w3c-prov-json` | `ProvTracker` callback, W3C PROV-JSON | superseded by the OGC flavour |
| `provenance-ogc-prov-json` | OGC/52N PROV profile, JSON-LD, `validate_prov.py` | relevant, **not in scope yet** |
| `feature/port-type-checks` | lenient input/output type check in the validator + TODO | **adopted** on this branch as "I/O type check" |

Local untracked leftovers (`prov/*.json`, `metrics/runs.jsonl`, `metrics/report_de.html`,
`diff_provs.txt`) are outputs of provenance test runs and a branch diff; they stay untouched.

## 5. Cross-check against `workflow-migration.md`

That note was written without the code as context and was read last, as a cross-check.

Confirmed: the measured lenient/strict numbers; "MCP variant" effectively means "all tools in
context" (MCP is only the catalog, execution always goes through the runner).

Corrected or clarified:

1. "A LangGraph graph is built" — the result is an OGC process DAG; LangGraph is the agent loop.
2. "RAG plans without tool knowledge, MCP plans and selects together" — in the code both use the
   **same incremental planning loop**; the manager never sees the catalog up front, only the
   candidates of the last search (MCP: all ~25, pgvector: top 5).
3. Strict/lenient: see section 3. "Lenient = acceptable result" is not what the code measures.
4. LLM calls per request: ~13–14 (see above).
5. Type check with feedback: not on `main`; a generic feedback path exists (`last_validation` →
   manager). Types only on `feature/port-type-checks`; the process schemas still need OGC format
   vocabulary for raster vs. vector to be told apart.
6. "Input/output types are used to check connections" — not yet (see 5).
7. "One few-shot example exists" — there is no example database; the only example is the inline
   "Buffer Munich 500m" in the manager prompt.
8. Token figures 191k/88k could not be traced to code or reports (the local `report_de.html` says
   154,665 vs 59,556 for a different run).
9. "Do not restructure the architecture before step 1 is measured" — superseded by the team's
   decision to make the variants modular now.

## 6. Decisions (human in the loop)

- **Exactly three variants**, from which the workflow graph is built. They differ **only in what is
  provided** to the manager and auto_build; the graph building loop is shared:

  | ID | Tools | Examples |
  |---|---|---|
  | `pgvector` ("rag") | top 5 by embedding search (as before) | – |
  | `mcp` | every tool of the MCP server (as before) | – |
  | `fewshot` (new) | **every** process of the catalog database, same presentation as before | few-shot examples, retrieved by embedding the request |

  The IDs `pgvector`/`mcp` are kept so existing run folders and reports stay valid.
- In `fewshot` the LLM sees the tools exactly as today (name, description, inputs/outputs). Then
  `mcp` vs `fewshot` isolates the effect of the examples. A two-stage selection (choose by
  description first, show inputs/outputs only for the chosen tool) is a possible later, separate
  switch.
- **Execution is the same for all variants**: the OGC runner.
- **Few-shot database**: the infrastructure is built here, the team adds the examples. Protection
  against data leakage is manual: no seed or paraphrase task (CoolSpots) may be an example, or the
  retrieval would hand the model the solution for every test prompt and inflate the scores.
- **I/O type check** from `feature/port-type-checks` is adopted as a switch independent of the
  variant (`VALIDATE_IO_TYPES`, default off so `pgvector`/`mcp` behave as measured).
- **Mechanism**: one entry point and one **variant registry** (`LangGraph/src/llm/variants.py`) as
  the single source; a variant is a combination of building blocks, a new combination is one
  registry entry.
- **No more "port"** where inputs/outputs are meant — code, UI, docs **and LLM prompts**.
- **All documentation in English** from now on.
- Not in scope: provenance, two-stage selection, a ReAct variant, execution via MCP, integration
  into the `velocityadapt-stack`.

## 7. Implementation plan (one commit per step)

1. **Variant registry, no behaviour change.** `variants.py` (pure data, no LLM/DB imports);
   `build_workflow(variant)` factory in `workflow.py`; `AUTO_BUILD_SYSTEM` derived from the
   registry with byte-identical prompts for `pgvector`/`mcp` (snapshot test); `batch.py`,
   `metrics.py`, `metrics/report/analysis.py` read the registry.
2. **`fewshot`, part 1: catalog in context.** `list_ogc_processes()` in `ogc_client.py` (same
   candidate shape as the search), `catalog_retriever_node`, registry entry.
3. **`fewshot`, part 2: few-shot infrastructure.** `fewshot_examples/` (README + template, YAML per
   example); `ogc_database/src/fewshot.py` syncs the files into a `fewshot_examples` pgvector table
   on every crawler run; `LangGraph/src/llm/tools/fewshot_client.py` retrieves the nearest examples;
   manager and auto_build add a "SOLVED EXAMPLES" block only when the variant asks for it; the
   example ids are logged in `decision_history`.
4. **I/O type check.** Cherry-pick the two commits of `feature/port-type-checks`, rename to
   inputs/outputs (`io_kinds`, `io_compatible`, `fetch_io_specs`), translate `TODO.md`, switch
   `VALIDATE_IO_TYPES`.
5. **"port" → inputs/outputs in code, comments and UI** (no prompt text).
6. **"port" → inputs/outputs in the LLM prompts** and the `set_input` argument. This changes the
   prompts of every variant: earlier measurements are no longer strictly comparable and
   `pgvector`/`mcp` need to be measured again.
7. Docs: variant section in `LangGraph/README.md` and `SETUP.md`, outdated root `README.md` fixed.

## 8. Verification

Approved: unit tests and Docker, **no LLM calls** (no Anthropic requests).

- Unit tests: registry consistency, prompt snapshots, I/O type check without a database, few-shot
  file parsing.
- Docker: build, start the stack, crawler + few-shot sync run, `langgraph` starts with every
  variant, retrievers return the same candidate shape (Ollama embeddings only), a temporary test
  example is found by the few-shot retrieval and shows up in the rendered prompt, then is removed.
- **Not verified here**: real agent runs and measurements — to be done by the team, in particular
  re-measuring `pgvector`/`mcp` after step 6.

## 9. Open points / decisions taken autonomously

The team was away during implementation; decisions taken without asking are listed here.

- Untracked German files (`docs/integration-velocityadapt-stack.md`, `workflow-migration.md`) were
  left untouched and untranslated; they are the team's local notes.
