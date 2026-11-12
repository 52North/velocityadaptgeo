# Architecture diagrams

Mermaid sources (`*.mmd`), rendered to `out/*.svg`.

```sh
npm install     # once; pulls mermaid-cli with a headless Chromium
npm run build   # renders every *.mmd to out/
```

| Diagram | Shows |
|---|---|
| `architecture.mmd` | Overall architecture; the retriever finds processes either by RAG (pgvector) or through MCP |
| `tool-retrieval.mmd` | Tool retrieval of both options step by step, and what it puts into the context window |
