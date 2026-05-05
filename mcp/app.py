from fastmcp import FastMCP
import tools.buffer
import tools.geocoder
import tools.regbez
import tools.point_in_polygon


mcp = FastMCP(name="geometry")

#mcp.add_tool(
#    tools.geocoder.geocode
#)

#mcp.add_tool(
#    tools.buffer.buffer_geometry
#)

#mcp.add_tool(
#   tools.regbez.search_district
#)

#mcp.add_tool(
#   tools.point_in_polygon.check_point_in_polygon
#)

#mcp.add_tool(
 #   tools.geocoder.reverse_geocode
#)

import pkgutil
import importlib
import inspect
from fastmcp import FastMCP

mcp = FastMCP(name="geometry")

def register_all_tools(mcp_server: FastMCP, package_name: str):
    package = importlib.import_module(package_name)
    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package_name}.{module_name}")
        for name, obj in inspect.getmembers(module, inspect.isfunction):
            if obj.__module__ == module.__name__:
                mcp_server.add_tool(obj)

register_all_tools(mcp, "tools")

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8001)
