import json
import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.llm.state.state import WorkflowState
from src.llm.nodes._helpers import _log

logger = logging.getLogger(__name__)


RESPONDER_SYSTEM = """You are a geospatial assistant speaking directly to the user.

The workflow-manager loop has finished (search/build/validate steps). Your job is to
write the final reply that goes back to the user, answering their ORIGINAL question.

Rules:
- Address the user's actual question, not the internal process. Do not just restate
  raw tool/search output (process ids, similarity scores, JSON blobs).
- Summarize what was found or built in plain language: which OGC process(es) will be
  used, what the resulting workflow graph does, and any caveats from validation.
- If the loop stopped without a usable result (no candidates found, validation
  failed, max iterations reached), say so plainly and explain what's missing.
- Do not invent process IDs, servers, or results that are not present in the context
  you were given.
- Be concise. No markdown fences, no JSON — just a natural-language answer.
"""


async def responder_node(state: WorkflowState, llm) -> dict:
    messages = list(state.get("messages", []))
    workflow_graph = state.get("workflow_graph", {"nodes": [], "edges": []})
    candidate_processes = state.get("candidate_processes", [])
    last_validation = state.get("last_validation")
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
{json.dumps(candidate_processes[:5], indent=2)}

LAST VALIDATION REPORT:
{json.dumps(last_validation, indent=2) if last_validation else "null"}

RECENT DECISIONS (for context on how we got here):
{json.dumps(decision_history[-5:], indent=2)}

Write the final answer to the user now."""),
    ]

    try:
        resp = await llm.ainvoke(prompt)
        answer = resp.content
    except Exception as exc:
        logger.exception("Responder failed to generate final answer")
        answer = f"I ran into an error while preparing the final answer: {exc}"

    messages.append(AIMessage(content=answer))

    return {
        "messages": messages,
        "decision_history": _log(state, "responder", latest_user, answer),
    }
