"""prompt-gen run | check-judge | rejudge | backfill-closest | backfill-embeddings"""

import argparse
import os

from prompt_gen.config import PACKAGE_ROOT

# Keep Hugging Face models inside the project (gitignored), before sentence-transformers is imported.
os.environ.setdefault("HF_HOME", str(PACKAGE_ROOT / "models"))


DEFAULT_SEED = "muenster_green_300m"


def run_seed(seed: str | None, resume: str | None) -> str:
    """The seed id for `run`: a resumed run keeps its own seed, so its candidates never mix two seeds."""
    if not resume:
        return seed or DEFAULT_SEED
    from prompt_gen.run import OUT_DIR, run_seed_id

    own = run_seed_id(OUT_DIR / resume)
    if seed and seed != own:
        raise SystemExit(f"--seed {seed} does not match run {resume}, which uses {own}")
    return own


def cmd_run(args) -> None:
    from prompt_gen import config, seeds, typology
    from prompt_gen.run import Run

    cfg = config.load()
    categories = args.categories or [c.key for c in typology.CATEGORIES]
    for key in categories:
        typology.get(key)
    seed = seeds.load(run_seed(args.seed, args.resume))
    run = Run(cfg, seed, args.resume)
    print(f"Run {run.run_id} -> {run.dir}")
    run.execute(categories, args.n or cfg.loop.n_per_category, args.hours)


def cmd_check_judge(args) -> None:
    from prompt_gen import config, seeds, typology
    from prompt_gen.judge import Judge, same_text

    cfg = config.load()
    seed = seeds.load(args.seed)
    judge = Judge(cfg.judge, cfg.ollama_host, cfg.num_ctx)

    print("Constraints (call A):")
    correct = 0
    for t in seed.trap_set:
        verdicts, _ = judge.check_constraints(seed, t.text)
        failed = [v.id for v in verdicts if v.status == "failed"]
        relative = [v.id for v in verdicts if v.status == "relative"]
        passed = not failed
        ok = passed == t.passes and (not t.passes or set(t.relative) <= set(relative))
        correct += ok
        print(
            f"{'OK' if ok else 'XX'}  expected {'pass' if t.passes else 'fail'}{list(t.relative) or ''}, "
            f"got {'pass' if passed else 'fail'} failed={failed} relative={relative}  [{t.reason}]",
            flush=True,
        )
        if not ok:
            for v in verdicts:
                print(f"      {v.id}: {v.status} - {v.reason}")
    print(f"{correct}/{len(seed.trap_set)} correct\n")

    print("Grammar (call B):")
    grammar_correct = 0
    for g in seed.grammar_set:
        b, _ = judge.check_category_grammar(seed, typology.get("lexical"), g.text)
        grammatical = same_text(b.corrected, g.text)
        ok = grammatical == g.grammatical
        grammar_correct += ok
        print(
            f"{'OK' if ok else 'XX'}  expected {'grammatical' if g.grammatical else 'ungrammatical'}, "
            f"got {'grammatical' if grammatical else 'ungrammatical'}  [{g.reason}]",
            flush=True,
        )
        if not grammatical:
            print(f"      corrected: {b.corrected}")
    print(f"{grammar_correct}/{len(seed.grammar_set)} correct")


def cmd_rejudge(args) -> None:
    """Re-judge stored candidates with the current judge, without regenerating them. Results go to
    out/<run_id>/rejudged.jsonl; candidates.jsonl is not changed."""
    import json
    from datetime import datetime

    from prompt_gen import config, seeds, stems, typology
    from prompt_gen.judge import Judge, JudgeError
    from prompt_gen.run import OUT_DIR, read_jsonl, run_seed_id

    cfg = config.load()
    run_dir = OUT_DIR / args.run_id
    seed = seeds.load(run_seed_id(run_dir))
    judge = Judge(cfg.judge, cfg.ollama_host, cfg.num_ctx)
    picked = [
        c
        for c in read_jsonl(run_dir / "candidates.jsonl")
        if c.get("prompt")
        and c["category"] == args.category
        and (not args.contains or args.contains in c["prompt"])
    ][: args.limit]
    out = run_dir / f"rejudged_{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    print(f"Re-judging {len(picked)} {args.category} candidates -> {out}", flush=True)
    for c in picked:
        stem_result = (
            stems.check(seed.text, c["prompt"])
            if c["category"] in cfg.thresholds.stem_check
            else None
        )
        try:
            j = judge.check(seed, typology.get(c["category"]), c["prompt"], stem_result)
        except JudgeError as e:
            print(
                f"  {c['category']}#{c['attempt']}: skipped, judge error: {e}",
                flush=True,
            )
            continue
        old = c.get("judge") or {}
        with out.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "category": c["category"],
                        "attempt": c["attempt"],
                        "prompt": c["prompt"],
                        "old": {
                            "matches_category": old.get("matches_category"),
                            "failed": [
                                v["id"]
                                for v in old.get("verdicts", [])
                                if v["status"] == "failed"
                            ],
                        },
                        "new": j.model_dump(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        print(
            f"{c['category']}#{c['attempt']}: category match {old.get('matches_category')} -> {j.matches_category}, "
            f"grammatical={j.grammatical}, failed={j.failed_ids}, {j.durations_s}",
            flush=True,
        )


def cmd_backfill_closest(args) -> None:
    from sentence_transformers import SentenceTransformer

    from prompt_gen import config
    from prompt_gen.run import OUT_DIR, backfill_closest
    from prompt_gen.scoring import Embedder

    cfg = config.load()
    embedder = Embedder(SentenceTransformer(cfg.embeddings.semantic, device="cpu"))

    def similarities(text, others):
        vectors = embedder.embed([text, *others])
        return [float(x) for x in vectors[1:] @ vectors[0]]

    run_dir = OUT_DIR / args.run_id
    report = backfill_closest(run_dir, similarities)
    action = (
        "Backed up to"
        if report["backup"] == "created"
        else "Kept the existing original backup"
    )
    print(
        f"{action} {run_dir / 'candidates.jsonl.bak'}; added closest matches to "
        f"{report['with_prompt']} of {report['records']} records."
    )
    print(
        f"Mismatches with the stored max_sem_same_category: {len(report['mismatches'])}"
    )
    for m in report["mismatches"]:
        print("  " + m)


def cmd_backfill_embeddings(args) -> None:
    from sentence_transformers import SentenceTransformer

    from prompt_gen import config
    from prompt_gen.run import OUT_DIR, backfill_embeddings
    from prompt_gen.scoring import Embedder

    cfg = config.load()
    embedder = Embedder(SentenceTransformer(cfg.embeddings.semantic, device="cpu"))
    run_dir = OUT_DIR / args.run_id
    report = backfill_embeddings(run_dir, embedder.embed, cfg.embeddings.semantic)
    print(
        f"Wrote {report['written']} embeddings to {run_dir / 'embeddings.jsonl'} ({report['present']} already there)."
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="prompt-gen")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("run", help="generate paraphrases for one seed")
    p.add_argument(
        "--seed",
        help=f"seed id (default: {DEFAULT_SEED}; with --resume: the run's own)",
    )
    p.add_argument("--categories", nargs="+", help="category keys (default: all six)")
    p.add_argument(
        "--n", type=int, help="accepted prompts per category (default: config)"
    )
    p.add_argument("--resume", metavar="RUN_ID", help="continue an interrupted run")
    p.add_argument(
        "--hours",
        type=float,
        help="time budget; each category gets an equal share of the remaining time",
    )
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("check-judge", help="run the judge on the seed's trap set")
    p.add_argument("--seed", default=DEFAULT_SEED)
    p.set_defaults(func=cmd_check_judge)

    p = sub.add_parser(
        "rejudge",
        help="re-judge stored candidates with the current judge (writes rejudged_<time>.jsonl)",
    )
    p.add_argument("run_id")
    p.add_argument("--category", required=True)
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--contains", help="only candidates whose prompt contains this text")
    p.set_defaults(func=cmd_rejudge)

    p = sub.add_parser(
        "backfill-closest",
        help="add each candidate's closest matches to an existing run (keeps candidates.jsonl.bak)",
    )
    p.add_argument("run_id")
    p.set_defaults(func=cmd_backfill_closest)

    p = sub.add_parser(
        "backfill-embeddings",
        help="store each paraphrase's embedding in embeddings.jsonl, for prompt-review's live similarities",
    )
    p.add_argument("run_id")
    p.set_defaults(func=cmd_backfill_embeddings)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
