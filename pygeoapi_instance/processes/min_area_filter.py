"""Step 3 of the cool-spots chain: drop polygons too small to be usable."""

from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError
from shapely.errors import ShapelyError

from processes._geo import feature_collection, load_features, to_utm, utm_epsg_for


class MinAreaFilterProcessor(BaseProcessor):
    """OGC API - Processes: keep only polygons above a ground-area threshold."""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "min-area-filter",
            "title": "Minimum Ground-Area Filter for Polygon Features",
            "description": (
                "Filters a polygon feature collection down to the features whose true "
                "ground area, measured in a local UTM projection rather than in degrees, "
                "reaches a minimum threshold in square metres, and annotates every "
                "surviving feature with its computed area. Removes slivers and patches "
                "too small to serve their purpose - a pocket of greenery a few metres "
                "across is no usable refuge - before distance or accessibility analysis."
            ),
            "keywords": [
                "filter",
                "area-threshold",
                "polygon",
                "sliver-removal",
                "minimum-size",
                "vector-generalisation",
            ],
            "inputs": {
                "features": {
                    "title": "Polygon features to filter (GeoJSON FeatureCollection, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "minArea": {
                    "title": "Minimum ground area to keep, in square metres",
                    "schema": {"type": "number"},
                    "required": True,
                },
            },
            "outputs": {
                "features": {
                    "title": "Features meeting the area threshold, each with an areaSqm property",
                    "schema": {"type": "object"},
                },
                "count": {
                    "title": "Number of features kept",
                    "schema": {"type": "integer"},
                },
                "removed": {
                    "title": "Number of features discarded as too small",
                    "schema": {"type": "integer"},
                },
            },
            "example": {"inputs": {"features": {"type": "FeatureCollection", "features": []}, "minArea": 200}},
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        try:
            pairs = load_features(data["features"])
            min_area = float(data["minArea"])
        except (KeyError, ValueError, TypeError, ShapelyError) as err:
            raise ProcessorExecuteError(f"min-area-filter needs 'features' and 'minArea': {err}")

        if not pairs:
            return "application/json", {
                "features": feature_collection([]), "count": 0, "removed": 0,
            }

        utm_epsg = utm_epsg_for(pairs[0][0])

        kept, removed = [], 0
        for geom, props in pairs:
            try:
                projected, _ = to_utm(geom, utm_epsg)
            except (ShapelyError, ValueError):
                removed += 1
                continue
            if projected.area >= min_area:
                kept.append((geom, {**props, "areaSqm": round(projected.area, 1)}))
            else:
                removed += 1

        return "application/json", {
            "features": feature_collection(kept),
            "count": len(kept),
            "removed": removed,
        }
