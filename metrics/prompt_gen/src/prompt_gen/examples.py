"""Few-shot examples per category, loaded from data/examples.yaml."""

from dataclasses import dataclass
from pathlib import Path

import yaml

from prompt_gen import typology


@dataclass(frozen=True)
class Span:
    type_id: int
    source: str
    target: str
    pair: int | None = None
    note: str | None = None


@dataclass(frozen=True)
class CategoryExamples:
    demo_source: str
    demo_paraphrase: str
    demo_operations: tuple[str, ...]
    spans: tuple[Span, ...]


def load(path: Path) -> dict[str, CategoryExamples]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = {}
    for category in typology.CATEGORIES:
        entry = data["categories"].get(category.key)
        if entry is None:
            raise ValueError(f"{path}: no examples for category {category.key!r}")
        extra = set(entry["spans"]) - category.type_ids
        if extra:
            raise ValueError(f"{path}: {category.key} lists type ids {sorted(extra)} that belong to another category")
        missing = category.type_ids - set(entry["spans"])
        if missing:
            raise ValueError(f"{path}: {category.key} has no span examples for type ids {sorted(missing)}")
        spans = tuple(
            Span(type_id, s["from"], s["to"], s.get("pair"), s.get("note"))
            for type_id, items in entry["spans"].items()
            for s in items
        )
        out[category.key] = CategoryExamples(
            demo_source=data["demo_source"],
            demo_paraphrase=entry["demo"]["paraphrase"],
            demo_operations=tuple(entry["demo"]["operations"]),
            spans=spans,
        )
    return out
