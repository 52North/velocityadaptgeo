"""Data and statistics behind the reports in this folder.

The results are read through LangGraph's `src.batch.load_results`, and correctness and the statistics come
from `src.batch_summary`, so the reports count exactly what `python -m src.batch --summary` counts. Both
modules only use the standard library, so the agent's dependencies are not needed here.

The run folder defaults to the Münster run; set `REPORT_RUN_DIR` to use another one. Every loader takes the
workflow `variant` (`VARIANTS`, from `src.llm.variants`; default pgvector), as `src.batch --variant` does.
"""

import collections
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from IPython.display import Markdown

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "LangGraph"))

from src.batch import DEFAULT_VARIANT, SEED_CATEGORY, _key, _read_jsonl, _sha1, latest_results, load_results, seed_prompt
from src.batch_summary import _edges, _structure, fisher, lenient, strict, trend, wilson
from src.llm.variants import VARIANTS as WORKFLOW_VARIANTS

RUN_DIR = Path(os.environ.get("REPORT_RUN_DIR", ROOT / "metrics/prompt_gen/out/20261012-174604_muenster_green_300m"))
CHAIN = ["city-boundary", "osm-green-areas", "min-area-filter", "multi-ring-buffer"]
CATEGORIES = ["syntactic", "other", "discourse", "lexico_syntactic", "morphological", "lexical"]
CATEGORY_NAMES = {
    "syntactic": "Syntactic",
    "other": "Other",
    "discourse": "Discourse",
    "lexico_syntactic": "Lexico-syntactic",
    "morphological": "Morphological",
    "lexical": "Lexical",
}
VARIANTS = {name: variant.label for name, variant in WORKFLOW_VARIANTS.items()}  # with plain names
SIZE_NOTE = "Drops the size requirement"
QUALITY_WORDING = re.compile(r"\b(adequate|suitable|sufficient) for recreation", re.IGNORECASE)
NETWORK_SEARCH = re.compile(r"network|route|\bstreets?\b|\bpaths?\b|pedestrian|isochron|travel", re.IGNORECASE)
Z95 = 1.959964
Z90 = 1.644854
Z80 = 0.841621  # one-sided, for 80% power


# --- rates and comparisons -------------------------------------------------------------------------


@dataclass(frozen=True)
class Rate:
    k: int
    n: int

    @property
    def p(self) -> float:
        return self.k / self.n if self.n else 0.0

    @property
    def ci(self) -> tuple[float, float]:
        return wilson(self.k, self.n)

    def pct(self, digits: int = 0) -> str:
        return f"{100 * self.p:.{digits}f}%"

    def range(self) -> str:
        lo, hi = self.ci
        return f"{100 * lo:.0f}–{100 * hi:.0f}%"

    def __str__(self) -> str:
        return f"{self.k}/{self.n} = {self.pct(1 if self.n >= 100 else 0)}"


def rate(results: list[dict], test) -> Rate:
    return Rate(sum(1 for r in results if test(r)), len(results))


@dataclass(frozen=True)
class Comparison:
    """`a` against the reference `b`: difference in points with a normal-approximation CI, and Fisher's p."""

    a: Rate
    b: Rate

    @property
    def diff(self) -> float:
        return self.a.p - self.b.p

    @property
    def se(self) -> float:
        return math.sqrt(self.a.p * (1 - self.a.p) / self.a.n + self.b.p * (1 - self.b.p) / self.b.n)

    def ci(self, z: float = Z95) -> tuple[float, float]:
        return self.diff - z * self.se, self.diff + z * self.se

    @property
    def p(self) -> float:
        return fisher(self.a.k, self.a.n - self.a.k, self.b.k, self.b.n - self.b.k)

    def tost_lower(self, margin: float) -> float:
        """p-value of the lower one-sided test against `diff <= -margin`; equivalence needs both below 0.05."""
        return 1 - _phi((self.diff + margin) / self.se) if self.se else 0.0

    def points(self) -> str:
        return signed(100 * self.diff)

    def ci_points(self, z: float = Z95) -> str:
        lo, hi = self.ci(z)
        return f"{signed(100 * lo, plus=False)} to {signed(100 * hi, plus=False)}"


def signed(x: float, digits: int = 1, plus: bool = True) -> str:
    """A number with a typographic minus, and a plus sign unless `plus` is off."""
    scale = 10**digits
    text = f"{math.floor(abs(x) * scale + 0.5 + 1e-9) / scale:.{digits}f}"  # half up, not half even
    return ("−" if x < 0 and float(text) else "+" if plus else "") + text


def _phi(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2))


def detectable(p: float, n_ref: int, n_other: int) -> float:
    """Smallest difference a two-sided test at 5% detects with 80% power (normal approximation)."""
    return (Z95 + Z80) * math.sqrt(p * (1 - p) / n_ref + p * (1 - p) / n_other)


def fmt_p(p: float) -> str:
    if p < 0.0001:
        return "< 0.0001"
    if p < 0.001:
        return f"{p:.4f}"
    return f"{p:.3f}" if p < 0.1 else f"{p:.2f}"


def p_is(p: float) -> str:
    """'p = 0.034' or 'p < 0.0001', for running text."""
    text = fmt_p(p)
    return f"p {text}" if text.startswith("<") else f"p = {text}"


def bonferroni(m: int = len(CATEGORIES)) -> float:
    return 0.05 / m


# --- results ------------------------------------------------------------------------------------------


def attempt(r: dict) -> int:
    return int(r["key"].split("#")[1])


def ok(results: list[dict]) -> list[dict]:
    return [r for r in results if not r.get("error") and r.get("workflow_graph")]


def is_lenient(r: dict) -> bool:
    return lenient(r, CHAIN)


def is_strict(r: dict) -> bool:
    return strict(r, CHAIN)


def types(r: dict) -> set[str]:
    return {n["type"] for n in r["workflow_graph"]["nodes"]}


def has(process: str):
    return lambda r: process in types(r)


def failure(r: dict) -> str | None:
    """Why a graph is not lenient-correct, as the first missing piece of the chain; None when correct."""
    present = types(r)
    for process in CHAIN:
        if process not in present:
            return f"no {process}"
    edges = _edges(r)
    if ("min-area-filter", "multi-ring-buffer") not in edges:
        return "filter not upstream of the rings"
    return None if is_lenient(r) else "other wiring"


FAILURES = {
    "no min-area-filter": "size filter missing",
    "filter not upstream of the rings": "size filter wired in the wrong place",
    "no multi-ring-buffer": "distance rings missing",
    "no city-boundary": "city boundary missing",
    "no osm-green-areas": "green areas missing",
    "other wiring": "other wiring error",
}


def structure(r: dict) -> tuple[str, ...]:
    return _structure(r)


def seed_prompt_text() -> str:
    return seed_prompt(RUN_DIR)


def current(variant: str = DEFAULT_VARIANT) -> list[dict]:
    """The currently accepted paraphrases and all seed runs of a variant, in their current review category."""
    return ok(load_results(RUN_DIR, variant))


def seeds(results: list[dict] | None = None, variant: str = DEFAULT_VARIANT) -> list[dict]:
    return sorted((r for r in results or current(variant) if r["category"] == SEED_CATEGORY), key=attempt)


def paraphrases(results: list[dict] | None = None, variant: str = DEFAULT_VARIANT) -> list[dict]:
    return [r for r in results or current(variant) if r["category"] != SEED_CATEGORY]


def reviewed(name: str = "reviewed.jsonl") -> list[dict]:
    return _read_jsonl(RUN_DIR / name)


def size_dropped() -> dict[str, dict]:
    """Paraphrases rejected in review for dropping the size requirement: key -> candidate."""
    return {_key(c): c for c in reviewed() if (c["review"].get("note") or "").startswith(SIZE_NOTE)}


def before_size_review() -> list[dict]:
    """Results of the paraphrases accepted before the size rule (2026-10-15), with their category then."""
    latest = latest_results(RUN_DIR)
    out = []
    for c in reviewed("reviewed.20261015-before-size.jsonl"):
        key = _key(c)
        if c["review"]["decision"] == "accept" and key in latest and latest[key]["text_sha1"] == _sha1(c["prompt"]):
            out.append({**latest[key], "category": c["review"]["category"], "prompt": c["prompt"]})
    return ok(out)


def archived(name: str = "workflows.20261014-haiku45.jsonl") -> list[dict]:
    """Latest result per key from an archived results file (the 2026-10-14 Haiku 4.5 run)."""
    return ok(list({r["key"]: r for r in _read_jsonl(RUN_DIR / name)}.values()))


def costs(runs_file: str = "runs.jsonl") -> dict[str, float]:
    return {m["thread_id"]: m.get("cost_usd") or 0.0 for m in _read_jsonl(RUN_DIR / runs_file)}


def cost(results: list[dict], runs_file: str = "runs.jsonl") -> float:
    c = costs(runs_file)
    return sum(c.get(r["thread_id"], 0.0) for r in results)


def metrics(results: list[dict], runs_file: str = "runs.jsonl") -> list[dict]:
    """The `RunTracker` record of each result; a re-run reuses the thread id, so the newest record counts."""
    records = {m["thread_id"]: m for m in _read_jsonl(RUN_DIR / runs_file)}
    return [records[r["thread_id"]] for r in results if r["thread_id"] in records]


@dataclass(frozen=True)
class Usage:
    """Mean context and cost per prompt of a group of results, from their `RunTracker` records."""

    n: int
    cost: float
    input_tokens: float
    output_tokens: float
    tool_def_share: float  # of all input tokens, the tool definitions shown to the LLM
    llm_calls: float
    seconds: float
    tools: float  # tools visible in the largest prompt

    @property
    def total(self) -> float:
        return self.cost * self.n


def usage(results: list[dict], runs_file: str = "runs.jsonl") -> Usage:
    records = metrics(results, runs_file)
    n = len(records)
    mean = lambda key: sum(m[key] or 0 for m in records) / n if n else 0.0
    tokens = sum(m["input_tokens"] for m in records)
    return Usage(
        n=n,
        cost=mean("cost_usd"),
        input_tokens=mean("input_tokens"),
        output_tokens=mean("output_tokens"),
        tool_def_share=sum(m["tool_def_tokens"] for m in records) / tokens if tokens else 0.0,
        llm_calls=mean("llm_calls"),
        seconds=mean("wall_ms") / 1000,
        tools=mean("max_visible_tools"),
    )


def by_category(results: list[dict]) -> dict[str, list[dict]]:
    out = collections.defaultdict(list)
    for r in results:
        out[r["category"]].append(r)
    return out


def params(results: list[dict], process: str, name: str) -> collections.Counter:
    counts = collections.Counter()
    for r in results:
        for n in r["workflow_graph"]["nodes"]:
            if n["type"] == process and name in n.get("config", {}):
                counts[json.dumps(n["config"][name], sort_keys=True)] += 1
            elif n["type"] == process:
                counts["unset"] += 1
    return counts


def unmet_counts(results: list[dict]) -> collections.Counter:
    return collections.Counter(len(r.get("unmet_capabilities") or []) for r in results)


VISUALISATION = re.compile(r"visuali|map|render|display|cartograph", re.IGNORECASE)
CLIP = re.compile(r"clip|intersect", re.IGNORECASE)


def unmet_matching(r: dict, rx: re.Pattern) -> bool:
    return any(rx.search(u["capability"]) for u in r.get("unmet_capabilities") or [])


def manager_searches(r: dict) -> list[str]:
    steps = [h.get("step") for h in r.get("decision_history") or [] if h.get("node") == "management_node"]
    return [s["instruction"] for s in steps if isinstance(s, dict) and isinstance(s.get("instruction"), str)]


def searched_network(r: dict) -> bool:
    # "OpenStreetMap" matches "street", so the word boundary in NETWORK_SEARCH matters.
    return any(NETWORK_SEARCH.search(q) for q in manager_searches(r))


def unmet_closest(results: list[dict], process: str) -> list[tuple[dict, dict]]:
    return [(r, u) for r in results for u in r.get("unmet_capabilities") or [] if u.get("closest_process") == process]


def mentions(results: list[dict], pattern: str) -> list[dict]:
    rx = re.compile(pattern, re.IGNORECASE)
    return [r for r in results if rx.search(r.get("response") or "")]


def wording(results: list[dict], pattern: str) -> list[dict]:
    rx = re.compile(pattern, re.IGNORECASE)
    return [r for r in results if rx.search(r["prompt"])]


def day(results: list[dict]) -> str:
    days = sorted({r["at"][:10] for r in results})
    return days[0] if len(days) == 1 else f"{days[0]} to {days[-1]}"


# --- output -------------------------------------------------------------------------------------------


def table(headers: list[str], rows: list[list], align: str | None = None) -> Markdown:
    """A Markdown table; `align` is one of l/r/c per column (default: first left, rest left)."""
    align = align or "l" * len(headers)
    rule = {"l": "---", "r": "---:", "c": ":---:"}
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(rule[a] for a in align) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return Markdown("\n".join(lines))


def md(text: str) -> Markdown:
    """Inline Markdown: a plain string from an inline expression is escaped, this isn't."""
    return Markdown(text)


def code(text: str) -> Markdown:
    return Markdown(f"`{text}`")


def yes(flag: bool) -> str:
    return "yes" if flag else "no"


def drift(results: list[dict], test) -> tuple[Comparison, float, float]:
    """Whether a rate drifts over the run order: first half vs second half, and the trend per 10 runs with its p."""
    xs = [int(test(r)) for r in results]
    h = len(xs) // 2
    slope, p = trend(xs)
    return Comparison(Rate(sum(xs[h:]), len(xs) - h), Rate(sum(xs[:h]), h)), 10 * slope, p
