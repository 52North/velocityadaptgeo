from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


class SuitabilityOverlayProcessor(BaseProcessor):
    """OGC API - Processes stub: multi-criteria weighted-overlay suitability analysis"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "multicriteria-suitability-overlay",
            "title": "Multi-Criteria Site Suitability Overlay",
            "description": (
                "Scores every location for how well it suits a purpose (site suitability "
                "or weighted-overlay analysis) by rescaling several criterion layers to a "
                "common scale, weighting them from a pairwise Analytic Hierarchy Process "
                "(AHP) comparison, and combining them by weighted sum, ordered weighted "
                "average or fuzzy AND. Layers are combined on one grid in their shared "
                "projected CRS. Returns a 0-1 suitability surface and the derived "
                "weights. Ranks candidate sites - for example where to place a wind farm."
            ),
            "keywords": [
                "site-suitability",
                "weighted-overlay",
                "multi-criteria-decision-analysis",
                "AHP",
                "land-use-planning",
                "site-selection",
            ],
            "inputs": {
                "criteriaLayers": {
                    "title": "Criterion layers, each a raster or vector reference with a reclassification ramp",
                    "schema": {"type": "array", "items": {"type": "object"}},
                    "required": True,
                },
                "pairwiseComparisonMatrix": {
                    "title": "Pairwise AHP comparison matrix the criterion weights are derived from",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "overlayOperator": {
                    "title": "Combination operator, e.g. 'WLC', 'OWA' or 'fuzzy-AND'",
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
                    "title": "Suitability surface from 0 to 1 (raster)",
                    "schema": {"type": "object"},
                },
                "derivedWeights": {
                    "title": "Criterion weights derived from the AHP eigenvector solution",
                    "schema": {"type": "object"},
                },
            },
            "example": {
                "inputs": {
                    "criteriaLayers": [],
                    "pairwiseComparisonMatrix": {},
                }
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        raise ProcessorExecuteError(
            "multicriteria-suitability-overlay is a metadata-only stub and has no execution backend yet"
        )
