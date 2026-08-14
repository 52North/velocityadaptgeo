"""The code map: symbols, the edges between them, and traversal over both.

This is the data structure the whole module is built around. A plain vector store
answers "which docstrings look like this question"; it cannot answer "what calls
this", "what does this node run before", or "how does a request reach the
database". Those are edge queries, so edges are first-class here rather than
something the LLM is left to infer from retrieved text.

Edge kinds
    contains    parent → child (module → class, class → method)
    imports     module → module
    calls       function → function it invokes
    inherits    class → base class
    flows_to    framework-level control flow (e.g. one agent node to the next)
    implements  framework construct → the code that backs it
    registers   config/registry entry → the thing it registers
"""

import json
import os
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

STRUCTURAL_EDGE_KINDS = ("calls", "flows_to", "implements", "registers")


@dataclass
class Symbol:
    """One documented thing in the codebase.

    `doc` is the docstring (or Javadoc-style comment) verbatim - never source code.
    Retrieval quality therefore tracks documentation quality, which `CodeMap.stats`
    reports so the gap is visible rather than silent.
    """

    qualname: str
    kind: str
    name: str
    file: str = ""
    lineno: int = 0
    doc: str = ""
    signature: str = ""
    decorators: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @property
    def summary(self) -> str:
        """First line of the docstring, or a synthesised stand-in when undocumented."""
        if self.doc:
            return self.doc.strip().splitlines()[0].strip()
        return f"(undocumented {self.kind})"

    @property
    def location(self) -> str:
        """`file:line`, the form a developer can click."""
        return f"{self.file}:{self.lineno}" if self.file else ""

    def embedding_text(self, parent_summary: str = "") -> str:
        """Build the text that represents this symbol in the vector index.

        Deliberately excludes the body. Identifier and signature are included because
        they carry real meaning and are the only signal left for undocumented symbols.

        Args:
            parent_summary: One-line summary of the containing module or class, giving
                a short method some of its parent's context.

        Returns:
            The text to embed.
        """
        parts = [
            f"{self.kind} {self.name}",
            self.qualname,
            self.signature,
            self.doc,
        ]
        if parent_summary:
            parts.append(f"context: {parent_summary}")
        if self.tags:
            parts.append(" ".join(self.tags))
        return "\n".join(p for p in parts if p).strip()


@dataclass
class Edge:
    """A directed relationship between two symbol qualnames. See module docstring."""

    src: str
    dst: str
    kind: str
    detail: str = ""

    def key(self) -> tuple[str, str, str, str]:
        """Identity tuple, used to deduplicate repeated extractions."""
        return (self.src, self.dst, self.kind, self.detail)


@dataclass
class CodeMap:
    """Symbols plus edges for one repository, with the queries the agent needs.

    Attributes:
        repo_name: Partition key shared with the index.
        symbols: Qualname → `Symbol`.
        edges: All relationships, deduplicated on load.
        notes: Framework-level narratives contributed by detectors. These are prose
            summaries of wiring that no single docstring states, and they go into the
            architecture digest verbatim.
        commit: Git commit the map was built from, when available.
    """

    repo_name: str = ""
    symbols: dict[str, Symbol] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    commit: str = ""

    def __post_init__(self) -> None:
        self._out: dict[str, list[Edge]] | None = None
        self._in: dict[str, list[Edge]] | None = None
        self._keys: set[tuple[str, str, str, str]] | None = None

    # ---------------------------------------------------------------- building

    def add_symbol(self, symbol: Symbol) -> None:
        """Add a symbol, keeping whichever copy carries a docstring on collision."""
        existing = self.symbols.get(symbol.qualname)
        if existing and existing.doc and not symbol.doc:
            return
        self.symbols[symbol.qualname] = symbol
        # Nothing to invalidate: every derived index below is built from `edges` alone.

    def add_edge(self, edge: Edge) -> None:
        """Add an edge unless an identical one is already present.

        Dedup happens here rather than only in `dedupe()` because this is public
        surface: a host that builds a map incrementally would otherwise accumulate
        duplicate `imports` edges, each counting again towards `importance()` and each
        printing another line in a symbol's neighbourhood. A hash lookup per edge is
        cheaper than appending duplicates and sweeping them up afterwards, so the full
        `build_code_map` run pays nothing for it.
        """
        keys = self._edge_keys()
        key = edge.key()
        if key in keys:
            return
        self.edges.append(edge)
        # The key set stays valid by construction; only the adjacency indexes are stale.
        # Dropping the keys here instead would make a whole-repo build quadratic.
        keys.add(key)
        self._out = None
        self._in = None

    def dedupe(self) -> None:
        """Collapse duplicate edges, preserving insertion order.

        Still needed with `add_edge` deduplicating, because the deserialising paths
        (`from_dict`, and `load_code_map_from_db`) assign `edges` wholesale instead of
        going through it. On a map built via `add_edge` this is a no-op scan.
        """
        seen: set[tuple[str, str, str, str]] = set()
        unique: list[Edge] = []
        for edge in self.edges:
            if edge.key() not in seen:
                seen.add(edge.key())
                unique.append(edge)
        self.edges = unique
        self._invalidate()
        self._keys = seen  # Just computed it; no reason to make the next insert rebuild.

    def _invalidate(self) -> None:
        """Drop every index derived from `edges`, after a change this class cannot see."""
        self._out = None
        self._in = None
        self._keys = None

    def _edge_keys(self) -> set[tuple[str, str, str, str]]:
        """Identity tuples of the current edges, cached for O(1) dedup on insert."""
        if self._keys is None:
            self._keys = {edge.key() for edge in self.edges}
        return self._keys

    def _adjacency(self) -> tuple[dict[str, list[Edge]], dict[str, list[Edge]]]:
        """Build (and cache) the outgoing/incoming edge indexes."""
        if self._out is None or self._in is None:
            out: dict[str, list[Edge]] = defaultdict(list)
            inc: dict[str, list[Edge]] = defaultdict(list)
            for edge in self.edges:
                out[edge.src].append(edge)
                inc[edge.dst].append(edge)
            self._out, self._in = out, inc
        return self._out, self._in

    # --------------------------------------------------------------- querying

    def resolve(self, name: str) -> list[str]:
        """Find qualnames matching a possibly-partial name.

        The agent (and the user it speaks for) will say `chat_node`, not
        `LangGraph.src.llm.nodes.chat.chat_node`. Matching walks from strict to loose
        and stops at the first tier that hits, so an exact name is never drowned out
        by substring matches.

        Args:
            name: Exact qualname, dotted suffix, bare identifier, or substring.

        Returns:
            Matching qualnames, best tier first.
        """
        if not name:
            return []
        if name in self.symbols:
            return [name]

        needle = name.lower()
        tiers: list[list[str]] = [[], [], []]
        for qualname, symbol in self.symbols.items():
            lowered = qualname.lower()
            if symbol.name.lower() == needle:
                tiers[0].append(qualname)
            elif lowered.endswith("." + needle) or lowered.endswith(":" + needle):
                tiers[1].append(qualname)
            elif needle in lowered:
                tiers[2].append(qualname)
        for tier in tiers:
            if tier:
                return sorted(tier)
        return []

    def out_edges(self, qualname: str, kinds: tuple[str, ...] | None = None) -> list[Edge]:
        """Edges leaving a symbol, optionally filtered by kind."""
        out, _ = self._adjacency()
        edges = out.get(qualname, [])
        return [e for e in edges if kinds is None or e.kind in kinds]

    def in_edges(self, qualname: str, kinds: tuple[str, ...] | None = None) -> list[Edge]:
        """Edges arriving at a symbol, optionally filtered by kind."""
        _, inc = self._adjacency()
        edges = inc.get(qualname, [])
        return [e for e in edges if kinds is None or e.kind in kinds]

    def neighborhood(self, qualname: str, depth: int = 1) -> dict:
        """Collect the local structure around a symbol.

        This is the half of the answer that vector search cannot produce: not "what
        is this", but "what is it wired to".

        Args:
            qualname: Exact qualname to expand from.
            depth: Hops to follow. 1 is direct neighbours.

        Returns:
            Dict with `center`, `outgoing`/`incoming` (grouped by edge kind), and
            `reached` - every qualname within `depth` hops.
        """
        out_groups: dict[str, list[dict]] = defaultdict(list)
        in_groups: dict[str, list[dict]] = defaultdict(list)

        for edge in self.out_edges(qualname):
            out_groups[edge.kind].append(self._edge_view(edge.dst, edge.detail))
        for edge in self.in_edges(qualname):
            in_groups[edge.kind].append(self._edge_view(edge.src, edge.detail))

        reached = {qualname}
        frontier = {qualname}
        for _ in range(max(depth, 1)):
            nxt: set[str] = set()
            for node in frontier:
                for edge in self.out_edges(node):
                    nxt.add(edge.dst)
                for edge in self.in_edges(node):
                    nxt.add(edge.src)
            frontier = nxt - reached
            reached |= frontier

        return {
            "center": qualname,
            "outgoing": dict(out_groups),
            "incoming": dict(in_groups),
            "reached": sorted(reached - {qualname}),
        }

    def _edge_view(self, qualname: str, detail: str) -> dict:
        """Render an edge endpoint with just enough context to be readable."""
        symbol = self.symbols.get(qualname)
        view = {
            "qualname": qualname,
            "summary": symbol.summary if symbol else "(not indexed)",
            "location": symbol.location if symbol else "",
        }
        if detail:
            view["detail"] = detail
        return view

    def shortest_path(
        self,
        start: str,
        end: str,
        kinds: tuple[str, ...] = STRUCTURAL_EDGE_KINDS,
    ) -> list[Edge]:
        """Breadth-first search for how control reaches `end` from `start`.

        Restricted to structural edge kinds by default: `contains` and `imports` would
        otherwise let the search hop through a shared parent module and return a path
        that is real in the graph but meaningless as a flow.

        Args:
            start: Source qualname.
            end: Target qualname.
            kinds: Edge kinds the path may traverse.

        Returns:
            Edges from `start` to `end`, or `[]` when unreachable.
        """
        if start == end or start not in self.symbols or end not in self.symbols:
            return []

        queue: deque[tuple[str, list[Edge]]] = deque([(start, [])])
        visited = {start}
        while queue:
            node, path = queue.popleft()
            for edge in self.out_edges(node, kinds):
                if edge.dst in visited:
                    continue
                extended = path + [edge]
                if edge.dst == end:
                    return extended
                visited.add(edge.dst)
                queue.append((edge.dst, extended))
        return []

    def modules(self) -> list[Symbol]:
        """All module symbols, ordered by qualname."""
        return sorted(
            (s for s in self.symbols.values() if s.kind == "module"),
            key=lambda s: s.qualname,
        )

    def children(self, qualname: str) -> list[Symbol]:
        """Symbols directly contained by a module or class, in source order."""
        found = [
            self.symbols[e.dst]
            for e in self.out_edges(qualname, ("contains",))
            if e.dst in self.symbols
        ]
        return sorted(found, key=lambda s: s.lineno)

    def importance(self) -> dict[str, int]:
        """Score modules by how much of the repo depends on or runs through them.

        Used to decide what earns space in a size-capped digest. Incoming imports say
        "many modules need this"; framework edges say "this is on the critical path",
        and are weighted higher because they are rarer and more diagnostic.

        Returns:
            Qualname → score, for module symbols only.
        """
        scores: dict[str, int] = defaultdict(int)
        for edge in self.edges:
            if edge.kind == "imports":
                scores[edge.dst] += 1
            elif edge.kind in ("implements", "registers", "flows_to"):
                owner = self.owning_module(edge.dst)
                if owner:
                    scores[owner] += 3
        return {q: scores.get(q, 0) for q in (m.qualname for m in self.modules())}

    def owning_module(self, qualname: str) -> str:
        """Walk `contains` edges upward to the module holding a symbol."""
        seen = set()
        current = qualname
        while current and current not in seen:
            seen.add(current)
            symbol = self.symbols.get(current)
            if symbol and symbol.kind == "module":
                return current
            parents = self.in_edges(current, ("contains",))
            if not parents:
                return ""
            current = parents[0].src
        return ""

    def stats(self) -> dict:
        """Counts by symbol kind and edge kind, plus documentation coverage.

        Coverage is reported because it is the honest ceiling on a docstring-only
        guide: an undocumented function is one the guide can locate but not explain.
        """
        by_kind: dict[str, int] = defaultdict(int)
        documented = 0
        documentable = 0
        for symbol in self.symbols.values():
            by_kind[symbol.kind] += 1
            if symbol.kind in ("module", "class", "function", "method"):
                documentable += 1
                if symbol.doc:
                    documented += 1

        edge_kinds: dict[str, int] = defaultdict(int)
        for edge in self.edges:
            edge_kinds[edge.kind] += 1

        return {
            "symbols": len(self.symbols),
            "by_kind": dict(sorted(by_kind.items())),
            "edges": len(self.edges),
            "by_edge_kind": dict(sorted(edge_kinds.items())),
            "documented": documented,
            "documentable": documentable,
            "doc_coverage_pct": round(100 * documented / documentable, 1) if documentable else 0.0,
        }

    def undocumented(self, limit: int = 20) -> list[Symbol]:
        """Undocumented symbols worth documenting first, most-referenced first."""
        _, inc = self._adjacency()
        candidates = [
            s for s in self.symbols.values()
            if not s.doc and s.kind in ("module", "class", "function", "method")
        ]
        candidates.sort(
            key=lambda s: len([e for e in inc.get(s.qualname, []) if e.kind != "contains"]),
            reverse=True,
        )
        return candidates[:limit]

    # ------------------------------------------------------------ persistence

    def to_dict(self) -> dict:
        """Serialise the whole map to plain JSON-compatible data."""
        return {
            "repo_name": self.repo_name,
            "commit": self.commit,
            "notes": self.notes,
            "symbols": [asdict(s) for s in self.symbols.values()],
            "edges": [asdict(e) for e in self.edges],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CodeMap":
        """Rebuild a map from `to_dict` output."""
        code_map = cls(
            repo_name=data.get("repo_name", ""),
            commit=data.get("commit", ""),
            notes=list(data.get("notes", [])),
        )
        code_map.symbols = {s["qualname"]: Symbol(**s) for s in data.get("symbols", [])}
        code_map.edges = [Edge(**e) for e in data.get("edges", [])]
        code_map.dedupe()
        return code_map

    def save(self, path: str | Path) -> Path:
        """Write the map to disk as JSON, creating parent directories.

        Written to a sibling temp file and renamed into place. Indexing a large repo
        takes long enough to be interrupted, and a half-written `codemap.json` is worse
        than no map at all: it makes every later `overview`, `ask` and `serve` fail on a
        parse error. `Path.replace` is atomic within a filesystem, so a reader sees
        either the previous complete map or the new one.

        Args:
            path: Destination file.

        Returns:
            The path written.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

        # Process id in the name so two concurrent indexers cannot share a temp file.
        temp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
        try:
            temp.write_text(payload, encoding="utf-8")
            temp.replace(target)
        except BaseException:
            # BaseException, not Exception: KeyboardInterrupt is the interruption this
            # guards against, and it must not leave a stray temp file behind either.
            temp.unlink(missing_ok=True)
            raise
        return target

    @classmethod
    def load(cls, path: str | Path) -> "CodeMap":
        """Read a map previously written by `save`.

        Args:
            path: File to read.

        Returns:
            The stored map.

        Raises:
            OSError: The file cannot be read.
            ValueError: The contents are not a valid map - a truncated write, say.
                `open_index` treats both as "rebuild from source" rather than failing.
        """
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
