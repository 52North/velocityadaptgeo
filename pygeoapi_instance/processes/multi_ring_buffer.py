"""Step 4 of the cool-spots chain: concentric distance bands around the features."""

from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError
from shapely.errors import ShapelyError
from shapely.geometry import mapping
from shapely.ops import unary_union

from processes._geo import (
    feature_collection,
    load_features,
    to_utm,
    to_wgs84,
    utm_epsg_for,
)

DEFAULT_DISTANCES = [75, 150, 225, 300]


class MultiRingBufferProcessor(BaseProcessor):
    """OGC API - Processes: nested proximity bands measured in metres."""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "multi-ring-buffer",
            "title": "Multi-Ring Proximity Bands Around Features",
            "description": (
                "Builds concentric distance bands (a multi-ring or graduated buffer) "
                "around a set of features by dissolving a buffer at each threshold "
                "distance and subtracting the next smaller one, so the output rings "
                "tile the surroundings without overlapping. Distances are measured in "
                "metres in a local UTM projection. Also returns the dissolved outer "
                "coverage, the area within reach of any feature. Shows how far away "
                "each location is from the nearest feature in graduated zones - for "
                "example how close residents are to the nearest park or cool refuge."
            ),
            "keywords": [
                "buffer",
                "multi-ring-buffer",
                "graduated-buffer",
                "proximity",
                "distance-bands",
                "catchment",
                "accessibility",
                "walking-distance",
                "service-area",
            ],
            "inputs": {
                "features": {
                    "title": "Features to buffer around (GeoJSON, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "distances": {
                    "title": "Ascending ring boundaries in metres; defaults to [75, 150, 225, 300]",
                    "schema": {"type": "array", "items": {"type": "number"}},
                    "required": False,
                },
            },
            "outputs": {
                "rings": {
                    "title": "Non-overlapping distance bands, each with innerDistance/outerDistance/label",
                    "schema": {"type": "object"},
                },
                "coverage": {
                    "title": "Dissolved area within the largest distance of any feature",
                    "schema": {"type": "object"},
                },
                "maxDistance": {
                    "title": "Largest ring distance applied, in metres",
                    "schema": {"type": "number"},
                },
            },
            "example": {
                "inputs": {
                    "features": {"type": "FeatureCollection", "features": []},
                    "distances": [75, 150, 225, 300],
                }
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        try:
            pairs = load_features(data["features"])
        except (KeyError, ValueError, ShapelyError) as err:
            raise ProcessorExecuteError(f"multi-ring-buffer needs valid 'features': {err}")

        if not pairs:
            raise ProcessorExecuteError("multi-ring-buffer received no features to buffer")

        distances = data.get("distances") or DEFAULT_DISTANCES
        try:
            distances = sorted({float(d) for d in distances})
        except (TypeError, ValueError) as err:
            raise ProcessorExecuteError(f"'distances' must be a list of numbers: {err}")
        if not distances or distances[0] <= 0:
            raise ProcessorExecuteError("'distances' must be positive, ascending metre values")

        utm_epsg = utm_epsg_for(pairs[0][0])
        try:
            projected = unary_union([to_utm(geom, utm_epsg)[0] for geom, _ in pairs])
        except (ShapelyError, ValueError) as err:
            raise ProcessorExecuteError(f"multi-ring-buffer projection failed: {err}")

        try:
            dissolved = {0.0: projected}
            for distance in distances:
                dissolved[distance] = projected.buffer(distance)

            rings = []
            bounds = [0.0] + distances
            for inner, outer in zip(bounds, bounds[1:]):
                band = dissolved[outer].difference(dissolved[inner])
                if band.is_empty:
                    continue
                rings.append((
                    to_wgs84(band, utm_epsg),
                    {
                        "label": f"{inner:g}m-{outer:g}m",
                        "innerDistance": inner,
                        "outerDistance": outer,
                    },
                ))

            coverage = to_wgs84(dissolved[distances[-1]], utm_epsg)
        except (ShapelyError, ValueError) as err:
            raise ProcessorExecuteError(f"multi-ring-buffer failed: {err}")

        return "application/json", {
            "rings": feature_collection(rings),
            "coverage": mapping(coverage),
            "maxDistance": distances[-1],
        }
