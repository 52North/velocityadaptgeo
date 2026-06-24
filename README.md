We are transitioning away from MCP to RAG, as the LLM is supposed to enrich the User-Interface by creating a Graph.

Part 1: RAG
- pgVector + JsonB
  - Vector to make Searching optimized, most likely overkill.
  - JsonB to store Json-Structure natively
    - Schema: Description, Node-Structure (Json), Name, Input, Output

Part 2: Combining Building-Blocks together
- LLM should get the current UI-State from the building blocks.
- LLM uses RAG to extract Building Blocks


Part 3: Validation
- Validate the whole graph to ask questions --> Should these be valid?
    - Ask questions, in case the inputs and outputs are misaligned



-----

Questions:
- Should MCP be used for geospatial tasks for an LLM?
  - Only valid
-

Plan:
- RAG instead of MCP
  - Integrate the Json-Graph as elements in some database.
- RAG: pgVector + JsonB



                       ┌─────────────────┐
                       │ tool_registry   │  loads OGC search tools (pgvector)
                       │                 │  + graph-builder tools (Agents)
                       └────────┬────────┘
                                │
                       ┌────────▼────────┐
                       │     manager     │  plans next step against current graph
                       └────────┬────────┘
                                │
                  ┌─────────────┼─────────────┐
                  │             │             │
            ┌─────▼────┐  ┌─────▼─────┐  ┌────▼─────┐
            │ retriever│  │  builder  │  │ validator│
            │ (search) │  │           │  │ (graph)  │
            └─────┬────┘  └─────┬─────┘  └────┬─────┘
                  │             │             │
                  └─────────────┼─────────────┘
                                │
                         (back to manager, until done) --> Recursive calls
                                │
                              END
