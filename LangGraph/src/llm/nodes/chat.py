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

Rules:
- Answer directly and conversationally, using the conversation so far for context.
- If asked what you can do, explain that you can search an OGC process catalog and
  assemble/validate a processing workflow graph to satisfy a geospatial task.
- Do not invent specific process IDs, servers, or catalog contents you have not
  actually seen in this conversation.
- Keep it concise. No markdown fences, no JSON — just a natural-language reply.
"""


async def chat_node(state: WorkflowState, llm) -> dict:
    messages = list(state.get("messages", []))

    prompt = [SystemMessage(content=CHAT_SYSTEM), *messages]

    try:
        resp = await llm.ainvoke(prompt)
        reply = resp.content
    except Exception as exc:
        logger.exception("Chat node failed to generate a reply")
        reply = f"I ran into an error while replying: {exc}"

    messages.append(AIMessage(content=reply))

    return {
        "messages": messages,
        "decision_history": _log(state, "chat", None, reply),
    }
