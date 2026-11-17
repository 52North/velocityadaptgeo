"""The runner caps a node's timeout, whoever set it."""

import asyncio

import httpx
import pytest

from src.execution.runner import _post_execution
from src.llm.state.graph import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_NODE_TIMEOUT_SECONDS,
    node_timeout,
)


@pytest.mark.parametrize("value, seconds", [
    (None, DEFAULT_TIMEOUT_SECONDS), (120, 120), (10 ** 9, MAX_NODE_TIMEOUT_SECONDS),
    (0, DEFAULT_TIMEOUT_SECONDS), (-5, DEFAULT_TIMEOUT_SECONDS), ("600", DEFAULT_TIMEOUT_SECONDS),
    (float("nan"), DEFAULT_TIMEOUT_SECONDS), (float("inf"), MAX_NODE_TIMEOUT_SECONDS), (True, DEFAULT_TIMEOUT_SECONDS),
])
def test_node_timeout(value, seconds):
    assert node_timeout(value) == seconds


def test_execution_request_uses_the_capped_timeout():
    seen = {}

    def handler(request):
        seen["timeout"] = request.extensions["timeout"]["read"]
        return httpx.Response(200, json={"result": 1})

    node = {"id": "a", "type": "buffer", "config": {"server_url": "http://pygeoapi:80/", "timeout_seconds": 10 ** 9}}

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await _post_execution(client, node, {})

    assert asyncio.run(run()) == {"result": 1}
    assert seen["timeout"] == MAX_NODE_TIMEOUT_SECONDS
