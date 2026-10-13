"""Full-screen manual review of a run's candidates.

Decisions are saved to out/<run_id>/reviewed.jsonl: one full candidate record per reviewed
candidate, plus a `review` object. candidates.jsonl is only read. reviewed.jsonl is rewritten
(temp file + rename) after every change, since moving back lets you change a decision.
"""

import difflib
import json
from datetime import datetime
from pathlib import Path

from rich.console import Console, Group
from rich.layout import Layout
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from prompt_gen import typology
from prompt_gen.run import read_jsonl

BASE_FILTERS = ("all", "passed gates", "rejected by gates", "unreviewed")
DEFAULT_FILTER = "passed gates"


def candidate_key(c: dict) -> str:
    return f"{c['category']}#{c['attempt']}"


def reason_group(c: dict) -> str | None:
    """`relative:green_space,size` -> `relative`."""
    return c["reject_reason"].split(":")[0] if c.get("reject_reason") else None


# --- state -------------------------------------------------------------------------------------


class ReviewState:
    def __init__(self, candidates: list[dict], decisions: dict[str, dict] | None = None):
        self.candidates = candidates
        self.decisions = dict(decisions or {})
        self.pending_notes: dict[str, str] = {}  # notes typed before the candidate was decided
        reasons = sorted({r for c in candidates if (r := reason_group(c))})
        self.filters = [*BASE_FILTERS, *(f"reason: {r}" for r in reasons)]
        self.filter = DEFAULT_FILTER
        self.index = 0  # position within visible()

    def _matches(self, c: dict) -> bool:
        f = self.filter
        if f == "all":
            return True
        if f == "passed gates":
            return c["accepted"]
        if f == "rejected by gates":
            return not c["accepted"]
        if f == "unreviewed":
            return candidate_key(c) not in self.decisions
        return reason_group(c) == f.removeprefix("reason: ")

    def visible(self) -> list[dict]:
        return [c for c in self.candidates if self._matches(c)]

    def current(self) -> dict | None:
        v = self.visible()
        return v[self.index] if v else None

    def _clamp(self) -> None:
        self.index = max(0, min(self.index, len(self.visible()) - 1))

    def move(self, delta: int) -> None:
        self.index += delta
        self._clamp()

    def first(self) -> None:
        self.index = 0

    def last(self) -> None:
        self.index = len(self.visible()) - 1
        self._clamp()

    def next_unreviewed(self) -> bool:
        v = self.visible()
        n = len(v)
        for step in range(1, n + 1):
            i = (self.index + step) % n
            if candidate_key(v[i]) not in self.decisions:
                self.index = i
                return True
        return False

    def _change(self, apply, advance: bool) -> None:
        """Apply a change to the current candidate, then land on the right candidate even if the
        change removed the current one from the filter (e.g. deciding while filtering unreviewed)."""
        before = self.visible()
        if not before:
            return
        current = before[self.index]
        target = before[self.index + 1] if advance and self.index + 1 < len(before) else current
        apply(candidate_key(current))
        after = [candidate_key(c) for c in self.visible()]
        for wanted in (target, current):
            if candidate_key(wanted) in after:
                self.index = after.index(candidate_key(wanted))
                return
        self._clamp()

    def decide(self, decision: str, category: str | None = None) -> None:
        def apply(key: str) -> None:
            c = next(c for c in self.candidates if candidate_key(c) == key)
            note = self.pending_notes.pop(key, None) or self.decisions.get(key, {}).get("note", "")
            self.decisions[key] = {
                "decision": decision,
                "category": category or c["category"],
                "note": note,
                "at": datetime.now().isoformat(timespec="seconds"),
            }

        self._change(apply, advance=True)

    def set_note(self, note: str) -> None:
        """A note on an undecided candidate is kept and saved with the decision later."""
        c = self.current()
        if c is None:
            return
        key = candidate_key(c)
        if key in self.decisions:
            self.decisions[key]["note"] = note
        else:
            self.pending_notes[key] = note

    def clear(self) -> None:
        self._change(lambda key: self.decisions.pop(key, None), advance=False)

    def cycle_filter(self) -> None:
        keep = self.current()
        self.filter = self.filters[(self.filters.index(self.filter) + 1) % len(self.filters)]
        keys = [candidate_key(c) for c in self.visible()]
        self.index = keys.index(candidate_key(keep)) if keep and candidate_key(keep) in keys else 0

    def counts(self, category: str | None = None) -> tuple[int, int, int]:
        """(accepted, rejected, unreviewed) over all candidates, optionally of one category."""
        acc = rej = todo = 0
        for c in self.candidates:
            if category and c["category"] != category:
                continue
            d = self.decisions.get(candidate_key(c))
            if d is None:
                todo += 1
            elif d["decision"] == "accept":
                acc += 1
            else:
                rej += 1
        return acc, rej, todo


# --- files -------------------------------------------------------------------------------------


def load_candidates(run_dir: Path) -> list[dict]:
    """Candidates that produced a paraphrase (generation errors are left out). Candidates rejected by
    the stem check have no scores or judge result."""
    return [c for c in read_jsonl(run_dir / "candidates.jsonl") if c.get("prompt")]


def load_decisions(path: Path) -> dict[str, dict]:
    return {candidate_key(r): r["review"] for r in read_jsonl(path)}


def save(path: Path, state: ReviewState) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for c in state.candidates:
            review = state.decisions.get(candidate_key(c))
            if review is not None:
                f.write(json.dumps({**c, "review": review}, ensure_ascii=False) + "\n")
    tmp.replace(path)


# --- drawing -----------------------------------------------------------------------------------


def word_diff(old: str, new: str) -> Text:
    """Word-level diff: deletions red and struck through, insertions green."""
    a, b = old.split(), new.split()
    text = Text()
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op in ("delete", "replace"):
            text.append(" ".join(a[i1:i2]) + " ", style="red strike")
        if op in ("insert", "replace"):
            text.append(" ".join(b[j1:j2]) + " ", style="green")
        if op == "equal":
            text.append(" ".join(a[i1:i2]) + " ")
    return text


def _badge(label: str, style: str) -> Text:
    return Text(f" {label} ", style=style)


def render(state: ReviewState, seed_text: str, details: bool, footer: Text) -> Layout:
    """Full screen: the candidate on top, the key bar pinned to the bottom. If the candidate doesn't
    fit (details open in a small terminal), its bottom is cut off, never the key bar."""
    layout = Layout()
    layout.split_column(Layout(_body(state, seed_text, details), name="body"), Layout(Group(Rule(), footer), size=4))
    return layout


def _body(state: ReviewState, seed_text: str, details: bool) -> Group:
    c = state.current()
    visible = state.visible()
    if c is None:
        return Group(Text(f"No candidates match the filter '{state.filter}'. Press f to change it, q to quit."))

    key = candidate_key(c)
    review = state.decisions.get(key)
    header = Text()
    # Position among all candidates of the run, whatever the filter.
    header.append(f"{state.candidates.index(c) + 1}/{len(state.candidates)}", style="bold")
    header.append("   ")
    header.append(f"{c['category']}", style="bold")
    header.append(f" · attempt {c['attempt']} · filter: {state.filter}")
    if state.filter != "all":
        header.append(f" ({state.index + 1}/{len(visible)})")
    header.append("   ")
    header.append_text(_badge("gates: ACCEPTED", "black on green") if c["accepted"] else _badge(f"gates: {c['reject_reason']}", "black on red"))
    header.append("  ")
    if review is None:
        header.append_text(_badge("review: —", "reverse"))
    else:
        moved = f" → {review['category']}" if review["category"] != c["category"] else ""
        header.append_text(_badge(f"review: {review['decision']}{moved}", "black on green" if review["decision"] == "accept" else "black on red"))

    info = Table.grid(padding=(0, 2))
    info.add_column(style="bold", no_wrap=True)
    info.add_column(ratio=1)
    j = c.get("judge")
    if "stems" in c:
        stem = c["stems"]
        if stem["new"] or stem["missing"]:
            row = Text("failed", style="red")
            if stem["new"]:
                row.append(f"   new words: {', '.join(stem['new'])}")
            if stem["missing"]:
                row.append(f"   missing: {', '.join(stem['missing'])}")
        else:
            row = Text("only forms of the seed's words", style="green")
        info.add_row("stems", row)
    if j is None:
        info.add_row("judge", Text("not run (rejected by the stem check)", style="dim"))
    else:
        scores = Text(f"sem {c['sem']:.3f}   prag {c['prag']:.3f}   prag (no instr.) {c['prag_no_instruction']:.3f}   ")
        scores.append(
            f"max sem in category {c['max_sem_same_category']:.3f}" if c["max_sem_same_category"] is not None
            else "max sem in category —"
        )
        problems = [v for v in j["verdicts"] if v["status"] != "kept"]
        if problems:
            judge = Text()
            for i, v in enumerate(problems):
                judge.append(("\n" if i else "") + f"{v['status']} {v['id']}: ", style="red" if v["status"] == "failed" else "yellow")
                judge.append(v["reason"])
        else:
            judge = Text(f"all {len(j['verdicts'])} constraints kept", style="green")
        if j["matches_category"]:
            category_row = Text("matches", style="green")
        else:
            category_row = Text("does not match: ", style="yellow")
            category_row.append(j["category_reason"], style="default")
        if "grammatical" not in j:  # judged before the grammar check existed
            grammar_row = Text("not checked", style="dim")
        elif j["grammatical"]:
            grammar_row = Text("ok", style="green")
        else:
            grammar_row = Text("ungrammatical: ", style="red")
            grammar_row.append(j["grammar_reason"], style="default")
        info.add_row("scores", scores)
        info.add_row("judge", judge)
        info.add_row("category", category_row)
        info.add_row("grammar", grammar_row)
    info.add_row("ops", "\n".join(c["operations_applied"]))
    note = (review or {}).get("note") or state.pending_notes.get(key)
    if note:
        info.add_row("note", Text(note, style="italic"))

    parts = [
        header,
        Panel(Text(c["prompt"]), title="Paraphrase", title_align="left"),
        Panel(word_diff(seed_text, c["prompt"]), title="Changes vs. seed", title_align="left"),
        info,
    ]
    if details:
        parts.append(Panel(Text(c["reasoning"]), title="Generator plan", title_align="left"))
    if details and j is not None:
        category_details = f"{j['category_reason']}\n" if j["matches_category"] else ""  # else already shown above
        main_change = f"Main change: {j['main_change']}\n" if j.get("main_change") else ""
        parts.append(Panel(
            Text(f"{main_change}{category_details}Operations found: {'; '.join(j['operations_found'])}"),
            title="Judge: category", title_align="left",
        ))
        verdicts = Text("\n".join(f"{v['status']:8} {v['id']}: {v['reason']}" for v in j["verdicts"]))
        parts.append(Panel(verdicts, title="Judge: all constraints", title_align="left"))
    return Group(*parts)


KEYS_HELP = "←/→ move · a accept · r reject · c category · n note · u undo · g unreviewed · d details · f filter · q quit"


def footer_text(state: ReviewState, prompt: str | None = None) -> Text:
    t = Text()
    if prompt:
        t.append(prompt, style="bold yellow")
        return t
    t.append(KEYS_HELP + "\n", style="dim")
    c = state.current()
    if c:  # overall progress is at the top of the screen
        a, r, u = state.counts(c["category"])
        t.append(f"{c['category']}: {a} accepted · {r} rejected · {u} to go")
    return t


# --- key loop ----------------------------------------------------------------------------------


def review(run_dir: Path) -> None:
    import readchar
    from readchar import key as k

    candidates = load_candidates(run_dir)
    seed_text = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))["seed"]["text"]
    path = run_dir / "reviewed.jsonl"
    state = ReviewState(candidates, load_decisions(path))
    categories = [c.key for c in typology.CATEGORIES]
    details = False
    console = Console()

    def read_line(screen, label: str, initial: str) -> str | None:
        buffer = initial
        while True:
            screen.update(render(state, seed_text, details, footer_text(state, f"{label}: {buffer}▏  (Enter to save, Esc to cancel)")))
            ch = readchar.readkey()
            if ch in (k.ENTER, k.CR):
                return buffer.strip()
            if ch == k.ESC:
                return None
            if ch == k.BACKSPACE:
                buffer = buffer[:-1]
            elif ch.isprintable():
                buffer += ch

    with console.screen() as screen:
        while True:
            screen.update(render(state, seed_text, details, footer_text(state)))
            try:
                ch = readchar.readkey()
            except KeyboardInterrupt:
                break
            if ch in ("q", k.ESC, k.CTRL_C):
                break
            elif ch == k.RIGHT:
                state.move(1)
            elif ch == k.LEFT:
                state.move(-1)
            elif ch == k.HOME:
                state.first()
            elif ch == k.END:
                state.last()
            elif ch == "g":
                state.next_unreviewed()
            elif ch == "d":
                details = not details
            elif ch == "f":
                state.cycle_filter()
            elif ch in ("a", "r", "u", "c", "n") and state.current() is not None:
                if ch == "a":
                    state.decide("accept")
                elif ch == "r":
                    state.decide("reject")
                elif ch == "u":
                    state.clear()
                elif ch == "c":
                    choices = "  ".join(f"{i} {name}" for i, name in enumerate(categories, 1))
                    screen.update(render(state, seed_text, details, footer_text(state, f"Move to category: {choices}  (Esc to cancel)")))
                    pick = readchar.readkey()
                    if pick.isdigit() and 1 <= int(pick) <= len(categories):
                        state.decide("accept", categories[int(pick) - 1])
                elif ch == "n":
                    key = candidate_key(state.current())
                    existing = state.decisions.get(key, {}).get("note") or state.pending_notes.get(key, "")
                    note = read_line(screen, "Note", existing)
                    if note is not None:
                        state.set_note(note)
                save(path, state)

    a, r, u = state.counts()
    console.print(f"Saved {a + r} reviews to {path} ({a} accepted, {r} rejected, {u} unreviewed).")

