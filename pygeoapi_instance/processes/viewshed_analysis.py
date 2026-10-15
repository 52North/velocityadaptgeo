from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


class ViewshedAnalysisProcessor(BaseProcessor):
    """OGC API - Processes stub: curvature/refraction-corrected viewshed analysis"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "viewshed-line-of-sight",
            "title": "Viewshed and Line-of-Sight Visibility Analysis",
            "description": (
                "Determines which parts of the terrain can be seen from one or more "
                "observer points (viewshed or line-of-sight analysis) over an elevation "
                "model, correcting for Earth curvature and atmospheric refraction, with "
                "sight lines optionally blocked by buildings or tree canopy. Heights are "
                "in metres above ground and areas in square metres. Returns a visibility "
                "raster and the visible ground area per observer. Assesses what is in "
                "view - for example the visual impact of a wind turbine."
            ),
            "keywords": [
                "viewshed",
                "line-of-sight",
                "visibility-analysis",
                "terrain-analysis",
                "visual-impact",
                "curvature-correction",
            ],
            "inputs": {
                "observerPoints": {
                    "title": "Observer locations with optional per-point height (GeoJSON MultiPoint, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "dem": {
                    "title": "Ground elevation model (COG URI)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "obstacleLayer": {
                    "title": "Above-ground obstacle heights, e.g. canopy or buildings (raster)",
                    "schema": {"type": "object"},
                    "required": False,
                },
                "observerHeightOffset": {
                    "title": "Observer height above ground, in metres",
                    "schema": {"type": "number"},
                    "required": False,
                },
                "targetHeightOffset": {
                    "title": "Target height above ground, in metres",
                    "schema": {"type": "number"},
                    "required": False,
                },
                "refractionCoefficient": {
                    "title": "Atmospheric refraction coefficient for the curvature correction, e.g. 0.13",
                    "schema": {"type": "number"},
                    "required": False,
                },
            },
            "outputs": {
                "viewshedRaster": {
                    "title": "Visible or graded visibility per cell (raster)",
                    "schema": {"type": "object"},
                },
                "visibleArea": {
                    "title": "Visible ground area per observer, in square metres",
                    "schema": {"type": "number"},
                },
            },
            "example": {
                "inputs": {
                    "observerPoints": {"type": "MultiPoint", "coordinates": [[7.6261, 51.9607]]},
                    "dem": {"href": "https://example.org/dem.tif"},
                }
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        raise ProcessorExecuteError(
            "viewshed-line-of-sight is a metadata-only stub and has no execution backend yet"
        )
