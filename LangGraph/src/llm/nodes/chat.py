import logging

from langchain_core.messages import AIMessage, SystemMessage

from src.llm.state.state import WorkflowState
from src.llm.nodes._helpers import _log

logger = logging.getLogger(__name__)


CHAT_SYSTEM = """You are a geospatial assistant that helps users build OGC processing
workflows (e.g. geocoding, buffering, isochrones, viewshed analysis, ...).

The user is currently just talking to you: making conversation, asking a general
question, or asking for clarification — not asking you to search the OGC catalog or
build a workflow right now.

What this system does and does not do:
- The ONLY deliverable is a workflow graph: OGC processes wired together as nodes and
  edges, ready to be executed later by a separate execution engine.
- This system does NOT execute processes, does NOT compute results, and has NO access
  to the user's files, uploads, datasets, credentials, or map layers.
- Concrete data (geometries, coordinates, file contents) is resolved at execution
  time, not here.

Rules:
- Answer directly and conversationally, using the conversation so far for context.
- If asked what you can do, explain that you can search an OGC process catalog and
  assemble/validate a processing workflow graph to satisfy a geospatial task.
- Never ask the user to upload, attach, provide, or name files, datasets, layers,
  coordinates, or API keys, and never offer to run or execute a workflow.
- Do not invent specific process IDs, servers, or catalog contents you have not
  actually seen in this conversation.
- Keep it concise. No markdown fences, no JSON — just a natural-language reply.
"""


async def chat_node(state: WorkflowState, llm) -> dict:
    """Answer a conversational turn that needs no catalog search or graph mutation.

    Returns only the newly produced message, forwarding the LLM's own `AIMessage` so
    its id still matches the already-streamed token chunks - see `responder_node`.
    """
    messages = state.get("messages", [])

    prompt = [SystemMessage(content=CHAT_SYSTEM), *messages]

    try:
        reply = await llm.ainvoke(prompt)
        answer = reply.content
    except Exception as exc:
        logger.exception("Chat node failed to generate a reply")
        answer = f"I ran into an error while replying: {exc}"
        reply = AIMessage(content=answer)

    return {
        "messages": [reply],
        "decision_history": _log(state, "chat", None, answer),
    }
