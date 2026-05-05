import os
import warnings
from fastmcp import FastMCP
from fastmcp.tools.tool import ToolResult
import httpx
from dotenv import load_dotenv
from models.result_models import GeoJSONResult

load_dotenv()
NOMINATIM_BASE_URL = os.getenv("NOMINATIM_BASE_URL", "http://localhost:8080")
if NOMINATIM_BASE_URL == "http://localhost:8080":
    warnings.warn(
        "NOMINATIM_BASE_URL is not set, using default: http://localhost:8080",
        UserWarning
    )

mcp = FastMCP(name="geometry")

@mcp.tool(
    name="geocode",
    description=(
        "This tool is for geocoding place names into latitude and longitude coordinates. \n"
        "- Do NOT provide GeoJSON manually."
        "- The tool returns structured geocoding results including lat/lon as a GeoJSON Point."
        "\n"
        "CORRECT USAGE EXAMPLE:\n"
        "{\n"
        "  \"query\": \"Berlin\"\n"
        "}"
    )
)
async def geocode(query: str) -> ToolResult:
    params = {"q": query, "format": "json", "limit": 1}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{NOMINATIM_BASE_URL}/search", params=params)

    if r.status_code != 200:
        return GeoJSONResult(
            message=f"Nominatim backend error: {r.status_code}",
            structured_content={}
        )

    data = r.json()
    print("Nominatim response data:", data)
    print("Query was:", params)
    
    if not data:
        return GeoJSONResult(
            message=f"Location '{query}' not found.",
            structured_content={}
        )

    first = data[0]
    lon = float(first.get("lon"))
    lat = float(first.get("lat"))
    
    geometry = {
        "type": "Point",
        "coordinates": [lon, lat]
    }
    
    return GeoJSONResult(
        message=f"Successfully geocoded '{query}'.",
        structured_content=geometry
    )


@mcp.tool(
    name="reverse_geocode",
    description=(
        "Converts latitude and longitude into a place description using Nominatim.\n"
        "RULES (must be followed exactly):"
        "- Always call this tool when the user provides coordinates and asks for a location name."
        "- `lat` MUST be a plain floating-point number."
        "- `lon` MUST be a plain floating-point number."
        "- Do NOT pass coordinates as strings."
        "- Do NOT wrap values in helper objects."
        "- The tool returns a GeoJSON Point representing the location."
        "\n"
        "CORRECT USAGE EXAMPLE:\n"
        "{\n"
        "  \"lat\": 52.52,\n"
        "  \"lon\": 13.405\n"
        "}"
    )
)
async def reverse_geocode(lat: float, lon: float) -> ToolResult:
    params = {"lat": lat, "lon": lon, "format": "json", "addressdetails": 1}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{NOMINATIM_BASE_URL}/reverse", params=params)

    if r.status_code != 200:
        return GeoJSONResult(
            message=f"Nominatim backend error: {r.status_code}",
            structured_content={}
        )

    data = r.json()
    if "error" in data:
         return GeoJSONResult(
            message=f"Reverse geocode failed: {data['error']}",
            structured_content={}
        )
        
    display_name = data.get("display_name", "Unknown Location")
    
    geometry = {
        "type": "Point",
        "coordinates": [lon, lat]
    }

    return GeoJSONResult(
        message=f"Successfully reverse geocoded coordinates to: {display_name}",
        structured_content=geometry
    )