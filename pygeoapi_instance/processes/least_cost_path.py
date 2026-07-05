from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


class LeastCostPathProcessor(BaseProcessor):
    """OGC API - Processes stub: anisotropic least-cost path routing"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "least-cost-path-routing",
            "title": "Anisotropic Least-Cost Path Routing over a Multi-Factor Friction Surface",
            "description": (
                "Computes the minimum cumulative-cost path between an origin and "
                "destination through a rasterised friction surface synthesised from "
                "slope, land-cover resistance, and directional (anisotropic) "
                "traversal penalties, using an 8-connected Dijkstra/A* accumulation "
                "graph with optional barrier masking."
            ),
            "keywords": [
                "routing",
                "least-cost-path",
                "anisotropic",
                "friction-surface",
                "graph-traversal",
                "terrain-analysis",
            ],
            "inputs": {
                "origin": {
                    "title": "Origin point (GeoJSON Point, source CRS)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "destination": {
                    "title": "Destination point (GeoJSON Point, source CRS)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "frictionSurface": {
                    "title": "Reference to friction raster (COG/Zarr URI) or inline cost grid",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "anisotropyFactor": {
                    "title": (
                        "Directional penalty multiplier applied against the "
                        "up-slope traversal vector (0 = isotropic, 1 = fully directional)"
                    ),
                    "schema": {"type": "number"},
                    "required": False,
                },
                "barrierMask": {
                    "title": "Optional vector mask of impassable cells (GeoJSON Polygon/MultiPolygon)",
                    "schema": {"type": "object"},
                    "required": False,
                },
            },
            "outputs": {
                "path": {
                    "title": "Least-cost path (GeoJSON LineString) with per-vertex cumulative cost",
                    "schema": {"type": "object"},
                },
                "cumulativeCost": {
                    "title": "Total accumulated cost of the resolved path",
                    "schema": {"type": "number"},
                },
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        raise ProcessorExecuteError(
            "least-cost-path-routing is a metadata-only stub and has no execution backend yet"
        )
