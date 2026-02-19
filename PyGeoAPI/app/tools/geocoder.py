import os
import warnings
from fastmcp import FastMCP
import httpx
from dotenv import load_dotenv

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
        "- The tool returns structured geocoding results including lat/lon."
        "\n"
        "CORRECT USAGE EXAMPLE:\n"
        "{\n"
        "  \"query\": \"Berlin\",\n"
        "}"
    )
)
async def geocode(query: str) -> dict:
    params = {"q": query, "format": "json", "limit": 1}  # only need the first result
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{NOMINATIM_BASE_URL}/search", params=params)

    if r.status_code != 200:
        raise RuntimeError(f"Nominatim backend error: {r.status_code}")

    data = r.json()
    print("Nominatim response data:", data)
    print("Query was:", params)
    if not data:
        return {"query": query, "lat": None, "lon": None}

    first = data[0]
    return {
        "query": query,
        "lat": float(first.get("lat")),
        "lon": float(first.get("lon"))
    }


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
        "- The tool returns structured location information."
        "\n"
        "CORRECT USAGE EXAMPLE:\n"
        "{\n"
        "  \"lat\": 52.52,\n"
        "  \"lon\": 13.405\n"
        "}"
    )
)
async def reverse_geocode(lat: float, lon: float) -> dict:
    params = {"lat": lat, "lon": lon, "format": "json", "addressdetails": 1}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{NOMINATIM_BASE_URL}/reverse", params=params)

    if r.status_code != 200:
        raise RuntimeError(f"Nominatim backend error: {r.status_code}")

    data = r.json()
    address = data.get("address", {})

    result = {
        "name": data.get("display_name"),
        "country": address.get("country"),
        "city": address.get("city") or address.get("town") or address.get("village"),
        "postcode": address.get("postcode"),
        "lat": float(data.get("lat")),
        "lon": float(data.get("lon")),
        "raw": data
    }

    return {"lat": lat, "lon": lon, "count": 1, "results": [result]}

# Just testing
if __name__ == "__main__":
    import asyncio
    asyncio.run(geocode("Muenster Bahnhof"))
