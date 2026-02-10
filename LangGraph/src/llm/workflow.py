from langgraph.graph import StateGraph, END
from langgraph.graph.message import MessagesState
from langchain_ollama import ChatOllama

from langchain_core.messages import SystemMessage
from llm.tools.mcp_client import load_mcp_tools
from langchain.agents import create_agent

llm = ChatOllama(
    model="llama3.2:3b",
    temperature=0,
    base_url="http://localhost:11434",
    streaming=False,
    num_predict=500,
    reasoning=False,
    keep_alive="10m",
)

SYSTEM_MESSAGE = (
    "You may call tools to perform operations. "
    "Do NOT explain, interpret, or summarize tool outputs. "
    "If a tool returns JSON containing a field named 'geometry', "
    "you MUST ignore that field completely and never reference, repeat, "
    "or describe its contents. "
    "Only acknowledge the operation using the 'Result' field if present. "
    "Only respond to the user request directly."
)



async def agent_node(state):
    mcp_tools = await load_mcp_tools()

    agent = create_agent(llm, mcp_tools, system_prompt=SYSTEM_MESSAGE)

    messages = [
        *state["messages"],
    ]

    result = await agent.ainvoke({"messages": messages})

    # TODO: Takes ages to process, even after receiving tool result. Why?
    # TODO Append tool result to state for future reference and return values.
    return {
        "messages": result["messages"]
    }

graph = StateGraph(MessagesState)

graph.add_node("agent", agent_node)
graph.set_entry_point("agent")
graph.add_edge("agent", END)

compiled_graph = graph.compile(
)

