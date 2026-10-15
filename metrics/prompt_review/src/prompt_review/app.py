"""Full-screen review of a run's candidates (Textual): a list of all candidates, and a review page for
one. Both share one ReviewState, so filter, sort order, position and decisions carry over."""

from pathlib import Path
from typing import ClassVar, cast

from rich.console import Console
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Input, OptionList, Static

from prompt_review.data import (
    candidate_key,
    categories,
    first_config,
    latest_config,
    load_candidates,
    load_decisions,
    save,
)
from prompt_review.render import (
    LIST_COLUMNS,
    _body,
    footer_text,
    list_preview,
    list_row,
)
from prompt_review.similarity import load_embeddings
from prompt_review.state import ReviewState

LIST_HELP = "↑/↓ PgUp/PgDn move · Enter open · a accept · r reject · u undo · f filter · s sort · q quit"


class NoteScreen(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, initial: str):
        super().__init__()
        self.initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static("Note  (Enter to save, Esc to cancel)")
            yield Input(value=self.initial, id="note")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss(None)


class CategoryScreen(ModalScreen[str | None]):
    """Pick the category to accept the candidate into: a number key, or ↑/↓ and Enter."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, categories: list[str]):
        super().__init__()
        self.categories = categories

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static("Accept into category  (number or Enter, Esc to cancel)")
            yield OptionList(
                *(f"{i} {name}" for i, name in enumerate(self.categories, 1)),
                id="categories",
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self.categories[event.option_index])

    def on_key(self, event) -> None:
        if (
            event.character
            and event.character.isdigit()
            and 1 <= int(event.character) <= len(self.categories)
        ):
            event.stop()
            self.dismiss(self.categories[int(event.character) - 1])

    def action_cancel(self) -> None:
        self.dismiss(None)


class ListScreen(Screen):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("a", "decide('accept')", "accept"),
        Binding("r", "decide('reject')", "reject"),
        Binding("u", "undo", "undo"),
        Binding("f", "filter", "filter"),
        Binding("s", "sort", "sort"),
        Binding("q", "app.quit", "quit"),
        Binding("escape", "app.quit", "quit", show=False),
    ]

    def __init__(self):
        super().__init__()
        self.shown: list[str] = []  # keys in table order
        self.cells: dict[str, list] = {}
        self.prompt_width = 0

    @property
    def app(self) -> "ReviewApp":  # type: ignore[override]
        return cast("ReviewApp", super().app)

    @property
    def state(self) -> ReviewState:
        return self.app.state

    def compose(self) -> ComposeResult:
        yield Static(id="list-header")
        yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
        yield Static(id="preview")
        yield Static(LIST_HELP, id="list-help")

    def on_screen_resume(self) -> None:
        self.refresh_rows()

    def on_resize(self) -> None:
        self.refresh_rows()

    def _prompt_width(self) -> int:
        fixed = (
            sum(w for _, w in LIST_COLUMNS if w) + 2 * len(LIST_COLUMNS) + 2
        )  # cell padding, scrollbar
        return max(20, self.size.width - fixed)

    def refresh_rows(self) -> None:
        """Update the table to the state: cells in place when the rows are the same, else rebuilt."""
        table = self.query_one(DataTable)
        visible = self.state.visible()
        keys = [candidate_key(c) for c in visible]
        width = self._prompt_width()
        if width != self.prompt_width or not table.columns:
            table.clear(columns=True)
            for label, w in LIST_COLUMNS:
                table.add_column(label, width=w or width, key=label)
            self.prompt_width, self.shown = width, []
        if keys != self.shown:
            table.clear()
            self.cells = {}
            for c in visible:
                self.cells[candidate_key(c)] = list_row(c, self.state, width)
                table.add_row(*self.cells[candidate_key(c)], key=candidate_key(c))
            self.shown = keys
        else:
            for c in visible:
                key = candidate_key(c)
                row = list_row(c, self.state, width)
                for (label, _), old, new in zip(LIST_COLUMNS, self.cells[key], row):
                    if str(old) != str(new) or getattr(old, "style", None) != getattr(
                        new, "style", None
                    ):
                        table.update_cell(key, label, new)
                self.cells[key] = row
        if visible:
            table.move_cursor(row=self.state.index)
        self.show_header()
        self.query_one("#preview", Static).update(
            list_preview(self.state.current(), self.state)
        )

    def show_header(self) -> None:
        s = self.state
        a, r, _ = s.counts()
        source = "live" if s.embeddings is not None else "at generation"
        self.query_one("#list-header", Static).update(
            f"[b]{self.app.run_name}[/b]   {a + r}/{len(s.candidates)} reviewed ({a} accepted, {r} rejected) · "
            f"filter: {s.filter} ({len(s.visible())}) · sort: {s.sort} · similarity: {source}"
        )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row < len(self.state.visible()):
            self.state.index = event.cursor_row
            self.query_one("#preview", Static).update(
                list_preview(self.state.current(), self.state)
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.state.index = event.cursor_row
        self.app.push_screen(ReviewScreen())

    def action_decide(self, decision: str) -> None:
        if self.state.current() is not None:
            self.state.decide(decision)
            self.app.save()
            self.refresh_rows()

    def action_undo(self) -> None:
        if self.state.current() is not None:
            self.state.clear()
            self.app.save()
            self.refresh_rows()

    def action_filter(self) -> None:
        self.state.cycle_filter()
        self.refresh_rows()

    def action_sort(self) -> None:
        self.state.cycle_sort()
        self.refresh_rows()


class ReviewScreen(Screen):
    # Priority, so the scroll container's own left/right/home/end don't take them.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "move(-1)", "previous", priority=True),
        Binding("right", "move(1)", "next", priority=True),
        Binding("home", "first", "first", priority=True),
        Binding("end", "last", "last", priority=True),
        Binding("a", "decide('accept')", "accept"),
        Binding("r", "decide('reject')", "reject"),
        Binding("u", "undo", "undo"),
        Binding("c", "category", "category"),
        Binding("n", "note", "note"),
        Binding("g", "next_unreviewed", "unreviewed"),
        Binding("d", "details", "details"),
        Binding("f", "filter", "filter"),
        Binding("s", "sort", "sort"),
        Binding("escape", "app.pop_screen", "list"),
        Binding("q", "app.quit", "quit"),
    ]

    @property
    def app(self) -> "ReviewApp":  # type: ignore[override]
        return cast("ReviewApp", super().app)

    @property
    def state(self) -> ReviewState:
        return self.app.state

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="scroll"):
            yield Static(id="body")
        yield Static(id="review-footer")

    def on_mount(self) -> None:
        self.query_one("#scroll").focus()

    def on_screen_resume(self) -> None:
        self.show(top=False)

    def show(self, top: bool = True) -> None:
        self.query_one("#body", Static).update(
            _body(self.state, self.app.seed_text, self.app.details)
        )
        self.query_one("#review-footer", Static).update(footer_text(self.state))
        if top:
            self.query_one("#scroll", VerticalScroll).scroll_home(animate=False)

    def _changed(self) -> None:
        self.app.save()
        self.show()

    def action_move(self, delta: int) -> None:
        self.state.move(delta)
        self.show()

    def action_first(self) -> None:
        self.state.first()
        self.show()

    def action_last(self) -> None:
        self.state.last()
        self.show()

    def action_next_unreviewed(self) -> None:
        self.state.next_unreviewed()
        self.show()

    def action_details(self) -> None:
        self.app.details = not self.app.details
        self.show(top=False)

    def action_filter(self) -> None:
        self.state.cycle_filter()
        self.show()

    def action_sort(self) -> None:
        self.state.cycle_sort()
        self.show(top=False)

    def action_decide(self, decision: str) -> None:
        if self.state.current() is not None:
            self.state.decide(decision)
            self._changed()

    def action_undo(self) -> None:
        if self.state.current() is not None:
            self.state.clear()
            self._changed()

    def action_category(self) -> None:
        if self.state.current() is None:
            return

        def done(category: str | None) -> None:
            if category is not None:
                self.state.decide("accept", category)
                self._changed()

        self.app.push_screen(CategoryScreen(self.app.categories), done)

    def action_note(self) -> None:
        c = self.state.current()
        if c is None:
            return
        key = candidate_key(c)
        existing = self.state.decisions.get(key, {}).get(
            "note"
        ) or self.state.pending_notes.get(key, "")

        def done(note: str | None) -> None:
            if note is not None:
                self.state.set_note(note)
                self.app.save()
                self.show(top=False)

        self.app.push_screen(NoteScreen(existing), done)


class ReviewApp(App):
    TITLE = "prompt-review"
    CSS = """
    #list-header, #list-help, #review-footer { height: auto; padding: 0 1; }
    #list-help, #review-footer { color: $text-muted; border-top: solid $panel; }
    #table { height: 1fr; }
    #preview { height: auto; max-height: 14; padding: 0 1; border-top: solid $panel; }
    #scroll { height: 1fr; padding: 0 1; }
    .dialog { width: 80%; height: auto; padding: 1 2; border: round $accent; background: $surface; }
    NoteScreen, CategoryScreen { align: center middle; }
    #categories { height: auto; }
    """

    def __init__(
        self,
        state: ReviewState,
        seed_text: str,
        categories: list[str],
        save_path: Path,
        run_name: str,
    ):
        super().__init__()
        self.state = state
        self.seed_text = seed_text
        self.categories = categories
        self.save_path = save_path
        self.run_name = run_name
        self.details = False

    def on_mount(self) -> None:
        self.push_screen(ListScreen())

    def save(self) -> None:
        save(self.save_path, self.state)


def build_app(run_dir: Path, save_path: Path | None = None) -> ReviewApp:
    candidates = load_candidates(run_dir)
    category_keys = categories(run_dir, candidates)
    path = save_path or run_dir / "reviewed.jsonl"
    state = ReviewState(
        candidates,
        load_decisions(run_dir / "reviewed.jsonl"),
        load_embeddings(run_dir, candidates),
        latest_config(run_dir)["config"]["thresholds"]["near_duplicate_sem"],
        category_keys,
    )
    return ReviewApp(
        state, first_config(run_dir)["seed"]["text"], category_keys, path, run_dir.name
    )


def review(run_dir: Path) -> None:
    app = build_app(run_dir)
    app.run()
    state, console = app.state, Console()
    if state.embeddings is not None and state.embeddings.warnings:
        console.print(
            f"{len(state.embeddings.warnings)} candidate(s) without a usable stored embedding (no live similarities):",
            style="yellow",
        )
        for w in state.embeddings.warnings:
            console.print("  " + w)
    a, r, u = state.counts()
    console.print(
        f"Saved {a + r} reviews to {app.save_path} ({a} accepted, {r} rejected, {u} unreviewed)."
    )
