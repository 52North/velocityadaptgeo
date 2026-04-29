import os
import warnings
from dotenv import load_dotenv
from fastmcp import FastMCP
import httpx
from fastmcp.tools.tool import ToolResult

from geojson_pydantic.geometries import Geometry
from models.result_models import GeoJSONResult
from pydantic import TypeAdapter

load_dotenv()
PYGEOAPI_URL = os.getenv("PYGEOAPI_URL", "http://localhost:5000")

if PYGEOAPI_URL == "http://localhost:5000":
    warnings.warn("PYGEOAPI_URL is not set, using default: ", UserWarning)

mcp = FastMCP(name="geometry")

# Use TypeAdapter to safely parse dictionary responses into the Geometry Union
geometry_adapter = TypeAdapter(Geometry)

@mcp.tool(
    name="buffer_geometry",
    description=(
        "Creates a buffer around a GeoJSON geometry by a numeric distance."
        "RULES (must be followed exactly):"
        "- Always call this tool when the user asks to buffer, expand, grow, or create a buffer around a geometry."
        "- `geometry` MUST be a raw GeoJSON *geometry object*, not a Feature or FeatureCollection."
        "- `geometry` MUST contain a valid `type` such as Point, LineString, Polygon, etc."
        "- `distance` MUST be a plain number (meters)."
        "- Do NOT pass strings for distance."
        "- Do NOT wrap values in helper objects or JSON Schema objects."
        "- The tool returns a raw GeoJSON geometry object."
        "CORRECT USAGE EXAMPLE:\n"
        "{\n"
        "  \"geometry\": { \"type\": \"Point\", \"coordinates\": [0, 0] },\n"
        "  \"distance\": 10\n"
        "}"
    )
)
async def buffer_geometry(geometry: Geometry, distance: float) -> ToolResult:
    payload = {
        "inputs": {
            "geometry": geometry.model_dump(),
            "distance": distance
        }
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{PYGEOAPI_URL}/processes/buffer/execution",
            json=payload,
            headers={"Accept": "application/json"},
            timeout=30
        )
        response.raise_for_status()

    data = response.json()
    result_data = data.get("outputs", {}).get("result") or data.get("result")

    validated_result = GeoJSONResult(
        message="Geometry successfully created.",
        structured_content=geometry_adapter.validate_python(result_data)
    )

    return validated_result.to_tool_result()
