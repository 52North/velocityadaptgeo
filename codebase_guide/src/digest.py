"""Render a code map as the architecture briefing injected into the system prompt.

The digest exists because of a retrieval failure mode: an agent that can only search
does not know what it does not know. Asked "how does a user request become a
workflow?", a search-only agent queries "user request workflow", gets three
plausible docstrings, and answers from those - never learning that the request also
passes through a validator. Giving it the map up front means search is for drilling
down, not for orienting.

Size-capped, so a large repo degrades to "top-level layout and wiring only" rather
than overflowing the context window. Detector notes are paid first: they state the
wiring, which is the part no individual docstring contains.
"""

from .model import CodeMap

_KIND_LABELS = {
    "agent_node": "agent nodes",
    "ogc_process": "OGC processes",
    "http_route": "HTTP routes",
}

# Named in every truncation marker: a coarse briefing must tell its reader which knob
# widens it, or the degradation looks like a missing feature.
_BUDGET_ENV = "GUIDE_DIGEST_MAX_CHARS"

# Held back from the elastic sections so the announcement is never itself the thing that
# gets cut. A constant rather than the notice's real length, because the notice's text
# depends on what was dropped, which depends on the budget - one pass, no feedback loop.
_NOTICE_RESERVE = 260

# What each elastic section may claim of the space still free when it is reached. Notes
# come first and get the largest share because they carry wiring no docstring states, but
# a share rather than everything: a repo with forty agent graphs must not push the
# key-module list and the blind spots out of the briefing entirely.
_NOTES_SHARE = 0.7
_MODULES_SHARE = 0.7


def architecture_digest(code_map: CodeMap, max_chars: int = 24000) -> str:
    """Build the architecture briefing for one repository.

    Every section is subject to the budget, including detector notes: they are the part
    that grows with repository size, so exempting them would make the cap meaningless.
    Priority runs header, layout, notes, key modules, coverage - the first two are
    load-bearing (without them the agent does not know what it is looking at) and bounded
    by the number of top-level components, so they are emitted whole and only the final
    clamp can touch them.

    Args:
        code_map: The extracted map.
        max_chars: Hard ceiling on the result. The return value is never longer, and
            anything dropped to stay under it is announced, never silent.

    Returns:
        A plain-text briefing of at most `max_chars` characters.
    """
    stats = code_map.stats()
    budget = max(max_chars, 0)

    sections: list[str] = []
    used = 0
    trimmed: list[str] = []

    def take(text: str) -> None:
        """Append a section, accounting for the blank line that will join it."""
        nonlocal used
        if text:
            sections.append(text)
            used += len(text) + 2

    def free() -> int:
        """Characters still available to an elastic section."""
        return max(budget - used - _NOTICE_RESERVE, 0)

    take(_header(code_map, stats))
    take(_layout(code_map))

    notes_section, dropped = _notes(code_map.notes, int(free() * _NOTES_SHARE))
    take(notes_section)
    trimmed.extend(dropped)

    modules_section, dropped = _key_modules(code_map, int(free() * _MODULES_SHARE))
    take(modules_section)
    trimmed.extend(dropped)

    coverage_section, dropped = _coverage(code_map, stats, free())
    take(coverage_section)
    trimmed.extend(dropped)

    if trimmed:
        sections.append(_trim_notice(trimmed, budget))

    return _clamp("\n\n".join(sections), budget)


def _trim_notice(trimmed: list[str], budget: int) -> str:
    """Name everything the budget cost, and the setting that buys it back."""
    return (
        "## Reduced briefing\n"
        f"Trimmed to fit {_BUDGET_ENV}={budget}; omitted: "
        + "; ".join(trimmed)
        + ". Raise that setting, or use search_code and list_module to reach the rest."
    )


def _clamp(text: str, budget: int) -> str:
    """Enforce the hard ceiling, marking the cut so a stub cannot read as complete.

    The last line of defence: on a repo whose header and layout alone exceed a small
    budget, there is nothing left to negotiate away and the briefing is simply cut.
    """
    if len(text) <= budget:
        return text
    marker = f"\n[briefing cut at {budget} chars - raise {_BUDGET_ENV}]"
    if budget <= len(marker):
        return text[:budget]
    return text[: budget - len(marker)].rstrip() + marker


def _header(code_map: CodeMap, stats: dict) -> str:
    """Repo identity and headline counts."""
    lines = [f"# Codebase: {code_map.repo_name}"]
    if code_map.commit:
        lines.append(f"Indexed at commit {code_map.commit}.")
    counts = ", ".join(f"{count} {kind}" for kind, count in stats["by_kind"].items())
    lines.append(f"Contains {counts}.")
    lines.append(
        f"Documentation coverage: {stats['doc_coverage_pct']}% "
        f"({stats['documented']}/{stats['documentable']} symbols carry a doc comment)."
    )
    return "\n".join(lines)


def _layout(code_map: CodeMap) -> str:
    """Top-level components, sized, with the best available one-line description.

    A package's own `__init__` docstring is preferred, then the shallowest documented
    module, then the most-depended-on one. Depth beats popularity here: a deeply nested
    helper can be imported everywhere and still describe only itself, which makes for a
    misleading one-line summary of a whole component.
    """
    groups: dict[str, list] = {}
    for module in code_map.modules():
        top = module.qualname.split(".")[0]
        groups.setdefault(top, []).append(module)

    importance = code_map.importance()
    lines = ["## Layout"]
    for top, modules in sorted(groups.items()):
        documented = [m for m in modules if m.doc]
        described = min(
            documented,
            key=lambda m: (m.qualname.count("."), -importance.get(m.qualname, 0)),
            default=None,
        )
        summary = described.summary if described else "no component-level docstring"
        lines.append(f"- {top}/ ({len(modules)} modules) - {summary}")
    return "\n".join(lines)


def _notes(notes: list[str], budget: int) -> tuple[str, list[str]]:
    """Emit detector notes, whole ones first, within `budget`.

    Args:
        notes: Prose wiring summaries contributed by detectors, in detector order.
        budget: Characters available.

    Returns:
        (section text, descriptions of what was dropped).
    """
    if not notes:
        return "", []

    header = "## How it is wired"
    kept: list[str] = []
    used = len(header)
    for note in notes:
        if used + len(note) + 2 > budget:
            break
        kept.append(note)
        used += len(note) + 2

    shown = len(kept)
    if shown == 0:
        # A single note larger than the whole allowance still beats no wiring at all: its
        # opening lines name the graph and its entry point, which is the orienting part.
        if head := _leading_lines(notes[0], budget - len(header) - 2):
            kept.append(f"{head}\n  ... (rest of this note omitted)")

    if not kept:
        return "", [f"all {len(notes)} wiring notes"]

    text = "\n\n".join([header, *kept])
    if shown == len(notes):
        return text, []
    return text, [f"{len(notes) - shown} of {len(notes)} wiring notes"]


def _leading_lines(text: str, budget: int) -> str:
    """As many whole leading lines of `text` as fit in `budget`."""
    kept: list[str] = []
    used = 0
    for line in text.splitlines():
        if used + len(line) + 1 > budget:
            break
        kept.append(line)
        used += len(line) + 1
    return "\n".join(kept)


def _key_modules(code_map: CodeMap, budget: int) -> tuple[str, list[str]]:
    """List modules most of the repo depends on, one line each, within `budget`.

    Args:
        code_map: The extracted map.
        budget: Characters available.

    Returns:
        (section text, descriptions of what was dropped).
    """
    importance = code_map.importance()
    ranked = sorted(
        code_map.modules(),
        key=lambda m: (-importance.get(m.qualname, 0), m.qualname),
    )
    if not ranked:
        return "", []
    if budget < 200:
        return "", [f"the key-module list ({len(ranked)} modules)"]

    header = "## Modules the rest of the code depends on"
    lines = [header]
    used = len(header)
    shown = 0
    dropped: list[str] = []
    reserve = 120  # leave room for the truncation notice

    for module in ranked:
        if importance.get(module.qualname, 0) == 0 and shown >= 10:
            break  # editorial stop, not a budget one: nothing depends on the rest
        line = f"- {module.qualname} ({module.file}) - {module.summary}"
        if used + len(line) + reserve > budget:
            # Marked twice on purpose: in place, where the reader is looking and can be
            # pointed at the tools, and once more in the notice that names the setting.
            lines.append(
                f"- ... {len(ranked) - shown} further modules omitted for length; "
                "use search_code or list_module to reach them."
            )
            dropped.append(f"{len(ranked) - shown} of {len(ranked)} key modules")
            break
        lines.append(line)
        used += len(line) + 1
        shown += 1

    return "\n".join(lines), dropped


def _coverage(code_map: CodeMap, stats: dict, budget: int) -> tuple[str, list[str]]:
    """State the guide's own blind spots.

    Surfacing undocumented-but-central symbols is the honest move: those are precisely
    where the guide will be least useful, and the reader deserves to know that before
    trusting an answer about them. Which is also why dropping this section for length has
    to be announced: a briefing with no blind-spot list reads like a repo with no gaps.

    Args:
        code_map: The extracted map.
        stats: Output of `CodeMap.stats`.
        budget: Characters available.

    Returns:
        (section text, descriptions of what was dropped).
    """
    lines: list[str] = []
    dropped: list[str] = []
    used = 0

    special = {
        label: stats["by_kind"].get(kind, 0)
        for kind, label in _KIND_LABELS.items()
        if stats["by_kind"].get(kind)
    }
    if special:
        block = "## Framework constructs indexed\n" + "\n".join(
            f"- {count} {label}" for label, count in special.items()
        )
        if used + len(block) <= budget:
            lines.append(block)
            used += len(block) + 2
        else:
            dropped.append("the framework-construct counts")

    gaps = code_map.undocumented(limit=8)
    if gaps:
        block = (
            "## Known blind spots\n"
            "These are referenced by other code but carry no doc comment, so this guide "
            "can locate them but cannot explain their intent:\n"
            + "\n".join(f"- {s.qualname} ({s.location})" for s in gaps)
        )
        if used + len(block) <= budget:
            lines.append(block)
        else:
            dropped.append(f"the blind-spot list ({len(gaps)} undocumented symbols)")

    return "\n\n".join(lines), dropped
