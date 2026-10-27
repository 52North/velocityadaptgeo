"""The prompts the manager and auto_build send, against recorded snapshots.

The snapshots of the `pgvector` and `mcp` variants were recorded before the variant registry was
introduced and changed once on purpose since, when "port" was replaced by input/output in the prompt
text (docs/modular-variants.md, step 6): as long as they match, the prompts are the ones measured
after that change. Newer variants were recorded when they were added.
A deliberate prompt change updates them with `UPDATE_SNAPSHOTS=1 uv run pytest`.
"""

import asyncio
import os
from pathlib import Path

import pytest

from src.llm.nodes.auto_builder import auto_build_node
from src.llm.nodes.management import management_node
from src.llm.variants import VARIANTS
from tests.fakes import STATE, FakeBuildLLM, FakeManagerLLM, render

SNAPSHOTS = Path(__file__).parent / "snapshots"


def check(name: str, text: str) -> None:
    path = SNAPSHOTS / name
    if os.environ.get("UPDATE_SNAPSHOTS"):
        path.write_text(text)
    assert text == path.read_text(), f"prompt differs from {path}"


def test_manager_prompt(monkeypatch):
    monkeypatch.setattr("src.llm.nodes.management.DECISION_MODEL", "")
    llm = FakeManagerLLM()
    asyncio.run(management_node(STATE, llm=llm))
    check("manager.txt", render(llm.prompt))


@pytest.mark.parametrize("name", list(VARIANTS))
def test_auto_build_prompt(name):
    llm = FakeBuildLLM()
    asyncio.run(auto_build_node(STATE, llm=llm, variant=VARIANTS[name]))
    check(f"auto_build.{name}.txt", render(llm.prompt))
