"""Language extractors: source files in, documented symbols and references out.

An extractor never returns source code. It returns symbols carrying doc comments,
plus *unresolved* references (imports, calls) which it later resolves itself in
`link`, because reference resolution is language-specific: Python's relative
imports and Java's package/classpath rules share no logic.

Adding a language means implementing `Extractor` and appending it to `EXTRACTORS`.
Only Python ships today; `python.py` is the reference implementation.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..model import Edge, Symbol


@dataclass
class FileParse:
    """Everything one source file contributed.

    Attributes:
        path: Repo-relative path of the parsed file.
        module_qualname: Qualname of the file-level symbol (module, compilation unit).
        symbols: Symbols found, including the module itself.
        edges: Edges already resolvable from this file alone (`contains`).
        refs: Language-specific unresolved reference records, consumed by `link`.
        errors: Human-readable parse problems, surfaced rather than swallowed.
    """

    path: str
    module_qualname: str = ""
    symbols: list[Symbol] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    refs: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@runtime_checkable
class Extractor(Protocol):
    """Contract for a per-language extractor."""

    name: str
    suffixes: tuple[str, ...]

    def parse(self, path: Path, repo_relative: str) -> FileParse:
        """Parse one file into symbols and unresolved references.

        Args:
            path: Absolute path to the file.
            repo_relative: Path relative to the repository root, POSIX style. Qualnames
                are derived from it so they stay unique across source roots - two
                packages may both contain `src/__init__.py`.

        Returns:
            The file's contribution to the map.
        """
        ...

    def link(self, symbols: dict[str, Symbol], parses: list[FileParse]) -> list[Edge]:
        """Resolve the references gathered by `parse` against the full symbol table.

        Args:
            symbols: Every symbol in the repo, qualname → symbol.
            parses: All `FileParse` results this extractor produced.

        Returns:
            Resolved `imports`, `calls`, and `inherits` edges. References pointing
            outside the repo are dropped: a third-party call is not repo structure.
        """
        ...


def _load_extractors() -> list[Extractor]:
    """Instantiate the registered extractors."""
    from .python import PythonExtractor

    return [PythonExtractor()]


EXTRACTORS: list[Extractor] = _load_extractors()


def extractor_for(path: Path) -> Extractor | None:
    """Return the extractor handling a file's suffix, or None when unsupported."""
    for extractor in EXTRACTORS:
        if path.suffix in extractor.suffixes:
            return extractor
    return None
