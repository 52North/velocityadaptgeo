"""Shared helpers for retriever, builder, and validator nodes."""

import json
import logging
from typing import Any

from src.llm.tools.fewshot_client import search_examples

logger = logging.getLogger(__name__)


def _log(
    state: dict,
    node: str,
    instruction: Any,
    result: Any = None,
    error: str | None = None,
) -> list[dict]:
    """Append a structured entry to `decision_history` and return the new list.

    Each node calls this with whatever context is relevant. The returned list
    should be put into the node's state update under `"decision_history"`.
    """
    history = list(state.get("decision_history", []))
    history.append({
        "node": node,
        "instruction": instruction,
        "result_summary": _summarize(result) if result is not None else None,
        "error": error,
    })
    return history


# Logged with manager decisions for the decision model and the few-shot audit, never shown to an LLM.
_LOGGED_ONLY = ("state", "laya", "examples")


def _for_prompt(entries: list[dict]) -> list[dict]:
    """`decision_history` entries without the decision-model fields, for an LLM prompt.

    The manager logs what it saw with each decision (`state`, see `management.decision_state`)
    and, in shadow mode, Laya's pick (`laya`). Repeating them in a prompt would add tokens, and
    Laya's pick would let it influence the decisions it is only meant to be compared with.
    """
    return [{k: v for k, v in entry.items() if k not in _LOGGED_ONLY} for entry in entries]


def _unmet(state: dict, capability: Any, closest: str | None, similarity: Any) -> list[dict]:
    """Append a capability the catalog cannot supply, and return the new list.

    Recorded whenever a search finds nothing that actually performs the requested
    operation, so the manager stops re-searching it and the final reply can say the
    step was NOT added rather than reporting a near-miss node as a success.
    """
    unmet = list(state.get("unmet_capabilities", []))
    entry = {"capability": capability, "closest_process": closest, "similarity": similarity}
    if entry not in unmet:
        unmet.append(entry)
    return unmet


def _summarize(obj: Any) -> Any:
    """Compact representation so decision_history stays readable."""
    if isinstance(obj, list):
        return f"list[{len(obj)}]"
    if isinstance(obj, dict):
        return {k: type(v).__name__ for k, v in obj.items()}
    return str(obj)[:200]


EXAMPLES_HEADING = (
    "SOLVED EXAMPLES (earlier requests similar to the USER GOAL, each with the workflow graph that "
    "solved it - follow their pattern of steps and wiring where it fits, but build only what the "
    "USER GOAL asks for):"
)


def lookup_examples(goal: str) -> list[dict]:
    """The fewshot variant's examples for `goal`; none, with the error logged, if the lookup fails.

    A failed lookup must not end the turn: the agent then works as without examples.
    """
    try:
        return search_examples(goal)
    except Exception:
        logger.exception("Few-shot lookup failed; continuing without examples")
        return []


def examples_block(examples: list[dict] | None) -> str:
    """The examples as a prompt section, or "" when there are none (the prompt is then unchanged)."""
    if not examples:
        return ""
    shown = [
        {"request": e["request"], "workflow_graph": (e.get("solution") or {}).get("workflow_graph"),
         **({"notes": e["notes"]} if e.get("notes") else {})}
        for e in examples
    ]
    return f"{EXAMPLES_HEADING}\n{json.dumps(shown, indent=2, ensure_ascii=False)}"
