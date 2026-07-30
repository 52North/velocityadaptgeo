from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError
import json
import geopandas as gpd
import osmnx as ox
from shapely import Polygon
from shapely.geometry import box, shape, mapping
from shapely.ops import transform
from shapely.errors import ShapelyError
from pyproj import Transformer



class CoolSpotsProcessor(BaseProcessor):
    # 1) Define location (city name, bbox or polygon)
    # 2) Download OSM data
    # 3) Reproject from EPSG:4326 to UTM
    # 4) Merge different datasets
    # 5) Apply buffer (for different levels)
    # 6) Calculate difference
    # 7) Export

    # Improvements:
    # - instead of a buffer distance (direct line) the walking distance should be used (-> routing)
    # - (more) criteria for an "attractive" cool spot (sufficiently large, combination of sun and shadow, benches, quiet, safe and clean)
    # - UTCI (Universal Thermal Climate Index), e.g. using ERA5
    # - landuse data

    def __init__(self, processor_def):
        process_metadata = {
            "id": "cool_spots",
            "title": "Cool Spots",
            "description": "Finds cool spots in cities",
            "inputs": {
                "city_name": {
                    "title": "City Name",
                    "schema": {"type": "string"},
                    "required": True
                }
            },
            "outputs": {
                "result": {
                    "title": "Buffered Geometry",
                    "schema": {"type": "object"}
                }
            }
        }

        super().__init__(processor_def, process_metadata)
        #in m2
        self.min_area = 200
        #in m
        self.max_distance = 300


    def execute(self, data, outputs=None):
        city_name = data.get("city_name")
        if not isinstance(city_name, str ):
            raise ProcessorExecuteError(f"city_name must be a string! You provided `{city_name}`")


        try:
            #----------------------------------------------------
            # 1. Get city layer and project to UTM
            city_gdf_geogr = ox.geocode_to_gdf({"city": city_name})
            target_crs = city_gdf_geogr.estimate_utm_crs()
            city_gdf = city_gdf_geogr.to_crs(target_crs)

            # ---------------------------------------------------
            # 2. Fetch Forest Areas via OSM (Automating QuickOSM)

            # Configure OSMnx to fetch data within our bounding box
            ox.settings.use_cache = True

            # Fetch forest/natural landuse tags from OpenStreetMap
            tags = {"landuse": "forest", "natural": "wood", "leisure": "park"}
            osm_df = ox.features_from_polygon(city_gdf_geogr["geometry"][0], tags=tags)

            # Filter to polygons/multipolygons and project to UTM
            osm_df = osm_df[osm_df.geometry.type.isin(["Polygon", "MultiPolygon"])]
            cool_spots = osm_df[["geometry"]].to_crs(target_crs)

            # --------------------------------------------
            # 4. Generate Distance Buffers and Differences

            # 1. Create the master >300m buffer difference layer
            buffer = cool_spots.buffer(self.max_distance)

            diff = city_gdf.union_all().difference(buffer.union_all())

            # 2. Create the internal rings (0-75m, 75-150m, 150-225m, 225-300m)
            intervals = [0, 75, 150, 225, 300]

            # Pre-calculate the dissolved geometries for clean mathematical differences
            buffers = {dist: cool_spots.buffer(dist).union_all() for dist in intervals}

            buffered_rings = []
            buffered_rings.append({
                "geometry": cool_spots.union_all(),
                "label": "cool spots"
            })
            buffered_rings.append({
                "geometry": diff,
                "label": f"> {self.max_distance} m"
            })
            for i in range(len(intervals) - 1):
                inner_dist = intervals[i]
                outer_dist = intervals[i + 1]
                label = f"{inner_dist}m-{outer_dist}m"

                # Difference of the outer buffer from the inner buffer
                ring_geom = buffers[outer_dist].difference(buffers[inner_dist])
                buffered_rings.append({
                    "geometry": ring_geom,
                    "label": label
                })

            all_intervalls_gdf = gpd.GeoDataFrame(buffered_rings, crs=target_crs)
            geojson_dict = json.loads(all_intervalls_gdf.to_crs("EPSG:4326").to_json())

            return "application/json", {
                "result": geojson_dict
            }

        except (KeyError, ValueError, ShapelyError) as err:
            raise ProcessorExecuteError(f"Process failed: {err}")