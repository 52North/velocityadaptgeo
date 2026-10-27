"""The workflow variants: how the agent is given the processes it builds the workflow graph from.

This is the single list of variants. The agent (`src.llm.workflow`), the batch runs (`src.batch`),
the metrics (`src.metrics`) and the reports (`metrics/report/analysis.py`) all read it. A variant
only decides what the manager and auto_build are shown; the graph building loop, the validator and
the executor are the same for every variant (docs/modular-variants.md).

Standard library only: `src.batch --status` and metrics/report import this without the agent's
dependencies.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Variant:
    """One way of providing candidate processes (and solved examples) to the agent."""

    name: str
    # Plain name for reports.
    label: str
    # Which retriever node fills `candidate_processes` (see `RETRIEVER_NODES` in src.llm.workflow):
    # "search" ranks the catalog by the manager's query, "mcp_all" lists every MCP tool,
    # "catalog_all" lists every process of the catalog database.
    tools: str
    # The auto_build prompt's sentence on where the candidates come from.
    candidate_source: str
    # Whether candidates carry a `similarity` score that the auto_build prompt explains.
    similarity_hint: bool = False
    # Whether the solved examples closest to the request are shown to the manager and auto_build.
    examples: bool = False


DEFAULT_VARIANT = "pgvector"

VARIANTS: dict[str, Variant] = {
    v.name: v
    for v in (
        Variant(
            name="pgvector",
            label="catalog search",
            tools="search",
            candidate_source="""The candidates are the nearest
  vector matches, NOT a guarantee of fitness: the search always returns something, even
  when nothing in the catalog performs the requested operation. """,
            similarity_hint=True,
        ),
        Variant(
            name="mcp",
            label="all MCP tools",
            tools="mcp_all",
            candidate_source="""The candidates are every process
  tool the MCP server exposes, most of them unrelated to the capability. """,
        ),
        Variant(
            name="fewshot",
            label="whole catalog + examples",
            tools="catalog_all",
            candidate_source="""The candidates are every process
  in the catalog, most of them unrelated to the capability. """,
            examples=True,
        ),
    )
}


def selected_variant(name: str | None = None) -> Variant:
    """The variant named `name`, else by WORKFLOW_VARIANT, else the default; unknown names fail."""
    name = name or os.environ.get("WORKFLOW_VARIANT") or DEFAULT_VARIANT
    if name not in VARIANTS:
        raise ValueError(f"WORKFLOW_VARIANT must be one of {', '.join(VARIANTS)}, not {name!r}")
    return VARIANTS[name]
