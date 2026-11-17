"""Fake LLMs that record the prompt a node sends, so prompts can be checked without an API call."""

from langchain_core.messages import HumanMessage

from src.llm.nodes.auto_builder import GraphBuildDecision

# One search turn of a small goal, with one candidate as the pgvector search would return it.
STATE = {
    "messages": [HumanMessage(content="Buffer the city of Muenster by 500m.")],
    "step": {"name": "find buffer", "instruction": "Find an OGC process that buffers a geometry by a distance in meters."},
    "workflow_graph": {"nodes": [], "edges": []},
    "candidate_processes": [
        {"server_url": "http://pygeoapi:80/", "process_id": "buffer", "title": "Buffer",
         "description": "Buffers a geometry.",
         "inputs": {"geometry": {"schema": {"type": "object"}}, "distance": {"schema": {"type": "number"}}},
         "outputs": {"result": {"schema": {"type": "object"}}}, "similarity": 0.81},
    ],
    "decision_history": [],
    "iteration": 0,
    "max_iterations": 16,
}


def render(prompt: list) -> str:
    """A prompt as text: each message's type and content."""
    return "\n\n".join(f"=== {type(m).__name__}\n{m.content}" for m in prompt)


class _Reply:
    def __init__(self, text: str):
        self.text = text


class FakeManagerLLM:
    """Answers the manager with "done" and keeps the prompt it was sent."""

    prompt: list | None = None

    async def ainvoke(self, prompt):
        self.prompt = prompt
        return _Reply('{"next_action": "done", "step": null, "reasoning": "fake"}')


class _FakeStructured:
    def __init__(self, outer: "FakeBuildLLM"):
        self.outer = outer

    async def ainvoke(self, prompt):
        self.outer.prompt = prompt
        return GraphBuildDecision(performs_capability=False, process_id="buffer",
                                  server_url="http://pygeoapi:80/", reasoning="fake")


class FakeBuildLLM:
    """Refuses every candidate in auto_build and keeps the prompt it was sent."""

    prompt: list | None = None

    def with_structured_output(self, _schema):
        return _FakeStructured(self)
