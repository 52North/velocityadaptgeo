from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError
from shapely.geometry import shape, mapping
from shapely.ops import transform
from shapely.errors import ShapelyError
from pyproj import Transformer


class BufferProcessor(BaseProcessor):
    """OGC API - Processes buffer example"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "buffer",
            "title": "Geometry Buffer",
            "description": "Buffers an input geometry by a given distance (meters)",
            "inputs": {
                "geometry": {
                    "title": "Input Geometry (GeoJSON)",
                    "schema": {"type": "object"},
                    "required": True
                },
                "distance": {
                    "title": "Buffer Distance (meters)",
                    "schema": {"type": "number"},
                    "required": True
                }
            },
            "outputs": {
                "result": {
                    "title": "Buffered Geometry",
                    "schema": {"type": "object"}
                }
            }
        }

        super().__init__(processor_def, process_metadata)

        # Transformers
        self.to_meters = Transformer.from_crs(
            "EPSG:4326", "EPSG:3857", always_xy=True
        ).transform

        self.to_degrees = Transformer.from_crs(
            "EPSG:3857", "EPSG:4326", always_xy=True
        ).transform

    def execute(self, data, outputs=None):
        try:
            geom = shape(data["geometry"])
            distance = float(data["distance"])

            # 1. project to meters
            geom_m = transform(self.to_meters, geom)

            # 2. buffer in meters
            buffered_m = geom_m.buffer(distance)

            # 3. project back to lon/lat
            buffered_ll = transform(self.to_degrees, buffered_m)

            return "application/json", {
                "result": mapping(buffered_ll)
            }

        except (KeyError, ValueError, ShapelyError) as err:
            raise ProcessorExecuteError(f"Buffer failed: {err}")
