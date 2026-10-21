from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


class LeastCostPathProcessor(BaseProcessor):
    """OGC API - Processes stub: anisotropic least-cost path routing"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "least-cost-path-routing",
            "title": "Least-Cost Path Routing over a Friction Surface",
            "description": (
                "Finds the cheapest route between an origin and a destination across open "
                "terrain (least-cost path or cost-distance routing), accumulating a "
                "travel cost built from slope, land-cover resistance and "
                "direction-dependent uphill penalties over an 8-connected grid, with "
                "optional impassable barriers. Costs accumulate on the friction raster's "
                "own grid. Returns the path with its cumulative cost per vertex, and the "
                "total cost. Plans cross-country routes - for example a hiking trail or a "
                "pipeline corridor."
            ),
            "keywords": [
                "routing",
                "least-cost-path",
                "cost-distance",
                "friction-surface",
                "anisotropic",
                "graph-traversal",
                "terrain-analysis",
                "corridor-planning",
            ],
            "inputs": {
                "origin": {
                    "title": "Origin point (GeoJSON Point, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "destination": {
                    "title": "Destination point (GeoJSON Point, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "frictionSurface": {
                    "title": "Friction raster (COG or Zarr URI) or inline cost grid",
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
                    "title": "Impassable areas to route around (GeoJSON Polygon or MultiPolygon, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": False,
                },
            },
            "outputs": {
                "path": {
                    "title": "Least-cost path with per-vertex cumulative cost (GeoJSON LineString, EPSG:4326)",
                    "schema": {"type": "object"},
                },
                "cumulativeCost": {
                    "title": "Total accumulated cost of the resolved path",
                    "schema": {"type": "number"},
                },
            },
            "example": {
                "inputs": {
                    "origin": {"type": "Point", "coordinates": [7.60, 51.95]},
                    "destination": {"type": "Point", "coordinates": [7.68, 51.99]},
                    "frictionSurface": {"href": "https://example.org/friction.tif"},
                }
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        raise ProcessorExecuteError(
            "least-cost-path-routing is a metadata-only stub and has no execution backend yet"
        )
