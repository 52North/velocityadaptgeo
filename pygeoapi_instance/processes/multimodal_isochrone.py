from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


class MultimodalIsochroneProcessor(BaseProcessor):
    """OGC API - Processes stub: multimodal isochrone generation"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "multimodal-isochrone",
            "title": "Multimodal Isochrone Generation across Combined Walk, Cycle and Scheduled-Transit Networks",
            "description": (
                "Builds a time-expanded multimodal graph that couples a "
                "pedestrian/cycling street network with a scheduled-transit "
                "timetable (GTFS-style stop times, transfers and headways), "
                "executes a multi-criteria time-dependent shortest-path expansion "
                "from a departure point and time, and contours the "
                "reachable-in-time frontier into isochrone polygons at one or "
                "more travel-time thresholds."
            ),
            "keywords": [
                "isochrone",
                "multimodal-routing",
                "time-dependent-routing",
                "GTFS",
                "accessibility-analysis",
            ],
            "inputs": {
                "origin": {
                    "title": "Departure location (GeoJSON Point)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "departureTime": {
                    "title": "Departure timestamp used to enter the time-expanded transit graph",
                    "schema": {"type": "string"},
                    "required": True,
                },
                "travelTimeThresholds": {
                    "title": "Travel-time cutoffs at which isochrone contours are generated (minutes)",
                    "schema": {"type": "array"},
                    "required": True,
                },
                "transitTimetable": {
                    "title": "Reference to the scheduled-transit timetable feed (GTFS-style)",
                    "schema": {"type": "object"},
                    "required": False,
                },
                "modalWeights": {
                    "title": "Relative preference weights applied to walk, cycle and transit legs during path expansion",
                    "schema": {"type": "object"},
                    "required": False,
                },
            },
            "outputs": {
                "isochrones": {
                    "title": "Reachable-in-time frontier polygons, one per travel-time threshold",
                    "schema": {"type": "object"},
                },
                "reachedStops": {
                    "title": "Transit stops/nodes captured within each isochrone threshold",
                    "schema": {"type": "object"},
                },
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        raise ProcessorExecuteError(
            "multimodal-isochrone is a metadata-only stub and has no execution backend yet"
        )
