"""Reference solution for the Münster cool-spots / green-space prompts.

    uv run --with geopandas --with osmnx python cool_spots.py [--min-area M2] [--intervals 0,75,150,225,300]
                                                              [--tags JSON] [--out outputs/reference.gpkg]

Writes one GeoPackage holding both answers, so either prompt can be graded against it:

    within   the city within `max(intervals)` of a qualifying green space (inclusions;
             the muenster_green_300m prompt)
    beyond   the rest of the city (exclusions; the CoolSpots prompt, "too far from green")
    rings    the distance bands between consecutive intervals, clipped to the city
    city, cool_spots (all OSM green spaces), cool_spots_filtered (area > min_area)

All layers are in the city's UTM zone. Next to it, `<out>.json` holds the parameters and
the area of each layer. `within` and `beyond` are complements within the city.

`fetch` (OSM download) and `reference` (geometry) are separate, so a sensitivity run over
several parameter sets downloads once.
"""

import argparse
import itertools
import json
from pathlib import Path

import geopandas as gpd
import osmnx as ox
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
        [7.4851106, 52.0054937],
    ]
)  # counter-clockwise
CITY_NAME = "muenster"
MIN_AREA = 4000  # in m²; large enough for recreation, a little below the 5000 m² the agents often pick
INTERVALS = [0, 75, 150, 225, 300]  # in m; the last one is the distance limit
TAGS = {"landuse": "forest", "natural": "wood", "leisure": "park"}


def fetch(
    city_name: str = CITY_NAME, tags: dict = TAGS
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """The city boundary and all its OSM green-space polygons, both in the city's UTM zone."""
    # Next to this file, not the working directory, so every caller shares one download.
    ox.settings.use_cache = True
    ox.settings.cache_folder = Path(__file__).parent / "cache"
    try:
        city_gdf_geogr = ox.geocode_to_gdf({"city": city_name})
    except Exception:  # noqa: BLE001 - geocoder down or name unknown: fall back to the bbox
        city_gdf_geogr = gpd.GeoDataFrame(geometry=[box(*bbox)], crs="EPSG:4326")
    target_crs = city_gdf_geogr.estimate_utm_crs()
    city = city_gdf_geogr[["geometry"]].to_crs(target_crs)

    osm_df = ox.features_from_polygon(city_gdf_geogr["geometry"].iloc[0], tags=tags)
    # Filter to polygons/multipolygons and project to UTM
    osm_df = osm_df[osm_df.geometry.type.isin(["Polygon", "MultiPolygon"])]
    cool_spots = osm_df[["geometry"]].reset_index(drop=True).to_crs(target_crs)
    return city, cool_spots


def reference(
    city: gpd.GeoDataFrame,
    cool_spots: gpd.GeoDataFrame,
    min_area: float = MIN_AREA,
    intervals: list = INTERVALS,
) -> dict[str, gpd.GeoDataFrame]:
    """Every layer of the answer, from `fetch`'s output (see the module docstring)."""
    crs = city.crs
    city_geom = city.union_all()
    cool_spots_filtered = cool_spots[cool_spots.area > min_area]

    # Dissolved buffers per distance, for clean differences between consecutive rings
    buffers = {dist: cool_spots_filtered.buffer(dist).union_all() for dist in intervals}
    rings = gpd.GeoDataFrame(
        {
            "label": [
                f"{inner:g}m-{outer:g}m"
                for inner, outer in itertools.pairwise(intervals)
            ],
            "inner_m": intervals[:-1],
            "outer_m": intervals[1:],
        },
        geometry=[
            buffers[outer].difference(buffers[inner]).intersection(city_geom)
            for inner, outer in itertools.pairwise(intervals)
        ],
        crs=crs,
    )

    coverage = buffers[intervals[-1]]
    return {
        "city": city,
        "cool_spots": cool_spots,
        "cool_spots_filtered": cool_spots_filtered,
        "rings": rings,
        "within": gpd.GeoDataFrame(
            geometry=[city_geom.intersection(coverage)], crs=crs
        ),
        "beyond": gpd.GeoDataFrame(geometry=[city_geom.difference(coverage)], crs=crs),
    }


def save(layers: dict[str, gpd.GeoDataFrame], out: Path, params: dict) -> dict:
    """Write every layer into one GeoPackage and the parameters and areas next to it."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(
        missing_ok=True
    )  # stale layers from another parameter set must not survive
    for name, gdf in layers.items():
        gdf.to_file(out, layer=name, driver="GPKG")
    meta = {
        **params,
        "crs": layers["city"].crs.to_string(),
        "counts": {
            "cool_spots": len(layers["cool_spots"]),
            "cool_spots_filtered": len(layers["cool_spots_filtered"]),
        },
        "area_m2": {
            name: round(layers[name].area.sum())
            for name in ("city", "within", "beyond")
        },
        "ring_area_m2": dict(
            zip(
                layers["rings"]["label"],
                layers["rings"].area.round().astype(int).tolist(),
            )
        ),
    }
    out.with_suffix(".json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--city", default=CITY_NAME)
    parser.add_argument(
        "--min-area", type=float, default=MIN_AREA, help="in m² (default %(default)s)"
    )
    parser.add_argument(
        "--intervals",
        default=",".join(map(str, INTERVALS)),
        help="ring bounds in m, ascending, from 0 (default %(default)s)",
    )
    parser.add_argument(
        "--tags",
        default=json.dumps(TAGS),
        help="OSM tags as JSON (default %(default)s)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path(__file__).parent / "outputs" / "reference.gpkg"
    )
    args = parser.parse_args()

    intervals = [float(d) for d in args.intervals.split(",")]
    if intervals[0] != 0 or intervals != sorted(set(intervals)) or len(intervals) < 2:
        parser.error("--intervals must start at 0 and ascend, e.g. 0,75,150,225,300")
    tags = json.loads(args.tags)

    city, cool_spots = fetch(args.city, tags)
    print(f"Downloaded {len(cool_spots)} green-space features from OSM.")
    layers = reference(city, cool_spots, args.min_area, intervals)
    meta = save(
        layers,
        args.out,
        {
            "city": args.city,
            "min_area": args.min_area,
            "intervals": intervals,
            "tags": tags,
        },
    )
    print(json.dumps(meta, indent=2))
    print(f"Written to {args.out}")


if __name__ == "__main__":
    main()
