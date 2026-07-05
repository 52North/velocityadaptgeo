from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


class WatershedDelineationProcessor(BaseProcessor):
    """OGC API - Processes stub: hydrological flow accumulation & watershed delineation"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "watershed-delineation",
            "title": (
                "Hydrological Flow-Direction, Flow-Accumulation and Watershed "
                "Delineation from a Digital Elevation Model"
            ),
            "description": (
                "Conditions a digital elevation model by filling spurious "
                "depressions, derives an eight-direction or D-infinity flow-routing "
                "grid, accumulates upstream contributing area, and delineates the "
                "drainage watershed and stream network upstream of one or more "
                "user-supplied pour points."
            ),
            "keywords": [
                "hydrology",
                "DEM",
                "flow-accumulation",
                "watershed-delineation",
                "drainage-network",
                "D-infinity",
            ],
            "inputs": {
                "dem": {
                    "title": "Reference to a hydrologically-conditioned digital elevation model (COG URI)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "pourPoints": {
                    "title": "Outlet/pour points from which watersheds are traced upstream (GeoJSON MultiPoint)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "flowRoutingAlgorithm": {
                    "title": "Flow-routing algorithm ('D8', 'D-infinity', 'MFD')",
                    "schema": {"type": "string"},
                    "required": False,
                },
                "streamThreshold": {
                    "title": "Minimum accumulated contributing area (cells) required to seed a stream reach",
                    "schema": {"type": "number"},
                    "required": False,
                },
            },
            "outputs": {
                "watershedBoundary": {
                    "title": "Delineated watershed boundary per pour point (GeoJSON Polygon)",
                    "schema": {"type": "object"},
                },
                "streamNetwork": {
                    "title": "Derived stream network above the given threshold (GeoJSON MultiLineString)",
                    "schema": {"type": "object"},
                },
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        raise ProcessorExecuteError(
            "watershed-delineation is a metadata-only stub and has no execution backend yet"
        )
