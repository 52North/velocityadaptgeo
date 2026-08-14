"""Configuration for the codebase guide.

The guide is repo-agnostic: everything that ties it to a particular codebase lives
in a `GuideConfig`, which can be built from environment variables, from a
`codebase-guide.json` file in the target repo, or constructed directly.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILENAME = "codebase-guide.json"

# Directory names never worth walking into, whatever the target repo looks like.
DEFAULT_EXCLUDED_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "site-packages", "dist", "build",
    ".tox", ".idea", ".vscode", "target", ".gradle", ".next", "coverage",
})

# Fallbacks, used when the corresponding environment variable is unset. They are read
# through the accessors below rather than captured at import time: a host application
# that calls `load_dotenv()` during its own startup has already imported this module, so
# import-time capture would silently ignore everything in its `.env` - the kind of bug
# that presents as "the guide keeps talking to localhost".
DEFAULT_DB_DSN = "postgresql://postgres:postgres@localhost:5432/velocityadaptgeo"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "nomic-embed-text"
DEFAULT_EMBED_DIM = 768
DEFAULT_CHAT_MODEL = "claude-opus-5"
# A walkthrough that names every location it mentions runs long, and a truncated
# explanation reads exactly like a wrong one, so the answer budget is generous.
DEFAULT_MAX_ANSWER_TOKENS = 4096
# Upper bound on the architecture digest injected into the system prompt. The digest
# is what keeps the agent from having to *discover* the repo layout by search; it is
# capped so a large repo degrades to "top-level map only" instead of blowing the
# context window.
DEFAULT_DIGEST_MAX_CHARS = 24000
# Both storage backends get an explicit timeout. Without one, a half-open port - a
# stopped Docker Desktop still holding its proxy, say - makes the guide hang instead of
# falling back to lexical search, and a hang is the one failure mode with no message.
DEFAULT_DB_CONNECT_TIMEOUT = 10
DEFAULT_OLLAMA_TIMEOUT = 120.0


def env_str(name: str, default: str) -> str:
    """Read a string setting from the environment, treating empty as unset."""
    return os.environ.get(name) or default


def env_num(name: str, default: float) -> float:
    """Read a numeric setting, falling back on anything unparseable."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def db_dsn() -> str:
    """Postgres DSN for the index. `$DB_DSN`, shared with the rest of the stack."""
    return env_str("DB_DSN", DEFAULT_DB_DSN)


def ollama_base_url() -> str:
    """Where to reach Ollama for embeddings. `$OLLAMA_BASE_URL`."""
    return env_str("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)


def ollama_model() -> str:
    """Embedding model name. `$OLLAMA_MODEL`."""
    return env_str("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)


def embed_dim() -> int:
    """Embedding width, which must match the `VECTOR(n)` column. `$EMBED_DIM`."""
    return int(env_num("EMBED_DIM", DEFAULT_EMBED_DIM))


def chat_model() -> str:
    """Anthropic model that answers questions. `$GUIDE_CHAT_MODEL`."""
    return env_str("GUIDE_CHAT_MODEL", DEFAULT_CHAT_MODEL)


def max_answer_tokens() -> int:
    """Answer length cap. `$GUIDE_MAX_ANSWER_TOKENS`."""
    return int(env_num("GUIDE_MAX_ANSWER_TOKENS", DEFAULT_MAX_ANSWER_TOKENS))


def digest_max_chars() -> int:
    """Architecture briefing cap. `$GUIDE_DIGEST_MAX_CHARS`."""
    return int(env_num("GUIDE_DIGEST_MAX_CHARS", DEFAULT_DIGEST_MAX_CHARS))


def db_connect_timeout() -> int:
    """Seconds to wait for Postgres. `$GUIDE_DB_CONNECT_TIMEOUT`."""
    return int(env_num("GUIDE_DB_CONNECT_TIMEOUT", DEFAULT_DB_CONNECT_TIMEOUT))


def ollama_timeout() -> float:
    """Seconds to wait for Ollama. `$GUIDE_OLLAMA_TIMEOUT`."""
    return env_num("GUIDE_OLLAMA_TIMEOUT", DEFAULT_OLLAMA_TIMEOUT)


def resolve_repo_root(repo_root: str | Path | None = None) -> Path:
    """Resolve which repository to explain: explicit path, then `$GUIDE_REPO_ROOT`, then cwd.

    Exposed rather than inlined into `GuideConfig.load` because a caller sometimes needs
    the root *before* the config exists - the CLI has to know it to find `<repo>/.env`,
    and that file may itself set `$DB_DSN`, which the config captures at construction.
    Two copies of this precedence would drift.

    Args:
        repo_root: Explicit repository path, or None to fall back to the environment.

    Returns:
        An absolute, resolved path.
    """
    return Path(repo_root or os.environ.get("GUIDE_REPO_ROOT") or Path.cwd()).resolve()


@dataclass
class GuideConfig:
    """Everything the guide needs to know about one target codebase.

    Attributes:
        repo_root: Absolute path to the repository to explain.
        repo_name: Short identifier, used as the partition key in the index.
        roots: Sub-paths of `repo_root` to walk. Empty means "discover automatically".
        excluded_dirs: Directory names to skip while walking.
        map_path: Where the extracted code map JSON is written/read.
        db_dsn: Postgres DSN for the pgvector-backed index. Empty means `$DB_DSN`.
        use_db: When False the guide runs purely off `map_path` with lexical search.
    """

    repo_root: Path
    repo_name: str = ""
    roots: list[str] = field(default_factory=list)
    excluded_dirs: frozenset[str] = DEFAULT_EXCLUDED_DIRS
    map_path: Path | None = None
    db_dsn: str = ""
    use_db: bool = True

    def __post_init__(self) -> None:
        self.repo_root = Path(self.repo_root).resolve()
        if not self.db_dsn:
            self.db_dsn = db_dsn()
        if not self.repo_name:
            self.repo_name = self.repo_root.name
        if self.map_path is None:
            self.map_path = self.repo_root / ".codebase-guide" / "codemap.json"
        else:
            self.map_path = Path(self.map_path)

    @classmethod
    def load(cls, repo_root: str | Path | None = None, **overrides) -> "GuideConfig":
        """Build a config from a repo's `codebase-guide.json`, env vars, and overrides.

        Precedence is overrides > file > environment default. A missing config file is
        not an error; auto-discovery covers the common case.

        Args:
            repo_root: Repository to explain. Defaults to `$GUIDE_REPO_ROOT` or cwd.
            **overrides: Any `GuideConfig` field, taking final precedence.

        Returns:
            A resolved `GuideConfig`.
        """
        root = resolve_repo_root(repo_root)

        settings: dict = {}
        config_file = root / CONFIG_FILENAME
        if config_file.exists():
            settings = json.loads(config_file.read_text(encoding="utf-8"))

        if env_roots := os.environ.get("GUIDE_ROOTS"):
            settings["roots"] = [r.strip() for r in env_roots.split(",") if r.strip()]

        if extra := settings.pop("extra_excluded_dirs", None):
            settings["excluded_dirs"] = DEFAULT_EXCLUDED_DIRS | frozenset(extra)

        settings.update(overrides)
        settings.pop("repo_root", None)
        return cls(repo_root=root, **settings)

    def source_roots(self) -> list[Path]:
        """Resolve the directories to walk, discovering them when none are configured.

        Discovery keeps only top-level directories that actually contain source files,
        so a repo full of data and notebooks does not produce an empty index.

        Returns:
            Absolute paths to walk. Falls back to `[repo_root]`.
        """
        if self.roots:
            return [self.repo_root / r for r in self.roots]

        discovered = [
            child for child in sorted(self.repo_root.iterdir())
            if child.is_dir()
            and child.name not in self.excluded_dirs
            and not child.name.startswith(".")
            and self._has_source(child)
        ]
        # Loose top-level files (a bare app.py) still belong in the map.
        if any(self.repo_root.glob("*.py")):
            discovered.append(self.repo_root)
        return discovered or [self.repo_root]

    def _has_source(self, directory: Path) -> bool:
        """Whether a directory holds any indexable source file, excluded dirs aside."""
        for path in directory.rglob("*.py"):
            if not self.is_excluded(path):
                return True
        return False

    def is_excluded(self, path: Path) -> bool:
        """Whether any path component names an excluded directory."""
        return any(part in self.excluded_dirs for part in path.parts)

    def relative(self, path: Path) -> str:
        """Repo-relative POSIX path, used as the stable file identifier in the map."""
        try:
            return path.resolve().relative_to(self.repo_root).as_posix()
        except ValueError:
            return path.as_posix()
