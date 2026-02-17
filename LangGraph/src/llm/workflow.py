from langgraph.graph import StateGraph, END
from langgraph.graph.message import MessagesState
from langchain_ollama import ChatOllama

from langchain_core.messages import SystemMessage
from llm.tools.mcp_client import load_mcp_tools
from langchain.agents import create_agent

llm = ChatOllama(
    model="llama3.2:3b",
    temperature=0.1,
    base_url="http://localhost:11434",
    streaming=True,
    reasoning=False,
    keep_alive="10m",
)


async def agent_node(state):
    messages = state.get("messages", [])

    print(f"[AGENT_NODE] Input message: {messages[-1].content if messages else 'None'}")

    SYSTEM_MESSAGE = (
        "You are a geospatial analysis assistant. Your task is to analyze the request and call appropriate tools."
        "First resolve the location with the geocode tool, then use the resulting coordinates to perform any spatial analysis or data retrieval needed to answer the user's question."
        "Only answer to the users request directly and do not suggest other actions."
        "Ignore structured content when answering to the user, but use it when calling tools."
    )

    mcp_tools = await load_mcp_tools()
    print(f"[AGENT_NODE] Available tools: {[tool.name for tool in mcp_tools]}")

    agent = create_agent(llm, mcp_tools, system_prompt=SYSTEM_MESSAGE)

    result = await agent.ainvoke({"messages": messages})

    # Extract and display tool calls from the result
    print(f"\n[AGENT_NODE] Decision process:")
    for msg in result["messages"]:
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            print(f"  → Tool calls decided: {msg.tool_calls}")
        if hasattr(msg, 'name') and msg.name == 'tool':
            print(f"  → Tool result from {msg.name}: {msg.content}")

    return {
        "messages": result["messages"]
    }


async def geocode_agent_node(state):
    print("\n" + "="*80)
    print("[GEOCODE_AGENT] Starting geocoding step")
    print("="*80)

    messages = state.get("messages", [])
    user_input = messages[-1].content if messages else "None"
    print(f"[GEOCODE_AGENT] User input: {user_input}")

    SYSTEM_MESSAGE = (
        "You are a geocoding specialist. Your task is to:"
        "\n1. Extract the location name from the user request."
        "\n2. Use the geocode tool to find the latitude and longitude of that location."
        "\n3. Reformat the original question to include these exact coordinates."
        "\n4. Provide only the reformatted question with coordinates included."
        "\n\nBe precise with the location name and always include the coordinates in the reformatted question."
    )
    mcp_tools = await load_mcp_tools()
    geocode_tool = [tool for tool in mcp_tools if tool.name == "geocode"]
    print(f"[GEOCODE_AGENT] Using tools: {[tool.name for tool in geocode_tool]}")

    agent = create_agent(llm, geocode_tool, system_prompt=SYSTEM_MESSAGE)

    result = await agent.ainvoke({"messages": messages})

    # Extract and display tool calls and results
    print(f"\n[GEOCODE_AGENT] Decision process:")
    for i, msg in enumerate(result["messages"]):
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            for tool_call in msg.tool_calls:
                print(f"  → Tool call #{i}: {tool_call['name']}({tool_call['args']})")
        elif hasattr(msg, 'name') and msg.name == 'geocode':
            try:
                import json
                content = json.loads(msg.content[0]['text']) if isinstance(msg.content, list) else msg.content
                print(f"  → Tool result: {content}")
            except:
                print(f"  → Tool result: {msg.content}")
        elif hasattr(msg, 'content') and isinstance(msg.content, str):
            print(f"  → Response: {msg.content[:200]}..." if len(msg.content) > 200 else f"  → Response: {msg.content}")

    print("="*80 + "\n")

    return {
        "messages": result["messages"]
    }

graph = StateGraph(MessagesState)

graph.add_node("geocode_agent", geocode_agent_node)
graph.add_node("agent", agent_node)
graph.set_entry_point("agent")
#graph.add_edge("geocode_agent", "agent")
graph.add_edge("agent", END)

compiled_graph = graph.compile()

