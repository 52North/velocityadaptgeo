"""prompt-review <run_dir> [--summary]: the full-screen review (app.py), or the per-category counts."""

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="prompt-review",
        description="review a generation run's candidates (full screen; decisions go to reviewed.jsonl)",
    )
    parser.add_argument(
        "run_dir", type=Path, help="a run folder, e.g. ../prompt_gen/out/<run_id>"
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="print per-category counts (generated, automated, manual, moves) and exit",
    )
    args = parser.parse_args()
    if not (args.run_dir / "candidates.jsonl").exists():
        parser.error(f"no candidates.jsonl in {args.run_dir}")

    if args.summary:
        from prompt_review.render import print_summary

        print_summary(args.run_dir)
    else:
        from prompt_review.app import review

        review(args.run_dir)


if __name__ == "__main__":
    main()
