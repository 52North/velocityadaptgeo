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
    Delegates buffering to pygeoapi OGC API Processes.
    Uses simple GeoJson inputs.
    Expects distance in a format "distance": 100 (meters).
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
            headers={"Accept": "application/json"},
            timeout=30
        )
        response.raise_for_status()

    print("STATUS:", response.status_code)
    print("HEADERS:", response.headers)
    print("BODY:", repr(response.text))


    data = response.json()

    # Accept both pygeoapi styles
    if "outputs" in data:
        result = data["outputs"].get("result")
    elif "result" in data:
        result = data["result"]
    else:
        raise RuntimeError(f"Unexpected pygeoapi response: {data}")

    return result



if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8001)
