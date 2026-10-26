"""Step 1 of the cool-spots chain: resolve a place name into a study-area polygon."""

import os

import requests
from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError
from shapely.errors import ShapelyError
from shapely.geometry import box, mapping, shape

from processes._geo import to_utm, utm_epsg_for

NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
USER_AGENT = os.environ.get("OSM_USER_AGENT", "north52-coolspots/1.0")
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "30"))


class CityBoundaryProcessor(BaseProcessor):
    """OGC API - Processes: place name or bounding box to study-area polygon."""

    def __init__(self, processor_def):
        process_metadata = {
            "id": "city-boundary",
            "title": "Administrative Boundary Lookup for a Named Place",
            "description": (
                "Resolves a place name (city, district, municipality) into its "
                "administrative boundary polygon by geocoding the name against an OSM "
                "Nominatim gazetteer, and reports the local UTM projection and ground "
                "area of the result. Establishes the study area that later analysis "
                "steps are restricted to and clipped against. A bounding box may be "
                "supplied instead of, or as a fallback for, the place name so the "
                "workflow still yields an area of interest when a name cannot be "
                "geocoded."
            ),
            "keywords": [
                "geocoding",
                "administrative-boundary",
                "place-name",
                "gazetteer",
                "study-area",
                "area-of-interest",
            ],
            "inputs": {
                "place": {
                    "title": "Place name to geocode, e.g. 'Muenster' or 'Muenster, Germany'",
                    "schema": {"type": "string"},
                    "required": False,
                },
                "bbox": {
                    "title": "Fallback bounding box [minLon, minLat, maxLon, maxLat] in EPSG:4326",
                    "schema": {"type": "array", "items": {"type": "number"}},
                    "required": False,
                },
            },
            "outputs": {
                "boundary": {
                    "title": "Study-area boundary polygon (GeoJSON, EPSG:4326)",
                    "schema": {"type": "object"},
                },
                "bbox": {
                    "title": "Bounding box of the study area",
                    "schema": {"type": "array", "items": {"type": "number"}},
                },
                "utmCrs": {
                    "title": "Local UTM CRS suited to metric analysis of this area",
                    "schema": {"type": "string"},
                },
                "areaSqm": {
                    "title": "Ground area of the study area in square metres",
                    "schema": {"type": "number"},
                },
            },
            "example": {"inputs": {"place": "Muenster", "bbox": [7.47, 51.84, 7.78, 52.06]}},
        }

        super().__init__(processor_def, process_metadata)

    def _geocode(self, place: str):
        """Return the first area among Nominatim's hits for a place name, and why there is none.

        The top hit is often a `place=*` node or a street rather than a boundary. A Point or
        LineString would pass for a study area and leave every later step empty, so the first
        polygon among the top hits is taken instead.
        """
        response = requests.get(
            NOMINATIM_URL,
            params={"q": place, "format": "jsonv2", "polygon_geojson": 1, "limit": 5},
            headers={"User-Agent": USER_AGENT},
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        found = []
        for hit in response.json():
            if "geojson" not in hit:
                continue
            geom = shape(hit["geojson"])
            if geom.geom_type in ("Polygon", "MultiPolygon") and not geom.is_empty:
                return geom, None
            found.append(geom.geom_type)
        if not found:
            return None, None
        return None, f"Nominatim matched only {', '.join(dict.fromkeys(found))}, not an area"

    def execute(self, data, outputs=None):
        place = data.get("place")
        bbox = data.get("bbox")

        if not place and not bbox:
            raise ProcessorExecuteError("city-boundary needs either 'place' or 'bbox'")

        geom = None
        source = None
        geocode_error = None
        if place:
            try:
                geom, geocode_error = self._geocode(place)
                source = "nominatim"
            except (requests.RequestException, ValueError, KeyError, ShapelyError) as err:
                geocode_error = f"Nominatim lookup failed ({type(err).__name__}: {err})"
                geom = None

        if geom is None or geom.is_empty:
            if not bbox:
                raise ProcessorExecuteError(
                    f"could not geocode '{place}' and no fallback bbox was supplied"
                    f"{': ' + geocode_error if geocode_error else ''}"
                )
            if len(bbox) != 4:
                raise ProcessorExecuteError("bbox must be [minLon, minLat, maxLon, maxLat]")
            min_lon, min_lat, max_lon, max_lat = (float(v) for v in bbox)
            if not (min_lon < max_lon and min_lat < max_lat):
                raise ProcessorExecuteError("bbox must be [minLon, minLat, maxLon, maxLat] with min < max")
            geom = box(min_lon, min_lat, max_lon, max_lat)
            source = "bbox"

        try:
            utm_geom, utm_epsg = to_utm(geom, utm_epsg_for(geom))
        except (ShapelyError, ValueError) as err:
            raise ProcessorExecuteError(f"city-boundary projection failed: {err}")

        return "application/json", {
            "boundary": {
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": {"place": place, "source": source, "error": geocode_error},
            },
            "bbox": [round(v, 6) for v in geom.bounds],
            "utmCrs": utm_epsg,
            "areaSqm": round(utm_geom.area, 1),
        }
