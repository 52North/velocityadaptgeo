"""Export the manager's decisions of batch runs as training rows for the Laya decision model.

    python -m src.laya_export --train <run_dir>[:variant] ... [--eval <run_dir>[:variant] ...] --out <dir>
                              [--all] [--no-merge]

One row per manager decision, in the `{state, questions, expected | gold}` JSONL that
`laya.train.finetune` reads: `state` is what the manager saw (`management.decision_state`, logged
with each decision since 2026-10-21), `questions` is `laya_client.NEXT_ACTION`, and the label is the
action Haiku picked. Laya distils Haiku, so only results graded correct against the reference
(`grades[.<variant>].jsonl`, `metrics/grading/grade.py`) teach, unless `--all` is given.

Rows with the same state are merged into one with the share of each action Haiku picked as a
`gold` distribution: the seed runs repeat one prompt, so their first decisions are otherwise the
same row hundreds of times. `--no-merge` keeps one row per decision.

`--train` and `--eval` split by run folder, never by row: paraphrases of one seed are near
duplicates, so a row split would score memorisation. Writes `<out>/train.jsonl` (and `eval.jsonl`,
for `TrainConfig(eval_data=...)`); each row also carries `meta` (where it came from), which Laya
ignores.
"""

import argparse
import collections
import json
from datetime import datetime
from pathlib import Path

from src.batch import DEFAULT_VARIANT, VARIANTS, _read_jsonl, load_results, results_file
from src.llm.nodes.management import ALLOWED_ACTIONS
from src.llm.tools.laya_client import NEXT_ACTION

# What management_node logs when Haiku's reply was not valid JSON: its action is then the
# fallback "done", not a decision, so the row would teach a wrong label.
UNPARSED = "No reasoning provided by LLM."


def _source(spec: str) -> tuple[Path, str]:
    run_dir, _, variant = spec.partition(":")
    variant = variant or DEFAULT_VARIANT
    if variant not in VARIANTS:
        raise argparse.ArgumentTypeError(
            f"variant must be one of {', '.join(VARIANTS)}, not {variant!r}"
        )
    return Path(run_dir), variant


def grades(run_dir: Path, variant: str, results: list[dict]) -> dict[str, bool]:
    """Key -> graded correct. Refuses grades older than the newest result, which would grade another run."""
    path = run_dir / (
        "grades.jsonl" if variant == DEFAULT_VARIANT else f"grades.{variant}.jsonl"
    )
    if not path.exists():
        raise SystemExit(
            f"{path} is missing: run --execute and grade.py first, or pass --all"
        )
    newest = max((r["at"] for r in results), default=None)
    if newest and datetime.fromisoformat(newest).timestamp() > path.stat().st_mtime:
        raise SystemExit(
            f"{path} is older than the newest result ({newest}): grade again, or pass --all"
        )
    return {g["key"]: bool(g.get("correct")) for g in _read_jsonl(path)}


def decisions(
    run_dir: Path, variant: str, graded_only: bool, skipped: collections.Counter
) -> list[dict]:
    """The labelled manager decisions of one results file, as unmerged rows."""
    results = load_results(run_dir, variant)
    if not results:
        raise SystemExit(f"no results in {run_dir / results_file(variant)}")
    correct = grades(run_dir, variant, results) if graded_only else {}
    rows = []
    for r in results:
        if r.get("error"):
            skipped["result error"] += 1
            continue
        if graded_only and not correct.get(r["key"]):
            skipped["result not graded correct"] += 1
            continue
        for d in r.get("decision_history") or []:
            if d.get("node") != "management_node" or "iteration" not in d:
                continue  # other nodes, and the max_iterations stop, which no model decided
            if d.get("error"):
                skipped["decision whose LLM call failed"] += 1
            elif "state" not in d:
                skipped["decision without state (run before 2026-10-21)"] += 1
            elif d.get("reasoning") == UNPARSED:
                skipped["decision with unparsed reply"] += 1
            elif d.get("current_action") not in ALLOWED_ACTIONS:
                skipped["decision with unknown action"] += 1
            else:
                rows.append(
                    {
                        "state": d["state"],
                        "action": d["current_action"],
                        "meta": {
                            "run": run_dir.name,
                            "variant": variant,
                            "key": r["key"],
                            "category": r["category"],
                            "iteration": d["iteration"],
                        },
                    }
                )
    return rows


def to_laya(rows: list[dict], merge: bool) -> list[dict]:
    """Laya rows: one per decision, or with `merge` one per distinct state with the actions' shares."""
    if not merge:
        return [
            {
                "state": r["state"],
                "questions": NEXT_ACTION,
                "expected": {"next_action": r["action"]},
                "meta": r["meta"],
            }
            for r in rows
        ]
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(
            json.dumps(r["state"], sort_keys=True, ensure_ascii=False), []
        ).append(r)
    out = []
    for group in groups.values():
        counts = collections.Counter(r["action"] for r in group)
        label = (
            {"expected": {"next_action": group[0]["action"]}}
            if len(counts) == 1
            else {
                "gold": {
                    "next_action": {
                        "probabilities": {a: n / len(group) for a, n in counts.items()}
                    }
                }
            }
        )
        out.append(
            {
                "state": group[0]["state"],
                "questions": NEXT_ACTION,
                **label,
                "meta": {**group[0]["meta"], "decisions": len(group)},
            }
        )
    return out


def write(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def describe(
    name: str, decided: list[dict], rows: list[dict], skipped: collections.Counter
) -> str:
    actions = collections.Counter(r["action"] for r in decided)
    mixed = sum("gold" in r for r in rows)
    lines = [
        f"{name}: {len(decided)} decisions -> {len(rows)} rows ({mixed} with a mixed label)",
        "  actions: "
        + ", ".join(
            f"{a} {actions[a]} ({actions[a] / max(1, len(decided)):.0%})"
            for a in ALLOWED_ACTIONS
        ),
    ]
    lines += [f"  skipped {n}: {reason}" for reason, n in skipped.most_common()]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--train", type=_source, nargs="+", required=True, metavar="RUN_DIR[:VARIANT]"
    )
    parser.add_argument(
        "--eval", type=_source, nargs="+", default=[], metavar="RUN_DIR[:VARIANT]"
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="folder for train.jsonl and eval.jsonl"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="keep decisions of results not graded correct",
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="one row per decision, even for equal states",
    )
    args = parser.parse_args()
    overlap = {s for s in args.train} & {s for s in args.eval}
    if overlap:
        parser.error(
            f"in both --train and --eval: {', '.join(f'{d}:{v}' for d, v in overlap)}"
        )

    args.out.mkdir(parents=True, exist_ok=True)
    for name, sources in (("train", args.train), ("eval", args.eval)):
        if not sources:
            continue
        skipped = collections.Counter()
        decided = [
            row for d, v in sources for row in decisions(d, v, not args.all, skipped)
        ]
        rows = to_laya(decided, merge=not args.no_merge)
        if not rows:
            raise SystemExit(f"{name}: no decisions left to export ({dict(skipped)})")
        write(args.out / f"{name}.jsonl", rows)
        print(describe(name, decided, rows, skipped))


if __name__ == "__main__":
    main()
