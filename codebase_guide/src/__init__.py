"""Codebase guide: an agent that explains a codebase the way a senior colleague would.

Public surface:
    `GuideConfig`      - what repository to explain and how to index it.
    `build_code_map`   - extract symbols, doc comments and structure.
    `architecture_digest` - render a map as an orientation briefing.
    `write_index` / `open_index` - persist and reopen the searchable index.
    `build_guide_agent`, `ask` - the LangGraph agent that answers questions.
    `guide_router`     - a mountable FastAPI router.

`agent`, `index` and `api` are imported lazily via `__getattr__`, so extraction works in
an environment with no LangChain, psycopg or FastAPI installed - useful for indexing in
CI, and it means merely importing the package cannot fail on a missing extra.
"""

from .build import build_code_map
from .config import GuideConfig
from .digest import architecture_digest
from .model import CodeMap, Edge, Symbol

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

_LAZY = {
    "GuideIndex": ".index",
    "open_index": ".index",
    "write_index": ".index",
    "build_guide_tools": ".tools",
    "ask": ".agent",
    "build_guide_agent": ".agent",
    "guide_router": ".api",
}


def __getattr__(name: str):
    """Import the agent/index layers on first access. See module docstring."""
    if name in _LAZY:
        from importlib import import_module

        module = import_module(_LAZY[name], __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
