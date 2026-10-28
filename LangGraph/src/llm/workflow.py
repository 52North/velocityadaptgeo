import os
from functools import partial

from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.llm.nodes import (
    action_router,
    auto_build_node,
    builder_node,
    catalog_retriever_node,
    chat_node,
    management_node,
    mcp_retriever_node,
    responder_node,
    retriever_node,
    validator_node,
)
from src.llm.nodes.management import MAX_WORKFLOW_ITERATIONS
from src.llm.state.state import WorkflowState
from src.llm.variants import Variant, selected_variant

_SUPERSTEPS_PER_ITERATION = 3
_TRAILING_SUPERSTEPS = 5

WORKFLOW_RECURSION_LIMIT = int(os.environ.get(
    "WORKFLOW_RECURSION_LIMIT",
    str(MAX_WORKFLOW_ITERATIONS * _SUPERSTEPS_PER_ITERATION + _TRAILING_SUPERSTEPS),
))
DEFAULT_WORKFLOW_CONFIG = {"recursion_limit": WORKFLOW_RECURSION_LIMIT}

# How the retriever node finds candidate processes, by `Variant.tools`: a pgvector catalog search
# (top 5), every tool of the MCP server in `mcp/`, or every process of the catalog. Everything else
# in the graph is shared.
RETRIEVER_NODES = {"search": retriever_node, "mcp_all": mcp_retriever_node, "catalog_all": catalog_retriever_node}

llm = ChatAnthropic(
    model=os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5"),
    api_key=os.environ.get("ANTHROPIC_API_KEY"),
    streaming=True,
    max_retries=int(os.environ.get("ANTHROPIC_MAX_RETRIES", "3")),
    # Thinking is on by default and counts toward max_tokens; temperature is not settable on Haiku 5.5.
    max_tokens=int(os.environ.get("ANTHROPIC_MAX_TOKENS", "16000")),
    effort=os.environ.get("ANTHROPIC_EFFORT", "medium"),
)


def build_workflow(variant: Variant):
    """Compile the agent graph for one workflow variant (src.llm.variants)."""
    graph = StateGraph(WorkflowState)

    graph.add_node("manager",       partial(management_node, llm=llm, use_examples=variant.examples))
    graph.add_node("retriever",     partial(RETRIEVER_NODES[variant.tools], llm=llm))
    graph.add_node("auto_build",    partial(auto_build_node, llm=llm, variant=variant))
    graph.add_node("builder",       builder_node)
    graph.add_node("validator",     validator_node)
    graph.add_node("responder",     partial(responder_node,  llm=llm))
    graph.add_node("chat",          partial(chat_node,       llm=llm))

    graph.set_entry_point("manager")

    graph.add_conditional_edges(
        "manager",
        action_router,
        {
            "search":   "retriever",
            "build":    "builder",
            "validate": "validator",
            "chat":     "chat",
            "done":     "responder",
        },
    )

    graph.add_edge("retriever",  "auto_build")
    graph.add_edge("auto_build", "manager")

    graph.add_edge("builder",   "manager")
    graph.add_edge("validator", "manager")

    graph.add_edge("responder", END)
    graph.add_edge("chat",      END)

    return graph.compile(checkpointer=MemorySaver())


VARIANT = selected_variant()
compiled_graph = build_workflow(VARIANT)
