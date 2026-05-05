import json
import re
import os
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage
from src.llm.state.state import WorkflowState

# override=True forces reloading of variables from the .env file
load_dotenv(override=True)

llm = ChatAnthropic(
    model="claude-haiku-4-5-20251001",
    temperature=0,
    api_key=os.environ.get("ANTHROPIC_API_KEY"),
    streaming=True,
    max_retries=3
)

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


async def management_node(state: WorkflowState, llm) -> WorkflowState:
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
