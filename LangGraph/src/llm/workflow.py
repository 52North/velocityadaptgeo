from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage,  ToolMessage
from langchain.agents import create_agent
from src.llm.tools.mcp_client import load_mcp_tools
from typing import TypedDict, Sequence, Annotated, Optional, Any
import json

from langchain_anthropic import ChatAnthropic
import os
import json
import re

from dotenv import load_dotenv

# override=True forces reloading of variables from the .env file
load_dotenv(override=True)

llm = ChatAnthropic(
    model="claude-haiku-4-5-20251001",
    temperature=0,
    api_key=os.environ.get("ANTHROPIC_API_KEY"),
    streaming=True,
    max_retries=3
)

def all_tool_messages(messages):
    return [m for m in (messages or []) if isinstance(m, ToolMessage)]

def serialize_tool_messages(messages) -> str:
    tool_msgs = [m for m in (messages or []) if isinstance(m, ToolMessage)]
    packed = []
    for tm in tool_msgs:
        item = {"tool": getattr(tm, "name", None)}
        # Prefer structured artifacts if present
        art = getattr(tm, "artifact", None) or {}
        if isinstance(art, dict) and "structured_content" in art:
            item["structured_content"] = art["structured_content"]
        else:
            item["content"] = tm.content
        packed.append(item)

    return json.dumps(packed, ensure_ascii=False, indent=2)

class WorkflowState(TypedDict, total=False):
    messages: Annotated[Sequence, add_messages]

    # planning/execution bookkeeping
    plan: list[dict]                 # ordered steps from manager
    current_step: int                # index into plan
    next_action: str                 # router decision

    tools_meta: list[dict]

    # optional tracking/debug
    decision_history: list
    tool_chain: list                 # tool calls made in latest agent run
    current_context: dict            # free-form context between steps

async def tool_registry_node(state: WorkflowState) -> WorkflowState:
    mcp_tools = await load_mcp_tools()

    # Keep only metadata that helps planning (no executable objects stored in state)
    tools_meta = []
    for t in mcp_tools:
        # Try to capture args schema where possible (varies by tool implementation)
        args_schema = None
        if hasattr(t, "args_schema") and t.args_schema:
            try:
                args_schema = t.args_schema.model_json_schema()
            except Exception:
                args_schema = str(t.args_schema)

        tools_meta.append({
            "name": getattr(t, "name", type(t).__name__),
            "description": getattr(t, "description", "") or "",
            "args_schema": args_schema,  # may be None
        })

    decision_history = state.get("decision_history", [])
    decision_history.append({
        "node": "tool_registry_node",
        "tools_available": [tm["name"] for tm in tools_meta],
        "reasoning": "Loaded MCP tools and stored metadata for planning/execution."
    })

    return {
        "tools_meta": tools_meta,
        "decision_history": decision_history,
        "next_action": "plan",
    }


MANAGER_SYSTEM = """You are a workflow manager for a geospatial assistant.
You plan steps but you NEVER execute tools.

A critical is the spatial correctness of the answer, so you MUST rely on the provided tools for any geospatial analysis, including geocoding, spatial queries, and geometry processing.
The Geocoder should always be the first step.

Rules:
- You must plan using ONLY the tools listed under AVAILABLE_TOOLS.
- Each step must be one logical action executable in one agent pass.
- Any step that requires geometry (buffer, intersect, distance, etc.) MUST come AFTER geometry has been produced by geocoding or provided explicitly.
- Each step must be one logical action executable in one agent pass.
- Prefer: geocode -> analyze/retrieve -> answer.
- Output only valid JSON without any explanation. This is IMPORTANT and MUST be followed strictly.
- Do not include coordinates in the plan, as they are to be taken from the message context.

Output:
{
  "plan": [
    {
      "name": "...",
      "instruction": "...",
      "expected_tools": ["..."]
    },
    {
      "name": "...",
      "instruction": "...",
      "expected_tools": ["..."]
    }
  ]
}
"""

async def management_node(state: WorkflowState) -> WorkflowState:
    messages = state.get("messages", [])
    tools_meta = state.get("tools_meta", [])

    latest_user = None
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            latest_user = m.content
            break

    if not latest_user:
        return {"next_action": "end", "plan": [], "current_step": 0}

    tools_blob = json.dumps(tools_meta, indent=2)

    prompt = [
        SystemMessage(content=MANAGER_SYSTEM),
        HumanMessage(content=f"""AVAILABLE_TOOLS (use only these):
        {tools_blob}

        User request:
        {latest_user}

        Create the plan JSON now.""")
    ]

    resp = await llm.ainvoke(prompt)

    text = resp.content.strip()
    def parse_llm_json(text: str):
        text = text.strip()

        # remove any markdown fences
        text = re.sub(r"```json", "", text)
        text = re.sub(r"```", "", text)

        # extract JSON object only
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None

        return json.loads(match.group(0))


    data = parse_llm_json(resp.content)
    plan = data.get("plan", []) if data else []

    decision_history = state.get("decision_history", [])
    decision_history.append({
        "node": "management_node",
        "plan": plan,
        "reasoning": "Created ordered plan constrained to AVAILABLE_TOOLS."
    })

    return {
        "plan": plan,
        "current_step": 0,
        "next_action": "run_step" if plan else "end",
        "decision_history": decision_history,
    }

async def agent_node(state: WorkflowState) -> WorkflowState:
    messages = state.get("messages", [])
    plan = state.get("plan", [])
    current_step = int(state.get("current_step", 0))

    if current_step >= len(plan):
        return {"next_action": "done"}

    step = plan[current_step]
    step_name = step.get("name", f"step_{current_step}")
    step_instruction = step.get("instruction", "")
    expected_tools = step.get("expected_tools", [])

    print(f"[AGENT_NODE] Executing step {current_step+1}/{len(plan)}: {step_name}")
    print(f"[AGENT_NODE] Step instruction: {step_instruction}")

    mcp_tools = await load_mcp_tools()
    tool_names = [t.name for t in mcp_tools]
    print(f"[AGENT_NODE] Available tools: {tool_names}")

    AGENT_SYSTEM_MESSAGE = f"""You are a geospatial analysis assistant.
        You MUST execute ONLY the current step described below.

        Available tools: {[t.name for t in mcp_tools]}
        Current step instruction: {step_instruction}

        Rules:
        - Wait for the tool result, before fetching the next tool.
        - If tools are needed, call them. Tool calling happens here.
        - Do NOT plan additional future steps. Do NOT execute other steps.
        - Use prior tool outputs already present in the conversation messages/state.
        - After completing this step, respond with the minimal necessary result for this step.

        Ignore structured content when answering to the user, but use it when calling tools.
        Make sure that the provided dictionary content is correctly formatted for tool calls (e.g. correct keys/values as per tool schema).
        """

    agent = create_agent(llm, mcp_tools, system_prompt=AGENT_SYSTEM_MESSAGE, )
    print(f"[AGENT_NODE] Invoking agent with current_instruction: {step_instruction}")

    agent_input = [
        SystemMessage(content=AGENT_SYSTEM_MESSAGE),
        *messages,
        HumanMessage(content=step_instruction),
    ]

    result = await agent.ainvoke({
        "messages": agent_input
    })

    print(f"[AGENT_NODE] Agent result: {result}")
    # collect tool calls made in this step (for logging)
    tool_calls_made = []
    for msg in result["messages"]:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            tool_calls_made.extend(msg.tool_calls)

    decision_history = state.get("decision_history", [])
    decision_history.append({
        "node": "agent_node",
        "step": {"index": current_step, "name": step_name},
        "tool_calls": tool_calls_made,
        "reasoning": "Executed exactly one planned step."
    })

    next_step = current_step + 1
    next_action = "run_step" if next_step < len(plan) else "done"

    return {
        "messages": result["messages"],
        "decision_history": decision_history,
        "tool_chain": tool_calls_made,
        "current_step": next_step,
        "next_action": next_action,
        "current_context": state.get("current_context", {}),
    }

def router(state: WorkflowState) -> str:
    return state.get("next_action", "end")


graph = StateGraph(WorkflowState)
graph.add_node("tool_registry", tool_registry_node)
graph.add_node("manager", management_node)
graph.add_node("agent", agent_node)

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
        "run_step": "agent",  # keep executing next logical step
        "done": END,          # plan complete
        "end": END,
    },
)

compiled_graph = graph.compile()
