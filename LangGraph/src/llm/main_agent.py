from langchain_core.messages import HumanMessage, AIMessage, RemoveMessage
from typing import TypedDict, Optional, Any

from langchain_classic.memory import ConversationBufferMemory
from langchain_core.messages import HumanMessage, SystemMessage, RemoveMessage, AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
# from langgraph.checkpoint.memory import InMemorySaver
from langchain_openai import ChatOpenAI
import json


from src.llm.state.agent_state import AgentState
from src.llm.tools.graph import StaticGraph
from src.llm.tools.dynamic_graph import DynamicGraph
from dotenv import load_dotenv
import os

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize LLM
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)


def new_query_node(state: AgentState) -> AgentState:
    """
    Reset only the parts of state relevant to graph/scheduling for a new user query.
    """
    state["static_graph_result"] = None
    state["dynamic_graph_result"] = None
    state["final_answer"] = None
    return state


def reformulate_query(state: AgentState) -> AgentState:
    """
    Reformulates the latest user query using the conversation history.
    Uses `history` as the canonical message store.
    """
    history = state.get("history", [])
    user_input = state["user_input"]

    if len(history) < 1:
        return {
            "user_input": user_input,
        }

    reformulation_prompt = (
        "Reformulate the user's latest query to be clearer and more precise.\n\n"
        f"User's original query:\n{user_input}\n\n"
        "Take the conversation history into account.\n\n"
        "Rule:\n"
        "- For questions about location (e.g. 'where', 'which floor', 'which room'), "
        "exclude the institute unless the user explicitly asks for it."
    )

    llm_messages = history + [HumanMessage(content=reformulation_prompt)]

    print("\n====== REFORMULATION PROMPT ======\n")
    print(reformulation_prompt)
    print("\n====== END PROMPT ======\n")
    print("\n====== LLM MESSAGES (DEBUG) ======\n")
    for m in llm_messages:
        print(type(m).__name__, ":", getattr(m, "content", ""))
    print("\n====== END MESSAGES ======\n")

    response = llm.invoke(llm_messages)

    print("\n====== RESPONSE ======\n")
    print(response)

    reformulated = response.content.strip()
    reformulated_message = HumanMessage(content=reformulated)

    # Optional: prune old history entries (keep last 2)
    delete_messages = [RemoveMessage(id=m.id) for m in history[:-2]]

    return {
        "history": delete_messages + [reformulated_message],
        "user_input": reformulated,
    }


def supervisor_node_rules(state: AgentState):
    """
    Deterministic routing using the 'needs' dictionary set by the router.
    Loops until all required agents finish.
    Resets the 'needs' flag for an agent once it has been routed.
    """
    needs = state.get("needs", {})

    # Route to graph agent if needed
    if needs.get("graph"):
        state["next_action"] = "graph"
        state["supervisor_reasoning"] = "Routing to Graph agent"
        # Reset flag so it doesn't run again
        state["needs"]["graph"] = False
        return state

    # Route to scheduling agent if needed
    if needs.get("scheduling"):
        state["next_action"] = "scheduling"
        state["supervisor_reasoning"] = "Routing to Scheduling agent"
        # Reset flag so it doesn't run again
        state["needs"]["scheduling"] = False
        return state

    # All required data collected → finish
    state["next_action"] = "finish"
    state["supervisor_reasoning"] = "All required data retrieved"
    return state


def supervisor_node_router(state: AgentState):
    """
    LLM-based router that runs once per new user query.
    Sets a single 'needs' dictionary in state for required actions.
    """
    messages = state.get("messages", [])
    user_input = state.get("user_input", "")

    # --- Supervisor System Prompt (LLM Persona) ---
    system_prompt = """
    You are an intelligent building information assistant.
    You have access to tools for querying:
    - a static building graph (rooms, people, connections)
    - dynamic scheduling (events, room occupation)
    Only use these tools when needed, do not invent data.
    """

    # --- Routing Prompt ---
    routing_prompt = f"""
    Messages so far: {messages}
    Current user query: {user_input}

    Decide which tools need to be run for this query:
    - If the query mentions any time/event-related concepts (time, today, tomorrow, schedule, occupied, free, event, when),
      then scheduling tool is required.
    - Otherwise, use the graph tool if needed.
    - Determine if the final answer can be produced directly.

    Respond ONLY in JSON with these fields:
    {{
        "graph": <true|false>,
        "scheduling": <true|false>,
        "reason": "<short explanation>"
    }}
    """

    # --- Call the LLM ---
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=routing_prompt)
    ])

    # --- Parse JSON safely ---
    parsed = json.loads(response.content)

    # --- Store a single 'needs' dictionary in state ---
    state["needs"] = {
        "graph": parsed.get("graph", False),
        "scheduling": parsed.get("scheduling", False),
        "finish": parsed.get("finish", False),
    }
    state["supervisor_reasoning"] = parsed.get("reason", "")

    return state


def final_answer_node(state: AgentState) -> AgentState:
    """
    Use LLM to generate final answer for the user.
    """
    graph_result_static = state.get("static_graph_result", {})
    graph_result_dynamic = state.get("dynamic_graph_result", {})

    prompt = (
        "Compress these two results into one. If one result has no meaningful result, ignore it.\n"
        f"Graph Result 1: {graph_result_static}\n"
        f"Graph Result 2: {graph_result_dynamic}\n"
        "Summarize these answers shortly, without indicating the source."
    )
    answer = llm.invoke([{"role": "user", "content": prompt}])
    print("###### Final Answer ##### ---", answer)
    state["final_answer"] = answer.content

    ai_message = AIMessage(content=answer.content)

    return {
        "history": [ai_message],
        "final_answer": ai_message.content,
    }


workflow = StateGraph(AgentState)

workflow.add_node("supervisor", supervisor_node_rules)
workflow.add_node("supervisor_router", supervisor_node_router)
workflow.add_node("static_graph_agent", StaticGraph.node)
workflow.add_node("dynamic_graph_agent", DynamicGraph.node)
workflow.add_node("final_answer", final_answer_node)
workflow.add_node("reformulate_query", reformulate_query)


workflow.add_node("new_query", new_query_node)
workflow.set_entry_point("new_query")
workflow.add_edge("new_query", "reformulate_query")
workflow.add_edge("reformulate_query", "supervisor_router")

workflow.add_conditional_edges(
    "supervisor",
    lambda state: state["next_action"],
    {
        "graph": "static_graph_agent",
        "finish": "final_answer",
        "scheduling": "dynamic_graph_agent",
    }
)

workflow.add_edge("supervisor_router", "supervisor")
workflow.add_edge("static_graph_agent", "supervisor")
workflow.add_edge("dynamic_graph_agent", "supervisor")

workflow.add_edge("final_answer", END)

checkpointer = InMemorySaver()

supervisor_app = workflow.compile(checkpointer=checkpointer)
