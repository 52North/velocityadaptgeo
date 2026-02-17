import os
import warnings
from dotenv import load_dotenv
from fastmcp import FastMCP
import httpx
from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent

load_dotenv()
PYGEOAPI_URL = os.getenv("PYGEOAPI_URL", "http://localhost:5000")

if PYGEOAPI_URL == "http://localhost:5000":
    warnings.warn("PYGEOAPI_URL is not set, using default: ", UserWarning)

mcp = FastMCP(name="geometry")

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
async def buffer_geometry(geometry: dict, distance: float) -> dict:
    """
    Delegates buffering to pygeoapi OGC API Processes.
    """

    payload = {
        "inputs": {
            "geometry": geometry,
            "distance": distance
        }
    }

    print("Sending request to pygeoapi with payload:", payload)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{PYGEOAPI_URL}/processes/buffer/execution",
            json=payload,
            headers={"Accept": "application/json"},
            timeout=30
        )
        response.raise_for_status()

    print("STATUS:", response.status_code)
    print("HEADERS:", response.headers)
    print("BODY:", repr(response.text))

    data = response.json()

    if "outputs" in data:
        result = data["outputs"].get("result")
    elif "result" in data:
        result = data["result"]
    else:
        raise RuntimeError(f"Unexpected pygeoapi response: {data}")

    return ToolResult(
        content=[
            TextContent(
                type="text",
                text="Geometry was successfully created."
            )
        ],
        structured_content=result,
    )
