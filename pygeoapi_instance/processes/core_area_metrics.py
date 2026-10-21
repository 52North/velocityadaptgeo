"""Enrichment leaf of the parallel cool-spots chain: how much interior a polygon has.

Depends only on the filtered refuge polygons, not on anything the distance branch
produces, so it runs alongside the buffering rather than after it.
"""

import math

from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError
from shapely.errors import ShapelyError

from processes._geo import (
    feature_collection,
    load_features,
    to_utm,
    to_wgs84,
    utm_epsg_for,
)

DEFAULT_EDGE_WIDTH = 20.0


class CoreAreaMetricsProcessor(BaseProcessor):
    """OGC API - Processes: interior core area and compactness per polygon."""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "core-area-metrics",
            "title": "Interior Core Area and Shape Compactness of Polygons",
            "description": (
                "Measures how much genuine interior each polygon has, as opposed to edge. "
                "Erodes every feature inward by an edge width, measured in metres in a "
                "local UTM projection, to obtain its core, and reports the core area, the "
                "core's share of the total and the Polsby-Popper compactness of the "
                "outline. Returns the eroded cores and the input features annotated with "
                "their metrics. Tells a broad, sheltered patch from a thin strip of the "
                "same area - for example a compact, cool grove from a narrow treeline."
            ),
            "keywords": [
                "core-area",
                "interior",
                "negative-buffer",
                "erosion",
                "edge-effect",
                "compactness",
                "polsby-popper",
                "shape-metrics",
                "fragmentation",
                "landscape-ecology",
                "shade",
            ],
            "inputs": {
                "features": {
                    "title": "Polygon features to measure (GeoJSON FeatureCollection, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "edgeWidth": {
                    "title": "Width of the edge zone to erode inward, in metres; defaults to 20",
                    "schema": {"type": "number"},
                    "required": False,
                },
            },
            "outputs": {
                "cores": {
                    "title": "Eroded interior cores of the features that have one (GeoJSON FeatureCollection, EPSG:4326)",
                    "schema": {"type": "object"},
                },
                "features": {
                    "title": "Input features annotated with coreAreaSqm, coreShare and compactness",
                    "schema": {"type": "object"},
                },
                "coreAreaSqm": {
                    "title": "Total interior core area across all features, in square metres",
                    "schema": {"type": "number"},
                },
                "withCore": {
                    "title": "Number of features left with a non-empty core",
                    "schema": {"type": "integer"},
                },
            },
            "example": {
                "inputs": {
                    "features": {"type": "FeatureCollection", "features": []},
                    "edgeWidth": 20,
                }
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        try:
            pairs = load_features(data["features"])
            edge_width = float(data.get("edgeWidth") or DEFAULT_EDGE_WIDTH)
        except (KeyError, ValueError, TypeError, ShapelyError) as err:
            raise ProcessorExecuteError(f"core-area-metrics needs valid 'features': {err}")

        if edge_width <= 0:
            raise ProcessorExecuteError("'edgeWidth' must be a positive distance in metres")
        if not pairs:
            return "application/json", {
                "cores": feature_collection([]), "features": feature_collection([]),
                "coreAreaSqm": 0.0, "withCore": 0,
            }

        utm_epsg = utm_epsg_for(pairs[0][0])

        cores, annotated, total = [], [], 0.0
        for geom, props in pairs:
            try:
                projected, _ = to_utm(geom, utm_epsg)
                core = projected.buffer(-edge_width)
            except (ShapelyError, ValueError):
                continue

            area, perimeter = projected.area, projected.length
            metrics = {
                "areaSqm": round(area, 1),
                "coreAreaSqm": round(core.area, 1),
                "coreShare": round(core.area / area, 4) if area else 0.0,
                "compactness": round(4 * math.pi * area / perimeter ** 2, 4) if perimeter else 0.0,
            }
            annotated.append((geom, {**props, **metrics}))
            if not core.is_empty:
                total += core.area
                cores.append((to_wgs84(core, utm_epsg), {**props, **metrics}))

        return "application/json", {
            "cores": feature_collection(cores),
            "features": feature_collection(annotated),
            "coreAreaSqm": round(total, 1),
            "withCore": len(cores),
        }
