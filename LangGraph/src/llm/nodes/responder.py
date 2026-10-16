import json
import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.llm.state.state import WorkflowState
from src.llm.nodes._helpers import _log

logger = logging.getLogger(__name__)


RESPONDER_SYSTEM = """You are a geospatial assistant speaking directly to the user.

The workflow-manager loop has finished (search/build/validate steps). Your job is to
write the final reply that goes back to the user, answering their ORIGINAL question.

What this system does and does not do:
- The ONLY deliverable is the workflow graph itself: OGC processes wired together as
  nodes and edges, ready to be executed later by a separate execution engine.
- This system does NOT execute processes, does NOT compute results, and has NO access
  to the user's files, uploads, datasets, credentials, or map layers.
- Concrete data (geometries, coordinates, file contents) is resolved at execution
  time, not here.

Rules:
- Address the user's actual question, not the internal process. Do not just restate
  raw tool/search output (process ids, similarity scores, JSON blobs).
- Summarize what was found or built in plain language: which OGC process(es) will be
  used, what the resulting workflow graph does, and any caveats from validation.
- Never ask the user to upload, attach, provide, or name files, datasets, layers,
  coordinates, API keys, or any other input data. Never ask a follow-up question whose
  answer this system could not act on.
- Never tell the user they "will need to supply" an input. Unresolved node inputs are
  filled in by the execution engine, so state them neutrally as open inputs of the
  graph (e.g. "the buffer node's geometry input is left open and bound at execution
  time"), not as a task for the user.
- Never offer to run, execute, or trigger the workflow, and never promise results,
  outputs, or downloads. Describe the graph that was produced instead.
- UNMET CAPABILITIES lists operations the user asked for that the catalog cannot
  perform. State plainly and unambiguously that these were NOT added to the graph and
  that the system cannot do them. Never describe an unmet capability as built,
  covered, handled or approximated, and never present the `closest_process` as a
  substitute for it - name it only as what was found instead, if at all.
- If the unmet list covers everything the user asked for, the honest answer is that
  no workflow could be built. Say that; do not soften it with a partial graph.
- If the loop stopped without a usable result (no candidates found, validation
  failed, max iterations reached), say so plainly and explain which capability is
  missing from the catalog.
- Do not invent process IDs, servers, or results that are not present in the context
  you were given.
- Be concise. No markdown fences, no JSON — just a natural-language answer.
"""


async def responder_node(state: WorkflowState, llm) -> dict:
    """Write the user-facing final answer describing the workflow graph that was built.

    Returns only the newly produced message. The `AIMessage` returned by the LLM is
    forwarded unchanged so that its id still matches the token chunks already emitted
    by `stream_mode="messages"`; rebuilding it (e.g. `AIMessage(content=resp.content)`)
    would produce an id-less message that LangGraph cannot deduplicate, and the answer
    would reach the frontend twice.
    """
    messages = state.get("messages", [])
    workflow_graph = state.get("workflow_graph", {"nodes": [], "edges": []})
    # Not capped: the pgvector search already returns its top 5, the mcp variant shows every tool.
    candidate_processes = state.get("candidate_processes", [])
    last_validation = state.get("last_validation")
    unmet = state.get("unmet_capabilities", [])
    decision_history = state.get("decision_history", [])

    latest_user = None
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            latest_user = m.content
            break

    prompt = [
        SystemMessage(content=RESPONDER_SYSTEM),
        HumanMessage(content=f"""USER'S ORIGINAL QUESTION:
{latest_user or "(none found)"}

FINAL WORKFLOW GRAPH:
{json.dumps(workflow_graph, indent=2)}

CANDIDATE PROCESSES CONSIDERED:
{json.dumps(candidate_processes, indent=2)}

LAST VALIDATION REPORT:
{json.dumps(last_validation, indent=2) if last_validation else "null"}

UNMET CAPABILITIES (asked for, but NOT in the catalog and NOT in the graph):
{json.dumps(unmet, indent=2)}

RECENT DECISIONS (for context on how we got here):
{json.dumps(decision_history[-5:], indent=2)}

Write the final answer to the user now."""),
    ]

    try:
        reply = await llm.ainvoke(prompt)
        answer = reply.text
    except Exception as exc:
        logger.exception("Responder failed to generate final answer")
        answer = f"I ran into an error while preparing the final answer: {exc}"
        reply = AIMessage(content=answer)

    return {
        "messages": [reply],
        "decision_history": _log(state, "responder", latest_user, answer),
    }
