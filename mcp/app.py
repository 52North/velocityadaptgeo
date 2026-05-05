from fastmcp import FastMCP
import tools.buffer
import tools.geocoder
import tools.regbez
import tools.point_in_polygon


mcp = FastMCP(name="geometry")

mcp.add_tool(
    tools.geocoder.geocode
)

mcp.add_tool(
    tools.buffer.buffer_geometry
)

mcp.add_tool(
   tools.regbez.search_district
)

mcp.add_tool(
   tools.point_in_polygon.check_point_in_polygon
)

#mcp.add_tool(
 #   tools.geocoder.reverse_geocode
#)

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8001)
