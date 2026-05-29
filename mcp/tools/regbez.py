import json
from fastmcp import FastMCP
from fastmcp.tools.tool import ToolResult
from models.result_models import GeoJSONResult

mcp = FastMCP(name="geometry")
import os
from pathlib import Path

DATABASE_FILE = os.path.join(os.path.dirname(__file__), "../data/gemeinden_simplify200.geojson")
@mcp.tool(
    name="search_district",
    description=(
        "Searches a local GeoJSON file database for a specific geographic district by its name, returning a polygon of said district."
        "RULES (must be followed exactly):"
        "- Always call this tool when the user asks to find, search, or retrieve a district by name."
        "- `query` MUST be a plain string representing the name of the location (e.g., 'Osnabrück')."
        "- The tool returns a raw GeoJSON Feature object."
    )
)
async def search_district(query: str) -> ToolResult:
    """
    Retrieves a feature from the FeatureCollection by matching the query against the 'GEN' property within the feature's properties[cite: 1].
    """
    try:
        with open(DATABASE_FILE, "r", encoding="utf-8") as f:
            database = json.load(f)
    except Exception as e:
        return GeoJSONResult(
            message=f"Error accessing database: {e}",
            structured_content={}
        )

    features = database.get("features", [])
    search_query = query.lower()
    
    result_geometry = None
    for feature in features:
        properties = feature.get("properties", {})
        feature_name = properties.get("GEN", "")
        
        if feature_name and feature_name.lower() == search_query:
            result_geometry = feature.get("geometry")
            break
            
    if result_geometry:
            print("Geometry result:", json.dumps(result_geometry, indent=2))
            return GeoJSONResult(
                message=f"Geometry for '{query}' successfully found.",
                structured_content=result_geometry
            )
        
    return GeoJSONResult(
        message=f"District '{query}' not found.",
        structured_content={}
    )