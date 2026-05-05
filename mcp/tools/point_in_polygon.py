import json
import ast
from typing import Any
from fastmcp import FastMCP
from fastmcp.tools.tool import ToolResult
from models.result_models import GeoJSONResult
from shapely.geometry import shape

mcp = FastMCP(name="geometry")

@mcp.tool(
    name="check_point_in_polygon",
    description=(
        "Checks if a given GeoJSON Point is inside a given GeoJSON Polygon.\n"
        "RULES (must be followed exactly):\n"
        "- Always call this tool when the user asks to check if a point is inside, within, or intersects a polygon.\n"
        "- `point` MUST be a raw GeoJSON Point geometry object.\n"
        "- `polygon` MUST be a raw GeoJSON Polygon or MultiPolygon geometry object.\n"
        "- Returns a GeometryCollection containing both the point and the polygon."
    )
)
async def check_point_in_polygon(point: Any, polygon: Any) -> ToolResult:
    def parse_input(data: Any) -> dict:
        if isinstance(data, dict):
            return data
        if isinstance(data, str):
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return ast.literal_eval(data)
        raise ValueError(f"Unsupported input type: {type(data)}")

    try:
        pt_dict = parse_input(point)
        poly_dict = parse_input(polygon)

        pt_shape = shape(pt_dict)
        poly_shape = shape(poly_dict)
        
        is_inside = poly_shape.contains(pt_shape)
        
        merged_geometry = {
            "type": "GeometryCollection",
            "geometries": [poly_dict, pt_dict]
        }
        
        print(f"Check result: Point is {'inside' if is_inside else 'outside'}")
        
        return GeoJSONResult(
            message=f"Point is {'inside' if is_inside else 'outside'} the polygon.",
            structured_content=merged_geometry
        )
    except Exception as e:
        return GeoJSONResult(
            message=f"Error checking point in polygon: {e}",
            structured_content={
                "type": "GeometryCollection",
                "geometries": []
            }
        )