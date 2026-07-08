from typing import TypedDict, Sequence, Annotated
from langchain_core.messages import BaseMessage

from src.llm.state.graph import WorkflowGraph


class WorkflowState(TypedDict, total=False):
    messages: list[BaseMessage]
    tools_meta: list[dict]
    decision_history: list[dict]

    # New for iterative graph building
    workflow_graph: WorkflowGraph  # {"nodes": [GraphNode, ...], "edges": [GraphEdge, ...]}
    candidate_processes: list[dict]
    last_validation: dict | None   # {"valid": bool, "errors": [...]}
    current_action: str            # "search" | "build" | "validate" | "chat" | "done"
    step: dict | None              # the single planned step
    step_tools_meta: list[dict]    # narrowed tools for current action
    iteration: int
    max_iterations: int

    # Router signal (unchanged)
    next_action: str               # "run_step" | "end"
