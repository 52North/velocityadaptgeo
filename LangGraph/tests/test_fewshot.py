"""The fewshot variant shows solved examples; the other variants' prompts stay as they were."""

import asyncio
from pathlib import Path

from src.llm.nodes._helpers import EXAMPLES_HEADING, _for_prompt
from src.llm.nodes.auto_builder import auto_build_node
from src.llm.nodes.management import management_node
from src.llm.variants import VARIANTS
from tests.fakes import STATE, FakeBuildLLM, FakeManagerLLM, render

SNAPSHOTS = Path(__file__).parent / "snapshots"
EXAMPLE = {
    "id": "munich-buffer", "request": "Buffer Munich by 500 m.", "similarity": 0.72, "notes": "Geometry first.",
    "solution": {"workflow_graph": {"nodes": [{"id": "b_1", "type": "buffer"}], "edges": []}},
}


def run_manager(monkeypatch, state, found):
    calls = []

    def lookup(goal):
        calls.append(goal)
        return found

    monkeypatch.setattr("src.llm.nodes.management.DECISION_MODEL", "")
    monkeypatch.setattr("src.llm.nodes.management.lookup_examples", lookup)
    llm = FakeManagerLLM()
    update = asyncio.run(management_node(state, llm=llm, use_examples=True))
    return render(llm.prompt), update, calls


def test_manager_looks_up_examples_once_per_turn(monkeypatch):
    prompt, update, calls = run_manager(monkeypatch, {**STATE, "examples": None}, [EXAMPLE])

    assert calls == ["Buffer the city of Muenster by 500m."]
    assert EXAMPLES_HEADING in prompt and "Buffer Munich by 500 m." in prompt and "Geometry first." in prompt
    assert update["examples"] == [EXAMPLE]
    assert update["decision_history"][-1]["examples"] == [{"id": "munich-buffer", "similarity": 0.72}]
    # The audit field is never shown to an LLM.
    assert "examples" not in _for_prompt(update["decision_history"])[-1]

    _, update, calls = run_manager(monkeypatch, {**STATE, "examples": [EXAMPLE]}, [])
    assert calls == []
    assert "examples" not in update


def test_manager_without_examples_sends_the_plain_prompt(monkeypatch):
    prompt, update, _ = run_manager(monkeypatch, {**STATE, "examples": None}, [])

    assert prompt == (SNAPSHOTS / "manager.txt").read_text()
    assert update["examples"] == []


def test_auto_build_shows_examples_only_for_the_fewshot_variant():
    state = {**STATE, "examples": [EXAMPLE]}
    for name, variant in VARIANTS.items():
        llm = FakeBuildLLM()
        asyncio.run(auto_build_node(state, llm=llm, variant=variant))
        assert (EXAMPLES_HEADING in render(llm.prompt)) == variant.examples, name
