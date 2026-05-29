# general 

create `.env` in `LangGraph/` and paste the LLM key there
```bash
cp LangGraph/.env.sample LangGraph/.env
```
## dev-setup
```bash
docker compose up
```

start them locally from their respective dirs:
```bash
# ./LangGraph
uv run uvicorn src.app:app --host 0.0.0.0 --port 8000
```

```bash
# ./mcp
uv run app.py
```

## usage
start docker
```bash
docker compose up
```

point you browser to `http://localhost:8000/` and try it out!