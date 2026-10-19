"""Grading measures on hand-made geometries: a 3 x 3 km city with two parks, no network."""

import json

import geopandas as gpd
import pytest
from shapely.geometry import box, mapping

import grade
from cool_spots import reference

CRS = "EPSG:32632"  # Münster's UTM zone, as in the real reference
CITY = gpd.GeoDataFrame(geometry=[box(400_000, 5_750_000, 403_000, 5_753_000)], crs=CRS)
# A 200 x 200 m park (40000 m²) and a 50 x 50 m one (2500 m²). Off the 25 m grid, as real parks are:
# on it, grid points sit exactly on ring edges and flip rings with the micrometres a reprojection moves.
SPOTS = gpd.GeoDataFrame(
    geometry=[
        box(400_513.3, 5_750_507.9, 400_713.3, 5_750_707.9),
        box(402_011.7, 5_752_004.1, 402_061.7, 5_752_054.1),
    ],
    crs=CRS,
)


def layers(min_area=1000, intervals=(0, 75, 150, 225, 300), answer="coverage"):
    """A graph's layers as the grader reads them, built like the reference."""
    built = grade.from_layers(reference(CITY, SPOTS, min_area, list(intervals)))
    if answer == "coverage":  # no geometry-difference node
        built["difference"] = None
    return built


@pytest.fixture(scope="module")
def ref():
    return grade.from_layers(reference(CITY, SPOTS, 1000, [0, 75, 150, 225, 300]))


@pytest.fixture(scope="module")
def grid(ref):
    g = grade.Grid(ref["city"], 25)
    return g, g.bands(ref)


def score(graph, ref, grid, target="within"):
    g, ref_bands = grid
    m = grade.measures(graph, ref, target, g, ref_bands)
    return m, grade.correct(m, target, ref["outer_m"])


def test_same_parameters_pass(ref, grid):
    m, ok = score(layers(), ref, grid)
    assert m["target_iou"] == 1.0 and m["band_agreement"] == 1.0 and ok


def test_other_ring_steps_pass_unchanged(ref, grid):
    m, ok = score(layers(intervals=(0, 50, 100, 150, 200, 250, 300)), ref, grid)
    assert m["target_iou"] == 1.0 and m["band_agreement"] == 1.0 and ok


def test_wider_limit_fails(ref, grid):
    m, ok = score(layers(intervals=(0, 150, 300, 450, 600)), ref, grid)
    assert m["outer_m"] == 600 and not ok


def test_no_rings_fails(ref, grid):
    graph = layers()
    graph["rings"] = None
    m, ok = score(graph, ref, grid)
    assert m["band_agreement"] is None and not ok


def test_dropping_a_park_lowers_the_score(ref, grid):
    m, _ = score(layers(min_area=5000), ref, grid)  # the 2500 m² park goes
    assert m["target_iou"] < 1.0 and m["band_agreement"] < 1.0


def test_inverse_answer_fails_within(ref, grid):
    m, ok = score(layers(answer="difference"), ref, grid)
    assert m["target_iou"] == 0.0 and m["coverage_iou"] == 1.0 and not ok


def test_beyond_target(ref, grid):
    m, ok = score(layers(answer="difference"), ref, grid, target="beyond")
    assert m["target_iou"] == 1.0 and ok
    m, ok = score(
        layers(), ref, grid, target="beyond"
    )  # no geometry-difference: no answer
    assert m["target_iou"] is None and not ok


def test_graph_layers_from_node_outputs(tmp_path, ref, grid):
    """The cached node outputs (GeoJSON in WGS84) read back into the same layers."""
    built = reference(CITY, SPOTS, 1000, [0, 75, 150, 225, 300])
    wgs = {name: gdf.to_crs("EPSG:4326") for name, gdf in built.items()}
    rings = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": {"innerDistance": inner, "outerDistance": outer},
            }
            for inner, outer, geom in zip(
                wgs["rings"]["inner_m"], wgs["rings"]["outer_m"], wgs["rings"].geometry
            )
        ],
    }
    outputs = {
        "c": {"boundary": mapping(wgs["city"].union_all())},
        "r": {
            "rings": rings,
            "coverage": mapping(wgs["within"].union_all()),
            "maxDistance": 300,
        },
    }
    for key, out in outputs.items():
        (tmp_path / f"{key}.json").write_text(json.dumps(out))
    execution = {
        "graph": {"nodes": [{"id": "n1", "config": {}}, {"id": "n2", "config": {}}]},
        "nodes": {
            "n1": {"type": "city-boundary", "output": "c"},
            "n2": {"type": "multi-ring-buffer", "output": "r"},
        },
    }
    graph = grade.graph_layers(execution, tmp_path, CRS)
    m, ok = score(graph, ref, grid)
    assert (
        m["target_iou"] > 0.999
        and m["band_agreement"] > 0.99
        and m["city_iou"] > 0.999
        and ok
    )
