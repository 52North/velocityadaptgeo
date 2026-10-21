from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


class MultimodalIsochroneProcessor(BaseProcessor):
    """OGC API - Processes stub: multimodal isochrone generation"""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "multimodal-isochrone",
            "title": "Walk, Cycle and Transit Travel-Time Isochrones",
            "description": (
                "Maps the area reachable from a departure point within given travel times "
                "(isochrones or travel-time catchments) by walking, cycling and scheduled "
                "public transit, over the street network and a GTFS-style timetable. "
                "Travel times are in minutes along the network, not straight-line "
                "distance. Returns one reachable-area polygon per time threshold and the "
                "transit stops reached. Measures real accessibility - for example which "
                "schools a district reaches within 30 minutes by bus."
            ),
            "keywords": [
                "isochrone",
                "travel-time",
                "accessibility-analysis",
                "multimodal-routing",
                "time-dependent-routing",
                "public-transit",
                "GTFS",
            ],
            "inputs": {
                "origin": {
                    "title": "Departure location (GeoJSON Point, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "departureTime": {
                    "title": "Departure time (ISO-8601 timestamp)",
                    "schema": {"type": "string"},
                    "required": True,
                },
                "travelTimeThresholds": {
                    "title": "Travel-time cutoffs in minutes, one isochrone each",
                    "schema": {"type": "array", "items": {"type": "number"}},
                    "required": True,
                },
                "transitTimetable": {
                    "title": "Transit timetable feed (GTFS URI)",
                    "schema": {"type": "object"},
                    "required": False,
                },
                "modalWeights": {
                    "title": "Relative preference weights for walk, cycle and transit legs",
                    "schema": {"type": "object"},
                    "required": False,
                },
            },
            "outputs": {
                "isochrones": {
                    "title": "Reachable-area polygons, one per travel-time threshold (GeoJSON FeatureCollection, EPSG:4326)",
                    "schema": {"type": "object"},
                },
                "reachedStops": {
                    "title": "Transit stops reached within each threshold (GeoJSON FeatureCollection, EPSG:4326)",
                    "schema": {"type": "object"},
                },
            },
            "example": {
                "inputs": {
                    "origin": {"type": "Point", "coordinates": [7.6261, 51.9607]},
                    "departureTime": "2026-07-01T08:00:00Z",
                    "travelTimeThresholds": [10, 20, 30],
                }
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        raise ProcessorExecuteError(
            "multimodal-isochrone is a metadata-only stub and has no execution backend yet"
        )
