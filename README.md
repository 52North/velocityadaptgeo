```
┌──────────────────────────────┐
│          LLM Client          │
│     (Claude / GPT / etc.)    │
└──────────────┬───────────────┘
               │ MCP (Tool Invocation)
               ▼
┌──────────────────────────────┐
│      FastAPI MCP Server      │
│                              │
│  • Exposes MCP tools         │
│  • No geoprocessing logic    │
│  • LLM-facing interface     │
└──────────────┬───────────────┘
               │ HTTP (OGC API – Processes)
               ▼
┌──────────────────────────────┐
│           pygeoapi           │
│                              │
│  /processes/buffer           │
│  /processes/*                │
│                              │
│  • OGC-compliant API         │
│  • Validated inputs          │
│  • Stable contracts          │
└──────────────┬───────────────┘
               │ Python (Shapely)
               ▼
┌──────────────────────────────┐
│      Geoprocessing Core      │
│                              │
│  Shapely Buffer              │
│  (authoritative logic)       │
└──────────────────────────────┘
```