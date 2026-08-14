"""Regression tests for the extraction layer: extractor, detectors, digest.

Every case here encodes a failure that produced a *plausible* map rather than an error,
which is the failure mode that matters for this module: the index still built, the CLI
still printed counts, and the answer was quietly wrong. A crash would have been caught
the first time it was run.

Deliberately dependency-free - `ast`, `yaml` and `tmp_path` only. No Postgres, no Ollama,
no network and no API key, so these run on a laptop with nothing started.
"""

import sys
from pathlib import Path

import pytest

# Same reason `app.py` does it: run from anywhere, the package's parent must be on the
# path before `codebase_guide.*` can be imported under its package name.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from codebase_guide.src.config import GuideConfig  # noqa: E402
from codebase_guide.src.detectors import DetectContext  # noqa: E402
from codebase_guide.src.detectors.entrypoints import EntrypointDetector  # noqa: E402
from codebase_guide.src.detectors.langgraph import LangGraphDetector  # noqa: E402
from codebase_guide.src.detectors.pygeoapi import PygeoapiDetector  # noqa: E402
from codebase_guide.src.digest import architecture_digest  # noqa: E402
from codebase_guide.src.extractors.python import PythonExtractor  # noqa: E402
from codebase_guide.src.model import CodeMap, Symbol  # noqa: E402


def _context(tmp_path: Path, files: dict[str, str]) -> DetectContext:
    """Build a detect context over a throwaway repo.

    Python files are run through the real extractor first, because the detectors read the
    symbol table language extraction produced - a hand-built map would not exercise the
    handover between the two phases.

    Args:
        tmp_path: Directory to materialise the repo in.
        files: Repo-relative path → file contents.

    Returns:
        A context the detectors can be called with. Nothing here opens a connection.
    """
    config = GuideConfig(repo_root=tmp_path, repo_name="test-repo", use_db=False)
    code_map = CodeMap(repo_name="test-repo")
    entries: list[tuple[Path, str, str]] = []
    extractor = PythonExtractor()

    for repo_relative, source in files.items():
        path = tmp_path / repo_relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        entries.append((path, repo_relative, repo_relative))
        if path.suffix == ".py":
            parse = extractor.parse(path, repo_relative)
            assert not parse.errors, parse.errors
            for symbol in parse.symbols:
                code_map.add_symbol(symbol)
            for edge in parse.edges:
                code_map.add_edge(edge)

    return DetectContext(config=config, code_map=code_map, files=entries)


# --------------------------------------------------------------- LangGraph detector

GRAPH_SOURCE = '''"""Agent graph."""

from langgraph.graph import StateGraph


def manager_node(state):
    """Route the request."""


def retriever_node(state):
    """Find candidate processes."""


def responder_node(state):
    """Answer the user."""


def build():
    """Wire the graph."""
    graph = StateGraph(dict)
    graph.add_node("manager", manager_node)
    graph.add_node("retriever", retriever_node)
    graph.add_node("responder", responder_node)

    # Three shapes this reader cannot evaluate. Each one used to raise, and one raise
    # cost the whole repo its agent nodes, its flows and its wiring note.
    graph.add_edge(start_key="manager", end_key="retriever")
    graph.add_edge(*("manager", "retriever"))
    graph.add_edge(END)

    # ...and one it can.
    graph.add_edge("retriever", "responder")
    graph.set_entry_point("manager")
    graph.set_finish_point("responder")
    return graph.compile()
'''


def test_unreadable_add_edge_costs_only_that_edge(tmp_path):
    """A keyword-argument `add_edge` must not take the graph down with it."""
    ctx = _context(tmp_path, {"agent/workflow.py": GRAPH_SOURCE})
    result = LangGraphDetector().detect(ctx)

    nodes = {s.name: s for s in result.symbols if s.kind == "agent_node"}
    assert set(nodes) == {"manager", "retriever", "responder"}

    # The implementations were resolved, so the nodes are findable by what they do.
    assert nodes["retriever"].extra["implementation"] == "agent.workflow.retriever_node"

    flows = {(e.src, e.dst) for e in result.edges if e.kind == "flows_to"}
    prefix = "agent.workflow#"
    assert (f"{prefix}retriever", f"{prefix}responder") in flows
    assert (f"{prefix}responder", "END") in flows

    # Not invented: nothing in the file states that hand-off in a form this reader can
    # verify, and a guessed edge would be quoted with a file citation like a fact.
    assert (f"{prefix}manager", f"{prefix}retriever") not in flows

    assert result.notes and "entry point: manager" in result.notes[0]


SEQUENCE_SOURCE = '''"""Sequential graph."""

from langgraph.graph import StateGraph


def fetch_step(state):
    """Fetch."""


def render_step(state):
    """Render."""


def build():
    """Wire the graph."""
    graph = StateGraph(dict)
    graph.add_sequence([("fetch", fetch_step), ("render", render_step)])
    return graph.compile()
'''


def test_add_sequence_registers_its_steps_and_their_order(tmp_path):
    """`add_sequence` is wiring too: it both declares nodes and orders them."""
    ctx = _context(tmp_path, {"agent/seq.py": SEQUENCE_SOURCE})
    result = LangGraphDetector().detect(ctx)

    assert {s.name for s in result.symbols if s.kind == "agent_node"} == {"fetch", "render"}
    flows = [(e.src, e.dst, e.detail) for e in result.edges if e.kind == "flows_to"]
    assert ("agent.seq#fetch", "agent.seq#render", "in sequence") in flows


def test_detector_is_silent_on_a_repo_without_the_framework(tmp_path):
    """A detector that does not recognise a repo returns empty, never raises."""
    ctx = _context(tmp_path, {"plain/util.py": '"""Nothing framework-ish here."""\n'})
    assert not LangGraphDetector().detect(ctx)


# ------------------------------------------------------------ cross-root imports


def test_same_named_modules_in_two_roots_do_not_collapse():
    """Two roots exposing `src.config`: the importer's own root is the right one."""
    extractor = PythonExtractor()
    modules = {
        "codebase_guide.src.config",
        "codebase_guide.src.index",
        "ogc_database.src.config",
        "ogc_database.src.pipeline",
        "LangGraph.src.app",
    }

    assert extractor._resolve_module(
        "src.config", modules, "codebase_guide.src.index"
    ) == "codebase_guide.src.config"
    assert extractor._resolve_module(
        "src.config", modules, "ogc_database.src.pipeline"
    ) == "ogc_database.src.config"

    # No candidate under the importer's root: genuinely ambiguous, so nothing is emitted.
    # A wrong `imports` edge is not a harmless guess - it feeds `importance()`, and the
    # briefing presents the winner as a module the rest of the code depends on.
    assert extractor._resolve_module("src.config", modules, "LangGraph.src.app") == ""

    # An unambiguous suffix still resolves, importer or no importer.
    assert extractor._resolve_module("src.pipeline", modules) == "ogc_database.src.pipeline"


def test_import_edge_points_inside_the_importers_own_root(tmp_path):
    """End to end: parse two roots that both define `src.config`, then link them."""
    extractor = PythonExtractor()
    files = {
        "alpha/src/config.py": '"""Alpha settings."""\n',
        "alpha/src/index.py": '"""Alpha index."""\nfrom src.config import Thing\n',
        "beta/src/config.py": '"""Beta settings."""\n',
        "beta/src/index.py": '"""Beta index."""\nfrom src.config import Thing\n',
    }
    parses = []
    for repo_relative, source in files.items():
        path = tmp_path / repo_relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        parses.append(extractor.parse(path, repo_relative))

    symbols = {s.qualname: s for p in parses for s in p.symbols}
    imports = {
        (e.src, e.dst) for e in extractor.link(symbols, parses) if e.kind == "imports"
    }
    assert imports == {
        ("alpha.src.index", "alpha.src.config"),
        ("beta.src.index", "beta.src.config"),
    }


# ------------------------------------------------------------------------- digest


def _digest_map(note_count: int = 3, note_chars: int = 1500) -> CodeMap:
    """A small documented repo carrying detector notes far larger than a tight budget."""
    code_map = CodeMap(repo_name="demo")
    for name in ("demo.api", "demo.core", "demo.util"):
        code_map.add_symbol(Symbol(
            qualname=name, kind="module", name=name.split(".")[-1],
            file=f"{name.replace('.', '/')}.py", lineno=1,
            doc=f"The {name} module.",
        ))
    code_map.notes = [
        f"Agent graph {i} wired in demo/api.py:\n" + ("  BULKY_WIRING_LINE\n" * (note_chars // 20))
        for i in range(note_count)
    ]
    return code_map


@pytest.mark.parametrize("max_chars", [0, 60, 120, 500, 2000, 24000])
def test_digest_never_exceeds_its_budget(max_chars):
    """The cap is a hard ceiling, at every size - including ones nothing fits into."""
    assert len(architecture_digest(_digest_map(), max_chars)) <= max_chars


def test_tight_digest_announces_what_it_dropped():
    """A shrunken briefing must not read like a complete one."""
    digest = architecture_digest(_digest_map(), 500)

    assert len(digest) <= 500
    assert "BULKY_WIRING_LINE" not in digest          # the notes really were cut
    assert "GUIDE_DIGEST_MAX_CHARS" in digest         # ...and the knob is named
    assert "wiring notes" in digest                   # ...and so is what went missing
    assert "# Codebase: demo" in digest               # the load-bearing part survived


def test_generous_digest_keeps_the_notes_whole():
    """The counterpart: with room, nothing is dropped and nothing is announced."""
    digest = architecture_digest(_digest_map(note_count=1, note_chars=200), 24000)

    assert "BULKY_WIRING_LINE" in digest
    assert "Reduced briefing" not in digest
    assert "briefing cut at" not in digest


# --------------------------------------------------------------- HTTP entry points

API_SOURCE = '''"""Guide API."""

from fastapi import APIRouter, FastAPI

router = APIRouter(prefix="/guide", tags=["guide"])
app = FastAPI()
detached = APIRouter(prefix=PREFIX_FROM_SETTINGS)


@router.post("/ask")
async def ask(question: str):
    """Answer a question about the codebase."""


@app.get("/health")
def health():
    """Liveness probe."""


@detached.get("/thing")
def thing():
    """Served under a prefix this file does not state."""


if __name__ != "__main__":
    raise RuntimeError("import me, do not run me")
'''

SCRIPT_SOURCE = '''"""A real script."""


def main():
    """Do the thing."""


if __name__ == "__main__":
    main()
'''


def test_route_urls_carry_their_router_prefix(tmp_path):
    """`APIRouter(prefix="/guide")` plus `@router.post("/ask")` serves `/guide/ask`."""
    ctx = _context(tmp_path, {"svc/api.py": API_SOURCE, "svc/run.py": SCRIPT_SOURCE})
    result = EntrypointDetector().detect(ctx)

    routes = {s.qualname: s for s in result.symbols if s.kind == "http_route"}
    assert "http:POST /guide/ask" in routes
    assert routes["http:POST /guide/ask"].extra["path_kind"] == "absolute"
    assert ctx.code_map.symbols["svc.api.ask"].extra["http"] == "POST /guide/ask"

    # A prefixless app is still absolute; the bug was reporting *everything* that way.
    assert "http:GET /health" in routes

    # An unreadable prefix is reported as relative rather than silently as absolute.
    relative = routes["http:GET /thing"]
    assert relative.extra["path_kind"] == "router-relative"
    assert "relative to its router" in relative.signature

    assert {e.src for e in result.edges if e.kind == "registers"} <= set(routes)


def test_a_negated_main_guard_is_not_a_script(tmp_path):
    """`if __name__ != "__main__":` is the opposite claim, and used to count as runnable."""
    ctx = _context(tmp_path, {"svc/api.py": API_SOURCE, "svc/run.py": SCRIPT_SOURCE})
    result = EntrypointDetector().detect(ctx)

    scripts = [n for n in result.notes if n.startswith("Runnable as a script")]
    assert len(scripts) == 1
    assert "svc/run.py" in scripts[0]
    assert "svc/api.py" not in scripts[0]


# -------------------------------------------------------------- pygeoapi registry

PYGEOAPI_CONFIG = """
server:
  bind:
    host: 0.0.0.0
resources:
  buffer:
    type: process
    title: Buffer
    description: Buffer a geometry.
    processor:
      name: processes.buffer.BufferProcessor
  centroid:
    type: process
    processor:
      name: processes.centroid.CentroidProcessor
  observations:
    type: collection
"""

BUFFER_SOURCE = '''"""Buffer process."""


class BufferProcessor:
    """Buffer an input geometry by a distance."""

    def execute(self, data):
        """Run it."""
'''


def test_registering_config_file_is_itself_a_symbol(tmp_path):
    """A `registers` edge has to start somewhere the map can actually look up."""
    ctx = _context(tmp_path, {
        "pygeoapi_instance/pygeoapi-config.yml": PYGEOAPI_CONFIG,
        "pygeoapi_instance/processes/buffer.py": BUFFER_SOURCE,
    })
    result = PygeoapiDetector().detect(ctx)

    emitted = {s.qualname for s in result.symbols}
    assert "config:pygeoapi_instance/pygeoapi-config.yml" in emitted
    assert {"process:buffer", "process:centroid"} <= emitted
    assert "process:observations" not in emitted  # not a process resource

    # The point of the fix: every registration edge is traversable from both ends, so
    # `shortest_path` can start at the config and `explain_symbol` stops saying
    # "(not indexed)".
    registers = [e for e in result.edges if e.kind == "registers"]
    assert registers
    assert all(e.src in emitted for e in registers)

    implements = {(e.src, e.dst) for e in result.edges if e.kind == "implements"}
    assert ("process:buffer",
            "pygeoapi_instance.processes.buffer.BufferProcessor") in implements
