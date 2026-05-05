from typing import TypedDict, Sequence, Annotated
from langgraph.graph.message import add_messages


class WorkflowState(TypedDict, total=False):
    messages: Annotated[Sequence, add_messages]

    # planning/execution bookkeeping
    plan: list[dict]                 # ordered steps from manager
    current_step: int                # index into plan
    next_action: str                 # router decision

    tools_meta: list[dict]

    # optional tracking/debug
    decision_history: list
    tool_chain: list                 # tool calls made in latest agent run
    current_context: dict            # free-form context between steps
