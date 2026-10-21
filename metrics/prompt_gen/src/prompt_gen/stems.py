"""Deterministic check that a paraphrase only uses words from the seed's word families.

Used as a gate for categories that must keep the seed's words (morphological). Function words,
pronouns, auxiliaries and modals are ignored: changing them is part of morphological edits
(modal verb changes) and of the small grammatical adjustments a derivation needs.

Known limits:
- Family matching by shared prefix can link unrelated words (park/parking). A meaning change
  that results is still caught by the constraint judge.
- It says nothing about grammar ("Identified all areas" passes); the judge checks that.
- Numbers are ignored; a changed value is caught by the constraint judge.
"""

import re
from dataclasses import dataclass

import snowballstemmer

_STEMMER = snowballstemmer.stemmer("english")

# Determiners, prepositions, conjunctions, pronouns, auxiliaries and modals. Quantifiers such as
# "all"/"every" are not listed: swapping them is a lexical change, not a morphological one.
_FUNCTION_WORDS_TEXT = """
a an the this that these those there here which who whom whose what
of to in on at for from by with within without into onto up down over under about as than
and or but nor so if then
i me my we us our you your it its they them their he him his she her
is are was were be been being am do does did done have has had having
can could should would will shall may might must
please not no
"""
FUNCTION_WORDS = frozenset(_FUNCTION_WORDS_TEXT.split())

_WORD = re.compile(r"[^\W\d_]+")


def _words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in FUNCTION_WORDS]


def _stem(word: str) -> str:
    return _STEMMER.stemWord(word)


def same_family(a: str, b: str) -> bool:
    """Stems of the same word family: equal, or sharing a prefix of at least 4 characters that
    covers all of the shorter stem except possibly its last character.

    walk/walkabl, visual/visualiz, identifi/identif, distanc/distant: same family.
    park/parti, area/arena: not."""
    if a == b:
        return True
    shorter = min(len(a), len(b))
    common = 0
    while common < shorter and a[common] == b[common]:
        common += 1
    return common >= 4 and common >= shorter - 1


@dataclass(frozen=True)
class StemCheck:
    new: tuple[str, ...]  # candidate words whose stem is in no seed family
    missing: tuple[str, ...]  # seed words whose family is gone from the candidate

    @property
    def passed(self) -> bool:
        return not self.new and not self.missing


def check(seed: str, candidate: str) -> StemCheck:
    seed_words = _words(seed)
    cand_words = _words(candidate)
    seed_stems = {_stem(w) for w in seed_words}
    cand_stems = {_stem(w) for w in cand_words}

    def first_word(words: list[str], stems: set[str]) -> list[str]:
        seen, out = set(), []
        for w in words:
            s = _stem(w)
            if s in stems and s not in seen:
                seen.add(s)
                out.append(w)
        return out

    new = {s for s in cand_stems if not any(same_family(s, t) for t in seed_stems)}
    missing = {t for t in seed_stems if not any(same_family(s, t) for s in cand_stems)}
    return StemCheck(
        tuple(first_word(cand_words, new)), tuple(first_word(seed_words, missing))
    )
