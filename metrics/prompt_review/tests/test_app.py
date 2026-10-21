"""The Textual screens, driven with Textual's Pilot on a small run folder."""

import asyncio
import json
from typing import cast

from helpers import CANDIDATES, current_key, embedding_lines
from textual.widgets import DataTable

from prompt_review.app import (
    CategoryScreen,
    ListScreen,
    NoteScreen,
    ReviewScreen,
    build_app,
)
from prompt_review.data import load_decisions

# Enough fields for the review page: rejected before judging, so no scores or judge output.
RECORDS = [
    {**c, "judge": None, "operations_applied": ["x"], "reasoning": "plan"}
    for c in CANDIDATES
]


def _run(tmp_path, embeddings=True):
    run = tmp_path / "run"
    run.mkdir()
    (run / "candidates.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in RECORDS)
    )
    (run / "config.json").write_text(
        json.dumps(
            {
                "seed": {"id": "s", "text": "seed text"},
                "n_per_category": 2,
                "categories": ["lexical", "syntactic", "discourse"],
                "config": {"thresholds": {"near_duplicate_sem": 0.97}},
            }
        )
    )
    if embeddings:
        (run / "embeddings.jsonl").write_text(embedding_lines(RECORDS))
    return run


def _drive(app, steps):
    """Run the app headless, apply `steps(pilot)`, and return what it returns."""

    async def main():
        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.pause()
            return await steps(pilot)

    return asyncio.run(main())


def _cursor_key(app):
    table = app.screen.query_one(DataTable)
    return list(table.rows)[table.cursor_row].value


def test_starts_on_the_list_with_one_row_per_visible_candidate(tmp_path):
    app = build_app(_run(tmp_path))

    async def steps(pilot):
        table = app.screen.query_one(DataTable)
        return type(app.screen), table.row_count, [k.value for k in table.rows]

    screen, n, keys = _drive(app, steps)
    assert screen is ListScreen and n == 3  # default filter: passed gates
    assert keys == ["lexical#1", "lexical#3", "syntactic#2"]


def test_open_accept_and_return_to_the_same_row(tmp_path):
    run = _run(tmp_path)
    app = build_app(run)

    async def steps(pilot):
        await pilot.press("down", "enter")
        await pilot.pause()
        opened = (type(app.screen), current_key(app.state))
        await pilot.press("r")  # reject lexical#3: auto-advances to syntactic#2
        await pilot.press("left")  # back to lexical#3
        await pilot.press("escape")
        await pilot.pause()
        table = app.screen.query_one(DataTable)
        row = table.get_row("lexical#3")
        return opened, type(app.screen), _cursor_key(app), str(row[4])

    opened, screen, cursor, review_cell = _drive(app, steps)
    assert opened == (ReviewScreen, "lexical#3")
    assert screen is ListScreen and cursor == "lexical#3"
    assert review_cell == "reject"  # the row was updated in place
    assert (
        load_decisions(run / "reviewed.jsonl")["lexical#3"]["decision"] == "reject"
    )  # saved right away


def test_quick_decisions_in_the_list(tmp_path):
    run = _run(tmp_path)
    app = build_app(run)

    async def steps(pilot):
        await pilot.press("a")  # accept lexical#1, cursor moves on
        await pilot.pause()
        after_accept = _cursor_key(app)
        await pilot.press("up", "u")  # undo it
        await pilot.pause()
        return after_accept, dict(app.state.decisions)

    after_accept, decisions = _drive(app, steps)
    assert after_accept == "lexical#3"
    assert decisions == {} and load_decisions(run / "reviewed.jsonl") == {}


def test_filter_and_sort_in_the_list(tmp_path):
    app = build_app(_run(tmp_path))

    async def steps(pilot):
        app.state.filter = "all"
        cast(ListScreen, app.screen).refresh_rows()
        await pilot.press("s")  # similarity
        await pilot.pause()
        table = app.screen.query_one(DataTable)
        return (
            app.state.sort,
            [k.value for k in table.rows],
            str(table.get_row("lexical#2")[5]),
        )

    sort, keys, sim = _drive(app, steps)
    assert sort == "similarity"
    assert keys == ["lexical#2", "lexical#1", "lexical#3", "syntactic#1", "syntactic#2"]
    assert sim == "0.995"


def test_seed_similarity_column_and_sort_in_the_list(tmp_path):
    run = _run(tmp_path)
    scored = [{**r, "sem": sem} for r, sem in zip(RECORDS, [0.8, 0.9, 0.95, 0.7, 0.85])]
    del scored[1]["sem"]  # no score: shown as "—", sorted last
    (run / "candidates.jsonl").write_text("".join(json.dumps(r) + "\n" for r in scored))
    app = build_app(run)

    async def steps(pilot):
        app.state.filter = "all"
        cast(ListScreen, app.screen).refresh_rows()
        await pilot.press("s", "s", "s")  # similarity, category, seed similarity
        await pilot.pause()
        table = app.screen.query_one(DataTable)
        seed = {k.value: str(table.get_row(k.value)[6]) for k in table.rows}
        return app.state.sort, [k.value for k in table.rows], seed

    sort, keys, seed = _drive(app, steps)
    assert sort == "seed similarity"
    assert keys == ["lexical#3", "syntactic#2", "lexical#1", "syntactic#1", "lexical#2"]
    assert seed["lexical#3"] == "0.950" and seed["lexical#2"] == "—"


def test_filter_cycles_through_all_filters(tmp_path):
    app = build_app(_run(tmp_path))

    async def steps(pilot):
        seen = [app.state.filter]
        for _ in app.state.filters:
            await pilot.press("f")
            await pilot.pause()
            seen.append(app.state.filter)
            assert app.screen.query_one(DataTable).row_count == len(app.state.visible())
        return seen

    seen = _drive(app, steps)
    assert seen[0] == seen[-1] == "passed gates" and "kept near-duplicates" in seen


def test_note_input_edits_in_the_middle_and_escape_cancels(tmp_path):
    run = _run(tmp_path)
    app = build_app(run)

    async def steps(pilot):
        await pilot.press(
            "enter", "a", "left", "n"
        )  # accept lexical#1, back to it, open the note
        await pilot.pause()
        assert isinstance(app.screen, NoteScreen)
        await pilot.press(
            *"chek", "left", "c", "enter"
        )  # "chek" -> "check" by inserting before the last letter
        await pilot.pause()
        note = app.state.decisions["lexical#1"]["note"]
        await pilot.press("n", "x", "escape")  # cancelled: unchanged
        await pilot.pause()
        return note, app.state.decisions["lexical#1"]["note"], type(app.screen)

    note, after_cancel, screen = _drive(app, steps)
    assert note == after_cancel == "check"
    assert screen is ReviewScreen
    assert load_decisions(run / "reviewed.jsonl")["lexical#1"]["note"] == "check"


def test_category_move_with_a_number_key(tmp_path):
    run = _run(tmp_path)
    app = build_app(run)

    async def steps(pilot):
        await pilot.press("enter", "c")
        await pilot.pause()
        assert isinstance(app.screen, CategoryScreen)
        await pilot.press("3")  # discourse
        await pilot.pause()
        return type(app.screen), current_key(app.state)

    screen, current = _drive(app, steps)
    assert screen is ReviewScreen and current == "lexical#3"  # moved on after accepting
    saved = load_decisions(run / "reviewed.jsonl")["lexical#1"]
    assert (saved["decision"], saved["category"]) == ("accept", "discourse")


def test_works_without_embeddings(tmp_path):
    app = build_app(_run(tmp_path, embeddings=False))

    async def steps(pilot):
        await pilot.press("s", "enter", "d")
        await pilot.pause()
        return app.state.sort, "kept near-duplicates" in app.state.filters

    sort, has_filter = _drive(app, steps)
    assert sort == "similarity" and not has_filter


def test_status_key_in_the_list_and_on_the_review_page(tmp_path):
    run = _run(tmp_path)
    app = build_app(run)

    async def steps(pilot):
        await pilot.press("k")  # passed gates · currently accepted: all three
        await pilot.pause()
        table = app.screen.query_one(DataTable)
        before = [k.value for k in table.rows]
        await pilot.press("r")  # reject lexical#1: leaves the list
        await pilot.pause()
        after = [k.value for k in table.rows]
        await pilot.press("enter", "k")  # currently rejected, on the review page
        await pilot.pause()
        on_page = app.state.status, [current_key(app.state)]
        await pilot.press("escape")
        await pilot.pause()
        return before, after, on_page, [k.value for k in table.rows]

    before, after, on_page, rejected_rows = _drive(app, steps)
    assert before == ["lexical#1", "lexical#3", "syntactic#2"]
    assert after == ["lexical#3", "syntactic#2"]
    assert on_page == ("currently rejected", ["lexical#1"])
    assert rejected_rows == ["lexical#1"]
