from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from pathlib import Path
from uuid import uuid4
import json
import logging
import os
from fastapi.responses import StreamingResponse
from src.llm.workflow import compiled_graph, DEFAULT_WORKFLOW_CONFIG, MAX_WORKFLOW_ITERATIONS
from src.llm.nodes.builder import apply_build_op
from src.llm.nodes.validator import validate_graph
from src.execution import store
from src.execution.runner import (
    ExecutionError,
    as_feature_collection,
    execute_graph,
    mappable_outputs,
    run_graph,
    summarise,
)
from src.helper.helper import pretty_print_messages
from src.metrics import RunTracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"
PROMPTS_FILE = BASE_DIR.parent / "prompts.jsonl"

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

    result = await compiled_graph.ainvoke(turn_input(req.prompt), config={**turn_config(thread_id), "callbacks": [RunTracker(thread_id)]})

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
            config={**turn_config(thread_id), "callbacks": [RunTracker(thread_id)]},
            stream_mode=["messages", "updates"],
            subgraphs=True
        ):
            if mode == "updates":
                for node_name, update in (chunk or {}).items():
                    if not isinstance(update, dict):
                        continue
                    graph_payload = {
                        key: update[key]
                        for key in ("workflow_graph", "last_validation", "unmet_capabilities")
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
        store.start_run(thread_id)
        try:
            async for event in run_graph(graph):
                if "outputs" in event:
                    produced = event["outputs"]
                    store.save_node_result(thread_id, event["node"], produced)
                    event = {
                        **event,
                        "outputs": summarise(produced),
                        "geo": mappable_outputs(produced),
                    }
                if "inputs" in event:
                    event = {**event, "inputs": summarise(event["inputs"])}
                event.pop("results", None)
                yield f"data: {json.dumps(event)}\n\n"
        except ExecutionError as exc:
            yield f"data: {json.dumps({'event': 'graph-error', 'error': str(exc)})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


MAX_MAP_FEATURES = int(os.environ.get("MAX_MAP_FEATURES", "3000"))


@app.get("/api/result")
async def result_layer(thread_id: str, node: str, output: str, limit: int = MAX_MAP_FEATURES):
    """Return one execution output as a FeatureCollection for the results map.

    Only fetched when a layer is actually switched on, and capped so a run that produced
    thousands of polygons cannot lock up the browser. Truncation is reported rather than
    hidden, so a partial layer is never mistaken for the whole result.
    """
    value = store.get_node_output(thread_id, node, output)
    if value is None:
        raise HTTPException(status_code=404, detail=f"no result for {node}.{output}")

    try:
        collection = as_feature_collection(value)
    except ExecutionError as exc:
        raise HTTPException(status_code=415, detail=str(exc))

    features = collection.get("features") or []
    truncated = len(features) > limit
    return {
        "type": "FeatureCollection",
        "features": features[:limit],
        "truncated": truncated,
        "total": len(features),
    }


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


class GraphOpRequest(BaseModel):
    thread_id: str
    op: str
    args: dict = {}


@app.post("/api/graph/op")
async def graph_op(req: GraphOpRequest):
    """Apply one hand edit to a thread's graph, through the same ops the assistant uses.

    Writing back into the conversation checkpoint - rather than into a copy owned by the
    browser - is what makes a manual edit real: the next chat turn plans from the edited
    graph, so the user and the assistant never end up describing different graphs. The
    validation report is returned but not enforced, since a graph is legitimately
    incomplete while it is being wired by hand.
    """
    config = turn_config(req.thread_id)
    state = compiled_graph.get_state(config).values
    graph = state.get("workflow_graph") or {"nodes": [], "edges": []}

    try:
        graph = apply_build_op(graph, req.op, req.args)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    validation = validate_graph(graph)
    compiled_graph.update_state(config, {
        "workflow_graph": graph,
        "last_validation": validation,
        # Recorded so the assistant's next reply accounts for the edit instead of
        # narrating the graph it last built itself.
        "decision_history": list(state.get("decision_history", [])) + [{
            "node": "manual_edit",
            "instruction": {"op": req.op, "args": req.args},
            "result_summary": f"{len(graph['nodes'])} nodes, {len(graph['edges'])} edges",
            "error": None,
        }],
    })
    return {"graph": graph, "validation": validation}


@app.get("/api/test-prompts")
async def test_prompts():
    """Canned prompts from `prompts.jsonl`, offered as one-click buttons in the UI.

    One `{"label": ..., "prompt": ...}` object per line. Read per request rather than at
    import, so editing the file updates the buttons on the next page load without a rebuild.
    """
    if not PROMPTS_FILE.exists():
        return []
    return [json.loads(line) for line in PROMPTS_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html", headers={"Cache-Control": "no-cache"})
