"""Interactive table of the batch results: which prompts were built correctly, which failed, and why.

    cd metrics/report
    uv run marimo run explorer.py     # as an app
    uv run marimo edit explorer.py    # to change it

Correctness comes from `analysis.py` (and through it `src.batch_summary`), so it matches the reports.
"""

import marimo

__generated_with = "0.25.1"
app = marimo.App(width="full", app_title="Run explorer")


@app.cell
def _():
    import json

    import marimo as mo

    import analysis as a

    return a, json, mo


@app.cell
def _(a, mo):
    out = a.ROOT / "metrics/prompt_gen/out"
    run_dirs = sorted(p.name for p in out.iterdir() if (p / "workflows.jsonl").exists())
    run_pick = mo.ui.dropdown(
        run_dirs, value=a.RUN_DIR.name if a.RUN_DIR.name in run_dirs else run_dirs[-1], label="Run"
    )
    scope = mo.ui.radio(
        {"Current (accepted paraphrases + seed)": "current", "All results (incl. rejected, stale)": "all"},
        value="Current (accepted paraphrases + seed)",
        label="Prompts",
    )
    mo.hstack([run_pick, scope], justify="start", gap=2)
    return out, run_pick, scope


@app.cell
def _(a, out, run_pick, scope):
    run_dir = out / run_pick.value

    def _all_results() -> list[dict]:
        """Latest result per key, labelled with the review decision; prompts whose text changed are 'stale'."""
        reviews = {f"{c['category']}#{c['attempt']}": c for c in a._read_jsonl(run_dir / "reviewed.jsonl")}
        seed = a.seed_prompt(run_dir)
        rows = []
        for key, r in a.latest_results(run_dir).items():
            if key.startswith(f"{a.SEED_CATEGORY}#"):
                rows.append({**r, "category": a.SEED_CATEGORY, "prompt": seed, "review": "seed"})
                continue
            c = reviews.get(key)
            if c is None:
                rows.append({**r, "category": key.split("#")[0], "prompt": "", "review": "not reviewed"})
                continue
            stale = r["text_sha1"] != a._sha1(c["prompt"])
            rows.append(
                {
                    **r,
                    "category": c["review"]["category"],
                    "prompt": c["prompt"],
                    "review": "stale" if stale else c["review"]["decision"],
                }
            )
        return rows

    if scope.value == "current":
        results = [
            {**r, "review": "seed" if r["category"] == a.SEED_CATEGORY else "accept"} for r in a.load_results(run_dir)
        ]
    else:
        results = _all_results()
    costs = {m["thread_id"]: m.get("cost_usd") or 0.0 for m in a._read_jsonl(run_dir / "runs.jsonl")}
    return costs, results, run_dir


@app.cell
def _(a, costs, results):
    def _status(r: dict) -> str:
        if r.get("error"):
            return "error"
        if not r.get("workflow_graph"):
            return "no graph"
        if a.is_strict(r):
            return "strict"
        return "lenient" if a.is_lenient(r) else "failed"

    def _row(r: dict) -> dict:
        status = _status(r)
        graph = r.get("workflow_graph") or {}
        return {
            "key": r["key"],
            "category": r["category"],
            "review": r["review"],
            "status": status,
            "correct": status in ("strict", "lenient"),
            "failure": (r.get("error") or "")[:80] if status == "error" else (a.failure(r) or "") if graph else "",
            "nodes": len(graph.get("nodes", [])),
            "unmet": len(r.get("unmet_capabilities") or []),
            "valid": (r.get("last_validation") or {}).get("valid"),
            "wall_s": round(r["wall_ms"] / 1000, 1),
            "cost_usd": round(costs.get(r["thread_id"], 0.0), 4),
            "at": r["at"],
            "prompt": r["prompt"],
        }

    rows = sorted((_row(r) for r in results), key=lambda x: (x["category"], a.attempt(x)))
    by_key = {r["key"]: r for r in results}
    return by_key, rows


@app.cell
def _(mo, rows):
    categories = sorted({r["category"] for r in rows})
    statuses = ["strict", "lenient", "failed", "error", "no graph"]
    reviews = sorted({r["review"] for r in rows})
    cat_filter = mo.ui.multiselect(categories, value=categories, label="Category")
    status_filter = mo.ui.multiselect(
        statuses, value=[s for s in statuses if any(r["status"] == s for r in rows)], label="Status"
    )
    review_filter = mo.ui.multiselect(reviews, value=reviews, label="Review")
    search = mo.ui.text(placeholder="regex over prompt", label="Search", full_width=True)
    mo.hstack([cat_filter, status_filter, review_filter, search], justify="start", gap=2, widths=[1, 1, 1, 2])
    return cat_filter, review_filter, search, status_filter


@app.cell
def _(cat_filter, mo, review_filter, rows, search, status_filter):
    import re

    try:
        _rx = re.compile(search.value, re.IGNORECASE) if search.value else None
    except re.error:
        _rx = None
    shown = [
        r
        for r in rows
        if r["category"] in cat_filter.value
        and r["status"] in status_filter.value
        and r["review"] in review_filter.value
        and (_rx is None or _rx.search(r["prompt"]))
    ]
    table = mo.ui.table(
        shown,
        selection="single",
        page_size=25,
        format_mapping={"cost_usd": "{:.4f}".format},
        wrapped_columns=["prompt"],
        label=f"{len(shown)} of {len(rows)} results — click a column header to sort, a row to see its details",
    )
    return shown, table


@app.cell
def _(a, mo, shown):
    def _summary(group: list[dict]) -> dict:
        n = len(group)
        lenient = sum(r["correct"] for r in group)
        strict = sum(r["status"] == "strict" for r in group)
        lo, hi = a.wilson(lenient, n)
        return {
            "n": n,
            "lenient": lenient,
            "lenient %": round(100 * lenient / n, 1) if n else None,
            "95% range": f"{100 * lo:.0f}–{100 * hi:.0f}%",
            "strict": strict,
            "failed": sum(r["status"] == "failed" for r in group),
            "errors": sum(r["status"] == "error" for r in group),
            "cost_usd": round(sum(r["cost_usd"] for r in group), 2),
        }

    _cats = sorted({r["category"] for r in shown})
    _per_cat = [{"category": c, **_summary([r for r in shown if r["category"] == c])} for c in _cats]
    if shown:
        _per_cat.append({"category": "all shown", **_summary(shown)})
    summary_table = mo.ui.table(_per_cat, selection=None, show_column_summaries=False, label="By category")
    return (summary_table,)


@app.cell
def _(mo, summary_table, table):
    mo.vstack([summary_table, table])


@app.cell
def _(a, json, mo):
    HIDDEN_CONFIG = {"server_url", "timeout_seconds"}

    def _mm(text: str) -> str:
        """Text inside a quoted Mermaid label."""
        return text.replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")

    def _mm_id(node_id: str) -> str:
        return "n_" + "".join(ch if ch.isalnum() else "_" for ch in node_id)

    def graph_view(r: dict):
        """The workflow graph as a Mermaid flowchart: the expected chain in green, other nodes grey, missing
        chain processes as dashed red nodes; edges labelled `output → input`."""
        graph = r.get("workflow_graph") or {}
        if not graph.get("nodes"):
            return mo.md("(no graph)")
        types = {n["id"]: n["type"] for n in graph["nodes"]}
        chain_edges = set(zip(a.CHAIN, a.CHAIN[1:]))
        lines = ["flowchart LR"]
        for n in graph["nodes"]:
            config = [
                f"{k}: {v if isinstance(v, str) else json.dumps(v)}"[:48]
                for k, v in (n.get("config") or {}).items()
                if k not in HIDDEN_CONFIG
            ]
            label = "<br/>".join([f"<b>{_mm(n['type'])}</b>", *(_mm(c) for c in config)])
            cls = "chain" if n["type"] in a.CHAIN else "extra"
            lines.append(f'    {_mm_id(n["id"])}["{label}"]:::{cls}')
        for t in a.CHAIN:
            if t not in types.values():
                lines.append(f'    missing_{_mm_id(t)}["{_mm(t)}<br/>(missing)"]:::missing')
        thick = []
        for i, e in enumerate(graph["edges"]):
            label = _mm(f"{e.get('source_output', '')} → {e.get('target_input', '')}")
            lines.append(f'    {_mm_id(e["source"])} -->|"{label}"| {_mm_id(e["target"])}')
            if (types.get(e["source"]), types.get(e["target"])) in chain_edges:
                thick.append(str(i))
        lines += [
            "    classDef chain fill:#d9f2e3,stroke:#2e8b57,color:#111",
            "    classDef extra fill:#eeeeee,stroke:#888,color:#111",
            "    classDef missing fill:#fde2e2,stroke:#c0392b,stroke-dasharray:5 5,color:#111",
        ]
        if thick:
            lines.append(f"    linkStyle {','.join(thick)} stroke:#2e8b57,stroke-width:3px")
        return mo.mermaid("\n".join(lines))

    return (graph_view,)


@app.cell
def _(a, by_key, graph_view, json, mo, table):
    def _details(r: dict):
        graph = r.get("workflow_graph") or {}
        unmet = r.get("unmet_capabilities") or []
        parts = [
            mo.md(f"### {r['key']} · {r['category']}"),
            mo.md(f"**Prompt**\n\n> {r['prompt'] or '(not in review file)'}"),
            mo.md(f"**Graph** · {a.failure(r) or 'correct'}" if graph else "**Graph**"),
            graph_view(r),
        ]
        if unmet:
            parts.append(
                mo.md(
                    "**Unmet capabilities**\n\n"
                    + "\n".join(f"- {u['capability']} (closest: `{u.get('closest_process')}`)" for u in unmet)
                )
            )
        if r.get("error"):
            parts.append(mo.md(f"**Error**\n\n```\n{r['error']}\n```"))
        parts.append(
            mo.accordion(
                {
                    "Response": mo.md(r.get("response") or ""),
                    "Manager searches": mo.md("\n".join(f"- {q}" for q in a.manager_searches(r)) or "(none)"),
                    "Workflow graph (JSON)": mo.md(f"```json\n{json.dumps(graph, indent=2)}\n```"),
                }
            )
        )
        return mo.vstack(parts)

    _sel = table.value
    _sel = _sel[0] if isinstance(_sel, list) and _sel else None
    _details(by_key[_sel["key"]]) if _sel else mo.md("_Select a row to see the prompt, graph and response._")


if __name__ == "__main__":
    app.run()
