"""Regression tests for the guide's configuration and index layers.

Everything here runs against a throwaway repository under `tmp_path`, with no Postgres,
no Ollama, no network and no API key - which is the point: the paths under test are the
ones the module promises work on a base install, and a test that needed infrastructure
could not tell whether they still do.

Run with `python -m pytest codebase_guide/tests` from the repository root.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

# The directory holding `codebase_guide/`, so these tests import the package the same way
# a host application does. Done here rather than in a `conftest.py` to keep the file
# self-contained; `python -m pytest` from the repo root would work either way.
PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from codebase_guide import app as guide_cli  # noqa: E402
from codebase_guide.src.config import GuideConfig  # noqa: E402
from codebase_guide.src.index import open_index, render_init_sql  # noqa: E402
from codebase_guide.src.model import CodeMap, Edge, Symbol  # noqa: E402

# Never a real credential: this only has to be distinguishable from the built-in default.
FIXTURE_DSN = "postgresql://u:p@fixture-host:5432/fixture"


def _tiny_repo(tmp_path: Path) -> Path:
    """Create a minimal but real Python repository for the extractor to walk.

    Args:
        tmp_path: Pytest-provided scratch directory.

    Returns:
        The repository root.
    """
    repo = tmp_path / "repo"
    package = repo / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""The pkg package."""\n', encoding="utf-8")
    (package / "thing.py").write_text(
        '"""Module that does a thing."""\n'
        "\n"
        "\n"
        "def do_thing(value: int) -> int:\n"
        '    """Double a number."""\n'
        "    return value * 2\n",
        encoding="utf-8",
    )
    return repo


# ------------------------------------------------------- a broken map on disk

def test_open_index_rebuilds_from_a_truncated_map(tmp_path, caplog):
    """A map left half-written by an interrupted `index` must not be fatal.

    `CodeMap.load` used to be called unguarded, so a truncated `codemap.json` made
    every later `overview`, `ask` and `serve` die on a raw JSONDecodeError.
    """
    repo = _tiny_repo(tmp_path)
    config = GuideConfig(repo_root=repo, use_db=False)
    config.map_path.parent.mkdir(parents=True, exist_ok=True)
    config.map_path.write_text('{"repo_name": "repo", "symb', encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="codebase-guide"):
        index = open_index(config)

    assert index.code_map.resolve("do_thing"), "the map should have been rebuilt from source"
    assert "unusable" in caplog.text
    assert index.backend == "lexical"


def test_open_index_rebuilds_from_a_map_that_is_not_json_at_all(tmp_path):
    """Same degradation for a file that was never a map - a stray editor swap, say."""
    repo = _tiny_repo(tmp_path)
    config = GuideConfig(repo_root=repo, use_db=False)
    config.map_path.parent.mkdir(parents=True, exist_ok=True)
    config.map_path.write_text("not json", encoding="utf-8")

    assert open_index(config).code_map.resolve("do_thing")


# ------------------------------------------------------------ atomic map write

def test_save_leaves_the_previous_map_intact_when_the_write_fails(tmp_path, monkeypatch):
    """A failed `save` must not destroy the map that was already there.

    The rename is what makes this true, so the rename is what the test breaks.
    """
    target = tmp_path / "codemap.json"

    good = CodeMap(repo_name="good")
    good.add_symbol(Symbol(qualname="pkg.a", kind="function", name="a", doc="Keep me."))
    good.save(target)

    doomed = CodeMap(repo_name="doomed")
    doomed.add_symbol(Symbol(qualname="pkg.b", kind="function", name="b"))

    def interrupted_replace(self, target_path):  # noqa: ARG001 - signature must match
        raise OSError("interrupted before the rename")

    monkeypatch.setattr(Path, "replace", interrupted_replace)

    with pytest.raises(OSError):
        doomed.save(target)

    survivor = CodeMap.load(target)
    assert survivor.repo_name == "good"
    assert "pkg.a" in survivor.symbols
    assert list(tmp_path.glob("*.tmp")) == [], "the temp file must not be left behind"


def test_save_writes_through_a_temp_file_and_returns_the_target(tmp_path):
    """The happy path still ends with exactly one file: the map itself."""
    target = tmp_path / "nested" / "codemap.json"
    code_map = CodeMap(repo_name="fresh")
    code_map.add_symbol(Symbol(qualname="pkg.a", kind="module", name="pkg.a", doc="Hi."))

    written = code_map.save(target)

    assert written == target
    assert json.loads(target.read_text(encoding="utf-8"))["repo_name"] == "fresh"
    assert sorted(p.name for p in target.parent.iterdir()) == ["codemap.json"]


# --------------------------------------------------------- .env load ordering

def test_config_loads_dotenv_before_capturing_the_dsn(tmp_path, monkeypatch):
    """`_config` must read `<repo>/.env` before `GuideConfig` freezes the DSN.

    The config used to be built first, so a `.env` naming the real database was ignored
    and `index` embedded into whatever was listening on localhost.
    """
    pytest.importorskip("dotenv", reason="the .env path needs python-dotenv")

    repo = _tiny_repo(tmp_path)
    (repo / ".env").write_text(f"DB_DSN={FIXTURE_DSN}\n", encoding="utf-8")
    monkeypatch.delenv("GUIDE_REPO_ROOT", raising=False)
    monkeypatch.delenv("GUIDE_ROOTS", raising=False)

    args = argparse.Namespace(
        repo=str(repo), no_db=True, roots=None, name=None, env_file=None
    )

    # `load_dotenv` mutates `os.environ` for the whole process, and monkeypatch only
    # undoes keys it set itself, so this one is restored by hand.
    previous = os.environ.pop("DB_DSN", None)
    try:
        config = guide_cli._config(args)
    finally:
        os.environ.pop("DB_DSN", None)
        if previous is not None:
            os.environ["DB_DSN"] = previous

    assert config.db_dsn == FIXTURE_DSN
    assert config.repo_root == repo.resolve()


def test_explicit_env_file_wins_over_the_repo_dotenv(tmp_path, monkeypatch):
    """`--env-file` is documented as taking precedence, and `<repo>/.env` must be ignored."""
    pytest.importorskip("dotenv", reason="the .env path needs python-dotenv")

    repo = _tiny_repo(tmp_path)
    (repo / ".env").write_text("DB_DSN=postgresql://u:p@wrong-host:5432/wrong\n", encoding="utf-8")
    chosen = tmp_path / "chosen.env"
    chosen.write_text(f"DB_DSN={FIXTURE_DSN}\n", encoding="utf-8")
    monkeypatch.delenv("GUIDE_REPO_ROOT", raising=False)

    args = argparse.Namespace(
        repo=str(repo), no_db=True, roots=None, name=None, env_file=str(chosen)
    )

    previous = os.environ.pop("DB_DSN", None)
    try:
        config = guide_cli._config(args)
    finally:
        os.environ.pop("DB_DSN", None)
        if previous is not None:
            os.environ["DB_DSN"] = previous

    assert config.db_dsn == FIXTURE_DSN


# ------------------------------------------------------------ edge dedup

def _two_modules() -> CodeMap:
    """A map holding two module symbols, ready for edges between them."""
    code_map = CodeMap(repo_name="r")
    for qualname in ("mod.a", "mod.b"):
        code_map.add_symbol(Symbol(qualname=qualname, kind="module", name=qualname))
    return code_map


def test_add_edge_ignores_an_identical_edge():
    """`add_edge` documents dedup, so it must actually dedup."""
    code_map = _two_modules()
    code_map.add_edge(Edge(src="mod.a", dst="mod.b", kind="imports"))
    code_map.add_edge(Edge(src="mod.a", dst="mod.b", kind="imports"))

    assert len(code_map.edges) == 1


def test_add_edge_keeps_edges_that_differ_in_detail_or_kind():
    """Dedup is on the full identity tuple; a different call site is a different edge."""
    code_map = _two_modules()
    code_map.add_edge(Edge(src="mod.a", dst="mod.b", kind="imports"))
    code_map.add_edge(Edge(src="mod.a", dst="mod.b", kind="imports", detail="line 3"))
    code_map.add_edge(Edge(src="mod.a", dst="mod.b", kind="calls"))

    assert len(code_map.edges) == 3


def test_add_edge_still_dedups_after_the_adjacency_indexes_are_read():
    """Reading the graph between inserts must not invalidate the dedup key set."""
    code_map = _two_modules()
    code_map.add_edge(Edge(src="mod.a", dst="mod.b", kind="imports"))
    assert len(code_map.out_edges("mod.a")) == 1

    code_map.add_edge(Edge(src="mod.a", dst="mod.b", kind="imports"))

    assert len(code_map.edges) == 1
    assert len(code_map.out_edges("mod.a")) == 1


def test_duplicate_imports_do_not_inflate_importance():
    """The reason dedup matters: `importance()` counts every `imports` edge separately."""
    code_map = _two_modules()
    for _ in range(4):
        code_map.add_edge(Edge(src="mod.a", dst="mod.b", kind="imports"))

    assert code_map.importance()["mod.b"] == 1


def test_dedupe_still_cleans_up_a_wholesale_edge_assignment():
    """`dedupe()` remains necessary for the deserialising paths, which bypass `add_edge`."""
    code_map = _two_modules()
    duplicate = Edge(src="mod.a", dst="mod.b", kind="imports")
    code_map.edges = [duplicate, Edge(src="mod.a", dst="mod.b", kind="imports")]

    code_map.dedupe()

    assert len(code_map.edges) == 1
    # And the key set it leaves behind must still reject a further duplicate.
    code_map.add_edge(Edge(src="mod.a", dst="mod.b", kind="imports"))
    assert len(code_map.edges) == 1


def test_from_dict_round_trips_a_map_with_duplicate_edges():
    """A map deserialised from stored JSON must not gain duplicates either."""
    data = {
        "repo_name": "r",
        "commit": "",
        "notes": [],
        "symbols": [{"qualname": "mod.a", "kind": "module", "name": "mod.a"}],
        "edges": [
            {"src": "mod.a", "dst": "mod.b", "kind": "imports", "detail": ""},
            {"src": "mod.a", "dst": "mod.b", "kind": "imports", "detail": ""},
        ],
    }

    assert len(CodeMap.from_dict(data).edges) == 1


# ---------------------------------------------------------------- schema file

def test_init_sql_matches_the_generated_schema():
    """`sql/init.sql` is generated, and drifting from `schema_statements` is a failure.

    `read_text` normalises newlines, so a CRLF checkout does not fail this.
    """
    init_sql = Path(__file__).resolve().parents[1] / "sql" / "init.sql"

    assert init_sql.read_text(encoding="utf-8") == render_init_sql()


# --------------------------------------------------------- import isolation

def test_importing_the_router_does_not_pull_in_the_agent_extra():
    """Mounting the HTTP surface must work on an install without langgraph.

    Checked in a subprocess: another test in this session may already have imported
    the agent, and `sys.modules` here would then prove nothing.
    """
    pytest.importorskip("fastapi", reason="the router needs the `serve` extra")

    probe = (
        "import sys, codebase_guide.src.api;"
        "print([m for m in ('langgraph', 'langchain_core', 'langchain_anthropic')"
        " if m in sys.modules])"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(PACKAGE_PARENT), capture_output=True, text=True, timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]", f"agent extra leaked: {result.stdout}"
