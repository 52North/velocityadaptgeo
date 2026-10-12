"""Interactive manual review of a run's candidates; decisions go to out/<run_id>/review.jsonl."""

import json
import textwrap
from datetime import datetime
from pathlib import Path

from prompt_gen import typology
from prompt_gen.run import read_jsonl


def _key(c: dict) -> str:
    return f"{c['category']}#{c['attempt']}"


def _show(c: dict, index: int, total: int) -> None:
    wrap = lambda s, indent="    ": textwrap.fill(s, 100, initial_indent=indent, subsequent_indent=indent)
    print("\n" + "=" * 100)
    status = "ACCEPTED by gates" if c["accepted"] else f"REJECTED by gates: {c['reject_reason']}"
    print(f"[{index}/{total}] {c['category']} attempt {c['attempt']} - {status}")
    print(wrap(c["prompt"]))
    print(f"  sem={c['sem']:.3f}  prag={c['prag']:.3f}  prag_no_instruction={c['prag_no_instruction']:.3f}  "
          f"max_sem_same_category={c['max_sem_same_category'] or 0:.3f}")
    j = c["judge"]
    for v in j["verdicts"]:
        if v["status"] != "kept":
            print(f"  {v['status'].upper()} {v['id']}: {v['reason']}")
    print(f"  category match: {j['matches_category']} - {j['category_reason']}")
    print(f"  operations (generator): {'; '.join(c['operations_applied'])}")
    print("  plan:\n" + wrap(c["reasoning"], "      "))


def review(run_dir: Path, include_rejected: bool = False) -> None:
    candidates = [c for c in read_jsonl(run_dir / "candidates.jsonl") if c.get("prompt") and "judge" in c]
    if not include_rejected:
        candidates = [c for c in candidates if c["accepted"]]
    review_path = run_dir / "review.jsonl"
    done = {r["candidate"] for r in read_jsonl(review_path)}
    todo = [c for c in candidates if _key(c) not in done]
    print(f"{len(todo)} to review ({len(done)} already reviewed) in {run_dir.name}")
    keys = ", ".join(c.key for c in typology.CATEGORIES)

    for i, c in enumerate(todo, 1):
        _show(c, i, len(todo))
        while True:
            choice = input("  [a]ccept  [r]eject  [c]hange category  [s]kip  [q]uit > ").strip().lower()
            if choice in {"a", "r", "c", "s", "q"}:
                break
        if choice == "q":
            return
        if choice == "s":
            continue
        decision = {"a": "accept", "r": "reject", "c": "accept"}[choice]
        category = c["category"]
        if choice == "c":
            while category not in typology.BY_KEY or category == c["category"]:
                category = input(f"  new category ({keys}) > ").strip()
        note = input("  note (optional) > ").strip()
        with review_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "candidate": _key(c),
                "decision": decision,
                "category": category,
                "note": note,
                "at": datetime.now().isoformat(timespec="seconds"),
            }, ensure_ascii=False) + "\n")
