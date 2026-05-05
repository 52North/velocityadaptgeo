from langgraph.graph import StateGraph, END
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import MemorySaver
import os
from dotenv import load_dotenv
from src.llm.state.state import WorkflowState
from src.llm.nodes import tool_registry_node, management_node, agent_node, router

# override=True forces reloading of variables from the .env file
load_dotenv(override=True)

llm = ChatAnthropic(
    model="claude-haiku-4-5-20251001",
    temperature=0,
    api_key=os.environ.get("ANTHROPIC_API_KEY"),
    streaming=True,
    max_retries=3
)


# Wrapper functions to pass llm to nodes
async def manager_node_wrapper(state):
    return await management_node(state, llm)

async def agent_node_wrapper(state):
    return await agent_node(state, llm)


graph = StateGraph(WorkflowState)
graph.add_node("tool_registry", tool_registry_node)
graph.add_node("manager", manager_node_wrapper)
graph.add_node("agent", agent_node_wrapper)

graph.set_entry_point("tool_registry")
graph.add_edge("tool_registry", "manager")

graph.add_conditional_edges(
    "manager",
    router,
    {
        "run_step": "agent",
        "end": END
    },
)

graph.add_conditional_edges(
    "agent",
    router,
    {
        "run_step": "agent",  
        "done": END,          
        "end": END,
    },
)

memory = MemorySaver()

compiled_graph = graph.compile(checkpointer=memory)
