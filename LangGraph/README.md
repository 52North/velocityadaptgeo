```sh
uv run uvicorn src.app:app --reload
```
from this folder: the modules import each other as `src.…`. SETUP.md has the variables a run outside compose needs.

The workflow variants (what the agent is shown: catalog search, every MCP tool, or the whole catalog
plus few-shot examples) are listed in `src/llm/variants.py`; `WORKFLOW_VARIANT` picks one, and
`build_workflow(variant)` in `src/llm/workflow.py` builds the agent for it. A new variant is a new
registry entry, plus a retriever node if it gets its candidates in a new way.

```sh
uv run pytest
```
runs the unit tests without an LLM: `tests/test_prompts.py` compares the prompts with
`tests/snapshots/`, so a prompt change shows up as a failing test; after a deliberate change,
`UPDATE_SNAPSHOTS=1 uv run pytest` records the new prompts.
