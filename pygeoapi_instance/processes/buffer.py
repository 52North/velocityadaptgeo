"""Buffer a geometry or feature collection by a distance in metres."""

from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError
from shapely.errors import ShapelyError
from shapely.geometry import mapping

from processes._geo import load_geometry, to_utm, to_wgs84


class BufferProcessor(BaseProcessor):
    """OGC API - Processes: a single buffer measured in metres."""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "buffer",
            "title": "Fixed-Distance Buffer Around Geometries",
            "description": (
                "Expands a geometry, or every feature of a collection, outward by a fixed "
                "distance and dissolves the result into one polygon covering everything "
                "within that distance. A negative distance shrinks polygons inward instead. "
                "Distances are measured in metres in a local UTM projection. Marks the zone "
                "of influence or reach around features - for example the area within 300 m "
                "of a park, or a protective setback around a road or river."
            ),
            "keywords": [
                "buffer",
                "proximity",
                "distance",
                "zone-of-influence",
                "catchment",
                "service-area",
                "setback",
            ],
            "inputs": {
                "geometry": {
                    "title": "Geometry, Feature or FeatureCollection to buffer (GeoJSON, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "distance": {
                    "title": "Buffer distance in metres; negative values shrink polygons",
                    "schema": {"type": "number"},
                    "required": True,
                },
            },
            "outputs": {
                "result": {
                    "title": "Dissolved buffer polygon (GeoJSON geometry, EPSG:4326)",
                    "schema": {"type": "object"},
                },
            },
            "example": {
                "inputs": {
                    "geometry": {"type": "Point", "coordinates": [7.6261, 51.9607]},
                    "distance": 300,
                }
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        try:
            geom = load_geometry(data["geometry"])
        except (KeyError, ValueError, ShapelyError) as err:
            raise ProcessorExecuteError(f"buffer needs a valid 'geometry': {err}")

        try:
            distance = float(data["distance"])
        except (KeyError, TypeError, ValueError) as err:
            raise ProcessorExecuteError(f"'distance' must be a number of metres: {err}")

        try:
            projected, utm_epsg = to_utm(geom)
            buffered = to_wgs84(projected.buffer(distance), utm_epsg)
        except (ShapelyError, ValueError) as err:
            raise ProcessorExecuteError(f"buffer failed: {err}")

        return "application/json", {"result": mapping(buffered)}
