import os
import httpx
from fastmcp import FastMCP

PYGEOAPI_URL = os.getenv("PYGEOAPI_URL", "http://localhost:5000")

# Create FastMCP server
mcp = FastMCP(
    name="geometry"
)

@mcp.tool(
    name="buffer_geometry",
    description="Buffer a GeoJSON geometry by a given distance"
)
async def buffer_geometry(geometry: dict, distance: float) -> dict:
    """
    Delegates buffering to pygeoapi OGC API – Processes.
    """
    payload = {
        "inputs": {
            "geometry": geometry,
            "distance": distance
        }
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{PYGEOAPI_URL}/processes/buffer/execution",
            json=payload,
            timeout=30
        )
        response.raise_for_status()

    return response.json()["outputs"]["result"]

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
