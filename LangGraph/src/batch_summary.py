"""Summary of a batch run: graph structures, parameters and, given the expected chain, how often it is built.

    python -m src.batch <run_dir> [--variant V] --summary [--seed-only] [--expect a,b,c,...]

Reads the results through `load_results`, so only the currently accepted paraphrases and the seed runs
count, in their current review category.

A graph's structure is its set of edges between process types; node ids, positions and input values are
ignored. With `--expect`, a graph is *correct* when the chain of process types is present and wired in
that order (lenient: other nodes allowed) or when it is exactly that chain (strict). The seed runs repeat
one prompt, so for them the correct ratio is also followed run by run, to see whether it has settled.
"""

import collections
import json
import math
from itertools import pairwise

from src.batch import (
    DEFAULT_VARIANT,
    RUNS_FILE,
    SEED_CATEGORY,
    _read_jsonl,
    load_results,
)

CHECKPOINTS = (10, 20, 30, 40, 50, 75, 100, 150, 200)
RARE = 3  # structures seen this often or less list their keys


def _edges(result: dict) -> set[tuple[str, str]]:
    graph = result["workflow_graph"]
    types = {n["id"]: n["type"] for n in graph["nodes"]}
    return {(types[e["source"]], types[e["target"]]) for e in graph["edges"]}


def _structure(result: dict) -> tuple[str, ...]:
    return tuple(sorted(f"{a}->{b}" for a, b in _edges(result)))


def _attempt(result: dict) -> int:
    return int(result["key"].split("#")[1])


def lenient(result: dict, chain: list[str]) -> bool:
    """The expected chain is present and wired in order; other nodes are allowed."""
    return set(pairwise(chain)) <= _edges(result)


def strict(result: dict, chain: list[str]) -> bool:
    """The graph is exactly the expected chain."""
    types = sorted(n["type"] for n in result["workflow_graph"]["nodes"])
    return _edges(result) == set(pairwise(chain)) and types == sorted(chain)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for k successes out of n."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def fisher(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact test on [[a, b], [c, d]]."""
    n1, n2, k = a + b, c + d, a + c
    total = math.comb(n1 + n2, k)

    def p(x: int) -> float:
        return math.comb(n1, x) * math.comb(n2, k - x) / total

    observed = p(a)
    return min(1.0, sum(p(x) for x in range(max(0, k - n2), min(n1, k) + 1) if p(x) <= observed * (1 + 1e-9)))


def trend(xs: list[int]) -> tuple[float, float]:
    """Least-squares slope of the outcome over the run index, and the Cochran-Armitage p-value."""
    n, p = len(xs), sum(xs) / len(xs)
    if p in (0, 1):
        return 0.0, 1.0
    mean = (n + 1) / 2
    sxx = sum((i - mean) ** 2 for i in range(1, n + 1))
    slope = sum((i - mean) * (x - p) for i, x in enumerate(xs, 1)) / sxx
    z = sum((i - mean) * x for i, x in enumerate(xs, 1)) / math.sqrt(p * (1 - p) * sxx)
    return slope, math.erfc(abs(z) / math.sqrt(2))


def _ratio(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {k / n:.0%} [{lo:.0%}-{hi:.0%}]"


def _convergence(name: str, xs: list[int]) -> list[str]:
    """The running correct ratio of the seed runs, and whether it has settled."""
    n, k = len(xs), sum(xs)
    out = [f"  {name}: {_ratio(k, n)}", "     N  running   95% CI"]
    running = 0
    for i, x in enumerate(xs, 1):
        running += x
        if i in CHECKPOINTS or i == n:
            lo, hi = wilson(running, i)
            out.append(f"  {i:4}   {running / i:6.1%}   [{lo:5.1%}, {hi:5.1%}]")
    seq = "".join("Y" if x else "." for x in xs)
    out.append("  runs: " + " ".join(seq[i:i + 10] for i in range(0, n, 10)))
    if n >= 10:
        tail = [sum(xs[:i]) / i for i in range(n - 9, n + 1)]
        out.append(f"  running ratio over the last 10 runs: {min(tail):.1%}-{max(tail):.1%}")
        h = n // 2
        a, c = sum(xs[:h]), sum(xs[h:])
        out.append(f"  first {h}: {a / h:.0%} vs last {n - h}: {c / (n - h):.0%}, "
                   f"Fisher p = {fisher(a, h - a, c, n - h - c):.2f}")
        slope, p = trend(xs)
        out.append(f"  trend: {slope * 10:+.1%} per 10 runs, p = {p:.2f}")
    p = k / n
    if 0 < p < 1:
        need = 1.96 ** 2 * p * (1 - p)
        out.append(f"  runs needed for +/-5%: ~{math.ceil(need / 0.05 ** 2)}, for +/-10%: ~{math.ceil(need / 0.1 ** 2)}")
    return out


def summary(run_dir, seed_only: bool = False, chain: list[str] | None = None, variant: str = DEFAULT_VARIANT) -> str:
    results = [r for r in load_results(run_dir, variant) if not seed_only or r["category"] == SEED_CATEGORY]
    if not results:
        return "No results."
    ok = [r for r in results if not r.get("error")]
    costs = {m["thread_id"]: m.get("cost_usd") or 0 for m in _read_jsonl(run_dir / RUNS_FILE)}
    walls = [r["wall_ms"] / 1000 for r in ok]
    out = [f"{len(results)} results, {len(results) - len(ok)} errors, "
           f"{sum(1 for r in ok if (r.get('last_validation') or {}).get('valid'))} valid | "
           f"${sum(costs.get(r['thread_id'], 0) for r in results):.2f}"
           + (f" | {min(walls):.0f}-{max(walls):.0f} s per prompt" if walls else "")]
    if not ok:
        return out[0]

    structures = {r["key"]: _structure(r) for r in ok}
    ranked = [s for s, _ in collections.Counter(structures.values()).most_common()]
    label = {s: chr(ord("A") + i) if i < 26 else f"#{i + 1}" for i, s in enumerate(ranked)}

    out += ["", "Structures (edges between process types):"]
    for s in ranked:
        keys = sorted((k for k, v in structures.items() if v == s), key=lambda k: (k.split("#")[0], int(k.split("#")[1])))
        out.append(f"  {label[s]:>3} {len(keys):3}x {len(keys) / len(ok):4.0%}  {', '.join(s) or '(no edges)'}")
        if len(keys) <= RARE:
            out.append(f"               {', '.join(keys)}")

    by_category = collections.defaultdict(list)
    for r in ok:
        by_category[r["category"]].append(r)
    out += ["", "Per category:"]
    header = f"  {'category':<16} {'n':>4}  {'structures':>10}  most common"
    if chain:
        header += f"{'':<12}lenient correct            strict correct"
    out.append(header)
    for category, rs in sorted(by_category.items()):
        common, count = collections.Counter(structures[r["key"]] for r in rs).most_common(1)[0]
        line = (f"  {category:<16} {len(rs):4}  {len({structures[r['key']] for r in rs}):10}  "
                f"{label[common]:>3} {count / len(rs):4.0%}")
        if chain:
            line += (f"        {_ratio(sum(lenient(r, chain) for r in rs), len(rs)):<26} "
                     f"{_ratio(sum(strict(r, chain) for r in rs), len(rs))}")
        out.append(line)

    seeds = sorted(by_category.get(SEED_CATEGORY, []), key=_attempt)
    if chain and seeds:
        out += ["", f"Seed runs, correct = {' -> '.join(chain)}:"]
        out += _convergence("lenient", [int(lenient(r, chain)) for r in seeds])
        out += _convergence("strict", [int(strict(r, chain)) for r in seeds])

    presence = collections.Counter(n["type"] for r in ok for n in r["workflow_graph"]["nodes"])
    out += ["", "Node presence: " + ", ".join(f"{t} {c}" for t, c in presence.most_common())]
    params = collections.defaultdict(collections.Counter)
    for r in ok:
        for n in r["workflow_graph"]["nodes"]:
            for name, value in n.get("config", {}).items():
                if name not in ("server_url", "timeout_seconds"):
                    params[f"{n['type']}.{name}"][json.dumps(value, sort_keys=True)] += 1
    out.append("Parameters:")
    out += [f"  {name}: " + ", ".join(f"{v} {c}" for v, c in counts.most_common()) for name, counts in sorted(params.items())]

    per_graph = collections.Counter(len(r.get("unmet_capabilities") or []) for r in ok)
    closest = collections.Counter(u.get("closest_process") for r in ok for u in r.get("unmet_capabilities") or [])
    out.append("Unmet capabilities per graph: " + ", ".join(f"{n} unmet {c}" for n, c in sorted(per_graph.items())))
    out.append("Closest process of unmet capabilities: " + ", ".join(f"{p} {c}" for p, c in closest.most_common()))
    return "\n".join(out)
