from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class WorkflowState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    tools_meta: list[dict]
    decision_history: list[dict]

    # New for iterative graph building
    workflow_graph: dict  # NodeGraph shape - see src.llm.state.graph.WorkflowGraph
    candidate_processes: list[dict]
    last_validation: dict | None   # {"valid": bool, "errors": [...]}
    unmet_capabilities: list[dict]  # capabilities asked for that the catalog cannot supply
    current_action: str            # "search" | "build" | "validate" | "chat" | "done"
    step: dict | None              # the single planned step
    step_tools_meta: list[dict]    # narrowed tools for current action
    iteration: int
    max_iterations: int

    # Router signal (unchanged)
    next_action: str               # "run_step" | "end"
