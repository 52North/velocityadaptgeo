from pydantic import BaseModel
from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent
from geojson_pydantic.geometries import Geometry

class GeoJSONResult(BaseModel):
    message: str
    structured_content: Geometry

    def to_tool_result(self) -> ToolResult:
        return ToolResult(
            content=[TextContent(type="text", text=self.message)],
            structured_content=self.structured_content.model_dump(),
        )
