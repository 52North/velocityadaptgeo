# Reports

Findings of the MCP vs. RAG evaluation, written as [Quarto](https://quarto.org) documents: Markdown with Python cells, so every number is computed from the run data when the document is rendered, and the sources diff like plain text.

| Source | Output | For |
|---|---|---|
| `summary.qmd` | `summary.md` (committed) | sharing: findings only, no operational detail |
| `detailed.qmd` | `detailed.html` (not committed) | the detailed report: runs, statistics, keys, open points |
| `analysis.py` | | data loading and statistics shared by both |
| `explorer.py` | | interactive table of the results (marimo) |

`analysis.py` reads the results through LangGraph's `src.batch.load_results` and uses the statistics in `src.batch_summary`, so the reports count exactly what `python -m src.batch --summary` counts. Those modules only use the standard library; the agent's dependencies aren't needed here.

## Rendering

Quarto comes with the project (`quarto-cli` on PyPI), so no system install is needed:

```
cd metrics/report
uv sync
uv run quarto render            # both documents
uv run quarto render summary.qmd
uv run quarto preview detailed.qmd   # live preview in the browser while editing
```

The run data lives in `metrics/prompt_gen/out/` (git-ignored), so rendering needs a local copy of the run. The run folder defaults to `20261012-174604_muenster_green_300m`; set `REPORT_RUN_DIR` for another.

After a review change or a new batch, re-render and commit `summary.md` with the sources.

## Run explorer

`explorer.py` is a [marimo](https://marimo.io) app for browsing the results: one row per run with its status (strict, lenient, failed, error), the failure reason, cost and prompt; sortable by any column, filterable by category, status, review decision and a prompt regex, with a per-category summary and the details of the selected row: its workflow graph drawn as a flowchart (expected chain in green, extra nodes grey, missing steps dashed red), the response and the searches.

```
uv run marimo run explorer.py     # as an app
uv run marimo edit explorer.py    # to change it
```

## Editing

- Inline numbers: `` `{python} seed.pct()` ``. A string from an inline expression is escaped; wrap it in `a.md(...)` or `a.code(...)` for Markdown or code formatting.
- Tables: `a.table(headers, rows)` in a cell.
- Cells are hidden (`echo: false` in `_quarto.yml`).
- `uv run ruff check . && uv run ruff format .` after editing `analysis.py`.

`report.html` (the earlier "CoolSpots Context Budget" page) is a separate, hand-made file, not rendered from here.
