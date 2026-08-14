"""Wiring detectors: the structure that lives in config and framework calls.

Doc comments describe units in isolation. `imports` and `calls` edges recover the
mechanical dependencies between them. Neither recovers the *architecture*, because
in a framework-driven codebase the architecture is data: which LangGraph nodes run
in what order, which classes a YAML file registers as OGC processes. Nothing calls
`chat_node` - `workflow.py` names it in a string, and a call-graph extractor sees
nothing at all.

A detector reads one of those framework conventions and contributes the edges plus
a prose `note` that goes into the architecture digest verbatim.

Detectors must be optional by construction: one that does not recognise a repo
returns an empty result, so this module stays usable on codebases that have never
heard of pygeoapi.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..config import GuideConfig
from ..model import CodeMap, Edge, Symbol

logger = logging.getLogger("codebase-guide")


@dataclass
class DetectContext:
    """What a detector gets to work with.

    Attributes:
        config: The target repo's configuration.
        code_map: The map after language extraction - symbols are already present.
        files: (absolute path, repo-relative, source-root-relative) for every walked file.
    """

    config: GuideConfig
    code_map: CodeMap
    files: list[tuple[Path, str, str]]

    def resolve_suffix(self, dotted: str, kinds: tuple[str, ...] = ("class", "function")) -> str:
        """Resolve a dotted reference from a config file to a symbol qualname.

        Config files name code the way the *runtime* sees it -
        `processes.buffer.BufferProcessor` under pygeoapi's `PYTHONPATH` - which is a
        suffix of the map's repo-rooted qualname.

        Args:
            dotted: Dotted path as written in configuration.
            kinds: Acceptable symbol kinds.

        Returns:
            The matched qualname, or "" if nothing matches.
        """
        if not dotted:
            return ""
        candidates = [
            q for q, s in self.code_map.symbols.items()
            if s.kind in kinds and (q == dotted or q.endswith("." + dotted))
        ]
        if not candidates:
            tail = dotted.rsplit(".", 1)[-1]
            candidates = [
                q for q, s in self.code_map.symbols.items()
                if s.kind in kinds and s.name == tail
            ]
        return min(candidates, key=len) if candidates else ""

    def files_containing(self, needle: str, suffixes: tuple[str, ...]) -> list[tuple[Path, str]]:
        """Cheap prefilter: files of the given suffixes whose text contains `needle`."""
        hits: list[tuple[Path, str]] = []
        for path, repo_relative, _ in self.files:
            if path.suffix not in suffixes:
                continue
            try:
                if needle in path.read_text(encoding="utf-8", errors="replace"):
                    hits.append((path, repo_relative))
            except OSError:
                continue
        return hits


@dataclass
class DetectResult:
    """A detector's contribution to the map."""

    symbols: list[Symbol] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.symbols or self.edges or self.notes)


@runtime_checkable
class Detector(Protocol):
    """Contract for a wiring detector."""

    name: str

    def detect(self, ctx: DetectContext) -> DetectResult:
        """Inspect the repo and return framework-level structure.

        Must return an empty `DetectResult` - not raise - when the repo does not use
        the framework it knows about.
        """
        ...


def _load_detectors() -> list[Detector]:
    """Instantiate the registered detectors, in the order their notes should appear."""
    from .entrypoints import EntrypointDetector
    from .langgraph import LangGraphDetector
    from .pygeoapi import PygeoapiDetector

    return [LangGraphDetector(), PygeoapiDetector(), EntrypointDetector()]


DETECTORS: list[Detector] = _load_detectors()


def run_detectors(ctx: DetectContext) -> DetectResult:
    """Run every detector, isolating failures.

    A detector crashing on an unfamiliar repo layout must not cost the caller the
    whole map, so each is wrapped and its failure logged.

    Args:
        ctx: Shared detection context.

    Returns:
        Merged results from all detectors that succeeded.
    """
    merged = DetectResult()
    for detector in DETECTORS:
        try:
            result = detector.detect(ctx)
        except Exception:
            logger.exception("Detector %s failed; continuing without it", detector.name)
            continue
        if result:
            logger.info(
                "Detector %s: %d symbols, %d edges", detector.name,
                len(result.symbols), len(result.edges),
            )
        merged.symbols.extend(result.symbols)
        merged.edges.extend(result.edges)
        merged.notes.extend(result.notes)
    return merged
