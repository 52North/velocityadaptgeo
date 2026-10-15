"""Step 5 of the cool-spots chain: the study area minus everything within reach."""

from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError
from shapely.errors import ShapelyError
from shapely.geometry import mapping

from processes._geo import load_geometry, to_utm, utm_epsg_for


class GeometryDifferenceProcessor(BaseProcessor):
    """OGC API - Processes: subtract one geometry from another."""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "geometry-difference",
            "title": "Geometry Difference and Gap Analysis",
            "description": (
                "Subtracts one geometry from another and reports the remaining area in "
                "square metres, measured in a local UTM projection. Isolates the part of "
                "a study area that is NOT covered by a second layer, which is how "
                "underserved, unreached or gap areas are identified - for instance the "
                "neighbourhoods left outside walking range of any park or cool refuge, "
                "or land outside a service catchment."
            ),
            "keywords": [
                "difference",
                "erase",
                "subtract",
                "gap-analysis",
                "underserved",
                "coverage-gap",
                "overlay",
                "not-covered",
            ],
            "inputs": {
                "subject": {
                    "title": "Geometry to subtract from, e.g. the study-area boundary (GeoJSON, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "subtrahend": {
                    "title": "Geometry to remove, e.g. the area within reach (GeoJSON, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": True,
                },
            },
            "outputs": {
                "result": {
                    "title": "The part of the subject not covered by the subtrahend (GeoJSON, EPSG:4326)",
                    "schema": {"type": "object"},
                },
                "areaSqm": {
                    "title": "Ground area of the remaining geometry in square metres",
                    "schema": {"type": "number"},
                },
                "shareOfSubject": {
                    "title": "Remaining area as a fraction of the subject's area",
                    "schema": {"type": "number"},
                },
            },
            "example": {
                "inputs": {
                    "subject": {"type": "Polygon", "coordinates": [[[7.6, 51.94], [7.7, 51.94], [7.7, 52.0], [7.6, 52.0], [7.6, 51.94]]]},
                    "subtrahend": {"type": "Polygon", "coordinates": [[[7.62, 51.95], [7.66, 51.95], [7.66, 51.98], [7.62, 51.98], [7.62, 51.95]]]},
                }
            },
        }

        super().__init__(processor_def, process_metadata)

    def execute(self, data, outputs=None):
        try:
            subject = load_geometry(data["subject"])
            subtrahend = load_geometry(data["subtrahend"])
        except (KeyError, ValueError, ShapelyError) as err:
            raise ProcessorExecuteError(
                f"geometry-difference needs 'subject' and 'subtrahend': {err}"
            )

        try:
            remainder = subject.difference(subtrahend)
            utm_epsg = utm_epsg_for(subject)
            subject_utm, _ = to_utm(subject, utm_epsg)
            remainder_utm, _ = to_utm(remainder, utm_epsg) if not remainder.is_empty else (remainder, None)
        except (ShapelyError, ValueError) as err:
            raise ProcessorExecuteError(f"geometry-difference failed: {err}")

        remaining_area = 0.0 if remainder.is_empty else remainder_utm.area
        share = remaining_area / subject_utm.area if subject_utm.area else 0.0

        return "application/json", {
            "result": mapping(remainder),
            "areaSqm": round(remaining_area, 1),
            "shareOfSubject": round(share, 4),
        }
