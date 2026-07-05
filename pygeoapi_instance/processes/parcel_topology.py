from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


class ParcelTopologyProcessor(BaseProcessor):
    """OGC API - Processes stub: cadastral parcel topology validation & auto-correction"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "parcel-topology-validation",
            "title": "Cadastral Parcel Topology Validation and Rule-Based Auto-Correction",
            "description": (
                "Validates a set of cadastral parcel polygons against a "
                "configurable rule set (no self-intersection, no gaps beyond a "
                "tolerance, no unexplained overlaps, shared-boundary snapping), "
                "reports every violation with its geometric location, and "
                "optionally applies a rule-ordered auto-correction pass "
                "(snapping, gap-closing, sliver removal) while preserving parcel "
                "area within a declared tolerance."
            ),
            "keywords": [
                "cadastre",
                "topology-validation",
                "geometry-repair",
                "sliver-removal",
                "land-parcels",
            ],
            "inputs": {
                "parcels": {
                    "title": "Cadastral parcel polygons to validate (GeoJSON FeatureCollection of Polygons)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "toleranceRules": {
                    "title": "Named tolerance thresholds for gap, overlap and snapping checks (metres)",
                    "schema": {"type": "object"},
                    "required": False,
                },
                "autoCorrect": {
                    "title": "Whether to apply the rule-ordered auto-correction pass after validation",
                    "schema": {"type": "string"},
                    "required": False,
                },
                "areaChangeTolerance": {
                    "title": "Maximum permitted relative parcel-area change introduced by auto-correction",
                    "schema": {"type": "number"},
                    "required": False,
                },
            },
            "outputs": {
                "violations": {
                    "title": "List of detected topology violations with rule id and violating geometry",
                    "schema": {"type": "object"},
                },
                "correctedParcels": {
                    "title": "Auto-corrected parcel geometries, present only if autoCorrect was requested",
                    "schema": {"type": "object"},
                },
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        raise ProcessorExecuteError(
            "parcel-topology-validation is a metadata-only stub and has no execution backend yet"
        )
