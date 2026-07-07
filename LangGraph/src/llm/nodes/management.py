import json
import os
import re

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from src.llm.state.state import WorkflowState

load_dotenv(override=True)

llm = ChatAnthropic(
    model="claude-haiku-4-5-20251001",
    temperature=0,
    api_key=os.environ.get("ANTHROPIC_API_KEY"),
    streaming=True,
    max_retries=3,
)


ALLOWED_ACTIONS = ("search", "build", "validate", "chat", "done")


MANAGER_SYSTEM = """You are a workflow manager for a geospatial assistant.
You plan the NEXT STEP of an iterative graph-building process. You NEVER execute tools.

Your job is to build an OGC processing workflow GRAPH that, when executed, will
satisfy the user's goal. You do this incrementally: pick ONE next action, observe
the result, then plan again.

Available actions (choose exactly one each turn):
  - "search":   ask the retriever to query the OGC catalog for candidate
                processes that advance the goal. Use when the graph is missing
                a capability and you don't yet know which process provides it.
                NOTE: a successful search automatically adds the best-matching
                candidate to the workflow graph and validates it for you in the
                same turn - you do NOT need a separate "build"/"validate" step
                right after a search.
  - "build":    apply a deterministic mutation to the workflow graph
                (add another node, connect two existing nodes, remove a node).
                Use this only for manual follow-up edits on a later turn - e.g.
                wiring two already-built nodes together, or removing one -
                using process_id/server_url values already present in
                candidate_processes or workflow_graph.
  - "validate": run the graph validator to check for type mismatches,
                dangling inputs, or cycles. Use after a manual "build" edit, or
                before "done" if the graph was changed by hand.
  - "chat":     the user is making conversation, asking a general question,
                or asking for clarification/explanation that does NOT require
                searching the OGC catalog or building a workflow (e.g. "hi",
                "what can you do?", "what does a buffer process do?", follow-up
                questions about a previous answer). Answer directly instead of
                starting a search/build cycle.
  - "done":     the graph satisfies the user's goal AND validation passes.

Rules:
- Spatial correctness is critical. Always ensure geometry exists in the graph
  (via a geocoding process) BEFORE adding any node that consumes geometry
  (buffer, intersect, distance, etc.).
- Pick exactly ONE action per turn.
- Do not include literal coordinates or other concrete data values; those are
  resolved at execution time.
- Output ONLY valid JSON, no prose, no markdown fences.

Output schema:
{
  "next_action": "search" | "build" | "validate" | "done",
  "step": {
    "name": "short label",
    "instruction": <string OR object — see below>
  },
  "reasoning": "Short justification referencing the current graph state."
}

Instruction format per action:
- "search":   instruction is a STRING — a focused natural-language query.
              Example: "Find an OGC process that buffers a polygon by a distance in meters."
- "build":    instruction is an OBJECT with `op` and `args`:
                {"op": "add_node",    "args": {"process_id": "...", "server_url": "...", "inputs": {}}}
                {"op": "connect",     "args": {"from_node": "node_0", "from_output": "result",
                                               "to_node": "node_1", "to_input": "geometry"}}
                {"op": "remove_node", "args": {"node_id": "node_2"}}
              Use process_id and server_url values from prior search results.
- "validate": instruction is a STRING — a short justification, e.g. "Verify wiring before finalizing."
- "chat":     "step" may be null; the chat node answers from the conversation directly.
- "done":     "step" may be null.

Examples:

User goal: "Buffer the city of Munich by 500m."
Current graph has a geocoder node producing geometry for "Munich". Next action:
{
  "next_action": "search",
  "step": {"name": "find buffer", "instruction": "Find an OGC process that buffers a geometry by a distance."},
  "reasoning": "Geometry exists; need a buffer capability."
}

After search returns a 'buffer' process:
{
  "next_action": "build",
  "step": {
    "name": "add buffer node",
    "instruction": {"op": "add_node", "args": {"process_id": "buffer", "server_url": "https://example/ogcapi", "inputs": {"distance": 500}}}
  },
  "reasoning": "Add the buffer node so we can wire the geocoder output into it."
}
"""


def parse_llm_json(text: str):
    """Extract a JSON object from possibly fenced/markdown-wrapped LLM output."""
    text = text.strip()
    text = re.sub(r"```json", "", text)
    text = re.sub(r"```", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


async def management_node(state: WorkflowState, llm) -> dict:
    messages = state.get("messages", [])
    workflow_graph = state.get("workflow_graph", {"nodes": [], "edges": []})
    candidate_processes = state.get("candidate_processes", [])
    last_validation = state.get("last_validation")
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 15)
    decision_history = list(state.get("decision_history", []))

    # Find the user goal
    latest_user = None
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            latest_user = m.content
            break

    if not latest_user:
        return {"current_action": "done", "step": None, "iteration": iteration}

    # Hard stop on runaway loops
    if iteration >= max_iterations:
        decision_history.append({
            "node": "management_node",
            "current_action": "done",
            "reasoning": f"Reached max_iterations={max_iterations}; stopping.",
        })
        return {
            "current_action": "done",
            "step": None,
            "iteration": iteration,
            "decision_history": decision_history,
        }

    graph_blob = json.dumps(workflow_graph, indent=2)
    candidates_blob = json.dumps(candidate_processes[:5], indent=2)
    validation_blob = json.dumps(last_validation, indent=2) if last_validation else "null"
    last_decisions = json.dumps(decision_history[-3:], indent=2)

    prompt = [
        SystemMessage(content=MANAGER_SYSTEM),
        HumanMessage(content=f"""USER GOAL:
            {latest_user}

            CURRENT WORKFLOW GRAPH:
            {graph_blob}

            RECENT CANDIDATE PROCESSES (from last search, if any):
            {candidates_blob}

            LAST VALIDATION REPORT:
            {validation_blob}

            RECENT DECISIONS (for context, avoid repeating yourself):
            {last_decisions}

            ITERATION: {iteration + 1} / {max_iterations}

            Pick the single best next action and emit the JSON now.""")
    ]

    resp = await llm.ainvoke(prompt)
    data = parse_llm_json(resp.content) or {}

    next_action = data.get("next_action", "done")
    if next_action not in ALLOWED_ACTIONS:
        next_action = "done"

    step = data.get("step")
    reasoning = data.get("reasoning", "")

    decision_history.append({
        "node": "management_node",
        "iteration": iteration + 1,
        "current_action": next_action,
        "step": step,
        "reasoning": reasoning or "No reasoning provided by LLM.",
    })

    return {
        "current_action": next_action,        # "search" | "build" | "validate" | "done"
        "step": step,                         # single step object (or None)
        "iteration": iteration + 1,
        "decision_history": decision_history,
    }
