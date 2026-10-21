"""Load the ETPC corpus and extract few-shot paraphrase examples per category.

Download the corpus files from https://github.com/venelink/ETPC (Corpus/) into data/raw/etpc/.
Only pairs that ETPC re-annotated as paraphrases (etpc_label=1) and sense-preserving
relations are used.
"""

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from prompt_gen.typology import BY_TYPE_ID, IDENTITY_TYPE_ID

# The corpus has a few stray C0 control characters, mostly mangled apostrophes (\x12).
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass(frozen=True)
class Relation:
    type_id: int
    s1_text: str
    s2_text: str


@dataclass(frozen=True)
class Pair:
    pair_id: int
    sent1: str
    sent2: str
    relations: tuple[Relation, ...]

    def categories(self) -> set[str]:
        return {
            BY_TYPE_ID[r.type_id].key for r in self.relations if r.type_id in BY_TYPE_ID
        }

    def is_pure(self, category: str) -> bool:
        """True if every change in the pair belongs to `category` (identity spans aside)."""
        changes = [r for r in self.relations if r.type_id != IDENTITY_TYPE_ID]
        return bool(changes) and all(
            r.type_id in BY_TYPE_ID and BY_TYPE_ID[r.type_id].key == category
            for r in changes
        )


def _parse(path: Path) -> ET.Element:
    text = _CONTROL.sub("'", path.read_text(encoding="utf-8"))
    return ET.fromstring(text)


def _text(el: ET.Element, tag: str) -> str:
    text = el.findtext(tag)
    if text is None:
        raise ValueError(f"<{el.tag}> has no <{tag}>")
    return text


def load_pairs(raw_dir: Path) -> list[Pair]:
    sentences: dict[int, tuple[str, str]] = {}
    for p in _parse(raw_dir / "text_pairs.xml"):
        if p.findtext("etpc_label") == "1":
            sentences[int(_text(p, "pair_id"))] = (
                _text(p, "sent1_raw").strip(),
                _text(p, "sent2_raw").strip(),
            )

    relations = defaultdict(list)
    for r in _parse(raw_dir / "textual_paraphrases.xml"):
        if r.findtext("sense_preserving") != "yes":
            continue
        relations[int(_text(r, "pair_id"))].append(
            Relation(
                int(_text(r, "type_id")),
                (r.findtext("s1_text") or "").strip(),
                (r.findtext("s2_text") or "").strip(),
            )
        )

    return [
        Pair(pid, *sentences[pid], tuple(rels))
        for pid, rels in sorted(relations.items())
        if pid in sentences
    ]
