from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


class WatershedDelineationProcessor(BaseProcessor):
    """OGC API - Processes stub: hydrological flow accumulation & watershed delineation"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "watershed-delineation",
            "title": "Watershed and Stream Network Delineation",
            "description": (
                "Traces the area that drains to one or more outlet points (watershed or "
                "catchment delineation) from a digital elevation model: fills spurious "
                "sinks, routes flow with D8, D-infinity or multiple flow directions, "
                "accumulates upstream area and extracts the stream network. Works on the "
                "elevation model's own grid and projected CRS. Returns a watershed "
                "boundary per pour point and the stream lines. Defines drainage areas - "
                "for example the catchment upstream of a river gauge for flood studies."
            ),
            "keywords": [
                "hydrology",
                "watershed-delineation",
                "catchment",
                "DEM",
                "flow-accumulation",
                "drainage-network",
                "D-infinity",
            ],
            "inputs": {
                "dem": {
                    "title": "Digital elevation model (COG URI)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "pourPoints": {
                    "title": "Outlet points to trace watersheds upstream from (GeoJSON MultiPoint, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "flowRoutingAlgorithm": {
                    "title": "Flow-routing method, e.g. 'D8', 'D-infinity' or 'MFD'",
                    "schema": {"type": "string"},
                    "required": False,
                },
                "streamThreshold": {
                    "title": "Smallest upstream area, in grid cells, that starts a stream",
                    "schema": {"type": "number"},
                    "required": False,
                },
            },
            "outputs": {
                "watershedBoundary": {
                    "title": "Watershed boundary per pour point (GeoJSON Polygon, EPSG:4326)",
                    "schema": {"type": "object"},
                },
                "streamNetwork": {
                    "title": "Stream network above the threshold (GeoJSON MultiLineString, EPSG:4326)",
                    "schema": {"type": "object"},
                },
            },
            "example": {
                "inputs": {
                    "dem": {"href": "https://example.org/dem.tif"},
                    "pourPoints": {"type": "MultiPoint", "coordinates": [[7.6261, 51.9607]]},
                }
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        raise ProcessorExecuteError(
            "watershed-delineation is a metadata-only stub and has no execution backend yet"
        )
