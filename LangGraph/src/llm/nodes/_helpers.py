"""Shared helpers for retriever, builder, and validator nodes."""

import json
from typing import Any

from langchain_core.messages import ToolMessage


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


def _last_tool_result(messages: list, tool_name: str) -> Any:
    """Walk the agent transcript backwards to find the most recent ToolMessage
    produced by the named tool, returning its parsed content."""
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage) and getattr(msg, "name", None) == tool_name:
            content = msg.content
            if isinstance(content, str):
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    return content
            return content
    return None
