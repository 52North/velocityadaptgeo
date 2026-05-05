import json
from fastmcp import FastMCP
from fastmcp.tools.tool import ToolResult
from models.result_models import GeoJSONResult
from shapely.geometry import shape

mcp = FastMCP(name="geometry")

@mcp.tool(
    name="check_point_in_polygon",
    description=(
        "Checks if a given GeoJSON Point is inside a given GeoJSON Polygon."
        "RULES (must be followed exactly):"
        "- Always call this tool when the user asks to check if a point is inside, within, or intersects a polygon."
        "- `point` MUST be a raw GeoJSON Point geometry object."
        "- `polygon` MUST be a raw GeoJSON Polygon or MultiPolygon geometry object."
        "- Returns a GeometryCollection containing both the point and the polygon."
    )
)
async def check_point_in_polygon(point: dict, polygon: dict) -> ToolResult:
    """
    Checks whether a point geometry is inside a polygon geometry and returns a merged GeometryCollection.
    """
    try:
        pt_shape = shape(point)
        poly_shape = shape(polygon)
        
        is_inside = poly_shape.contains(pt_shape)
        
        merged_geometry = {
            "type": "GeometryCollection",
            "geometries": [polygon, point]
        }
        
        print(f"Check result: Point is {'inside' if is_inside else 'outside'}")
        print("Merged Geometry:", json.dumps(merged_geometry, indent=2))
        
        return GeoJSONResult(
            message=f"Point is {'inside' if is_inside else 'outside'} the polygon.",
            structured_content=merged_geometry
        )
    except Exception as e:
        return GeoJSONResult(
            message=f"Error checking point in polygon: {e}",
            structured_content={}
        )