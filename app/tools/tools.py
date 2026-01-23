import os
import httpx

PYGEOAPI_URL = os.getenv("PYGEOAPI_URL", "http://localhost:5000")


async def buffer_geometry(geometry: dict, distance: float) -> dict:
    """
    Buffers a GeoJSON geometry using pygeoapi OGC Process.
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

        data = response.json()
        return data["outputs"]["result"]
