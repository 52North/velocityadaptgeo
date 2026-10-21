from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


class PointCloudSegmentationProcessor(BaseProcessor):
    """OGC API - Processes stub: LiDAR ground classification & semantic segmentation"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "pointcloud-ground-segmentation",
            "title": "LiDAR Point-Cloud Ground and Object Classification",
            "description": (
                "Classifies a LiDAR point cloud into ground and non-ground points (ground "
                "filtering or point-cloud segmentation) with a progressive morphological "
                "filter, then labels the non-ground points as vegetation, building or "
                "water from their height, intensity and density. Heights are in metres in "
                "the point cloud's own projected CRS. Also returns a bare-earth digital "
                "terrain model built from the ground points. Prepares elevation data - "
                "for example a terrain model for flood modelling or tree heights."
            ),
            "keywords": [
                "point-cloud",
                "LiDAR",
                "ground-classification",
                "semantic-segmentation",
                "digital-terrain-model",
                "morphological-filter",
                "elevation",
            ],
            "inputs": {
                "pointCloud": {
                    "title": "LiDAR point cloud (COPC or LAZ URI)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "structuringElementSchedule": {
                    "title": "Increasing filter window sizes, in metres",
                    "schema": {"type": "array", "items": {"type": "number"}},
                    "required": False,
                },
                "slopeToleranceCurve": {
                    "title": "Slope-dependent height tolerance used by the ground filter",
                    "schema": {"type": "object"},
                    "required": False,
                },
                "semanticClasses": {
                    "title": "Classes to assign to non-ground points, e.g. ['vegetation', 'building']",
                    "schema": {"type": "array", "items": {"type": "string"}},
                    "required": False,
                },
            },
            "outputs": {
                "classifiedPointCloud": {
                    "title": "Point cloud with a ground or object class label on every point",
                    "schema": {"type": "object"},
                },
                "terrainModel": {
                    "title": "Bare-earth digital terrain model built from the ground points (raster)",
                    "schema": {"type": "object"},
                },
            },
            "example": {
                "inputs": {
                    "pointCloud": {"href": "https://example.org/tile.copc.laz"},
                }
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        raise ProcessorExecuteError(
            "pointcloud-ground-segmentation is a metadata-only stub and has no execution backend yet"
        )
