from typing import TypedDict, List, Optional, Dict, Any, Annotated
from langchain_classic.memory import ConversationBufferMemory
from langgraph.graph import add_messages


class AgentState(TypedDict, total=False):
    # User input
    user_input: str
    current_time: Optional[str]

    # LLM / graph outputs
    static_graph_result: str
    dynamic_graph_result: str
    final_answer: str
    static_json_result: Optional[dict]
    dynamic_json_result: Optional[dict]
    supervisor_reasoning: Optional[dict]
    # Conversation memory
    history: Annotated[list, add_messages]

    # Control flow
    next_action: str
    supervisor_output: Optional[str]

    # Routing needs consolidated into a single dict
    needs: Optional[Dict[str, bool]]  # Example: {"graph": True, "scheduling": False, "finish": False}