from langgraph.graph import StateGraph, END
from langgraph.graph.message import MessagesState
from langchain_ollama import ChatOllama

llm = ChatOllama(
    model="llama3.2:3b",
    temperature=0.7,
    base_url="http://localhost:11434",
    streaming=True,
)

async def agent_node(state):
    result = await llm.ainvoke(state["messages"])  # ✅ async
    return {"messages": [result]}

graph = StateGraph(MessagesState)

graph.add_node("agent", agent_node)
graph.set_entry_point("agent")
graph.add_edge("agent", END)

compiled_graph = graph.compile()
