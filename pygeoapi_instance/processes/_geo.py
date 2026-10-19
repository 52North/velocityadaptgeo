"""Shared geometry helpers for the cool-spots process chain.

The pygeoapi image ships shapely and pyproj but not geopandas, so the coordinate
handling the original CoolSpots script (now `metrics/grading/cool_spots.py`) got from GeoDataFrames is done
explicitly here: every process speaks GeoJSON in EPSG:4326 on the wire and projects to
a local UTM zone internally whenever it needs metres.
"""

from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform, unary_union

WGS84 = "EPSG:4326"


def utm_epsg_for(geom) -> str:
    """Return the UTM zone EPSG code covering a geometry's centroid.

    Replaces `GeoDataFrame.estimate_utm_crs()`. Buffers and areas must be computed in a
    projected CRS; Web Mercator would overstate distances by ~60% at Münster's latitude.
    """
    centroid = geom.centroid
    zone = int((centroid.x + 180) / 6) + 1
    return f"EPSG:{(32600 if centroid.y >= 0 else 32700) + zone}"


def projector(from_crs: str, to_crs: str):
    """Build a shapely-compatible coordinate transform between two CRS."""
    return Transformer.from_crs(from_crs, to_crs, always_xy=True).transform


def to_utm(geom, utm_epsg: str | None = None):
    """Project a WGS84 geometry into its local UTM zone, returning (geometry, epsg)."""
    utm_epsg = utm_epsg or utm_epsg_for(geom)
    return transform(projector(WGS84, utm_epsg), geom), utm_epsg


def to_wgs84(geom, utm_epsg: str):
    """Project a UTM geometry back to WGS84 for the response."""
    return transform(projector(utm_epsg, WGS84), geom)


def load_geometry(value):
    """Coerce any GeoJSON shape into a single shapely geometry.

    Accepts a bare geometry, a Feature, or a FeatureCollection so that a process can be
    wired to the output of any other process in the chain without a conversion step.
    """
    if not isinstance(value, dict):
        raise ValueError("expected a GeoJSON object")

    kind = value.get("type")
    if kind == "FeatureCollection":
        geoms = [shape(f["geometry"]) for f in value.get("features", []) if f.get("geometry")]
        if not geoms:
            raise ValueError("FeatureCollection contains no geometries")
        return unary_union(geoms)
    if kind == "Feature":
        return shape(value["geometry"])
    return shape(value)


def load_features(value):
    """Coerce any GeoJSON shape into a list of (geometry, properties) pairs."""
    if not isinstance(value, dict):
        raise ValueError("expected a GeoJSON object")

    kind = value.get("type")
    if kind == "FeatureCollection":
        return [
            (shape(f["geometry"]), dict(f.get("properties") or {}))
            for f in value.get("features", [])
            if f.get("geometry")
        ]
    if kind == "Feature":
        return [(shape(value["geometry"]), dict(value.get("properties") or {}))]
    return [(shape(value), {})]


def feature_collection(pairs) -> dict:
    """Build a GeoJSON FeatureCollection from (geometry, properties) pairs."""
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": mapping(geom), "properties": props}
            for geom, props in pairs
            if geom is not None and not geom.is_empty
        ],
    }


def explode_polygons(geom):
    """Yield the polygonal parts of a geometry, discarding lower-dimensional debris."""
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == "Polygon":
        yield geom
    elif geom.geom_type == "MultiPolygon":
        yield from geom.geoms
    elif geom.geom_type == "GeometryCollection":
        for part in geom.geoms:
            yield from explode_polygons(part)
