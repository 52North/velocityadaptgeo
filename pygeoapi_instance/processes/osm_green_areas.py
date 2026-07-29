"""Step 2 of the cool-spots chain: pull tagged OSM polygons inside the study area."""

import os

import requests
from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError
from shapely.errors import ShapelyError
from shapely.geometry import LineString
from shapely.ops import polygonize, unary_union

from processes._geo import explode_polygons, feature_collection, load_geometry

OVERPASS_ENDPOINTS = [
    url.strip()
    for url in os.environ.get(
        "OVERPASS_ENDPOINTS",
        "https://overpass.kumi.systems/api/interpreter,"
        "https://overpass-api.de/api/interpreter,"
        "https://overpass.private.coffee/api/interpreter",
    ).split(",")
    if url.strip()
]
USER_AGENT = os.environ.get("OSM_USER_AGENT", "north52-coolspots/1.0")
OVERPASS_TIMEOUT = float(os.environ.get("OVERPASS_TIMEOUT", "180"))

DEFAULT_TAGS = {"landuse": "forest", "natural": "wood", "leisure": "park"}


class OsmGreenAreasProcessor(BaseProcessor):
    """OGC API - Processes: tagged OSM land-cover polygons within an area."""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "osm-green-areas",
            "title": "OpenStreetMap Green and Shaded Land-Cover Extraction",
            "description": (
                "Downloads OpenStreetMap polygon features carrying the given land-use, "
                "landcover or leisure tags from inside a study-area polygon, defaulting "
                "to woodland, forest and park tags that mark shaded, vegetated ground. "
                "Assembles closed ways and multipolygon relations into clean polygons, "
                "clips them to the study area and returns them as a feature "
                "collection. Supplies the candidate cool, shaded refuges that heat-relief "
                "and green-space accessibility analyses are built from."
            ),
            "keywords": [
                "openstreetmap",
                "overpass",
                "landuse",
                "landcover",
                "green-space",
                "parks",
                "woodland",
                "urban-heat",
                "cool-spots",
            ],
            "inputs": {
                "area": {
                    "title": "Study-area polygon to search within (GeoJSON, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "tags": {
                    "title": (
                        "OSM tag filter as {key: value} or {key: [values]}; defaults to "
                        "{'landuse': 'forest', 'natural': 'wood', 'leisure': 'park'}"
                    ),
                    "schema": {"type": "object"},
                    "required": False,
                },
            },
            "outputs": {
                "features": {
                    "title": "Matching land-cover polygons (GeoJSON FeatureCollection)",
                    "schema": {"type": "object"},
                },
                "count": {
                    "title": "Number of polygons returned",
                    "schema": {"type": "integer"},
                },
            },
            "example": {
                "inputs": {
                    "area": {"type": "Polygon", "coordinates": [[[7.6, 51.94], [7.65, 51.94], [7.65, 51.97], [7.6, 51.97], [7.6, 51.94]]]},
                    "tags": {"leisure": "park"},
                }
            },
        }

        super().__init__(processor_def, process_metadata)

    def _query(self, bounds, tags) -> list:
        """Run a bbox Overpass query, trying each configured endpoint in turn.

        A bounding-box filter is used rather than a `poly:` filter because the public
        Overpass instances routinely time out on many-vertex polygons; the results are
        clipped to the true study-area polygon afterwards.
        """
        min_lon, min_lat, max_lon, max_lat = bounds
        extent = f"({min_lat:.6f},{min_lon:.6f},{max_lat:.6f},{max_lon:.6f})"

        clauses = []
        for key, value in tags.items():
            values = value if isinstance(value, (list, tuple)) else [value]
            for item in values:
                clauses.append(f'way["{key}"="{item}"]{extent};')
                clauses.append(f'relation["{key}"="{item}"]{extent};')

        query = f"[out:json][timeout:90];({''.join(clauses)});out geom;"

        errors = []
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                response = requests.post(
                    endpoint,
                    data={"data": query},
                    headers={"User-Agent": USER_AGENT},
                    timeout=OVERPASS_TIMEOUT,
                )
                if response.status_code == 200 and "json" in response.headers.get("content-type", ""):
                    return response.json().get("elements", [])
                errors.append(f"{endpoint} -> HTTP {response.status_code}")
            except requests.RequestException as err:
                errors.append(f"{endpoint} -> {type(err).__name__}")

        raise ProcessorExecuteError("no Overpass endpoint answered: " + "; ".join(errors))

    def _polygons(self, elements):
        """Turn Overpass way/relation elements into polygons with their tags."""
        for element in elements:
            tags = element.get("tags") or {}
            try:
                if element["type"] == "way":
                    coords = [(p["lon"], p["lat"]) for p in element.get("geometry") or []]
                    if len(coords) < 4 or coords[0] != coords[-1]:
                        continue
                    built = unary_union(list(polygonize([LineString(coords)])))
                elif element["type"] == "relation":
                    outer, inner = [], []
                    for member in element.get("members") or []:
                        coords = [(p["lon"], p["lat"]) for p in member.get("geometry") or []]
                        if len(coords) < 2:
                            continue
                        (inner if member.get("role") == "inner" else outer).append(LineString(coords))
                    shell = unary_union(list(polygonize(outer)))
                    holes = unary_union(list(polygonize(inner)))
                    built = shell.difference(holes) if not holes.is_empty else shell
                else:
                    continue
            except (ShapelyError, KeyError, TypeError, ValueError):
                continue

            for polygon in explode_polygons(built):
                yield polygon, tags

    def execute(self, data, outputs=None):
        try:
            area = load_geometry(data["area"])
        except (KeyError, ValueError, ShapelyError) as err:
            raise ProcessorExecuteError(f"osm-green-areas needs a valid 'area': {err}")

        tags = data.get("tags") or DEFAULT_TAGS
        if not isinstance(tags, dict) or not tags:
            raise ProcessorExecuteError("'tags' must be a non-empty object")

        elements = self._query(area.bounds, tags)

        kept = []
        for polygon, osm_tags in self._polygons(elements):
            clipped = polygon.intersection(area)
            for part in explode_polygons(clipped):
                kept.append((part, {k: v for k, v in osm_tags.items() if k in tags}))

        return "application/json", {
            "features": feature_collection(kept),
            "count": len(kept),
        }
