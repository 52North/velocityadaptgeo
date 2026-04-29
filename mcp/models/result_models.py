from pydantic import BaseModel, field_validator
from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent
from geojson_pydantic.geometries import Geometry
from pydantic import TypeAdapter
import json

geometry_adapter = TypeAdapter(Geometry)


class GeoJSONResult(BaseModel):
    message: str
    structured_content: dict

    @field_validator("structured_content", mode="before")
    @classmethod
    def validate_geometry(cls, v):
        geom = geometry_adapter.validate_python(v)
        return json.loads(json.dumps(geom.model_dump(mode="json")))