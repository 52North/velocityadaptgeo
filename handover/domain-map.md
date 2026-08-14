# Domain map

*Durable. Stable filename — every agent reads this first, so it is never dated, renamed,
or moved. Correct it in place; never compressed or dropped. This is the only place this
repository's specifics are written down — agent definitions are generic and read from here.*

**Last updated:** 2026-08-14

NORTH52 (VeloCityAdapt, 52°North) is a LangGraph agent that turns natural-language
geospatial questions into an executable OGC API - Processes workflow graph, runs it, and
maps the result.

## Domains

- **`database`** — `ogc_database/`: pgvector schema in `sql/init.sql`, and `src/`
  (`pipeline.py` crawls OGC servers, plus `embeddings.py`, `database.py`, `client.py`,
  `config.py`). Owns the `postgres-vector` and `ollama` services.
  *Not:* the code that queries the catalog — that is `backend`.
- **`backend`** — `LangGraph/src/` except `frontend/`, plus all of `pygeoapi_instance/`.
  - `app.py` — FastAPI. Routes: `POST /api/chat`, `GET /api/stream` (SSE),
    `GET|POST /api/execute` (SSE on GET), `GET /api/result`, `GET /`, and
    `/static` mounted from the frontend dir via a `RevalidatingStaticFiles` subclass.
  - `llm/workflow.py` — the graph. `llm/nodes/` — node bodies. `llm/state/state.py` — shared state.
  - `execution/runner.py` — topological ordering, cross-edge input resolution, and the
    GeoJSON helpers the map depends on.
  - `llm/tools/ogc_client.py` — **all** process search and execution goes through here.
  - `pygeoapi_instance/processes/` — 17 processes plus shared geometry helpers in `_geo.py`.
  - *Not:* the schema or ingest pipeline; not the browser code.
- **`frontend`** — `LangGraph/src/frontend/`: `app.js`, `index.html`, `styles.css`.
  Plain JS, no framework and no build step. Consumes the SSE stream and renders the map.

`mcp/` is **legacy and frozen** — being retired in favour of the RAG path. Do not extend
it; new capability goes on the RAG side.

## Running it

`docker compose up` → langgraph app `:8000`, pygeoapi `:5000` (container port 80),
postgres-vector `:5432` (db `velocityadaptgeo`), ollama `:11434` (`nomic-embed-text`),
mcp `:8001`.

Python ≥3.12, `uv`. **Three separate dependency trees** — `LangGraph/`, `mcp/`,
`ogc_database/` — each with its own `pyproject.toml`. Run commands from the directory that
owns the code you are touching.

Database shell: `docker compose exec postgres-vector psql -U postgres -d velocityadaptgeo`

Secrets: untracked `LangGraph/.env` (template `.env.sample`), passed to the container via
`env_file`. Never print, echo, or commit their values.

## Verification

**There is none for the application code.** `pytest>=8.4.2` is declared in
`LangGraph/pyproject.toml:21` and **zero tests exist** for `LangGraph/`, `ogc_database/`,
or `pygeoapi_instance/`. There is no frontend test setup at all. The only tests in the
tree are under `codebase_guide/tests/`, which is a separate untracked tooling directory,
not the application.

Consequence: nothing is confirmed by having been written. Verify by execution — import the
module, `curl` the endpoint, run the process through pygeoapi, run the query against the
live database, load the page in a browser.

## Quiet couplings

- **A new pygeoapi process is inert until registered** in
  `pygeoapi_instance/pygeoapi-config.yml` with its processor path, inputs, and outputs.
  Adding the Python file is half the change.
- **A new LangGraph node needs its edges in `llm/workflow.py`**, and if the manager is to
  route to it, the action must also be in `ALLOWED_ACTIONS` (`llm/nodes/management.py:25`)
  *and* described in `MANAGER_SYSTEM` (same file, `:30`). A node with no route is dead code.
  `ALLOWED_ACTIONS` is currently `("search", "build", "validate", "chat", "done")`.
- **Exporting a node from `llm/nodes/__init__.py` does not wire it.** `agent_node`,
  `action_router`, and `tool_registry_node` are all exported but never added to the graph.
- **`ogc_database/sql/init.sql` is mounted into postgres's `docker-entrypoint-initdb.d`,
  so it runs only on first initialisation of an empty volume.** Editing it does not migrate
  an existing database. A schema change needs an explicit migration path or a documented
  volume drop and re-crawl.
- **Embedding model and vector dimensionality are a joint fact** between
  `ogc_database/src/embeddings.py` and the vector column. Changing one without the other
  gives insert errors or silently meaningless distances. Re-embedding is mandatory when the
  model changes.
- **SSE event names and payload keys are a cross-domain contract** between `app.py` and
  `frontend/app.js`. Renaming a field breaks the map with nothing server-side complaining.

## Traps

- **Most pygeoapi processes are AI-generated stubs, not working implementations** —
  `kriging_interpolation`, `viewshed_analysis`, `watershed_delineation`, `least_cost_path`,
  `multimodal_isochrone`, `parcel_topology`, `pointcloud_segmentation`,
  `raster_pansharpening`, `suitability_overlay`, `trajectory_anomaly`. Read the body before
  describing one as functional.
- **The chain that is actually exercised** is CoolSpots: `city_boundary`,
  `osm_green_areas`, `min_area_filter`, `multi_ring_buffer`, `geometry_difference`,
  `buffer`, `cool_spots`.
- **Control flow is decided at runtime by model output**, not only by static edges. Graph
  wiring is `manager` (entry) → conditional → `retriever` → `auto_build` → `manager`;
  `builder` → `manager`; `validator` → `manager`; `responder` → `END`; `chat` → `END`.
  A correctly wired path the manager never selects is as dead as a missing one.
