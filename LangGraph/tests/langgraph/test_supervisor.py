import pytest
import os

import pytest
from src.llm.main_agent import supervisor_app  # adjust import if needed



from dotenv import load_dotenv
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# -- Real end-to-end test --


@pytest.mark.parametrize(
    "user_input",
    [
        #"In which office number is Christian Kray?",
        #"Which events are in room 242 in January 2026?",
        "Is room GEO1 242 on the 10th of February 2026 occupied at 19:00?"
    ]
)
def test_run_workflow_query_real(user_input):
    state = {"user_input": user_input}
    config = {"configurable": {"thread_id": "test",
              "verbose": True}}


    result_state = supervisor_app.invoke(state, config)


    # --- Validate the structure ---
    assert isinstance(result_state, dict)
    assert "final_answer" in result_state, (
        "Workflow finished but no final_answer was produced."
    )

    answer = result_state["final_answer"]

    assert isinstance(answer, str)
    assert answer.strip() != ""
    print(f"\nInput: {user_input}\nAnswer: {answer}\n")
    print(f"\n State: {result_state}\n")