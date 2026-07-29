from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from pathlib import Path
from uuid import uuid4
import json
import logging
from fastapi.responses import StreamingResponse
from src.llm.workflow import compiled_graph, DEFAULT_WORKFLOW_CONFIG, MAX_WORKFLOW_ITERATIONS
from src.execution.runner import ExecutionError, execute_graph, run_graph, summarise
from src.helper.helper import pretty_print_messages

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI()


class RevalidatingStaticFiles(StaticFiles):
    """Static files the browser must revalidate before reusing.

    Without this the frontend is served with only `etag`/`last-modified`, which lets a
    browser reuse a heuristically-cached `app.js` after an edit - the page then runs
    stale JavaScript against fresh markup. Revalidation still answers 304 from the
    etag, so the cost is one conditional request per asset.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", RevalidatingStaticFiles(directory=FRONTEND_DIR), name="static")

class ChatRequest(BaseModel):
    prompt: str
    thread_id: str | None = None

class ChatResponse(BaseModel):
    response: str
    thread_id: str


def turn_input(prompt: str) -> dict:
    """Build the state update for one user turn.

    `iteration` is reset on every request so a new user turn gets a fresh planning
    budget - it is checkpointed per thread and would otherwise keep growing until the
    manager hard-stops at `max_iterations` for the rest of the session. The budget is
    sent along so it stays consistent with the `recursion_limit` derived from it.
    """
    return {
        "messages": [HumanMessage(content=prompt)],
        "iteration": 0,
        "max_iterations": MAX_WORKFLOW_ITERATIONS,
    }


def turn_config(thread_id: str) -> dict:
    """Build the run config for one user turn.

    The compiled graph carries a checkpointer, which requires a `thread_id` - without
    one every call raises `ValueError`.
    """
    config = dict(DEFAULT_WORKFLOW_CONFIG)
    config["configurable"] = {"thread_id": thread_id}
    return config


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Run the workflow to completion and return the final reply, without streaming.

    Omitting `thread_id` starts a fresh conversation; pass the returned one back to
    continue it.
    """
    thread_id = req.thread_id or str(uuid4())

    result = await compiled_graph.ainvoke(turn_input(req.prompt), config=turn_config(thread_id))

    # Last message is the assistant reply
    assistant_message = result["messages"][-1].content

    pretty_print_messages(result["messages"])

    return ChatResponse(response=assistant_message, thread_id=thread_id)

@app.get("/api/stream")
async def stream(prompt: str, thread_id: str):
    async def gen():
        """Forward LangGraph message chunks and graph updates as server-sent events.

        Two stream modes are multiplexed onto one event stream: "messages" carries the
        chat tokens, "updates" carries node state so the workflow graph can be drawn
        while it is being built. Every event names its kind in `event`.
        """
        async for path, mode, chunk in compiled_graph.astream(
            turn_input(prompt),
            config=turn_config(thread_id),
            stream_mode=["messages", "updates"],
            subgraphs=True
        ):
            if mode == "updates":
                for node_name, update in (chunk or {}).items():
                    if not isinstance(update, dict):
                        continue
                    graph_payload = {
                        key: update[key]
                        for key in ("workflow_graph", "last_validation")
                        if update.get(key) is not None
                    }
                    if graph_payload:
                        graph_payload.update({"event": "graph", "node": node_name})
                        yield f"data: {json.dumps(graph_payload)}\n\n"
                continue

            message_chunk, metadata = chunk
            content = message_chunk.content

            payload = {
                "event": "message",
                "path": path,
                "metadata": metadata,
                "type": message_chunk.type,
                "id": message_chunk.id,
            }

            # Stream artifact if present to render geometry on frontend map
            if getattr(message_chunk, "artifact", None):
                payload["artifact"] = message_chunk.artifact
                logging.getLogger(__name__).info("Streaming artifact: %s", message_chunk.artifact)

            # Normal textual streaming
            if isinstance(content, str):
                payload["content"] = content
                yield f"data: {json.dumps(payload)}\n\n"

            elif isinstance(content, list):
                for block in content:
                    if block.get("type") == "text":
                        payload["content"] = block["text"]
                        yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")

def graph_for_thread(thread_id: str) -> dict:
    """Read the execution graph the assistant built for a conversation thread."""
    state = compiled_graph.get_state(turn_config(thread_id)).values
    return state.get("workflow_graph") or {"nodes": [], "edges": []}


@app.get("/api/execute")
async def execute(thread_id: str):
    """Stream the execution of a thread's graph as server-sent events.

    Node payloads are summarised rather than forwarded: a single OSM step can return
    megabytes of geometry, which belongs in the process response, not in the browser.
    Use POST /api/execute when the full result is wanted.
    """
    async def gen():
        graph = graph_for_thread(thread_id)
        try:
            async for event in run_graph(graph):
                if "outputs" in event:
                    event = {**event, "outputs": summarise(event["outputs"])}
                if "inputs" in event:
                    event = {**event, "inputs": summarise(event["inputs"])}
                event.pop("results", None)
                yield f"data: {json.dumps(event)}\n\n"
        except ExecutionError as exc:
            yield f"data: {json.dumps({'event': 'graph-error', 'error': str(exc)})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


class ExecuteRequest(BaseModel):
    thread_id: str | None = None
    graph: dict | None = None


@app.post("/api/execute")
async def execute_sync(req: ExecuteRequest):
    """Run a graph to completion and return the full results.

    Takes either a `thread_id`, to run what the assistant built, or a `graph` posted
    directly - so the executor is usable from a script or another service without going
    through the chat at all.
    """
    graph = req.graph if req.graph is not None else graph_for_thread(req.thread_id or "")
    try:
        return await execute_graph(graph)
    except ExecutionError as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html", headers={"Cache-Control": "no-cache"})
