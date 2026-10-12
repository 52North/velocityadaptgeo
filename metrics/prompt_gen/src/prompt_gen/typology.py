"""Paraphrase categories and their ETPC atomic types (Kovatchev et al. 2018).

Single source of truth for the category mapping. The six categories follow ETPC's own
meta-categories; ETPC's "Extremes" group (Identity, Non-paraphrase, Entailment) is not
a paraphrase operation and is left out.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ParaphraseType:
    id: int
    name: str
    description: str


@dataclass(frozen=True)
class Category:
    key: str
    name: str
    definition: str
    types: tuple[ParaphraseType, ...]
    forbidden: str

    @property
    def type_ids(self) -> frozenset[int]:
        return frozenset(t.id for t in self.types)


CATEGORIES: tuple[Category, ...] = (
    Category(
        key="morphological",
        name="Morphological",
        definition="Change the form of words while keeping the same word stems and sentence structure.",
        types=(
            ParaphraseType(1, "Inflectional changes", "change number, tense, person or degree of a word (park -> parks, identify -> identifying)"),
            ParaphraseType(2, "Modal verb changes", "swap or add a modal verb (identify -> could you identify, should be highlighted)"),
            ParaphraseType(3, "Derivational changes", "change the word class with an affix (visualize -> visualization, recreate -> recreational)"),
        ),
        forbidden="Do not replace words with synonyms, reorder clauses, or restructure sentences.",
    ),
    Category(
        key="lexical",
        name="Lexical",
        definition="Replace individual words or expressions with others of the same meaning, keeping the sentence structure.",
        types=(
            ParaphraseType(4, "Spelling changes", "change spelling or abbreviation (metres/meters, Köln/Koeln)"),
            ParaphraseType(5, "Same polarity substitution (habitual)", "swap a word for a general-purpose synonym (identify -> find, large -> big)"),
            ParaphraseType(6, "Same polarity substitution (contextual)", "swap a word for one that is only synonymous in this context (areas -> neighbourhoods)"),
            ParaphraseType(7, "Same polarity substitution (named entity)", "refer to a named entity differently (Bonn -> the city of Bonn)"),
            ParaphraseType(8, "Change of format", "change the format of a number or unit (500-metre -> 0.5 km, five hundred metres)"),
        ),
        forbidden="Do not change word forms only, change grammatical structure, or reorder clauses.",
    ),
    Category(
        key="lexico_syntactic",
        name="Lexico-syntactic",
        definition="Replace a word or phrase in a way that also forces a change in the surrounding grammar.",
        types=(
            ParaphraseType(9, "Opposite polarity substitution (habitual)", "use an antonym plus a negation (within -> not beyond, large enough -> not too small)"),
            ParaphraseType(10, "Opposite polarity substitution (contextual)", "same as above with a context-dependent antonym"),
            ParaphraseType(11, "Synthetic/analytic substitution", "replace a single word with a phrase or vice versa (walking distance -> distance on foot)"),
            ParaphraseType(13, "Converse substitution", "use the converse relation (areas near parks -> parks near areas, A serves B -> B is served by A)"),
            ParaphraseType(32, "Synthetic/analytic substitution (named entity)", "expand or compress a named entity (Bonn -> the former West German capital Bonn)"),
        ),
        forbidden="Do not restructure whole sentences or change the order of the request's parts.",
    ),
    Category(
        key="syntactic",
        name="Syntactical",
        definition="Change the grammatical structure of the sentences while keeping the same words.",
        types=(
            ParaphraseType(14, "Diathesis alternation", "switch active and passive voice (Output a visualization -> a visualization should be output)"),
            ParaphraseType(15, "Negation switching", "move a negation to another part of the sentence"),
            ParaphraseType(16, "Ellipsis", "omit words that the reader can recover from context"),
            ParaphraseType(17, "Coordination changes", "join or split coordinated clauses (two sentences -> one with 'and')"),
            ParaphraseType(18, "Subordination and nesting changes", "turn a clause into a subordinate or relative clause, or the reverse"),
        ),
        forbidden="Do not swap words for synonyms or change the request's tone or speech act.",
    ),
    Category(
        key="discourse",
        name="Discourse-based",
        definition="Change how the request is presented to the reader, keeping its content.",
        types=(
            ParaphraseType(21, "Punctuation changes", "change punctuation (sentences -> a colon-separated list, dashes, parentheses)"),
            ParaphraseType(22, "Direct/indirect style alternations", "switch between direct and reported speech (I need you to ..., The task is to ...)"),
            ParaphraseType(23, "Sentence modality changes", "change the speech act (command -> question: Which schools in Bonn are ...?)"),
            ParaphraseType(24, "Syntax/discourse structure changes", "reorganize the information structure (topicalize, split into steps, cleft sentences)"),
        ),
        forbidden="Do not add or remove information.",
    ),
    Category(
        key="other",
        name="Other",
        definition="Larger changes: add or drop non-essential material, reorder the parts, or rephrase through inference.",
        types=(
            ParaphraseType(25, "Addition/Deletion", "add or remove non-essential words or context (e.g. a short reason for the request)"),
            ParaphraseType(26, "Change of order", "reorder the parts of the request (the output description first, then the analysis)"),
            ParaphraseType(28, "Semantic based", "express the same meaning with a different lexicalization that requires inference"),
        ),
        forbidden="Do not add or remove anything that changes what analysis is run or what output is produced.",
    ),
)

BY_KEY: dict[str, Category] = {c.key: c for c in CATEGORIES}
BY_TYPE_ID: dict[int, Category] = {t.id: c for c in CATEGORIES for t in c.types}
IDENTITY_TYPE_ID = 29


def get(key: str) -> Category:
    try:
        return BY_KEY[key]
    except KeyError:
        raise KeyError(f"unknown category {key!r}; expected one of {sorted(BY_KEY)}") from None
