from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


class ParcelTopologyProcessor(BaseProcessor):
    """OGC API - Processes stub: cadastral parcel topology validation & auto-correction"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "parcel-topology-validation",
            "title": "Cadastral Parcel Topology Validation and Repair",
            "description": (
                "Checks cadastral parcel polygons for topology errors (topology "
                "validation or geometry repair) - self-intersections, gaps and overlaps "
                "between neighbours, shared boundaries that do not meet - and reports "
                "each violation with its location. Can then fix them by snapping, closing "
                "gaps and removing slivers while keeping each parcel's area within a "
                "tolerance. Tolerances are in metres. Cleans a land register before "
                "analysis - for example before merging parcel data from two surveys."
            ),
            "keywords": [
                "cadastre",
                "land-parcels",
                "topology-validation",
                "geometry-repair",
                "quality-control",
                "sliver-removal",
                "snapping",
            ],
            "inputs": {
                "parcels": {
                    "title": "Parcel polygons to validate (GeoJSON FeatureCollection, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "toleranceRules": {
                    "title": "Named gap, overlap and snapping tolerances, in metres",
                    "schema": {"type": "object"},
                    "required": False,
                },
                "autoCorrect": {
                    "title": "Whether to apply the auto-correction pass after validation",
                    "schema": {"type": "boolean"},
                    "required": False,
                },
                "areaChangeTolerance": {
                    "title": "Largest relative parcel-area change auto-correction may introduce, e.g. 0.01",
                    "schema": {"type": "number"},
                    "required": False,
                },
            },
            "outputs": {
                "violations": {
                    "title": "Detected topology violations, each with its rule id and violating geometry",
                    "schema": {"type": "object"},
                },
                "correctedParcels": {
                    "title": "Corrected parcels (GeoJSON FeatureCollection, EPSG:4326), only when autoCorrect is set",
                    "schema": {"type": "object"},
                },
            },
            "example": {
                "inputs": {
                    "parcels": {"type": "FeatureCollection", "features": []},
                    "autoCorrect": False,
                }
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        raise ProcessorExecuteError(
            "parcel-topology-validation is a metadata-only stub and has no execution backend yet"
        )
