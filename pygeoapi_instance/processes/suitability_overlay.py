from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


class SuitabilityOverlayProcessor(BaseProcessor):
    """OGC API - Processes stub: multi-criteria weighted-overlay suitability analysis"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "multicriteria-suitability-overlay",
            "title": (
                "Multi-Criteria Weighted-Overlay Suitability Analysis with "
                "Analytic-Hierarchy-Process Weighting"
            ),
            "description": (
                "Derives a normalised site-suitability surface by reclassifying an "
                "arbitrary set of input raster or vector criteria onto a common "
                "ordinal scale, deriving criterion weights from a pairwise "
                "Analytic Hierarchy Process (AHP) comparison matrix, and combining "
                "the weighted layers through a configurable overlay operator "
                "(weighted-linear-combination, ordered-weighted-average, or fuzzy-AND)."
            ),
            "keywords": [
                "site-suitability",
                "multi-criteria-decision-analysis",
                "AHP",
                "weighted-overlay",
                "land-use-planning",
            ],
            "inputs": {
                "criteriaLayers": {
                    "title": "Set of criterion layers, each with a raster/vector reference and a reclassification ramp",
                    "schema": {"type": "array"},
                    "required": True,
                },
                "pairwiseComparisonMatrix": {
                    "title": "Pairwise AHP comparison matrix used to derive normalised criterion weights",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "overlayOperator": {
                    "title": "Combination operator applied across weighted criteria ('WLC', 'OWA', 'fuzzy-AND')",
                    "schema": {"type": "string"},
                    "required": False,
                },
                "consistencyRatioThreshold": {
                    "title": "Maximum acceptable AHP consistency ratio before the request is rejected",
                    "schema": {"type": "number"},
                    "required": False,
                },
            },
            "outputs": {
                "suitabilitySurface": {
                    "title": "Normalised suitability surface (0-1) as a georeferenced raster",
                    "schema": {"type": "object"},
                },
                "derivedWeights": {
                    "title": "Criterion weights derived from the AHP eigenvector solution",
                    "schema": {"type": "object"},
                },
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        raise ProcessorExecuteError(
            "multicriteria-suitability-overlay is a metadata-only stub and has no execution backend yet"
        )
