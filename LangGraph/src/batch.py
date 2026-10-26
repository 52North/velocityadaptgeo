"""Build a workflow graph for every reviewed paraphrase of a prompt_gen run.

    python -m src.batch <run_dir> [--variant V] [--limit N] [--seed-runs N] [--seed-only] [--concurrency N]
    python -m src.batch <run_dir> [--variant V] --status [--seed-runs N] [--seed-only] [--concurrency N]
    python -m src.batch <run_dir> [--variant V] --summary [--seed-only] [--expect a,b,c,...]
    python -m src.batch <run_dir> [--variant V] --execute

Which prompts run, and in which category they count, is read from the reviewer's
`<run_dir>/reviewed.jsonl` (see metrics/prompt_review/FORMAT.md) and nowhere else. The
results in `<run_dir>/workflows.jsonl` hold only the candidate key, never the category or
the decision, so a later change in the reviewer applies to existing results without a
re-run: `load_results` joins them with the current decisions. A paraphrase accepted later
is picked up by the next batch run; one rejected later is left out by `load_results`.

The seed prompt runs `--seed-runs` times under the keys `seed#1`, `seed#2`, ..., as the
baseline for how much the graph varies for the same prompt. `--seed-only` runs just those,
leaving the paraphrases for a later call.

The `RunTracker` metrics of each prompt go to `<run_dir>/runs.jsonl` rather than METRICS_FILE,
so a run folder holds everything about its run; they join to the results by `thread_id`.
Each result also keeps the run's `decision_history` (the manager's steps and the auto_builder's
decisions with their reasoning), so a wrong graph can be traced without re-running it.

`--variant` (default `WORKFLOW_VARIANT`, else pgvector) picks how the agent finds processes:
pgvector catalog search, or every tool of the MCP server. Each variant keeps its own results on
the same reviewed prompts: pgvector in `workflows.jsonl` with thread ids `<run_id>/<key>`, any
other variant in `workflows.<variant>.jsonl` with thread ids `<run_id>/<variant>/<key>`. Their
metrics share `runs.jsonl` (every record carries its `variant`).

`--status` prints one line on a run in progress (or finished) and exits, without loading the
agent: progress, errors, cost so far, and the time and cost left, estimated from the last
results. Pass the same `--seed-runs`, `--seed-only` and `--concurrency` as the run.

`--summary` prints the graph structures, parameters and unmet capabilities of the results and
exits, also without loading the agent; `--expect` names the correct chain of process types, to
count how often it is built and whether the seed runs have settled (see `src/batch_summary.py`).

`--execute` runs each distinct graph of the results once against the OGC servers, answering inputs the
agent left unset with a scripted user reply, and stores the outputs for grading against the CoolSpots
reference (see `src/batch_execute.py` and `metrics/grading/grade.py`). It does not load the agent.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path

# Not __name__: run with `python -m`, that is "__main__".
logger = logging.getLogger("src.batch")

RESULTS_FILE = "workflows.jsonl"
RUNS_FILE = "runs.jsonl"
VARIANTS = ("pgvector", "mcp")  # src.llm.workflow.RETRIEVERS; not imported, so --status stays agent-free
DEFAULT_VARIANT = "pgvector"
SEED_CATEGORY = "seed"
STATUS_WINDOW = 20  # recent results the --status estimate is based on


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _key(candidate: dict) -> str:
    return f"{candidate['category']}#{candidate['attempt']}"


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def variant_suffix(variant: str = DEFAULT_VARIANT) -> str:
    """`.<variant>` in a variant's file names; none for pgvector's, as before there were variants."""
    return "" if variant == DEFAULT_VARIANT else f".{variant}"


def results_file(variant: str = DEFAULT_VARIANT) -> str:
    """The results file of a variant (`workflows[.<variant>].jsonl`)."""
    return f"workflows{variant_suffix(variant)}.jsonl"


def thread_id(run_dir: Path, key: str, variant: str = DEFAULT_VARIANT) -> str:
    return f"{run_dir.name}/{key}" if variant == DEFAULT_VARIANT else f"{run_dir.name}/{variant}/{key}"


def seed_prompt(run_dir: Path) -> str:
    return json.loads((run_dir / "config.json").read_text(encoding="utf-8"))["seed"]["text"]


def accepted_prompts(run_dir: Path, seed_runs: int = 0, seed_only: bool = False) -> dict[str, dict]:
    """Key -> {prompt, category} for every paraphrase currently accepted in review, plus the seed runs.

    The category is the reviewer's (after a move), not the one the paraphrase was generated for.
    With `seed_only` the paraphrases are left out and only the seed runs are returned.
    """
    selected = {} if seed_only else {
        _key(r): {"prompt": r["prompt"], "category": r["review"]["category"]}
        for r in _read_jsonl(run_dir / "reviewed.jsonl")
        if r["review"]["decision"] == "accept"
    }
    seed = seed_prompt(run_dir)
    for i in range(1, seed_runs + 1):
        selected[f"{SEED_CATEGORY}#{i}"] = {"prompt": seed, "category": SEED_CATEGORY}
    return selected


def latest_results(run_dir: Path, variant: str = DEFAULT_VARIANT) -> dict[str, dict]:
    """The last result line per key; a retry after an error appends a new line."""
    return {r["key"]: r for r in _read_jsonl(run_dir / results_file(variant))}


def load_results(run_dir: Path, variant: str = DEFAULT_VARIANT) -> list[dict]:
    """Results of the currently accepted paraphrases and the seed runs, with the current review category.

    Results whose prompt is no longer accepted, or whose text no longer matches (`text_sha1`), are left out.
    """
    results = latest_results(run_dir, variant)
    selected = accepted_prompts(run_dir, seed_runs=sum(k.startswith(f"{SEED_CATEGORY}#") for k in results))
    return [
        {**results[key], "category": s["category"], "prompt": s["prompt"]}
        for key, s in selected.items()
        if key in results and results[key]["text_sha1"] == _sha1(s["prompt"])
    ]


def _finished_at(result: dict) -> float:
    return time.mktime(time.strptime(result["at"], "%Y-%m-%dT%H:%M:%S")) + result["wall_ms"] / 1000


def status(run_dir: Path, seed_runs: int, concurrency: int = 1, seed_only: bool = False,
           variant: str = DEFAULT_VARIANT) -> str:
    """One line on the state of a run: progress, errors, cost so far, time and cost left."""
    wanted = accepted_prompts(run_dir, seed_runs, seed_only)
    results = {k: r for k, r in latest_results(run_dir, variant).items() if k in wanted}
    done = [r for r in results.values() if not r.get("error")]
    errors = sorted(k for k, r in results.items() if r.get("error"))
    costs = {m["thread_id"]: m.get("cost_usd") or 0 for m in _read_jsonl(run_dir / RUNS_FILE)}
    spent = sum(costs.get(r["thread_id"], 0) for r in results.values())

    line = f"[{time.strftime('%H:%M')}] {len(done)}/{len(wanted)} done ({len(done) / max(len(wanted), 1):.0%}), {len(errors)} errors"
    if errors:
        line += f" ({', '.join(errors[:5])}{', ...' if len(errors) > 5 else ''})"
    line += f" | ${spent:.2f} so far"

    recent = sorted(results.values(), key=_finished_at)[-STATUS_WINDOW:]
    left = len(wanted) - len(done)
    if recent and left:
        per_s = sum(r["wall_ms"] for r in recent) / 1000 / len(recent) / concurrency
        per_usd = sum(costs.get(r["thread_id"], 0) for r in recent) / len(recent)
        finish = time.strftime("%H:%M", time.localtime(time.time() + left * per_s))
        line += f" | ~{left * per_s / 60:.0f} min left (until ~{finish}), ~${left * per_usd:.2f} to go, ~${spent + left * per_usd:.2f} total"
    if recent:
        line += f" | last: {recent[-1]['key']}, {(time.time() - _finished_at(recent[-1])) / 60:.0f} min ago"
    return line


async def build_one(run_dir: Path, key: str, prompt: str, variant: str = DEFAULT_VARIANT) -> dict:
    """Run the agent on one prompt in a fresh thread and return the result line."""
    # Imported here so --status does not load the agent and its LLM client.
    from src.app import turn_config, turn_input
    from src.llm.workflow import compiled_graph
    from src.metrics import RunTracker

    thread = thread_id(run_dir, key, variant)
    started = time.time()
    record = {"key": key, "text_sha1": _sha1(prompt), "thread_id": thread,
              "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        state = await compiled_graph.ainvoke(
            turn_input(prompt),
            config={**turn_config(thread), "callbacks": [RunTracker(thread, str(run_dir / RUNS_FILE))]},
        )
    except Exception as exc:
        logger.exception("%s failed", key)
        return {**record, "error": repr(exc), "wall_ms": round((time.time() - started) * 1000)}
    return {
        **record,
        "error": None,
        "wall_ms": round((time.time() - started) * 1000),
        "workflow_graph": state.get("workflow_graph") or {"nodes": [], "edges": []},
        "last_validation": state.get("last_validation"),
        "unmet_capabilities": state.get("unmet_capabilities") or [],
        "response": state["messages"][-1].text if state.get("messages") else None,
        # The manager's planned steps and the auto_builder's decisions, each with its reasoning, so
        # a wrong graph can be traced to the step that went wrong without re-running it.
        "decision_history": state.get("decision_history") or [],
    }


async def build_all(run_dir: Path, seed_runs: int, limit: int | None, concurrency: int, seed_only: bool = False,
                    variant: str = DEFAULT_VARIANT) -> None:
    """Build the accepted prompts that have no successful result yet, appending one line each."""
    done = {k for k, r in latest_results(run_dir, variant).items() if not r.get("error")}
    todo = [(k, s["prompt"]) for k, s in accepted_prompts(run_dir, seed_runs, seed_only).items() if k not in done]
    todo = todo[:limit] if limit is not None else todo
    logger.info("%s: %d to build, %d already done", variant, len(todo), len(done))

    gate = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    out = run_dir / results_file(variant)

    async def worker(key: str, prompt: str) -> None:
        async with gate:
            record = await build_one(run_dir, key, prompt, variant)
        async with lock:
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        graph = record.get("workflow_graph") or {}
        logger.info("%s: %s", key, record["error"] or f"{len(graph.get('nodes', []))} nodes")

    await asyncio.gather(*(worker(k, p) for k, p in todo))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--variant", choices=VARIANTS, default=os.environ.get("WORKFLOW_VARIANT", DEFAULT_VARIANT),
                        help="how the agent finds processes (default: WORKFLOW_VARIANT, else pgvector)")
    parser.add_argument("--seed-runs", type=int, default=3, help="times to run the seed prompt as a baseline")
    parser.add_argument("--seed-only", action="store_true", help="run only the seed prompt, no paraphrases")
    parser.add_argument("--limit", type=int, help="build at most this many prompts in this call")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--status", action="store_true", help="print the state of the run and exit")
    parser.add_argument("--summary", action="store_true", help="summarise the results and exit")
    parser.add_argument("--expect", help="with --summary: the correct chain of process types, comma-separated")
    parser.add_argument("--execute", action="store_true", help="execute each distinct graph once for grading")
    args = parser.parse_args()
    if args.expect and not args.summary:
        parser.error("--expect only applies to --summary")
    if args.summary:
        from src.batch_summary import summary

        chain = [p.strip() for p in args.expect.split(",")] if args.expect else None
        if chain is not None and len(chain) < 2:
            parser.error("--expect needs at least two process types")
        print(summary(args.run_dir, args.seed_only, chain, args.variant))
        return
    if args.execute:
        from src.batch_execute import execute_all

        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        asyncio.run(execute_all(args.run_dir, args.variant))
        return
    if args.seed_only and args.seed_runs < 1:
        parser.error("--seed-only needs --seed-runs of at least 1")
    if args.status:
        print(status(args.run_dir, args.seed_runs, args.concurrency, args.seed_only, args.variant))
        return
    # Read by the agent and RunTracker when they load with the first prompt.
    os.environ["WORKFLOW_VARIANT"] = args.variant
    # Set here since the agent, which configures logging on import, is only loaded with the first prompt.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # RunTracker only logs a warning when it cannot write, so check up front rather than lose the metrics.
    try:
        for name in (results_file(args.variant), RUNS_FILE):
            open(args.run_dir / name, "a").close()
    except OSError as exc:
        parser.error(f"cannot write to {args.run_dir}: {exc}")
    asyncio.run(build_all(args.run_dir, args.seed_runs, args.limit, args.concurrency, args.seed_only, args.variant))


if __name__ == "__main__":
    main()
