Open: 
- Datenquellen als Node-Type
    - Open-Source-Endpunkte wie z.B. Satellite Data oder Ähnliches.
    - Hypertegrity-Endpunkte
    - S3-Kompatible-Endpunkte
    - Problem: Was macht die Anwendung, wenn wir große Daten haben, die nicht mehr so einfach hereinpassen. 
        - Idee: Automatisches Threshholding, wo anstelle der Rohdaten eine Referenz zu einem S3-Bucket geschickt wird.

- Mehr OGC-Prozesse, die Weiteres abbilden
- Capability den Graphen zu speichern und zu sharen
    - Man shared einen Workflow
- Done, Message sollte nicht in dem letzten Schritt dargestellt werden
- Ben fragen: Müssen wir die MCP-Geschichte mit als "Zweite" Geschichte machen? 
- Trennen des Graph-Runners und der LangGraph-Application auf zwei Dockerfiles/Setups.
- Give the Chatbot the capability to run the graph



On MCP-Tooling: 
Next: 
- MCP-Processes generation of process handler, but on demand, not hardcoded in any way. Same retrieval as OGC-Processes. 
- Change the Workflow of the graph, so it's less of a graph and more of an MCP-Workflow. This leans into the "Plug and Play"-Option of things. 

Restrictions: 
- Cost: with 20+ processes, all tool definitions sit in the LLM context. Bypasses pgvector retrieval.
- https://scottspence.com/posts/    optimising-mcp-server-context-usage-in-claude-code
    - Use defer loading, which only makes the tool names be introduced. 
    - No explanations provided, as we only see the names. Good when you want to e.g. call "Maps"
    - Not "how many servers" but "how many tools are simultaneously visible and how well-differentiated their names/descriptions are"