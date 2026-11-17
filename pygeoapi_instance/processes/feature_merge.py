"""Join point of the enriched cool-spots chain: two feature collections into one.

The fan-in counterpart to the parallel extraction branches - one node with two incoming
edges - so everything downstream sees a single collection of refuges regardless of how
many kinds were gathered in parallel.
"""

from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError
from shapely.errors import ShapelyError
from shapely.ops import unary_union

from processes._geo import explode_polygons, feature_collection, load_features


class FeatureMergeProcessor(BaseProcessor):
    """OGC API - Processes: concatenate two feature collections, optionally dissolving."""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "feature-merge",
            "title": "Merge and Combine Two Feature Collections",
            "description": (
                "Combines two GeoJSON feature collections produced by separate, "
                "independent branches of an analysis into a single collection, tagging "
                "each feature with the branch it came from. Optionally dissolves "
                "overlapping polygons into their union, so shapes counted twice - a pond "
                "lying inside a park, say - are not double-counted downstream. This is "
                "the join, merge or combine step that lets several parallel extractions "
                "feed one common set of features."
            ),
            "keywords": [
                "merge",
                "combine",
                "join",
                "union",
                "append",
                "concatenate",
                "dissolve",
                "overlay",
                "feature-collection",
            ],
            "inputs": {
                "features": {
                    "title": "First feature collection (GeoJSON, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "otherFeatures": {
                    "title": "Second feature collection to merge in (GeoJSON, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "dissolve": {
                    "title": "Dissolve overlapping polygons into their union; defaults to false",
                    "schema": {"type": "boolean"},
                    "required": False,
                },
            },
            "outputs": {
                "features": {
                    "title": "The merged collection, each feature carrying a mergeSource property",
                    "schema": {"type": "object"},
                },
                "count": {
                    "title": "Number of features in the merged collection",
                    "schema": {"type": "integer"},
                },
            },
            "example": {
                "inputs": {
                    "features": {"type": "FeatureCollection", "features": []},
                    "otherFeatures": {"type": "FeatureCollection", "features": []},
                    "dissolve": False,
                }
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        try:
            pairs = [
                (geom, {**props, "mergeSource": name})
                for name in ("features", "otherFeatures")
                for geom, props in load_features(data[name])
            ]
        except (KeyError, ValueError, TypeError, ShapelyError) as err:
            raise ProcessorExecuteError(
                f"feature-merge needs 'features' and 'otherFeatures': {err}"
            )

        if data.get("dissolve"):
            try:
                merged = unary_union([geom for geom, _ in pairs])
            except (ShapelyError, ValueError) as err:
                raise ProcessorExecuteError(f"feature-merge could not dissolve: {err}")
            pairs = [(part, {"mergeSource": "dissolved"}) for part in explode_polygons(merged)]

        return "application/json", {
            "features": feature_collection(pairs),
            "count": len(pairs),
        }
