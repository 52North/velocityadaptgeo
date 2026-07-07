import os
from functools import partial

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.llm.nodes import (
    action_router,
    builder_node,
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
graph.add_node("builder",       builder_node)
graph.add_node("validator",     validator_node)
graph.add_node("responder",     partial(responder_node,  llm=llm))

graph.set_entry_point("manager")

graph.add_conditional_edges(
    "manager",
    action_router,
    {
        "search":   "retriever",
        "build":    "builder",
        "validate": "validator",
        "done":     "responder",
    },
)

graph.add_edge("retriever", "responder")
graph.add_edge("builder",   "manager")
graph.add_edge("validator", "manager")
graph.add_edge("responder", END)

compiled_graph = graph.compile(checkpointer=MemorySaver())
