from src.llm.state.state import WorkflowState


def router(state: WorkflowState) -> str:
    return state.get("next_action", "end")
