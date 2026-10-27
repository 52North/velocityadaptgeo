```sh
uv run uvicorn src.app:app --reload
```
from this folder: the modules import each other as `src.…`. SETUP.md has the variables a run outside compose needs.

The workflow variants (what the agent is shown: catalog search, every MCP tool, or the whole catalog
plus few-shot examples) are listed in `src/llm/variants.py`; `WORKFLOW_VARIANT` picks one, and
`build_workflow(variant)` in `src/llm/workflow.py` builds the agent for it. A new variant is a new
registry entry, plus a retriever node if it gets its candidates in a new way.

```sh
uv run pytest
```
runs the unit tests without an LLM: `tests/test_prompts.py` compares the prompts with
`tests/snapshots/`, so a prompt change shows up as a failing test; after a deliberate change,
`UPDATE_SNAPSHOTS=1 uv run pytest` records the new prompts.

## HTTP API for other services

Another service (for example a web app's backend) uses the assistant through the routes below. They are version 1 of this contract: changes to them are additive only, and a breaking change gets a new route prefix. Routes not listed here serve the demo frontend; they work, but their shapes may still change.

### Authentication

Set `LANGGRAPH_API_TOKEN` in `LangGraph/.env` and every `/api/*` request must carry `Authorization: Bearer <token>`, otherwise it gets `401`. Unset, the API is open, which is what a local run and the demo frontend need: the frontend uses `EventSource`, which cannot send that header. `/health` and the frontend's static files are never gated.

### `GET /health`

`200 {"status": "ok"}` while the process answers. It does not probe postgres or ollama.

### `POST /api/chat`

Runs one conversation turn to completion.

Request:

| Field | Type | |
|---|---|---|
| `prompt` | string | The user's message. |
| `thread_id` | string, optional | Continues that conversation; omitted, a new one starts. |
| `graph` | graph, optional | The caller's current graph (format below). It replaces the thread's graph for this turn. A graph that does not match the format is rejected with `422`; one that matches but is incomplete (dangling edges, unknown inputs or outputs, cycles) is accepted, and the assistant sees its validation errors. |

Response:

| Field | Type | |
|---|---|---|
| `response` | string | The assistant's reply. |
| `thread_id` | string | The thread the turn ran on. |
| `graph` | graph | The graph after the turn; `{"nodes": [], "edges": []}` when nothing was built. |
| `validation` | object or null | `{"valid": bool, "errors": [string]}` for `graph`; null when no graph has been validated yet. |
| `unmet_capabilities` | list | Steps the catalog has no process for, and so were not added: `{"capability", "closest_process", "similarity"}`. |

### Who owns the graph and the thread

Two ways to call it:

- **The caller owns the graph** (recommended for services): send `graph` on every turn and leave `thread_id` out. The service keeps nothing the caller depends on.
- **The service owns the graph**: send the returned `thread_id` on the next turn. Threads live in memory only and are lost on restart.

Thread ids are not tied to users: anyone who can reach the API and knows an id can read and continue that thread. A caller that uses threads mints the ids itself, from a random source, and keeps track of which of its users each one belongs to.

### Graph format

```json
{
  "nodes": [
    {
      "id": "n1",
      "type": "<process_id>",
      "label": "",
      "position": {"x": 0, "y": 200},
      "config": {"server_url": "https://demo.pygeoapi.io/master/", "timeout_seconds": 300, "distance": 500},
      "inputs": ["geometry", "distance"],
      "outputs": ["result"]
    }
  ],
  "edges": [
    {"source": "n1", "target": "n2", "source_output": "result", "target_input": "geometry"}
  ]
}
```

- `type` is the id of an OGC API - Processes process, not a fixed set of node kinds.
- `config.server_url` is the OGC server the process runs on, `config.timeout_seconds` its time limit; every other `config` key is a static input value of the process.
- `inputs`/`outputs` are the names of the process's inputs and outputs; an edge connects `source_output` of one node to `target_input` of another.
- `id` matches `^[a-zA-Z0-9_\-]+$`; unknown fields are rejected.
- The graph is a DAG. This service executes it only against the servers in `OGC_SERVERS` and the local pygeoapi.

### `GET /api/stream`

Streams a turn as server-sent events for the demo frontend. Only these parts are part of the contract: `event` (`message`, `graph`, `error`, `done`), `content` on `message` events, and `workflow_graph`, `last_validation`, `unmet_capabilities` on `graph` events. Every other field passes LangGraph internals through and may change.
