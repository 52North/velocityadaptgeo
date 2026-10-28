# setup

paste the LLM key - the only value not in `docker-compose.yml`
```bash
cp LangGraph/.env.sample LangGraph/.env
```

## usage
```bash
docker compose up
```
then open `http://localhost:8000/` - the API starts only after pygeoapi answers and the
catalog crawl has finished, so the first start takes a while

every port is published on the host's loopback only: the API has no auth and each chat turn
spends the Anthropic key. From another machine, tunnel in and open the same address
```bash
ssh -L 8000:localhost:8000 <user>@<host>
```

re-crawl the process catalog without restarting the stack
```bash
docker compose run --rm ogc-database
```
a crawl also removes processes a server no longer lists and those of servers dropped from
`OGC_SERVERS`; a server that cannot be listed completely keeps its entries

the same run syncs the few-shot examples of the `fewshot` variant from `fewshot_examples/`
(format and rules in its README); add, change or delete a file there, then re-crawl

change the LLM, a crawl target or an OSM endpoint: edit the `environment:` block of that
service in `docker-compose.yml`

switch the workflow variant (`LangGraph/src/llm/variants.py`): set `WORKFLOW_VARIANT` of the
`langgraph` service to `pgvector`, `mcp` or `fewshot`, then recreate the service. The I/O type
check is a separate switch, `VALIDATE_IO_TYPES` (`"true"`/`"false"`), in the same block
```bash
docker compose up -d langgraph
```

change the embedding model: set `OLLAMA_MODEL` (`x-ollama`) and `EMBED_DIM` (`postgres-vector`,
the model's vector size) in `docker-compose.yml`, then rebuild the catalog. The vector column
is sized only when the database volume is created, and vectors from two models cannot be
compared, so the catalog is recreated rather than updated (it holds nothing a crawl does not
rebuild)
```bash
docker compose down
docker volume rm velocityadaptgeo_postgres_data
docker compose up
```

run the API on the host instead of in compose - addresses default to the compose
service names, so off-network runs must override them
```bash
# ./LangGraph
DB_DSN=postgresql://postgres:postgres@localhost:5432/velocityadaptgeo \
OLLAMA_BASE_URL=http://localhost:11434 \
uv run uvicorn src.app:app --host 127.0.0.1 --port 8000
```

run the tests (no LLM calls, no services needed)
```bash
(cd LangGraph && uv run pytest)
(cd ogc_database && uv run pytest)
```
