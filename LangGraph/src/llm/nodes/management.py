import asyncio
import json
import logging
import os
import re

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage

from src.llm.nodes._helpers import _for_prompt
from src.llm.state.graph import CONFIG_KEYS
from src.llm.state.state import WorkflowState
from src.llm.tools.laya_client import shadow_next_action

logger = logging.getLogger(__name__)

load_dotenv(override=True)

ALLOWED_ACTIONS = ("search", "build", "validate", "chat", "done")

MAX_WORKFLOW_ITERATIONS = int(os.environ.get("MAX_WORKFLOW_ITERATIONS", "16"))

# Unset: Haiku decides alone. "laya-shadow": Laya also picks next_action, logged as `laya` next
# to Haiku's decision; Haiku still routes (metrics/.docs/laya_finetune_plan.md).
DECISION_MODELS = ("", "laya-shadow")
DECISION_MODEL = os.environ.get("DECISION_MODEL", "")
if DECISION_MODEL not in DECISION_MODELS:
    raise ValueError(f"DECISION_MODEL must be unset or one of {', '.join(DECISION_MODELS[1:])}, not {DECISION_MODEL!r}")


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
- Write each search query from the USER GOAL, not from the catalog. Name the operation
  and the form of result the goal asks for ("noise zones every 50 m out to 200 m from
  a motorway", not just "a buffer"), plus the inputs it works on. Do NOT copy
  implementation details - projections, algorithms, libraries, data sources - from the
  descriptions in RECENT CANDIDATE PROCESSES: those describe how one process works,
  and a query that demands them rejects every other process that does the same job.
- The graph is never discarded. It only ever grows or is edited: a new message
  extends or corrects what is already there ("now also buffer that result", "drop the
  second step"). If the user moves on to a different task, add its capabilities to the
  existing graph rather than starting over - removing nodes is an explicit "build" op
  the user has to ask for.
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


def decision_state(state: WorkflowState, goal: str) -> dict:
    """What the manager sees when it picks `next_action`, compacted for a small decision model.

    Logged as `state` with each manager decision: the input side of a training row for Laya,
    with the action picked as its label (metrics/.docs/laya_finetune_plan.md). Process ids,
    config values and port names only, no descriptions, to fit Laya's ~1k-token context.
    """
    graph = state.get("workflow_graph") or {"nodes": [], "edges": []}
    validation = state.get("last_validation")
    iteration = state.get("iteration", 0)
    return {
        "goal": goal,
        "graph": {
            "nodes": [
                {
                    "id": n.get("id"),
                    "type": n.get("type"),
                    "config": {k: v for k, v in (n.get("config") or {}).items() if k not in CONFIG_KEYS},
                    "inputs": n.get("inputs", []),
                    "outputs": n.get("outputs", []),
                }
                for n in graph.get("nodes", [])
            ],
            "edges": [
                f"{e.get('source')}.{e.get('source_output')} -> {e.get('target')}.{e.get('target_input')}"
                for e in graph.get("edges", [])
            ],
        },
        "candidates": [
            {"process": c.get("tool") or c.get("process_id"), "similarity": c.get("similarity")}
            for c in state.get("candidate_processes") or []
        ],
        "validation": validation and {"valid": validation.get("valid"), "errors": validation.get("errors", [])},
        "unmet": [u.get("capability") for u in state.get("unmet_capabilities") or []],
        "recent": [_recent(e) for e in state.get("decision_history", [])[-3:]],
        "iteration": f"{iteration + 1}/{state.get('max_iterations', MAX_WORKFLOW_ITERATIONS)}",
    }


def _recent(entry: dict) -> dict:
    """One `decision_history` entry as the gist a decision model needs: who acted, and how it went."""
    node, instruction = entry.get("node"), entry.get("instruction")
    if node == "management_node":
        step = entry.get("step")
        return {"node": node, "action": entry.get("current_action"),
                "step": step.get("name") if isinstance(step, dict) else None}
    if node == "auto_build" and isinstance(instruction, dict):
        return {"node": node, "process": instruction.get("process_id"),
                "performs_capability": instruction.get("performs_capability"), "error": entry.get("error")}
    if isinstance(instruction, dict):
        instruction = instruction.get("op")
    elif isinstance(instruction, str):
        instruction = instruction[:200]  # a search query; the responder's is the whole goal again
    return {"node": node, "instruction": instruction, "error": entry.get("error")}


async def management_node(state: WorkflowState, llm) -> dict:
    """Plan the next action for the current user goal.

    The graph built so far is never cleared here: it survives every turn and is only
    changed by an explicit build op, so nothing the manager decides can silently
    discard work the user can still see on the canvas.
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
    # Not capped: the pgvector search already returns its top 5, the mcp variant shows every tool.
    candidates_blob = json.dumps(candidate_processes, indent=2)
    validation_blob = json.dumps(last_validation, indent=2) if last_validation else "null"
    last_decisions = json.dumps(_for_prompt(decision_history[-3:]), indent=2)

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

    seen = decision_state(state, latest_user)
    laya = None
    try:
        if DECISION_MODEL == "laya-shadow":
            # Side by side, so the shadow call adds no wall time.
            resp, laya = await asyncio.gather(llm.ainvoke(prompt), shadow_next_action(seen))
        else:
            resp = await llm.ainvoke(prompt)
    except Exception as exc:
        # End the turn: the responder then explains the failure instead of the stream just stopping.
        logger.exception("Manager failed to plan the next action")
        decision_history.append({
            "node": "management_node",
            "iteration": iteration + 1,
            "current_action": "done",
            "step": None,
            "reasoning": f"The manager LLM call failed, so the turn ends here: {exc}",
            "error": str(exc),
            "state": seen,
        })
        return {
            "current_action": "done",
            "step": None,
            "iteration": iteration + 1,
            "decision_history": decision_history,
        }
    data = parse_llm_json(resp.text) or {}

    next_action = data.get("next_action", "done")
    if next_action not in ALLOWED_ACTIONS:
        next_action = "done"

    # The retriever and builders read `step` as a dict; a bare string is the instruction alone.
    step = data.get("step")
    if isinstance(step, str):
        step = {"name": "", "instruction": step}
    elif not isinstance(step, dict):
        step = None
    reasoning = data.get("reasoning", "")

    decision_history.append({
        "node": "management_node",
        "iteration": iteration + 1,
        "current_action": next_action,
        "step": step,
        "reasoning": reasoning or "No reasoning provided by LLM.",
        "state": seen,
    })
    if laya is not None:
        decision_history[-1]["laya"] = laya

    update = {
        "current_action": next_action,        # "search" | "build" | "validate" | "done"
        "step": step,                         # single step object (or None)
        "iteration": iteration + 1,
        "decision_history": decision_history,
    }

    return update
