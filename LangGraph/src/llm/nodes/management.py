import json
import logging
import os
import re

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from src.llm.state.state import WorkflowState

logger = logging.getLogger(__name__)

load_dotenv(override=True)

llm = ChatAnthropic(
    model="claude-haiku-4-5-20251001",
    temperature=0,
    api_key=os.environ.get("ANTHROPIC_API_KEY"),
    streaming=True,
    max_retries=3,
)


ALLOWED_ACTIONS = ("search", "build", "validate", "chat", "done")

MAX_WORKFLOW_ITERATIONS = int(os.environ.get("MAX_WORKFLOW_ITERATIONS", "12"))


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
                candidate to the workflow graph, wires it to the upstream node
                that feeds it, and validates it for you - you do NOT need a
                separate "build"/"validate" step right after a search.
                Control then returns to you, so search ONE capability per turn
                and keep searching on later turns until every capability the
                goal needs is present in the graph.
  - "build":    apply a deterministic mutation to the workflow graph
                (add or remove a node, connect or disconnect two ports, set a
                literal value on one input port, or swap two nodes' places in
                the chain).
                Use this only for manual follow-up edits on a later turn - e.g.
                wiring two already-built nodes together, or removing one -
                using process_id/server_url values already present in
                candidate_processes or workflow_graph.
  - "validate": run the graph validator to check for type mismatches,
                dangling inputs, or cycles. Use after a manual "build" edit, or
                before "done" if the graph was changed by hand.
  - "chat":     ONLY for messages that ask for nothing to be built: greetings
                ("hi"), questions about your own abilities ("what can you do?"),
                or a question purely about a previous answer ("why did you pick
                that one?"). Nothing else belongs here.
                If the newest user message describes a problem, task, outcome or
                analysis they want - in ANY phrasing, however plain, informal or
                non-technical, and even if it arrives as a follow-up in a long
                conversation - it is a GOAL, not chat: plan "search" and build
                the graph. Users describe problems in everyday words ("figure
                out the best spots for a project", "flag anything unusual in
                these ship tracks"); it is your job to recognise the geospatial
                capabilities behind that wording. NEVER answer a goal by
                describing in prose which process would suit it - build it.
  - "done":     the graph satisfies the user's goal AND validation passes.

Rules:
- EVERY capability in the graph is an OGC process found in the catalog - including
  geocoding. There are no built-in or implicit steps: if the goal names a place
  ("Munich", "the city centre") rather than supplying geometry, the graph needs a
  geocoding process node, and you find it with "search" exactly like any other.
- Spatial correctness is critical. Always ensure geometry exists in the graph
  (via a geocoding process node) BEFORE adding any node that consumes geometry
  (buffer, intersect, distance, etc.). So for a goal like "buffer Munich by 500m"
  the first search is for geocoding, and only the next one for buffering.
- Build the graph one capability at a time and only answer "done" once every
  capability the goal needs is present as a node.
- Judge whether the newest user message continues the graph already built or starts
  a fresh problem, and report it in "goal_scope". A graph must only ever contain the
  capabilities of ONE problem: if the user has moved on to a different task, answer
  "new" so the old nodes are cleared, then build the new graph from scratch. Answer
  "continue" only when the message extends or corrects the current graph ("now also
  buffer that result", "drop the second step").
- If the graph is UNCHANGED since your previous decision, do not repeat that
  decision - the capability was either already added or is not in the catalog.
  Search for a different capability, or answer "done" and let the final reply
  explain what is missing.
- UNMET CAPABILITIES below lists capabilities the catalog was already searched for
  and cannot supply; nothing was added to the graph for them. Never search one of
  those again, and never substitute a different process for one. Move on to the
  remaining capabilities, and answer "done" once only unmet ones are left - even if
  that leaves the graph empty. An honest "this cannot be built" is the correct
  outcome; a graph padded with processes that do something else is not.
- Pick exactly ONE action per turn.
- Do not include literal coordinates or other concrete data values; those are
  resolved at execution time.
- The pipeline ENDS with the finished graph. Nothing here executes a process, and
  there is no access to user files, uploads, datasets or credentials. Never plan a
  step that needs data from the user; if a required value is unknown, leave the
  input unset and let it be resolved at execution time.
- Output ONLY valid JSON, no prose, no markdown fences.

Output schema:
{
  "next_action": "search" | "build" | "validate" | "chat" | "done",
  "goal_scope": "new" | "continue",
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
                {"op": "add_node",         "args": {"process_id": "...", "server_url": "...", "inputs": {}}}
                {"op": "add_top_candidate", "args": {}}
                {"op": "connect",          "args": {"source": "node_0", "source_output": "result",
                                                     "target": "node_1", "target_input": "geometry"}}
                {"op": "remove_node",      "args": {"node_id": "node_2"}}
                {"op": "disconnect",       "args": {"source": "node_0", "source_output": "result",
                                                     "target": "node_1", "target_input": "geometry"}}
                {"op": "set_input",        "args": {"node_id": "node_1", "port": "distance", "value": 500}}
                {"op": "swap_nodes",       "args": {"node_a": "node_1", "node_b": "node_2"}}
              Use process_id and server_url values from prior search results.
              "add_top_candidate" needs no process_id/server_url - it deterministically
              adds the #1 ranked result from the most recent search (RECENT CANDIDATE
              PROCESSES below) as a new node.
- "validate": instruction is a STRING — a short justification, e.g. "Verify wiring before finalizing."
- "chat":     "step" may be null; the chat node answers from the conversation directly.
- "done":     "step" may be null.

Examples - one goal, across consecutive turns:

User goal: "Buffer the city of Munich by 500m."

Turn 1, graph is empty. The goal names a place, so geometry must be produced first:
{
  "next_action": "search",
  "step": {"name": "find geocoder", "instruction": "Find an OGC process that geocodes a place name into a geometry."},
  "reasoning": "Graph is empty and the goal names 'Munich'; geometry must exist before buffering."
}

Turn 2, the graph now holds a geocoding node (the search added and wired it):
{
  "next_action": "search",
  "step": {"name": "find buffer", "instruction": "Find an OGC process that buffers a geometry by a distance in meters."},
  "reasoning": "Geocoding node provides geometry; the buffer capability is still missing."
}

Turn 3, the graph holds the geocoding node feeding a buffer node and validation passed:
{
  "next_action": "done",
  "step": null,
  "reasoning": "Every capability the goal needs is present and wired, and validation reported no errors."
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
    """Plan the next action for the current user goal.

    On the first planning step of a turn the manager also judges whether the newest
    message starts a fresh problem; if so the previously built graph is cleared, so a
    graph never mixes the capabilities of two unrelated problems. Later steps of the
    same turn skip that check - the graph they are midway through building is the one
    being asked about.
    """
    messages = state.get("messages", [])
    workflow_graph = state.get("workflow_graph", {"nodes": [], "edges": []})
    candidate_processes = state.get("candidate_processes", [])
    last_validation = state.get("last_validation")
    unmet = state.get("unmet_capabilities", [])
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", MAX_WORKFLOW_ITERATIONS)
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

            UNMET CAPABILITIES (already searched, not in the catalog - do not retry):
            {json.dumps(unmet, indent=2)}

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
    starts_new_goal = iteration == 0 and data.get("goal_scope") == "new" and workflow_graph.get("nodes")

    decision_history.append({
        "node": "management_node",
        "iteration": iteration + 1,
        "current_action": next_action,
        "step": step,
        "goal_scope": "new" if starts_new_goal else "continue",
        "reasoning": reasoning or "No reasoning provided by LLM.",
    })

    update = {
        "current_action": next_action,        # "search" | "build" | "validate" | "done"
        "step": step,                         # single step object (or None)
        "iteration": iteration + 1,
        "decision_history": decision_history,
    }

    if starts_new_goal:
        logger.info("New goal detected; clearing the %d-node graph from the previous problem.",
                    len(workflow_graph.get("nodes", [])))
        update["workflow_graph"] = {"nodes": [], "edges": []}
        update["candidate_processes"] = []
        update["last_validation"] = None
        update["unmet_capabilities"] = []

    return update
