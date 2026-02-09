from langgraph.graph import StateGraph, END
from langgraph.graph.message import MessagesState
from langchain_ollama import ChatOllama

from langchain_core.messages import SystemMessage
from llm.tools.mcp_client import load_mcp_tools
from langchain.agents import create_agent

llm = ChatOllama(
    model="llama3.2:3b",
    temperature=0.4,
    base_url="http://localhost:11434",
    streaming=False,
)

BUFFER_TOOL_SYSTEM_PROMPT = """
You have access to a tool called `buffer_geometry`.

This tool buffers a GeoJSON geometry by a numeric distance.

RULES (always follow these exactly):
- Always call `buffer_geometry` when the user asks to buffer, expand, grow, or create a buffer around a geometry.
- The `geometry` argument MUST be a raw GeoJSON geometry object.
- The `geometry` argument MUST contain a "type" such as "Point", "LineString", "Polygon", or similar.
- The `distance` argument MUST be a plain number.
- Do NOT pass strings for distance.
- Do NOT wrap values in objects like { "type": "...", "value": "..." }.
- Do NOT pass JSON Schema objects.
- Do NOT pass Feature or FeatureCollection objects unless explicitly requested.
- The tool returns a raw GeoJSON geometry object.

CORRECT EXAMPLE:

{
  "tool": "buffer_geometry",
  "arguments": {
    "geometry": {
      "type": "Point",
      "coordinates": [0, 0]
    },
    "distance": 10
  }
}

IMPORTANT OUTPUT NOTE:
- If the user wants a Feature or FeatureCollection, wrap the geometry yourself AFTER receiving the tool result.
"""

async def agent_node(state):
    mcp_tools = await load_mcp_tools()

    agent = create_agent(llm, mcp_tools)

    messages = [
        SystemMessage(content=BUFFER_TOOL_SYSTEM_PROMPT),
        *state["messages"],
    ]

    print(messages)

    result = await agent.ainvoke({"messages": messages})
    # TODO: Invokes correctly, but never returns a result. Need to debug why the agent isn't returning tool results properly.
    print("Agent result:", result)

    return {
        "messages": result["messages"]
    }

graph = StateGraph(MessagesState)

graph.add_node("agent", agent_node)
graph.set_entry_point("agent")
graph.add_edge("agent", END)

compiled_graph = graph.compile(
)

