import geopandas as gpd
import osmnx as ox
import contextily as ctx
import matplotlib.pyplot as plt
import numpy as np
from shapely import Polygon
from shapely.geometry import box


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

# -------------------------------------------------
# Define your city's bounding box (min longitude, min latitude, max longitude, max latitude)
# Example coordinates for a region in UTM zone 34N:
bbox = [7.7, 51.85, 7.75, 52.0]
polygon = Polygon(
    [
        [7.4851106, 52.0054937],
        [7.5165422, 51.9345983],
        [7.6355149, 51.8846002],
        [7.7843607, 51.9067216],
        [7.7311087, 52.0149273],
        [7.5960305, 52.006773],
        [7.4851106, 52.0054937]
    ]
)  # counter-clockwise
city_name = "muenster"
min_area = 200  # in m²
max_distance = 300  # in m

try:
    city_gdf_geogr = ox.geocode_to_gdf({"city": city_name})
except Exception:
    city_polygon = box(*bbox)
    city_gdf_geogr = gpd.GeoDataFrame(geometry=[city_polygon], crs="EPSG:4326")

target_crs = city_gdf_geogr.estimate_utm_crs()
city_gdf = city_gdf_geogr.to_crs(target_crs)

city_gdf.to_file("outputs/city.gpkg", layer="city", driver="GPKG")

print("City area layer initialized.")

# ---------------------------------------------------
# 3. Fetch Forest Areas via OSM (Automating QuickOSM)

# Configure OSMnx to fetch data within our bounding box
ox.settings.use_cache = True

# Fetch forest/natural landuse tags from OpenStreetMap
tags = {"landuse": "forest", "natural": "wood", "leisure": "park"}
osm_df = ox.features_from_polygon(city_gdf_geogr["geometry"][0], tags=tags)

# Filter to polygons/multipolygons and project to UTM
osm_df = osm_df[osm_df.geometry.type.isin(["Polygon", "MultiPolygon"])]
cool_spots = osm_df[["geometry"]].to_crs(target_crs)
cool_spots.to_file("outputs/cool_spots.gpkg", layer="cool_spots", driver="GPKG")

cool_spots_filtered = cool_spots[cool_spots.area > min_area]
cool_spots_filtered.to_file("outputs/cool_spots_filtered.gpkg", layer="cool_spots_filtered", driver="GPKG")

print(f"Successfully downloaded {len(cool_spots)} forest features from OSM.")

# --------------------------------------------
# 4. Generate Distance Buffers and Differences

# 1. Create the master >300m buffer difference layer
buffer = cool_spots.buffer(max_distance)
buffer.to_file("outputs/buffer.gpkg", layer="buffer", driver="GPKG")

diff = gpd.GeoDataFrame(geometry=[city_gdf.union_all().difference(buffer.union_all())], crs=target_crs)
diff.to_file("outputs/diff.gpkg", layer="diff", driver="GPKG")

# 2. Create the internal rings (0-75m, 75-150m, 150-225m, 225-300m)
intervals = [0, 75, 150, 225, 300]
buffer_layers = {}

# Pre-calculate the dissolved geometries for clean mathematical differences
buffers = {dist: cool_spots.buffer(dist).union_all() for dist in intervals}

for i in range(len(intervals) - 1):
    inner_dist = intervals[i]
    outer_dist = intervals[i+1]
    label = f"{inner_dist}m-{outer_dist}m"
    
    # Difference of the outer buffer from the inner buffer
    ring_geom = buffers[outer_dist].difference(buffers[inner_dist])
    
    # Clip it to the city boundary
    # clipped_ring = ring_geom.intersection(city_gdf.union_all())
    
    # buffer_layers[label] = gpd.GeoDataFrame(geometry=[clipped_ring], crs=target_crs)
    buffer_layers[label] = gpd.GeoDataFrame(geometry=[ring_geom], crs=target_crs)
    buffer_layers[label].to_file(f"outputs/diff_{label}.gpkg", layer="diff", driver="GPKG")

print("Buffer intervals and spatial differences calculated successfully.")
