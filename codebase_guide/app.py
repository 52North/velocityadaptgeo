"""Command line entry point for the codebase guide.

    python app.py index                      # extract + embed the target repo
    python app.py overview                   # print the architecture briefing
    python app.py ask "how does a request become a workflow?"
    python app.py chat                       # interactive session
    python app.py serve                      # HTTP API on :8100

Point it at any repository with `--repo`, or `$GUIDE_REPO_ROOT`. With `--no-db` it runs
entirely off a JSON map and lexical search, which needs no Postgres and no Ollama.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from codebase_guide.src.build import build_code_map  
from codebase_guide.src.config import (  
    GuideConfig,
    digest_max_chars,
    resolve_repo_root,
)
from codebase_guide.src.digest import architecture_digest  
from codebase_guide.src.index import open_index, write_index  

logger = logging.getLogger("codebase-guide")


def _load_env(args: argparse.Namespace, repo_root: Path) -> None:
    """Load a `.env` file so credentials need not be exported by hand.

    Explicit `--env-file` wins; otherwise `<repo>/.env` is used when present. Nothing is
    loaded silently from elsewhere, and values are never logged.
    """
    candidates = [Path(args.env_file)] if args.env_file else [repo_root / ".env"]
    for candidate in candidates:
        if candidate.exists():
            try:
                from dotenv import load_dotenv
            except ImportError:
                logger.warning("python-dotenv not installed; ignoring %s", candidate)
                return
            load_dotenv(candidate, override=False)
            logger.info("Loaded environment from %s", candidate)
            return


def _config(args: argparse.Namespace) -> GuideConfig:
    """Build the target-repo config from CLI arguments.

    The `.env` is loaded *before* the config is constructed, not after: `GuideConfig`
    captures the DSN at construction, so loading afterwards would leave the config
    pointing at `localhost` while the environment named the real host - and `index`
    would then embed the whole repo into whatever was listening locally.
    """
    overrides: dict = {"use_db": not args.no_db}
    if args.roots:
        overrides["roots"] = [r.strip() for r in args.roots.split(",") if r.strip()]
    if args.name:
        overrides["repo_name"] = args.name

    repo_root = resolve_repo_root(args.repo)
    _load_env(args, repo_root)
    return GuideConfig.load(repo_root, **overrides)


def cmd_index(args: argparse.Namespace) -> int:
    """Extract the code map, write it to disk, and embed it into Postgres."""
    config = _config(args)
    code_map = build_code_map(config)
    digest = architecture_digest(code_map, digest_max_chars())

    path = code_map.save(config.map_path)
    stats = code_map.stats()
    print(f"Wrote map to {path}")
    print(
        f"{stats['symbols']} symbols, {stats['edges']} edges, "
        f"{stats['doc_coverage_pct']}% documented"
    )
    print(f"  symbols: {stats['by_kind']}")
    print(f"  edges:   {stats['by_edge_kind']}")

    if config.use_db:
        try:
            count = write_index(config, code_map, digest)
            print(f"Embedded {count} symbols into {config.repo_name} (pgvector)")
        except Exception as exc:
            print(f"Vector index skipped: {exc}", file=sys.stderr)
            print("The map on disk still works, with lexical search.", file=sys.stderr)
            return 1
    else:
        print("Vector index skipped (--no-db); lexical search will be used.")

    gaps = code_map.undocumented(limit=5)
    if gaps:
        print("\nMost-referenced undocumented symbols (document these first):")
        for symbol in gaps:
            print(f"  {symbol.qualname} ({symbol.location})")
    return 0


def cmd_overview(args: argparse.Namespace) -> int:
    """Print the architecture briefing the agent is given."""
    index = open_index(_config(args))
    print(f"[index backend: {index.backend}]\n")
    print(index.digest)
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    """Answer a single question."""
    from codebase_guide.src.agent import ask, build_guide_agent

    index = open_index(_config(args))
    agent = build_guide_agent(index)
    print(ask(agent, " ".join(args.question), thread_id=args.thread))
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    """Hold a multi-turn conversation, keeping context across questions."""
    from codebase_guide.src.agent import ask, build_guide_agent

    index = open_index(_config(args))
    agent = build_guide_agent(index)
    print(
        f"Guide ready for '{index.repo_name}' ({index.backend} search). "
        "Ask anything; Ctrl-C or 'exit' to finish.\n"
    )
    while True:
        try:
            question = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if question.lower() in {"exit", "quit"}:
            return 0
        if not question:
            continue
        print()
        print(ask(agent, question, thread_id=args.thread))
        print()


def cmd_serve(args: argparse.Namespace) -> int:
    """Serve the guide over HTTP."""
    import uvicorn
    from fastapi import FastAPI

    from codebase_guide.src.api import guide_router

    app = FastAPI(title="Codebase guide")
    app.include_router(guide_router(config=_config(args)))
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to a subcommand."""
    parser = argparse.ArgumentParser(
        prog="codebase-guide", description="Explain a codebase like a senior colleague."
    )
    parser.add_argument("--repo", help="Repository to explain (default: $GUIDE_REPO_ROOT or cwd)")
    parser.add_argument("--name", help="Index partition name (default: repo directory name)")
    parser.add_argument("--roots", help="Comma-separated sub-paths to index")
    parser.add_argument(
        "--no-db", action="store_true",
        help="Run without Postgres/Ollama: JSON map plus lexical search",
    )
    parser.add_argument(
        "--env-file",
        help="Path to a .env holding ANTHROPIC_API_KEY etc. (default: <repo>/.env)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Log progress")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("index", help="Extract and embed the codebase").set_defaults(func=cmd_index)
    sub.add_parser("overview", help="Print the architecture briefing").set_defaults(
        func=cmd_overview
    )

    ask_parser = sub.add_parser("ask", help="Ask one question")
    ask_parser.add_argument("question", nargs="+")
    ask_parser.set_defaults(func=cmd_ask)

    chat_parser = sub.add_parser("chat", help="Interactive session")
    chat_parser.set_defaults(func=cmd_chat)

    serve_parser = sub.add_parser("serve", help="Serve the HTTP API")
    serve_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1; pass 0.0.0.0 to expose the "
             "unauthenticated API beyond this machine)",
    )
    serve_parser.add_argument("--port", type=int, default=8100)
    serve_parser.set_defaults(func=cmd_serve)

    for name in ("ask", "chat"):
        sub.choices[name].add_argument(
            "--thread", default="cli", help="Conversation id, for follow-up questions"
        )

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
