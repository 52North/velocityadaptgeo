# setup

paste the LLM key - the only value not in `docker-compose.yml`
```bash
cp LangGraph/.env.sample LangGraph/.env
```

## usage
```bash
docker compose up
```
then open `http://localhost:8000/`

re-crawl the process catalog without restarting the stack
```bash
docker compose run --rm ogc-database
```

change a model, embedding dimension, crawl target or OSM endpoint: edit the
`environment:` block of that service in `docker-compose.yml`

run the API on the host instead of in compose - addresses default to the compose
service names, so off-network runs must override them
```bash
# ./LangGraph
DB_DSN=postgresql://postgres:postgres@localhost:5432/velocityadaptgeo \
OLLAMA_BASE_URL=http://localhost:11434 \
uv run uvicorn src.app:app --host 0.0.0.0 --port 8000
```
