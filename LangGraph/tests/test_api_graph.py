"""The API graph layout (values in `config.values`) and its conversion to and from the internal one."""

import pytest
from pydantic import ValidationError

from src.api_graph import ApiGraph, from_api, to_api
from src.llm.state.graph import new_graph_node

SERVER = "http://pygeoapi:80/"


def internal_graph():
    node = new_graph_node("buffer_1", "buffer", SERVER, inputs={"distance": 500, "values": "x"})
    edge = {"source": "a", "target": "buffer_1", "source_output": "result", "target_input": "geometry"}
    return {"nodes": [node], "edges": [edge]}


def test_to_api_nests_every_value_and_keeps_the_settings():
    config = to_api(internal_graph())["nodes"][0]["config"]
    # An input that happens to be called "values" is just another value.
    assert config == {"server_url": SERVER, "timeout_seconds": 300, "values": {"distance": 500, "values": "x"}}


def test_round_trip_is_lossless():
    graph = internal_graph()
    api = ApiGraph.model_validate(to_api(graph)).model_dump()
    assert from_api(api) == graph


def test_unset_settings_are_left_out_internally():
    api = ApiGraph.model_validate({"nodes": [{"id": "a", "type": "buffer", "config": {"values": {"distance": 5}}}]})
    assert from_api(api.model_dump())["nodes"][0]["config"] == {"distance": 5}


def test_empty_graph():
    assert to_api(None) == {"nodes": [], "edges": []}


@pytest.mark.parametrize("config, message", [
    ({"server_url": SERVER, "distance": 500}, "Extra inputs are not permitted"),
    ({"server_url": SERVER, "values": {"server_url": "http://evil.example/"}}, "'values' cannot contain server_url"),
    ({"values": {"timeout_seconds": 1}}, "'values' cannot contain timeout_seconds"),
    ({"timeout_seconds": 601}, "less than or equal to 600"),
    ({"timeout_seconds": 0}, "greater than 0"),
])
def test_flat_values_and_setting_names_are_refused(config, message):
    with pytest.raises(ValidationError, match=message):
        ApiGraph.model_validate({"nodes": [{"id": "a", "type": "buffer", "config": config}]})
