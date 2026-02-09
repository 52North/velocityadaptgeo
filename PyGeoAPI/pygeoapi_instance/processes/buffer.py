from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError
from shapely.geometry import shape, mapping
from shapely.errors import ShapelyError


class BufferProcessor(BaseProcessor):
    """OGC API - Processes buffer example"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "buffer",
            "title": "Geometry Buffer",
            "description": "Buffers an input geometry by a given distance",
            "inputs": {
                "geometry": {
                    "title": "Input Geometry (GeoJSON)",
                    "schema": {
                        "type": "object"
                    },
                    "required": True
                },
                "distance": {
                    "title": "Buffer Distance",
                    "schema": {
                        "type": "number"
                    },
                    "required": True
                }
            },
            "outputs": {
                "result": {
                    "title": "Buffered Geometry",
                    "schema": {
                        "type": "object"
                    }
                }
            }
        }

        # 🔴 REQUIRED in newer pygeoapi
        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        try:
            geom = shape(data["geometry"])
            distance = float(data["distance"])

            buffered = geom.buffer(distance)

            result = {
                "result": mapping(buffered)
            }

            # 🔴 MUST return (outputs, mimetype)
            return "application/json", result

        except (KeyError, ValueError, ShapelyError) as err:
            raise ProcessorExecuteError(f"Buffer failed: {err}")

