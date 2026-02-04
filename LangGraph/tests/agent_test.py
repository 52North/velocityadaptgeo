import pytest
from src.llm.main_agent import supervisor_agent

QUERIES = [
    "In what room does Christian Kray work?",
    #     #"What institute is on the second floor?",
    # "Where does Christian Kray work?",
    # "Where does Prof. Dr. Christian Kray work?",
    # "On what floor is room 137?",
    # "Which rooms are on floor 1?",
    # "Which rooms are on plattform 1?",
    # "Which rooms are on level 1?",
    # "In what room does Christian Kray work?",
    # "Where is the office of Christian Kray?",
    # "Does Christian Kray work here?",
    # "Where is the secretariat?",
    # "How many people are working at the institute of Geoinformatics?",
    # "How many persons are working at the institute?"
]


def invoke_query(query: str):
    """Helper to invoke the supervisor agent and capture output messages."""
    outputs = []
    for step in supervisor_agent.stream({"messages": [{"role": "user", "content": query}]}):
        for update in step.values():
            for message in update.get("messages", []):
                outputs.append(message.content)
                message.pretty_print()
    return outputs


@pytest.mark.parametrize("query", QUERIES)
def test_queries_run_without_error(query):
    """Ensure that supervisor agent can process building-related queries."""
    outputs = invoke_query(query)

    assert any(isinstance(o, str) and len(o) >
               0 for o in outputs), "Outputs are empty strings"

    # Optional: ensure the model didn’t produce an crashing error, even though it would then crash anyhow.
    error_indicators = ["error", "exception", "traceback", "not defined"]
    joined_output = " ".join(outputs).lower()
    assert not any(
        e in joined_output for e in error_indicators), f"Error found in output: {joined_output}"


@pytest.mark.parametrize("query", QUERIES)
def test_queries_produce_reasonable_response(query):
    """Optional deeper test to check semantic content (can be expanded later)."""
    outputs = invoke_query(query)
    joined_output = " ".join(outputs).lower()
    assert "room" in joined_output or "office" in joined_output, (
        f"Expected room-related info in output for query: {query}"
    )
