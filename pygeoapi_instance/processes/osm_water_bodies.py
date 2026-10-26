"""Blue-space branch of the enriched cool-spots chain: open water inside the study area.

Runs independently of `osm-green-areas` - both need only the study-area boundary - so the
two extractions form the parallel branches of the graph. Everything else - the Overpass
querying, the polygon assembly and `execute` - is inherited; only the tag defaults and the
metadata differ.
"""

from pygeoapi.process.base import BaseProcessor

from processes.osm_green_areas import OsmGreenAreasProcessor

DEFAULT_WATER_TAGS = {
    "natural": "water",
    "landuse": ["reservoir", "basin"],
    "waterway": "riverbank",
}


class OsmWaterBodiesProcessor(OsmGreenAreasProcessor):
    """OGC API - Processes: open-water polygons within an area."""

    default_tags = DEFAULT_WATER_TAGS

    def __init__(self, processor_def):
        # BaseProcessor directly, not super(): the parent's __init__ exists only to install
        # the green-areas metadata, which is exactly what is being replaced here.
        BaseProcessor.__init__(self, processor_def, {
            "id": "osm-water-bodies",
            "title": "OpenStreetMap Open-Water and Blue-Space Extraction",
            "description": (
                "Downloads OpenStreetMap polygon features describing open water - lakes, "
                "ponds, reservoirs, basins and river surfaces - from inside a study-area "
                "polygon, and clips them to it. Water surfaces cool the air around them "
                "much as tree canopy does, so these blue spaces complement vegetated "
                "green space when mapping where people can escape summer heat. Tags may "
                "be overridden to extract any other water-related land cover."
            ),
            "keywords": [
                "openstreetmap",
                "overpass",
                "water",
                "blue-space",
                "lakes",
                "rivers",
                "ponds",
                "evaporative-cooling",
                "urban-heat",
                "cool-spots",
            ],
            "inputs": {
                "area": {
                    "title": "Study-area polygon to search within (GeoJSON, EPSG:4326)",
                    "schema": {"type": "object"},
                    "required": True,
                },
                "tags": {
                    "title": (
                        "OSM tag filter as {key: value} or {key: [values]}; defaults to "
                        "{'natural': 'water', 'landuse': ['reservoir', 'basin'], "
                        "'waterway': 'riverbank'}"
                    ),
                    "schema": {"type": "object"},
                    "required": False,
                },
            },
            "outputs": {
                "features": {
                    "title": "Open-water polygons (GeoJSON FeatureCollection, EPSG:4326)",
                    "schema": {"type": "object"},
                },
                "count": {
                    "title": "Number of polygons returned",
                    "schema": {"type": "integer"},
                },
            },
            "example": {
                "inputs": {
                    "area": {"type": "Polygon", "coordinates": [[[7.6, 51.94], [7.65, 51.94], [7.65, 51.97], [7.6, 51.97], [7.6, 51.94]]]},
                }
            },
        })
