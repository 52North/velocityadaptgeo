"""The build ops the manager and the frontend send."""

import pytest

from src.llm.nodes.builder import apply_build_op

GRAPH = {"nodes": [{"id": "b_1", "type": "buffer", "config": {"server_url": "http://pygeoapi:80/"},
                    "inputs": ["geometry", "distance"], "outputs": ["result"]}], "edges": []}


def test_set_input_takes_the_input_name():
    graph = apply_build_op(GRAPH, "set_input", {"node_id": "b_1", "input": "distance", "value": 500})
    assert graph["nodes"][0]["config"]["distance"] == 500

    cleared = apply_build_op(graph, "set_input", {"node_id": "b_1", "input": "distance", "value": None})
    assert "distance" not in cleared["nodes"][0]["config"]


def test_set_input_refuses_the_old_argument_name():
    with pytest.raises(TypeError):
        apply_build_op(GRAPH, "set_input", {"node_id": "b_1", "port": "distance", "value": 500})


def test_set_input_refuses_transport_settings():
    with pytest.raises(ValueError, match="transport setting"):
        apply_build_op(GRAPH, "set_input", {"node_id": "b_1", "input": "server_url", "value": "x"})


def test_add_node_takes_settings_only_from_their_own_sources():
    # Values from the LLM's plan that are named like a setting must not overwrite it: a
    # server_url would redirect the process call, a timeout_seconds lift the time limit.
    graph = apply_build_op({"nodes": [], "edges": []}, "add_node", {
        "process_id": "buffer", "server_url": "http://pygeoapi:80/",
        "inputs": {"distance": 500, "server_url": "http://evil.example/", "timeout_seconds": 99999},
        "config": {"server_url": "http://evil.example/", "timeout_seconds": 120, "cap_style": "round"},
    })
    assert graph["nodes"][0]["config"] == {
        "server_url": "http://pygeoapi:80/", "timeout_seconds": 120, "distance": 500, "cap_style": "round",
    }


def test_add_node_caps_the_timeout():
    graph = apply_build_op({"nodes": [], "edges": []}, "add_node", {
        "process_id": "buffer", "server_url": "http://pygeoapi:80/", "config": {"timeout_seconds": 10 ** 9},
    })
    assert graph["nodes"][0]["config"]["timeout_seconds"] == 600
