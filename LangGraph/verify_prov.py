"""One-off: run the real agent loop with the retriever's catalog search stubbed, then verify
the resulting PROV document. Does NOT need the docker-compose stack running - only
ANTHROPIC_API_KEY, set in LangGraph/.env, as a precondition.

    cd LangGraph && uv run python verify_prov.py
"""
import asyncio
import os
import subprocess
import sys
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()

from langchain_core.messages import HumanMessage

import src.llm.nodes.retriever as retriever_module
from src.llm.workflow import compiled_graph, DEFAULT_WORKFLOW_CONFIG, MAX_WORKFLOW_ITERATIONS
from src.prov_tracker import ProvTracker, NODE_READS, PROV_ROOT_URL, PROV_PROCESS_ID

PROMPT = "Buffer the city of Münster by 500m."

CANNED_CANDIDATES = [
    {"process_id": "geocode", "server_url": "http://pygeoapi:80", "title": "Geocode place name",
     "description": "Resolve a place name to a point/polygon geometry.",
     "inputs": {"place": {"type": "string"}}, "outputs": {"geometry": {"type": "geometry"}},
     "similarity": 0.91},
    {"process_id": "buffer", "server_url": "http://pygeoapi:80", "title": "Buffer geometry",
     "description": "Buffer a geometry by a distance in meters.",
     "inputs": {"geometry": {"type": "geometry"}, "distance": {"type": "number"}},
     "outputs": {"result": {"type": "geometry"}}, "similarity": 0.88},
]


class _StubSearchTool:
    """Replaces the live pgvector/Ollama-backed catalog search so this script needs no
    docker-compose stack - only a real Anthropic LLM driving the actual node loop."""

    async def ainvoke(self, input: dict):
        return CANNED_CANDIDATES


async def main() -> int:
    # retriever.py did `from src.llm.tools.ogc_client import search_ogc_processes`, binding
    # the name into ITS OWN module namespace - patching ogc_client's attribute would not
    # affect that already-bound reference. Patch the name where it's actually looked up.
    retriever_module.search_ogc_processes = _StubSearchTool()

    job_id, thread_id = str(uuid4()), str(uuid4())
    tracker = ProvTracker(
        compiled_graph, root_url=PROV_ROOT_URL, process_id=PROV_PROCESS_ID,
        job_id=job_id, output_keys=["workflow_graph"], node_reads=NODE_READS,
    )

    inputs = {
        "messages": [HumanMessage(content=PROMPT)],
        "iteration": 0,
        "max_iterations": MAX_WORKFLOW_ITERATIONS,
    }
    config = {**DEFAULT_WORKFLOW_CONFIG, "configurable": {"thread_id": thread_id}, "callbacks": [tracker]}

    result = await compiled_graph.ainvoke(inputs, config=config)
    tracker.add_result("final_reply", result["messages"][-1].content)

    print("Node invocation counts:", tracker._invocations)
    print("Final workflow_graph:", result.get("workflow_graph"))
    print("Final reply:", result["messages"][-1].content)

    os.makedirs("prov", exist_ok=True)
    tracker.document.serialize("prov/job_prov.json", indent=2)
    tracker.document.serialize("prov/job_prov.ttl", format="rdf", rdf_format="turtle")
    with open("prov/job_prov.provn", "w") as f:
        f.write(tracker.document.get_provn())
    print("Wrote prov/job_prov.{json,ttl,provn}")

    rc = subprocess.call([sys.executable, "check_ogc.py", "prov/job_prov.ttl"])
    print("check_ogc.py exit code:", rc)
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
