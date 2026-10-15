"""Reading a run folder and saving review decisions. The files and fields used are listed in FORMAT.md.

Decisions are saved to <run_dir>/reviewed.jsonl: one full candidate record per reviewed candidate,
plus a `review` object. candidates.jsonl is only read. reviewed.jsonl is rewritten (temp file +
rename) after every change, since moving back lets you change a decision.
"""

import json
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def candidate_key(c: dict) -> str:
    return f"{c['category']}#{c['attempt']}"


def load_candidates(run_dir: Path) -> list[dict]:
    """Candidates that produced a paraphrase (generation errors are left out). Candidates rejected by
    the stem check have no scores or judge result. Keys must be unique: decisions are stored by key."""
    records = read_jsonl(run_dir / "candidates.jsonl")
    seen: set[str] = set()
    for r in records:
        key = candidate_key(r)
        if key in seen:
            raise ValueError(
                f"duplicate candidate key {key} in {run_dir / 'candidates.jsonl'}"
            )
        seen.add(key)
    return [c for c in records if c.get("prompt")]


def load_decisions(path: Path) -> dict[str, dict]:
    return {candidate_key(r): r["review"] for r in read_jsonl(path)}


def save(path: Path, state) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for c in state.candidates:
            review = state.decisions.get(candidate_key(c))
            if review is not None:
                f.write(json.dumps({**c, "review": review}, ensure_ascii=False) + "\n")
    tmp.replace(path)


def config_paths(run_dir: Path) -> list[Path]:
    """config.json is the first session; each resumed session adds config_<time>.json."""
    return [run_dir / "config.json", *sorted(run_dir.glob("config_*.json"))]


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_config(run_dir: Path) -> dict:
    return _read(config_paths(run_dir)[-1])


def first_config(run_dir: Path) -> dict:
    return _read(run_dir / "config.json")


def categories(run_dir: Path, candidates: list[dict] = ()) -> list[str]:
    """All category keys, in typology order. From the `typology` field of the latest config snapshot;
    runs from before that field fall back to the union of the sessions' `categories`, config.json first,
    plus any category that only appears in the candidates."""
    configs = [_read(p) for p in config_paths(run_dir) if p.exists()]
    if configs and configs[-1].get("typology"):
        keys = [c["key"] for c in configs[-1]["typology"]]
    else:
        keys = []
        for cfg in configs:
            keys += [k for k in cfg.get("categories", []) if k not in keys]
    return keys + list(
        dict.fromkeys(c["category"] for c in candidates if c["category"] not in keys)
    )
