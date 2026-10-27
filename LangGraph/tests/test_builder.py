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
