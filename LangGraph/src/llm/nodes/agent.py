from langchain.agents import create_agent
from langchain_core.messages import SystemMessage, HumanMessage
from src.llm.state.state import WorkflowState
from src.llm.tools.mcp_client import load_mcp_tools


async def agent_node(state: WorkflowState, llm) -> WorkflowState:
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
