"""Codebase guide - an agent that explains a codebase the way a senior colleague would.

Drop-in usage: put this directory anywhere on the import path and import from it.

    from codebase_guide import GuideConfig, guide_router
    app.include_router(guide_router(GuideConfig.load("/path/to/repo")))

Every name is resolved lazily, so `import codebase_guide` costs nothing and works in an
environment with neither LangChain nor psycopg installed - `build_code_map` and
`architecture_digest` need only the standard library and PyYAML, which is what lets the
indexing step run in CI without the model stack.

The implementation lives in the `src` subpackage, matching the layout of the other
services in this repository; this module is the public surface, and importing from it
rather than from `codebase_guide.src` keeps consumers clear of internal moves.
"""

from importlib import import_module

__all__ = [
    "CodeMap",
    "Edge",
    "GuideConfig",
    "GuideIndex",
    "Symbol",
    "architecture_digest",
    "ask",
    "build_code_map",
    "build_guide_agent",
    "build_guide_tools",
    "guide_router",
    "open_index",
    "write_index",
]


def __getattr__(name: str):
    """Resolve a public name from `src` on first use. See the module docstring."""
    if name in __all__:
        return getattr(import_module(".src", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """List the public surface, since `__getattr__` hides it from introspection."""
    return sorted(__all__)
