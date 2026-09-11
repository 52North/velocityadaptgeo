"""Per-turn context and cost tracking, for comparing workflow variants (MCP tool listing vs pgvector retrieval).

`RunTracker` is a LangChain callback attached to one turn's run config. It only reads what every
variant shares - the prompts the LLM receives, the usage it reports, and the `candidate_processes`
a node returns - so the same file works on every branch. Each turn appends one JSON line to
METRICS_FILE, labelled with WORKFLOW_VARIANT.
"""

import json
import os
import time
from difflib import SequenceMatcher
from functools import lru_cache
from itertools import combinations

import anthropic
from langchain_core.callbacks import BaseCallbackHandler

METRICS_FILE = os.getenv("METRICS_FILE", "metrics/runs.jsonl")
VARIANT = os.getenv("WORKFLOW_VARIANT", "unknown")
PRICES_PER_MTOK = {"claude-haiku-4-5-20251001": (1.0, 5.0)}  # USD (input, output)


def _name(candidate: dict) -> str:
    return candidate.get("tool") or candidate.get("process_id") or ""


@lru_cache(maxsize=None)
def _tokens(model: str, text: str) -> int | None:
    """Exact token count of `text` for `model` via Anthropic's free count_tokens endpoint (None if unavailable)."""
    try:
        return len(text) and anthropic.Anthropic().messages.count_tokens(model=model, messages=[{"role": "user", "content": text}]).input_tokens
    except Exception:
        return None


def _closest_pair(candidates: list[dict], text) -> list:
    """Return `[ratio, name_a, name_b]` for the two candidates whose `text` is most alike (1.0 = identical)."""
    return max(([round(SequenceMatcher(None, text(a), text(b)).ratio(), 3), _name(a), _name(b)]
                for a, b in combinations(candidates, 2)), default=[0.0, None, None])


class RunTracker(BaseCallbackHandler):
    """Collect LLM context size, token usage, cost, node timings and tool visibility of one workflow turn.

    Per LLM call: input/output tokens, prompt size, how many candidate tools the prompt carries
    (`visible_tools`), and the estimated tokens of their full definitions (`tool_def_tokens`) versus
    their names only (`tool_name_tokens`, the deferred-loading equivalent). Both are counted exactly on
    the candidate block as it appears in the prompt, once the turn has ended. Per search: tool and server count, and the most
    similar tool names and descriptions, as a measure of how well-differentiated the visible tools are.
    """

    run_inline = True

    def __init__(self, thread_id: str):
        self.thread_id, self.root, self.calls, self.searches, self.nodes, self.open = thread_id, None, [], [], [], {}
        self.candidates: list[dict] = []

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, metadata=None, **kwargs):
        if parent_run_id is None:
            self.root, self.started = run_id, time.time()
            self.prompt = getattr(((inputs or {}).get("messages") or [None])[-1], "content", None)
        elif kwargs.get("name") and kwargs.get("name") == (metadata or {}).get("langgraph_node"):
            self.open[run_id] = {"node": kwargs["name"], "t": time.time()}

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        if run_id == self.root:
            return self._write(outputs if isinstance(outputs, dict) else {})
        node = self.open.pop(run_id, None)
        if node is None:
            return
        self.nodes.append((node["node"], (time.time() - node["t"]) * 1000))
        if isinstance(outputs, dict) and "candidate_processes" in outputs:
            self.candidates = outputs["candidate_processes"] or []
            self.searches.append({
                "node": node["node"], "visible_tools": len(self.candidates),
                "servers": len({c.get("server_url") for c in self.candidates}),
                "closest_names": _closest_pair(self.candidates, _name),
                "closest_descriptions": _closest_pair(self.candidates, lambda c: c.get("description") or ""),
            })

    def on_chain_error(self, error, *, run_id, **kwargs):
        if run_id == self.root:
            self._write({}, error=repr(error))

    def on_chat_model_start(self, serialized, messages, *, run_id, metadata=None, **kwargs):
        text = "".join(str(m.content) for m in messages[0])
        n, block = next(((n, b) for n in range(len(self.candidates), 0, -1)
                         for b in (json.dumps(self.candidates[:n], indent=2), str(self.candidates[:n])) if b in text), (0, ""))
        visible = self.candidates[:n] or [c for c in self.candidates if f"{_name(c)}\"" in text or f"{_name(c)}'" in text]
        self.open[run_id] = {
            "node": (metadata or {}).get("langgraph_node"), "model": (metadata or {}).get("ls_model_name"),
            "t": time.time(), "messages": len(messages[0]), "prompt_chars": len(text), "visible_tools": len(visible),
            "defs": block or (json.dumps(visible) if visible else ""), "names": json.dumps([_name(c) for c in visible]) if visible else "",
        }

    def on_llm_end(self, response, *, run_id, **kwargs):
        call = self.open.pop(run_id, None)
        if call is None:
            return
        usage = getattr(response.generations[0][0], "message", None)
        usage = getattr(usage, "usage_metadata", None) or {}
        started, price = call.pop("t"), PRICES_PER_MTOK.get(call["model"])
        self.calls.append({
            **call, "ms": round((time.time() - started) * 1000),
            "input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0),
            "cost_usd": price and (usage.get("input_tokens", 0) * price[0] + usage.get("output_tokens", 0) * price[1]) / 1e6,
        })

    def _write(self, state: dict, error: str | None = None):
        wall_ms = round((time.time() - self.started) * 1000)
        for c in self.calls:
            c["tool_def_tokens"], c["tool_name_tokens"] = _tokens(c["model"], c.pop("defs")), _tokens(c["model"], c.pop("names"))
        total = lambda key: sum(c[key] or 0 for c in self.calls)
        nodes = {}
        for name, ms in self.nodes:
            nodes.setdefault(name, {"runs": 0, "ms": 0})
            nodes[name]["runs"] += 1
            nodes[name]["ms"] += round(ms)
        record = {
            "variant": VARIANT, "thread_id": self.thread_id, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "prompt": self.prompt, "error": error, "wall_ms": wall_ms,
            "iterations": state.get("iteration"), "graph_nodes": len((state.get("workflow_graph") or {}).get("nodes", [])),
            "unmet_capabilities": len(state.get("unmet_capabilities") or []),
            "llm_calls": len(self.calls), "input_tokens": total("input_tokens"), "output_tokens": total("output_tokens"),
            "peak_input_tokens": max((c["input_tokens"] for c in self.calls), default=0),
            "tool_def_tokens": total("tool_def_tokens"), "tool_name_tokens": total("tool_name_tokens"),
            "max_visible_tools": max((c["visible_tools"] for c in self.calls), default=0),
            "cost_usd": round(total("cost_usd"), 6), "nodes": nodes, "searches": self.searches, "calls": self.calls,
        }
        os.makedirs(os.path.dirname(METRICS_FILE) or ".", exist_ok=True)
        with open(METRICS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")


def _closest(searches: list[dict], key: str) -> str | None:
    """Most alike candidate pair over all searches, as `ratio (name_a / name_b)`."""
    if not searches:
        return None
    ratio, a, b = max((s[key] for s in searches), key=lambda pair: pair[0])
    return f"{ratio} ({str(a).split('__')[-1]} / {str(b).split('__')[-1]})"


def _row(runs: list[dict]) -> dict:
    """Average one group of turn records into report metrics: context cost first, then tool visibility, then outcome."""
    mean = lambda f, digits=None: round(sum(map(f, runs)) / len(runs), digits)
    searches = [s for r in runs for s in r["searches"]]
    saved = lambda r: sum(((c.get("tool_def_tokens") or 0) - (c.get("tool_name_tokens") or 0))
                          * PRICES_PER_MTOK.get(c.get("model"), (0, 0))[0] for c in r["calls"]) / 1e6
    return {
        "runs (failed)": f"{len(runs)} ({sum(bool(r['error']) for r in runs)})",
        "LLM calls": mean(lambda r: r["llm_calls"], 1),
        "input tokens": mean(lambda r: r["input_tokens"]),
        "peak input tokens (one call)": mean(lambda r: r["peak_input_tokens"]),
        "output tokens": mean(lambda r: r["output_tokens"]),
        "tool definition tokens": mean(lambda r: r["tool_def_tokens"]),
        "tool definition share of input": f"{sum(r['tool_def_tokens'] for r in runs) / max(sum(r['input_tokens'] for r in runs), 1):.0%}",
        "tool name tokens (defer loading)": mean(lambda r: r["tool_name_tokens"]),
        "cost USD": mean(lambda r: r["cost_usd"], 4),
        "cost USD with names only": mean(lambda r: r["cost_usd"] - saved(r), 4),
        "max visible tools (one call)": max(r["max_visible_tools"] for r in runs),
        "tools per search": round(sum(s["visible_tools"] for s in searches) / len(searches), 1) if searches else None,
        "servers per search": round(sum(s["servers"] for s in searches) / len(searches), 1) if searches else None,
        "closest tool names": _closest(searches, "closest_names"),
        "closest tool descriptions": _closest(searches, "closest_descriptions"),
        "wall time s": mean(lambda r: r["wall_ms"] / 1000, 1),
        "graph nodes": mean(lambda r: r["graph_nodes"], 1),
        "unmet capabilities": mean(lambda r: r["unmet_capabilities"], 1),
    }


def _table(runs: list[dict]) -> str:
    """Markdown table with one column per workflow variant, averaged over its runs."""
    groups = {}
    for r in runs:
        groups.setdefault(r["variant"], []).append(r)
    rows = {variant: _row(group) for variant, group in groups.items()}
    cell = lambda v: f"{v:,}" if isinstance(v, (int, float)) else (v or "-")
    lines = [f"| metric | {' | '.join(rows)} |", f"|---|{'---|' * len(rows)}"]
    return "\n".join(lines + [f"| {k} | {' | '.join(cell(r[k]) for r in rows.values())} |" for k in next(iter(rows.values()))])


def report(path: str = METRICS_FILE) -> str:
    """Write `report.md` next to the metrics file: variants compared over all turns, then per prompt. Returns its path."""
    runs = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    parts = ["# Workflow variant comparison", "", "## All prompts", _table(runs)]
    for prompt in dict.fromkeys(r["prompt"] for r in runs):
        title = prompt if len(prompt or "") <= 80 else prompt[:80] + "…"
        parts += ["", f"## {title}", _table([r for r in runs if r["prompt"] == prompt])]
    out = os.path.join(os.path.dirname(path) or ".", "report.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(parts) + "\n")
    return out


if __name__ == "__main__":
    print(report())
