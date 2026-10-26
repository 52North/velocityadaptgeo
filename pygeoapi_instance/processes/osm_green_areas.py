"""Step 2 of the cool-spots chain: pull tagged OSM polygons inside the study area."""

import math
import os
import time

import requests
from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError
from shapely.errors import ShapelyError
from shapely.geometry import LineString
from shapely.ops import polygonize, unary_union

from processes._geo import explode_polygons, feature_collection, load_area

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
OVERPASS_ATTEMPTS = int(os.environ.get("OVERPASS_ATTEMPTS", "3"))
OVERPASS_BACKOFF = float(os.environ.get("OVERPASS_BACKOFF", "2"))
# Total wall-clock budget for all retries: must stay under the workflow runner's
# per-node timeout (300s) so a dead upstream surfaces as this error rather than as an
# opaque client-side timeout.
OVERPASS_DEADLINE = float(os.environ.get("OVERPASS_DEADLINE", "240"))
# Limits on what one request may ask of the public instances: the bounding box queried (about
# 5x Münster's), the memory the instance may spend on the query (and so the size of the answer
# this process holds in memory), and the number of tag values.
OVERPASS_MAX_AREA_KM2 = float(os.environ.get("OVERPASS_MAX_AREA_KM2", "2500"))
OVERPASS_MAXSIZE = int(os.environ.get("OVERPASS_MAXSIZE", str(256 * 1024 * 1024)))
MAX_TAG_VALUES = 20

DEFAULT_TAGS = {"landuse": "forest", "natural": "wood", "leisure": "park"}


def ql_string(value) -> str:
    """Quote a tag key or value for Overpass QL, so it cannot end the string and add a query."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ProcessorExecuteError(f"tag keys and values must be strings, not {value!r}")
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    text = text.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{text}"'


class OsmGreenAreasProcessor(BaseProcessor):
    """OGC API - Processes: tagged OSM land-cover polygons within an area."""

    default_tags = DEFAULT_TAGS  # replaced by subclasses that extract other features

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
                    "title": "Matching land-cover polygons (GeoJSON FeatureCollection, EPSG:4326)",
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

    def _fetch(self, endpoint: str, query: str, timeout: float) -> list:
        """POST one query to one endpoint, raising RuntimeError with a short reason."""
        response = requests.post(
            endpoint,
            data={"data": query},
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}")

        payload = response.json()
        remark = (payload.get("remark") or "").strip()
        if remark:
            raise RuntimeError(remark)
        return payload.get("elements", [])

    def _query(self, bounds, tags) -> list:
        """Run a bbox Overpass query, retrying each configured endpoint in turn.

        A bounding-box filter is used rather than a `poly:` filter because the public
        Overpass instances routinely time out on many-vertex polygons; the results are
        clipped to the true study-area polygon afterwards. Those instances also drop
        requests under load (502/504) while a sibling mirror answers fine, so every
        endpoint is tried in several rounds with a growing pause between them.
        """
        min_lon, min_lat, max_lon, max_lat = bounds
        extent = f"({min_lat:.6f},{min_lon:.6f},{max_lat:.6f},{max_lon:.6f})"
        # Exact for a lat/lon box on the authalic sphere, at any size (a projection is not).
        km2 = 6371.0072**2 * math.radians(max_lon - min_lon) * abs(
            math.sin(math.radians(max_lat)) - math.sin(math.radians(min_lat))
        )
        if not km2 <= OVERPASS_MAX_AREA_KM2:
            raise ProcessorExecuteError(
                f"the study area's bounding box covers {km2:,.0f} km²; one query may cover at "
                f"most {OVERPASS_MAX_AREA_KM2:,.0f} km² (OVERPASS_MAX_AREA_KM2)"
            )

        filters = [
            f"[{ql_string(key)}={ql_string(item)}]"
            for key, value in tags.items()
            for item in (value if isinstance(value, (list, tuple)) else [value])
        ]
        if len(filters) > MAX_TAG_VALUES:
            raise ProcessorExecuteError(f"at most {MAX_TAG_VALUES} tag values per query, got {len(filters)}")
        clauses = [f"{kind}{f}{extent};" for f in filters for kind in ("way", "relation")]

        query = f"[out:json][timeout:90][maxsize:{OVERPASS_MAXSIZE}];({''.join(clauses)});out geom;"

        attempts = max(OVERPASS_ATTEMPTS, 1)
        deadline = time.monotonic() + OVERPASS_DEADLINE
        errors = {}
        for attempt in range(attempts):
            for endpoint in OVERPASS_ENDPOINTS:
                budget = min(OVERPASS_TIMEOUT, deadline - time.monotonic())
                if budget <= 0:
                    break
                try:
                    return self._fetch(endpoint, query, budget)
                except (requests.RequestException, RuntimeError, ValueError) as err:
                    errors[endpoint] = f"{endpoint} -> {err or type(err).__name__}"
            pause = min(OVERPASS_BACKOFF * 2 ** attempt, deadline - time.monotonic())
            if attempt + 1 == attempts or pause <= 0:
                break
            time.sleep(pause)

        raise ProcessorExecuteError(
            "every Overpass mirror failed; the public instances are overloaded, retry "
            f"in a few minutes: {'; '.join(errors.values())}"
        )

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
            area = load_area(data["area"])
        except (KeyError, ValueError, ShapelyError) as err:
            raise ProcessorExecuteError(f"{self.metadata['id']} needs a valid 'area': {err}")

        tags = data.get("tags") or self.default_tags
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
