import os
from functools import partial

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.llm.nodes import (
    action_router,
    auto_build_node,
    builder_node,
    chat_node,
    management_node,
    responder_node,
    retriever_node,
    tool_registry_node,
    validator_node,
)
from src.llm.state.state import WorkflowState

load_dotenv(override=True)

WORKFLOW_RECURSION_LIMIT = int(os.environ.get("WORKFLOW_RECURSION_LIMIT", "20"))
DEFAULT_WORKFLOW_CONFIG = {"recursion_limit": WORKFLOW_RECURSION_LIMIT}

llm = ChatAnthropic(
    model="claude-haiku-4-5-20251001",
    temperature=0,
    api_key=os.environ.get("ANTHROPIC_API_KEY"),
    streaming=True,
    max_retries=3,
)

graph = StateGraph(WorkflowState)

graph.add_node("manager",       partial(management_node, llm=llm))
graph.add_node("retriever",     partial(retriever_node,  llm=llm))
graph.add_node("auto_build",    partial(auto_build_node, llm=llm))
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

# A successful search is immediately turned into a graph node + validation
# report in one step, then summarized for the user - no extra manager turn.
graph.add_edge("retriever",  "auto_build")
graph.add_edge("auto_build", "responder")

# "build"/"validate" stay available for manual follow-up edits (connecting or
# removing nodes, re-validating after a manual edit).
graph.add_edge("builder",   "manager")
graph.add_edge("validator", "manager")

graph.add_edge("responder", END)
graph.add_edge("chat",      END)

compiled_graph = graph.compile(checkpointer=MemorySaver())
