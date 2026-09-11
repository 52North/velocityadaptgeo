from fastmcp import FastMCP

import asyncio
import logging
import pkgutil
import importlib
import inspect
from fastmcp import FastMCP

from ogc_processes import register_ogc_tools

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
    logging.basicConfig(level=logging.INFO)
    asyncio.run(register_ogc_tools(mcp))
    mcp.run(transport="http", host="0.0.0.0", port=8001)
