"""Seed prompts and their hard constraints, one folder per seed under seeds/."""

from dataclasses import dataclass
from pathlib import Path

import yaml

from prompt_gen.config import PACKAGE_ROOT

SEEDS_DIR = PACKAGE_ROOT / "seeds"


@dataclass(frozen=True)
class Constraint:
    id: str
    requirement: str
    accept: tuple[str, ...]
    reject: tuple[str, ...]
    relative: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrapCase:
    text: str
    passes: bool
    reason: str
    relative: tuple[str, ...] = ()


@dataclass(frozen=True)
class Seed:
    id: str
    text: str
    constraints: tuple[Constraint, ...]
    trap_set: tuple[TrapCase, ...]


def load(seed_id: str, seeds_dir: Path = SEEDS_DIR) -> Seed:
    folder = seeds_dir / seed_id
    data = yaml.safe_load((folder / "constraints.yaml").read_text(encoding="utf-8"))
    return Seed(
        id=seed_id,
        text=" ".join((folder / "prompt.txt").read_text(encoding="utf-8").split()),
        constraints=tuple(
            Constraint(c["id"], c["requirement"], tuple(c["accept"]), tuple(c["reject"]), tuple(c.get("relative", ())))
            for c in data["constraints"]
        ),
        trap_set=tuple(
            TrapCase(" ".join(t["text"].split()), t["pass"], t["reason"], tuple(t.get("relative", ())))
            for t in data.get("trap_set", [])
        ),
    )


def available(seeds_dir: Path = SEEDS_DIR) -> list[str]:
    return sorted(p.name for p in seeds_dir.iterdir() if (p / "prompt.txt").exists())
