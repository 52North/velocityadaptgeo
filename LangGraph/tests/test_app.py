"""The HTTP API: contract fields, auth, input limits, turn limits and error hygiene.

The agent is replaced by a stub graph, so no LLM, database or OGC server is needed.
"""

import asyncio
import json
import os
import subprocess
import sys

import pytest

# Building the agent at import needs a key to construct the client, not to call it; no metrics
# lines from test turns.
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ["METRICS_FILE"] = ""

from fastapi.testclient import TestClient

from src import app as app_module
from src.execution import store
from src.openapi import OPENAPI_FILE, spec

THREAD = "thread-0001"
SERVER = "http://pygeoapi:80/"


def node(node_id, server_url=SERVER):
    return {"id": node_id, "type": "buffer", "config": {"server_url": server_url},
            "inputs": ["geometry"], "outputs": ["result"]}


class StubGraph:
    """Stands in for the compiled agent: echoes the turn's graph, or fails or stalls on request."""

    def __init__(self, fail: Exception | None = None, delay: float = 0):
        self.fail, self.delay = fail, delay

    async def ainvoke(self, update, config):
        await asyncio.sleep(self.delay)
        if self.fail:
            raise self.fail
        return {
            "messages": [*update["messages"], type("Reply", (), {"text": "ok"})()],
            "workflow_graph": update.get("workflow_graph"),
            "last_validation": update.get("last_validation"),
        }

    async def astream(self, update, config, **kwargs):
        await asyncio.sleep(self.delay)
        if self.fail:
            raise self.fail
        yield (), "updates", {"builder": {"workflow_graph": {"nodes": [], "edges": []}}}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_module, "compiled_graph", StubGraph())
    monkeypatch.setattr(app_module, "API_TOKEN", "")
    return TestClient(app_module.app)


def events(response) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_health_is_never_gated(client, monkeypatch):
    monkeypatch.setattr(app_module, "API_TOKEN", "secret")
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("header, status", [(None, 401), ("Bearer wrong", 401), ("Bearer secret", 200)])
def test_token_gates_the_api(client, monkeypatch, header, status):
    monkeypatch.setattr(app_module, "API_TOKEN", "secret")
    headers = {"Authorization": header} if header else {}
    assert client.post("/api/chat", json={"prompt": "hi"}, headers=headers).status_code == status


def test_chat_returns_the_graph_and_its_validation(client):
    graph = {"nodes": [node("a"), node("b", "http://evil.example/")], "edges": []}
    body = client.post("/api/chat", json={"prompt": "buffer it", "graph": graph}).json()
    assert {"response", "thread_id", "graph", "validation", "unmet_capabilities"} <= body.keys()
    assert [n["id"] for n in body["graph"]["nodes"]] == ["a", "b"]
    # The server allowlist is part of every validation, so a host learns about it before running.
    assert body["validation"]["errors"] == [
        "Node 'b': server 'http://evil.example/' is not one of the allowed OGC servers."
    ]


@pytest.mark.parametrize("body", [
    {"prompt": ""},
    {"prompt": "x" * (app_module.MAX_PROMPT_CHARS + 1)},
    {"prompt": "hi", "thread_id": "short"},
    {"prompt": "hi", "thread_id": "../../etc"},
    {"prompt": "hi", "unknown": 1},
    {"prompt": "hi", "graph": {"nodes": [node(f"n{i}") for i in range(app_module.MAX_GRAPH_NODES + 1)], "edges": []}},
    {"prompt": "hi", "graph": {"nodes": [{**node("a"), "extra": 1}], "edges": []}},
])
def test_chat_input_limits(client, body):
    assert client.post("/api/chat", json=body).status_code == 422


def test_stream_input_limits(client):
    assert client.get("/api/stream", params={"prompt": "hi", "thread_id": "x"}).status_code == 422
    too_long = "x" * (app_module.MAX_PROMPT_CHARS + 1)
    assert client.get("/api/stream", params={"prompt": too_long, "thread_id": THREAD}).status_code == 422


def test_busy_service_answers_429(client, monkeypatch):
    monkeypatch.setattr(app_module, "_turns", asyncio.Semaphore(0))
    assert client.post("/api/chat", json={"prompt": "hi"}).status_code == 429
    assert client.get("/api/stream", params={"prompt": "hi", "thread_id": THREAD}).status_code == 429


def test_chat_timeout_answers_504(client, monkeypatch):
    monkeypatch.setattr(app_module, "compiled_graph", StubGraph(delay=1))
    monkeypatch.setattr(app_module, "TURN_TIMEOUT_SECONDS", 0.05)
    response = client.post("/api/chat", json={"prompt": "hi"})
    assert response.status_code == 504
    assert response.json()["detail"] == "The turn took longer than 0.05 s and was stopped."


def test_stream_timeout_ends_with_error_and_done(client, monkeypatch):
    monkeypatch.setattr(app_module, "compiled_graph", StubGraph(delay=1))
    monkeypatch.setattr(app_module, "TURN_TIMEOUT_SECONDS", 0.05)
    sent = events(client.get("/api/stream", params={"prompt": "hi", "thread_id": THREAD}))
    assert sent == [{"event": "error", "error": "The turn took longer than 0.05 s and was stopped."}, {"event": "done"}]


def test_stream_error_hides_exception_text(client, monkeypatch):
    monkeypatch.setattr(app_module, "compiled_graph", StubGraph(fail=RuntimeError("dsn=postgres://secret")))
    error, done = events(client.get("/api/stream", params={"prompt": "hi", "thread_id": THREAD}))
    assert "secret" not in error["error"] and error["error"].startswith("The turn failed (error id ")
    assert done == {"event": "done"}


def test_stream_forwards_graph_events(client):
    sent = events(client.get("/api/stream", params={"prompt": "hi", "thread_id": THREAD}))
    assert sent[0]["event"] == "graph" and sent[-1] == {"event": "done"}


def test_graph_op_hides_python_errors(client, monkeypatch):
    monkeypatch.setattr(app_module, "compiled_graph", type("G", (), {
        "get_state": lambda self, config: type("S", (), {"values": {"workflow_graph": {"nodes": [node("a")], "edges": []}}})(),
    })())
    response = client.post("/api/graph/op", json={
        "thread_id": THREAD, "op": "set_input", "args": {"node_id": "a", "port": "distance", "value": 5},
    })
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid arguments for op 'set_input'"}


def test_result_limit_is_capped(client, monkeypatch):
    monkeypatch.setattr(app_module, "MAX_MAP_FEATURES", 2)
    point = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [7.6, 51.9]}, "properties": {}}
    store.start_run(THREAD)
    store.save_node_result(THREAD, "a", {"result": {"type": "FeatureCollection", "features": [point] * 5}})
    body = client.get("/api/result", params={"thread_id": THREAD, "node": "a", "output": "result", "limit": 1000}).json()
    assert (len(body["features"]), body["truncated"], body["total"]) == (2, True, 5)


def run_app(env: dict) -> subprocess.CompletedProcess:
    """Import the app in a fresh interpreter: PRODUCTION is decided at import."""
    code = "from src.app import app; print(sorted(r.path for r in app.routes))"
    env = {**os.environ, "ANTHROPIC_API_KEY": "test", **env}
    return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False,
                          cwd=os.path.dirname(os.path.dirname(__file__)))


def test_production_refuses_to_start_without_token():
    result = run_app({"APP_ENV": "production", "LANGGRAPH_API_TOKEN": ""})
    assert result.returncode != 0 and "APP_ENV=production needs LANGGRAPH_API_TOKEN" in result.stderr


def test_production_serves_no_frontend_and_no_docs():
    result = run_app({"APP_ENV": "production", "LANGGRAPH_API_TOKEN": "secret"})
    assert result.returncode == 0, result.stderr
    routes = result.stdout
    for absent in ("'/'", "/static", "/api/test-prompts", "/docs", "/openapi.json"):
        assert absent not in routes
    assert "/api/chat" in routes and "/health" in routes


def test_openapi_file_is_current():
    """The published spec matches the app; after a deliberate change, `uv run python -m src.openapi`."""
    current = spec()
    if os.environ.get("UPDATE_SNAPSHOTS"):
        OPENAPI_FILE.write_text(current, encoding="utf-8")
    assert OPENAPI_FILE.read_text(encoding="utf-8") == current, f"{OPENAPI_FILE.name} is out of date"
