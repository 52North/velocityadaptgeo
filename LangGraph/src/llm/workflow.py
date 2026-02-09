from langgraph.graph import StateGraph, END
from langgraph.graph.message import MessagesState
from langchain_ollama import ChatOllama

from llm.tools.mcp_client import load_mcp_tools
from langchain.agents import create_agent

llm = ChatOllama(
    model="llama3.2:3b",
    temperature=0.7,
    base_url="http://localhost:11434",
    streaming=False,
)

async def agent_node(state):
    mcp_tools = await load_mcp_tools()

    agent = create_agent(llm, mcp_tools)

    result = await agent.ainvoke({"messages": state["messages"]})


    return {"messages": [result["output"]]}

graph = StateGraph(MessagesState)

graph.add_node("agent", agent_node)
graph.set_entry_point("agent")
graph.add_edge("agent", END)

compiled_graph = graph.compile()
