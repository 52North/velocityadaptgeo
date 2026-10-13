"""prompt-gen run | check-judge | rejudge | review"""

import argparse
import os

from prompt_gen.config import PACKAGE_ROOT

# Keep Hugging Face models inside the project (gitignored), before sentence-transformers is imported.
os.environ.setdefault("HF_HOME", str(PACKAGE_ROOT / "models"))


def cmd_run(args) -> None:
    from prompt_gen import config, seeds, typology
    from prompt_gen.run import Run

    cfg = config.load()
    categories = args.categories or [c.key for c in typology.CATEGORIES]
    for key in categories:
        typology.get(key)
    seed = seeds.load(args.seed)
    run = Run(cfg, seed, args.resume)
    print(f"Run {run.run_id} -> {run.dir}")
    run.execute(categories, args.n or cfg.loop.n_per_category, args.hours)


def cmd_check_judge(args) -> None:
    from prompt_gen import config, seeds, typology
    from prompt_gen.judge import Judge

    cfg = config.load()
    seed = seeds.load(args.seed)
    judge = Judge(cfg.judge, cfg.ollama_host, cfg.num_ctx)
    correct = 0
    for t in seed.trap_set:
        r = judge.check(seed, typology.get("lexical"), t.text)
        ok = r.passed == t.passes and (not t.passes or set(t.relative) <= set(r.relative_ids))
        correct += ok
        print(f"{'OK' if ok else 'XX'}  expected {'pass' if t.passes else 'fail'}{list(t.relative) or ''}, "
              f"got {'pass' if r.passed else 'fail'} failed={r.failed_ids} relative={r.relative_ids}  [{t.reason}]", flush=True)
        if not ok:
            for v in r.verdicts:
                print(f"      {v.id}: {v.status} - {v.reason}")
    print(f"{correct}/{len(seed.trap_set)} correct")


def cmd_rejudge(args) -> None:
    """Re-judge stored candidates with the current judge, without regenerating them. Results go to
    out/<run_id>/rejudged.jsonl; candidates.jsonl is not changed."""
    import json

    from prompt_gen import config, seeds, stems, typology
    from prompt_gen.judge import Judge
    from prompt_gen.run import OUT_DIR, read_jsonl

    cfg = config.load()
    run_dir = OUT_DIR / args.run_id
    seed = seeds.load(json.loads((run_dir / "config.json").read_text(encoding="utf-8"))["seed"]["id"])
    judge = Judge(cfg.judge, cfg.ollama_host, cfg.num_ctx)
    picked = [
        c for c in read_jsonl(run_dir / "candidates.jsonl")
        if c.get("prompt") and c["category"] == args.category and (not args.contains or args.contains in c["prompt"])
    ][: args.limit]
    out = run_dir / "rejudged.jsonl"
    print(f"Re-judging {len(picked)} {args.category} candidates -> {out}", flush=True)
    for c in picked:
        stem_result = stems.check(seed.text, c["prompt"]) if c["category"] in cfg.thresholds.stem_check else None
        j = judge.check(seed, typology.get(c["category"]), c["prompt"], stem_result)
        old = c.get("judge") or {}
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "category": c["category"], "attempt": c["attempt"], "prompt": c["prompt"],
                "old": {"matches_category": old.get("matches_category"), "failed": [v["id"] for v in old.get("verdicts", []) if v["status"] == "failed"]},
                "new": j.model_dump(),
            }, ensure_ascii=False) + "\n")
        print(f"{c['category']}#{c['attempt']}: category match {old.get('matches_category')} -> {j.matches_category}, "
              f"grammatical={j.grammatical}, failed={j.failed_ids}", flush=True)


def cmd_review(args) -> None:
    from prompt_gen.review import review
    from prompt_gen.run import OUT_DIR

    review(OUT_DIR / args.run_id)


def main() -> None:
    parser = argparse.ArgumentParser(prog="prompt-gen")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("run", help="generate paraphrases for one seed")
    p.add_argument("--seed", default="muenster_green_300m")
    p.add_argument("--categories", nargs="+", help="category keys (default: all six)")
    p.add_argument("--n", type=int, help="accepted prompts per category (default: config)")
    p.add_argument("--resume", metavar="RUN_ID", help="continue an interrupted run")
    p.add_argument("--hours", type=float, help="time budget; each category gets an equal share of the remaining time")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("check-judge", help="run the judge on the seed's trap set")
    p.add_argument("--seed", default="muenster_green_300m")
    p.set_defaults(func=cmd_check_judge)

    p = sub.add_parser("rejudge", help="re-judge stored candidates with the current judge (writes rejudged.jsonl)")
    p.add_argument("run_id")
    p.add_argument("--category", required=True)
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--contains", help="only candidates whose prompt contains this text")
    p.set_defaults(func=cmd_rejudge)

    p = sub.add_parser("review", help="review a run's candidates (full screen; decisions go to reviewed.jsonl)")
    p.add_argument("run_id")
    p.set_defaults(func=cmd_review)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
