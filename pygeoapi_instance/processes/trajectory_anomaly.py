from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


class TrajectoryAnomalyProcessor(BaseProcessor):
    """OGC API - Processes stub: spatiotemporal trajectory anomaly detection"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "trajectory-anomaly-detection",
            "title": (
                "Spatiotemporal Anomaly and Behavioural Change-Point Detection in "
                "Moving-Object Trajectory Streams"
            ),
            "description": (
                "Segments a stream of moving-object position reports (AIS, GPS, "
                "ADS-B) into stop/move episodes, extracts kinematic features "
                "(speed, heading-change, sinuosity), and flags trajectories whose "
                "local density or kinematic profile deviates from a learned "
                "baseline via density-based clustering and change-point "
                "statistics, surfacing candidate anomalies such as loitering, "
                "course deviation or rendezvous."
            ),
            "keywords": [
                "trajectory-analysis",
                "anomaly-detection",
                "moving-objects",
                "change-point-detection",
                "AIS",
                "density-clustering",
            ],
            "inputs": {
                "trajectoryStream": {
                    "title": (
                        "Time-ordered moving-object position reports (GeoJSON "
                        "FeatureCollection of Points with timestamp/id properties)"
                    ),
                    "schema": {"type": "object"},
                    "required": True,
                },
                "baselineProfile": {
                    "title": "Reference to a previously learned baseline kinematic/density profile",
                    "schema": {"type": "object"},
                    "required": False,
                },
                "clusteringEpsilon": {
                    "title": "Spatial neighbourhood radius (metres) used by the density-based clustering step",
                    "schema": {"type": "number"},
                    "required": False,
                },
                "minEpisodeDuration": {
                    "title": "Minimum duration (seconds) for a stop episode to be considered significant",
                    "schema": {"type": "number"},
                    "required": False,
                },
            },
            "outputs": {
                "anomalies": {
                    "title": "Flagged trajectory segments with anomaly type and confidence score",
                    "schema": {"type": "object"},
                },
                "episodes": {
                    "title": "Extracted stop/move episode segmentation of the input trajectories",
                    "schema": {"type": "object"},
                },
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        raise ProcessorExecuteError(
            "trajectory-anomaly-detection is a metadata-only stub and has no execution backend yet"
        )
