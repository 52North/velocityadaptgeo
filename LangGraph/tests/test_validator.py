"""The validator, with and without the I/O type check (VALIDATE_IO_TYPES)."""

import pytest

from src.llm.nodes import validator
from src.llm.nodes.validator import io_compatible, io_kinds, validate_graph

SERVER = "http://pygeoapi:80/"
GEOJSON = {"schema": {"type": "object", "contentMediaType": "application/geo+json"}}
RASTER = {"schema": {"type": "string", "contentMediaType": "image/tiff"}}
NUMBER = {"schema": {"type": "number"}}
OBJECT = {"schema": {"type": "object"}}
SPECS = {
    ("areas", SERVER): {"inputs": {}, "outputs": {"result": GEOJSON, "count": NUMBER}},
    ("buffer", SERVER): {"inputs": {"geometry": OBJECT, "distance": NUMBER}, "outputs": {"result": OBJECT}},
    ("slope", SERVER): {"inputs": {"dem": RASTER}, "outputs": {"result": RASTER}},
}


def node(node_id, process, inputs=(), outputs=()):
    return {"id": node_id, "type": process, "config": {"server_url": SERVER},
            "inputs": list(inputs), "outputs": list(outputs)}


def edge(source, output, target, input_):
    return {"source": source, "source_output": output, "target": target, "target_input": input_}


def graph(*edges):
    return {
        "nodes": [node("a", "areas", outputs=["result", "count"]),
                  node("b", "buffer", ["geometry", "distance"], ["result"]),
                  node("s", "slope", ["dem"], ["result"])],
        "edges": list(edges),
    }


@pytest.mark.parametrize("spec, kinds", [
    (GEOJSON, {"geojson"}), (RASTER, {"raster"}), (NUMBER, {"number"}),
    ({"schema": {"type": "integer"}}, {"number"}), ({"schema": {"format": "ogc-bbox"}}, {"bbox"}),
    ({"schema": {"oneOf": [GEOJSON["schema"], {}]}}, set()), (None, set()),
])
def test_io_kinds(spec, kinds):
    assert io_kinds(spec) == kinds


def test_io_compatible_is_lenient_only_where_it_should_be():
    assert io_compatible(GEOJSON, OBJECT)
    assert io_compatible(None, RASTER)
    assert not io_compatible(GEOJSON, RASTER)
    assert not io_compatible(NUMBER, OBJECT)


def test_type_mismatch_is_reported_with_the_check_on():
    report = validate_graph(graph(edge("a", "count", "b", "geometry")), io_specs=SPECS, check_types=True)
    assert not report["valid"]
    assert "type mismatch" in report["errors"][0]


def test_matching_types_pass_with_the_check_on():
    report = validate_graph(graph(edge("a", "result", "b", "geometry")), io_specs=SPECS, check_types=True)
    assert report == {"valid": True, "errors": []}


def test_check_off_is_names_only_and_never_asks_the_catalog(monkeypatch):
    def no_lookup(_):
        raise AssertionError("the catalog must not be queried with the type check off")

    monkeypatch.setattr(validator, "fetch_io_specs", no_lookup)
    assert validate_graph(graph(edge("a", "count", "b", "geometry")), check_types=False)["valid"]
    report = validate_graph(graph(edge("a", "nope", "b", "geometry")), check_types=False)
    assert report["errors"] == ["Edge 0: 'a' has no output 'nope' (declared outputs: ['count', 'result'])."]


def test_check_off_does_not_fill_in_undeclared_names():
    bare = {"nodes": [node("a", "areas"), node("b", "buffer")], "edges": [edge("a", "x", "b", "y")]}
    assert validate_graph(bare, io_specs=SPECS, check_types=False)["valid"]
    assert not validate_graph(bare, io_specs=SPECS, check_types=True)["valid"]


def test_default_follows_the_switch(monkeypatch):
    monkeypatch.setattr(validator, "fetch_io_specs", lambda _: SPECS)
    mismatch = graph(edge("a", "count", "b", "geometry"))
    monkeypatch.setattr(validator, "VALIDATE_IO_TYPES", False)
    assert validate_graph(mismatch)["valid"]
    monkeypatch.setattr(validator, "VALIDATE_IO_TYPES", True)
    assert not validate_graph(mismatch)["valid"]


@pytest.mark.parametrize("server_url, error", [
    ("http://pygeoapi:80", None),  # the trailing slash does not matter
    ("http://evil.example/", "Node 'a': server 'http://evil.example/' is not one of the allowed OGC servers."),
    ("", "Node 'a' has no server_url."),
])
def test_server_allowlist_is_always_checked(server_url, error):
    one = {"nodes": [{**node("a", "areas"), "config": {"server_url": server_url}}], "edges": []}
    for check_types in (False, True):
        report = validate_graph(one, io_specs={}, check_types=check_types)
        assert report["errors"] == ([error] if error else [])
