from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


class ViewshedAnalysisProcessor(BaseProcessor):
    """OGC API - Processes stub: curvature/refraction-corrected viewshed analysis"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "viewshed-line-of-sight",
            "title": "Curvature- and Refraction-Corrected Viewshed and Line-of-Sight Analysis",
            "description": (
                "Computes the set of terrain cells visible from one or more "
                "observer points against an elevation surface, accounting for "
                "Earth curvature, atmospheric refraction, observer/target offset "
                "heights, and optional obstruction by a supplementary "
                "above-ground-level obstacle layer (vegetation canopy, buildings)."
            ),
            "keywords": [
                "viewshed",
                "line-of-sight",
                "visibility-analysis",
                "terrain-analysis",
                "curvature-correction",
            ],
            "inputs": {
                "observerPoints": {
                    "title": "Observer locations with optional per-point offset height (GeoJSON MultiPoint)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "dem": {
                    "title": "Reference to the ground-elevation surface (COG URI)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "obstacleLayer": {
                    "title": "Optional above-ground obstruction layer (canopy/building height raster)",
                    "schema": {"type": "object"},
                    "required": False,
                },
                "observerHeightOffset": {
                    "title": "Height of the observer above the ground surface (metres)",
                    "schema": {"type": "number"},
                    "required": False,
                },
                "targetHeightOffset": {
                    "title": "Height of the notional target above the ground surface (metres)",
                    "schema": {"type": "number"},
                    "required": False,
                },
                "refractionCoefficient": {
                    "title": "Atmospheric refraction coefficient applied to the curvature correction",
                    "schema": {"type": "number"},
                    "required": False,
                },
            },
            "outputs": {
                "viewshedRaster": {
                    "title": "Binary/graded visibility raster across the analysis extent",
                    "schema": {"type": "object"},
                },
                "visibleArea": {
                    "title": "Total visible ground area per observer (square metres)",
                    "schema": {"type": "number"},
                },
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        raise ProcessorExecuteError(
            "viewshed-line-of-sight is a metadata-only stub and has no execution backend yet"
        )
