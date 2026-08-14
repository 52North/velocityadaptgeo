"""Build a `CodeMap` for a repository: walk, extract, link, detect.

Order matters. Language extraction must finish before linking, because a reference
can only be resolved against the complete symbol table; linking must finish before
detection, because detectors resolve config strings like
`processes.buffer.BufferProcessor` against the symbols already found.
"""

import logging
import subprocess
from pathlib import Path

from .config import GuideConfig
from .detectors import DetectContext, run_detectors
from .extractors import EXTRACTORS, FileParse, extractor_for
from .model import CodeMap

logger = logging.getLogger("codebase-guide")


def discover_files(config: GuideConfig) -> list[tuple[Path, str]]:
    """Collect every extractable source file in the configured roots.

    Args:
        config: Target repo configuration.

    Returns:
        (absolute path, repo-relative path) pairs, deduplicated and sorted. Roots can
        overlap - `repo_root` is itself a root when loose files exist - so the same
        file must not be parsed twice.
    """
    suffixes = {s for extractor in EXTRACTORS for s in extractor.suffixes}
    seen: set[Path] = set()
    files: list[tuple[Path, str]] = []

    for root in config.source_roots():
        if not root.exists():
            logger.warning("Configured root does not exist: %s", root)
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            if config.is_excluded(path):
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append((path, config.relative(path)))

    return files


def discover_config_files(config: GuideConfig) -> list[tuple[Path, str]]:
    """Collect the config files detectors care about (currently YAML).

    Kept separate from `discover_files`: these are never parsed for docstrings, only
    read for wiring. Confined to the configured roots plus the repo's own top level -
    a root list that deliberately leaves a directory out must not have that directory's
    wiring reappear here, and stack-level manifests (`docker-compose.yml`) sit at the top.

    Args:
        config: Target repo configuration.

    Returns:
        (absolute path, repo-relative path) pairs, deduplicated and sorted.
    """
    patterns = ("*.yml", "*.yaml")
    seen: set[Path] = set()
    files: list[tuple[Path, str]] = []

    searches = [(root, True) for root in config.source_roots()]
    searches.append((config.repo_root, False))

    for directory, recursive in searches:
        if not directory.exists():
            continue
        for pattern in patterns:
            found = directory.rglob(pattern) if recursive else directory.glob(pattern)
            for path in sorted(found):
                resolved = path.resolve()
                if not path.is_file() or config.is_excluded(path) or resolved in seen:
                    continue
                seen.add(resolved)
                files.append((path, config.relative(path)))

    return sorted(files, key=lambda pair: pair[1])


def git_commit(repo_root: Path) -> str:
    """Short commit hash of the repo, or "" when it is not a git checkout."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def build_code_map(config: GuideConfig) -> CodeMap:
    """Extract a complete code map for the configured repository.

    Args:
        config: Target repo configuration.

    Returns:
        A populated `CodeMap`. Parse errors are logged and skipped rather than fatal:
        one unparseable file should not deny the guide the other two hundred.
    """
    code_map = CodeMap(repo_name=config.repo_name, commit=git_commit(config.repo_root))

    source_files = discover_files(config)
    logger.info("Parsing %d source files under %s", len(source_files), config.repo_root)

    parses_by_extractor: dict[str, list[FileParse]] = {}
    errors: list[str] = []

    for path, repo_relative in source_files:
        extractor = extractor_for(path)
        if extractor is None:
            continue
        parse = extractor.parse(path, repo_relative)
        errors.extend(parse.errors)
        for symbol in parse.symbols:
            code_map.add_symbol(symbol)
        for edge in parse.edges:
            code_map.add_edge(edge)
        parses_by_extractor.setdefault(extractor.name, []).append(parse)

    for extractor in EXTRACTORS:
        parses = parses_by_extractor.get(extractor.name)
        if not parses:
            continue
        for edge in extractor.link(code_map.symbols, parses):
            code_map.add_edge(edge)

    detect_files = [
        (path, repo_relative, repo_relative)
        for path, repo_relative in [*source_files, *discover_config_files(config)]
    ]
    detected = run_detectors(DetectContext(config=config, code_map=code_map, files=detect_files))
    for symbol in detected.symbols:
        code_map.add_symbol(symbol)
    for edge in detected.edges:
        code_map.add_edge(edge)
    code_map.notes.extend(detected.notes)

    code_map.dedupe()

    if errors:
        logger.warning("%d file(s) could not be parsed:", len(errors))
        for error in errors[:10]:
            logger.warning("  %s", error)

    stats = code_map.stats()
    logger.info(
        "Map built: %d symbols, %d edges, %.1f%% documented",
        stats["symbols"], stats["edges"], stats["doc_coverage_pct"],
    )
    return code_map
