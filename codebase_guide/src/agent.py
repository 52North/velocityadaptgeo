"""The guide agent: a LangGraph loop that answers questions about a codebase.

Deliberately a small graph - one reasoning node and a tool node, looping until the
model stops asking for lookups. The intelligence that matters here is in the index and
the tools, not in the control flow; a router with five specialised branches would add
failure modes without adding answers.

Two decisions worth knowing about:

* The architecture digest goes into the system prompt rather than being fetched by a
  tool. An agent that has to *discover* the layout tends to answer from the first three
  search hits, which is exactly the failure mode this module exists to avoid.
* The prompt insists on locations and on admitting undocumented code. A guide that
  invents plausible behaviour is worse than no guide, because a newcomer has no way to
  tell the difference.
"""

import logging
import os
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from .config import chat_model, max_answer_tokens
from .index import GuideIndex
from .tools import build_guide_tools

logger = logging.getLogger("codebase-guide")

SYSTEM_PROMPT = """You are a senior engineer on the {repo} codebase, walking a new \
colleague through it. You have worked here a long time: you know what each part is for, \
which pieces talk to each other, and where the surprises are.

How you answer:
- Explain the workflow, not just the API. When asked what something does, say what \
triggers it, what it hands off to, and where it ends up.
- Always name locations as `path/to/file.py:LINE` so they can open the code themselves.
- Answer at the level of the question. A newcomer asking "how does this work" wants the \
path through the system in a few steps; someone asking about one function wants that \
function.
- Look things up before answering. You have the architecture briefing below, but the \
tools have the details.
- Prefer `trace_flow` for "what happens when ..." questions. It follows the real wiring, \
including framework-level control flow that no single doc comment mentions.

What you must not do:
- Do not invent behaviour. Your knowledge comes from doc comments and extracted \
structure, never from reading function bodies. If something is undocumented, say so \
plainly - "no doc comment, here is where it lives and what calls it" is a useful answer; \
a confident guess is not.
- Do not claim two things are connected unless an edge or a doc comment says so.
- If the tools disagree with your expectations, trust the tools.

Architecture briefing
=====================
{digest}
"""


class GuideState(TypedDict):
    """Conversation state. Message history is all the agent needs to carry."""

    messages: Annotated[list, add_messages]


def build_guide_agent(
    index: GuideIndex,
    model: str = "",
    checkpointer=None,
):
    """Compile the guide agent for one repository.

    Args:
        index: Open index supplying the digest and backing the tools.
        model: Anthropic chat model id. Empty means `$GUIDE_CHAT_MODEL`.
        checkpointer: LangGraph checkpointer. Defaults to an in-process `MemorySaver`,
            which keeps follow-up questions coherent within a run but not across
            restarts - pass a persistent saver if that matters.

    Returns:
        A compiled LangGraph app taking `{"messages": [...]}`.
    """
    from langchain_anthropic import ChatAnthropic

    tools = build_guide_tools(index)
    # No `temperature`: the newer Anthropic models reject it with a 400, and the grounding
    # here comes from the tools rather than from sampling settings anyway.
    model = model or chat_model()
    llm = ChatAnthropic(
        model=model,
        max_tokens=max_answer_tokens(),
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        max_retries=3,
    ).bind_tools(tools)

    system_prompt = SYSTEM_PROMPT.format(repo=index.repo_name, digest=index.digest)
    logger.info(
        "Guide agent ready for '%s' (%s, %s search, %d chars of briefing)",
        index.repo_name, model, index.backend, len(index.digest),
    )

    def colleague_node(state: GuideState) -> dict:
        """Reason about the question, calling tools until the answer is grounded."""
        messages = [SystemMessage(content=system_prompt), *state["messages"]]
        return {"messages": [llm.invoke(messages)]}

    graph = StateGraph(GuideState)
    graph.add_node("colleague", colleague_node)
    graph.add_node("tools", ToolNode(tools))

    graph.set_entry_point("colleague")
    graph.add_conditional_edges(
        "colleague",
        tools_condition,
        {"tools": "tools", END: END},
    )
    graph.add_edge("tools", "colleague")

    return graph.compile(checkpointer=checkpointer or MemorySaver())


def ask(agent, question: str, thread_id: str = "default", recursion_limit: int = 24) -> str:
    """Ask one question and return the final answer text.

    Args:
        agent: A compiled agent from `build_guide_agent`.
        question: The newcomer's question.
        thread_id: Conversation id; reuse it for follow-up questions.
        recursion_limit: Cap on reason/lookup cycles, guarding against a tool loop.

    Returns:
        The assistant's final message, or a note if it produced none.
    """
    result = agent.invoke(
        {"messages": [HumanMessage(content=question)]},
        config={
            "configurable": {"thread_id": thread_id},
            "recursion_limit": recursion_limit,
        },
    )
    for message in reversed(result["messages"]):
        if isinstance(message, AIMessage) and message.content:
            if isinstance(message.content, str):
                return message.content
            return "\n".join(
                block.get("text", "")
                for block in message.content
                if isinstance(block, dict) and block.get("type") == "text"
            ).strip()
    return "(the agent returned no answer)"
