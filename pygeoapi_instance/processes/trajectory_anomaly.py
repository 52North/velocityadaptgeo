from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


class TrajectoryAnomalyProcessor(BaseProcessor):
    """OGC API - Processes stub: spatiotemporal trajectory anomaly detection"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "trajectory-anomaly-detection",
            "title": "Anomaly Detection in Moving-Object Tracks",
            "description": (
                "Flags unusual behaviour in the tracks of ships, vehicles or aircraft "
                "(trajectory anomaly detection) by splitting AIS, GPS or ADS-B position "
                "reports into stops and moves, deriving speed, heading change and "
                "sinuosity, and comparing them with a learned baseline through density "
                "clustering and change-point statistics. Distances are in metres, "
                "durations in seconds. Returns the anomalous segments with type and "
                "confidence, and the stop and move episodes. Spots loitering or course "
                "deviations at sea."
            ),
            "keywords": [
                "trajectory-analysis",
                "anomaly-detection",
                "moving-objects",
                "change-point-detection",
                "AIS",
                "GPS",
                "density-clustering",
                "maritime-surveillance",
            ],
            "inputs": {
                "trajectoryStream": {
                    "title": "Time-ordered position reports with timestamp and id (GeoJSON FeatureCollection, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "baselineProfile": {
                    "title": "Previously learned baseline profile of normal movement",
                    "schema": {"type": "object"},
                    "required": False,
                },
                "clusteringEpsilon": {
                    "title": "Neighbourhood radius for density clustering, in metres",
                    "schema": {"type": "number"},
                    "required": False,
                },
                "minEpisodeDuration": {
                    "title": "Shortest stop episode to keep, in seconds",
                    "schema": {"type": "number"},
                    "required": False,
                },
            },
            "outputs": {
                "anomalies": {
                    "title": "Anomalous track segments with anomaly type and confidence (GeoJSON FeatureCollection, EPSG:4326)",
                    "schema": {"type": "object"},
                },
                "episodes": {
                    "title": "Stop and move episodes of the input tracks (GeoJSON FeatureCollection, EPSG:4326)",
                    "schema": {"type": "object"},
                },
            },
            "example": {
                "inputs": {
                    "trajectoryStream": {"type": "FeatureCollection", "features": []},
                }
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        raise ProcessorExecuteError(
            "trajectory-anomaly-detection is a metadata-only stub and has no execution backend yet"
        )
