from src.llm.state.state import WorkflowState


def action_router(state: WorkflowState) -> str:
    action = state.get("current_action")
    if action in ("search", "build", "validate"):
        return action
    return "done"
