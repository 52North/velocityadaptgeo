"""Rich renderables: the review page, the list rows and preview, and the summary table."""

import difflib
from datetime import datetime
from pathlib import Path

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from prompt_review.data import candidate_key, categories, latest_config, load_candidates, load_decisions, read_jsonl
from prompt_review.similarity import kept_near_duplicates, load_embeddings
from prompt_review.state import ReviewState, SummaryRow, current_category, kept, match_status, reason_group, summarize


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


def _match_entry(match: dict | None, candidate: dict, state: "ReviewState", show_current: bool, empty: str,
                 repeat_text: bool = True) -> Text:
    """Meta line (key, current category, similarity, review status), then the match's text and its word
    diff with the candidate. With repeat_text=False only the meta line (the text is shown above)."""
    if match is None:
        return Text(empty, style="dim")
    t = Text(f"{match['key']} · ")
    status = match_status(match["key"], state.by_key, state.decisions)
    if status is None:
        t.append("(not found in this run) · ", style="yellow")
    else:
        current, moved, _ = status
        if show_current:
            t.append(f"now in {current}" + (" (moved)" if moved else "") + " · ")
        elif moved:
            t.append(f"since moved to {current} · ", style="yellow")
    over = state.threshold is not None and match["sem"] > state.threshold
    t.append(f"similarity {match['sem']:.3f}", style="red" if over else "")
    if over:
        t.append(f" ▲ over {state.threshold:.3f}", style="red")
    if status is not None:
        t.append(" · review: ")
        t.append(status[2], style={"accept": "green", "reject": "red"}.get(status[2], "dim"))
    if not repeat_text:
        t.append("\nsame paraphrase as within the category", style="dim")
        return t
    t.append("\n" + match["prompt"])
    t.append("\ndiff, match → this candidate: ", style="dim")
    t.append_text(word_diff(match["prompt"], candidate["prompt"]))
    return t


def _matches_grid(within: dict | None, any_: dict | None, candidate: dict, state: "ReviewState", category: str,
                  empty_within: str, empty_any: str) -> Table:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold", no_wrap=True)
    grid.add_column(ratio=1)
    grid.add_row(f"Within the category\n({category})",
                 _match_entry(within, candidate, state, show_current=False, empty=empty_within))
    grid.add_row("", "")
    grid.add_row("Compared with all\ncategories",
                 _match_entry(any_, candidate, state, show_current=True, empty=empty_any,
                              repeat_text=not (within and any_ and within["key"] == any_["key"])))
    return grid


def _stored_grid(candidate: dict, state: "ReviewState") -> Table | Text:
    """The closest matches stored at generation (closest_match_plan.md)."""
    if "closest_accepted" not in candidate:
        return Text("not stored; add it with the generator's `prompt-gen backfill-closest <run_id>`", style="dim")
    return _matches_grid(candidate["closest_accepted"], candidate["closest_any"], candidate, state, candidate["category"],
                         "no accepted paraphrase in this category yet", "no accepted paraphrase yet")


def closest_panel(candidate: dict, state: "ReviewState") -> Panel:
    """Live closest matches among all other kept paraphrases (review_similarity_plan.md), then the ones
    stored at generation, which explain the gate's near-duplicate check. Without embeddings, only the
    stored ones."""
    live = state.live(candidate)
    if live is None:
        if state.embeddings is None:
            note = "live similarities need embeddings.jsonl; add it with the generator's `prompt-gen backfill-embeddings <run_id>`"
        else:
            note = "no usable stored embedding for this candidate; showing the matches at generation only"
        return Panel(Group(Text(note, style="yellow"), _stored_grid(candidate, state)), title="Closest matches", title_align="left")

    parts = [
        Text("Now · all other kept paraphrases (your decision, else the gates')", style="bold underline"),
        _matches_grid(live["within"], live["any"], candidate, state, current_category(candidate, state.decisions),
                      "no other kept paraphrase in this category", "no other kept paraphrase"),
        Text(""),
        Text("At generation · earlier gate-accepted paraphrases only", style="bold underline"),
    ]
    stored = (candidate.get("closest_accepted"), candidate.get("closest_any"))
    if "closest_accepted" in candidate and [m and m["key"] for m in stored] == [m and m["key"] for m in (live["within"], live["any"])]:
        parts.append(Text("same matches as now", style="dim"))
    else:
        parts.append(_stored_grid(candidate, state))
    return Panel(Group(*parts), title="Closest matches", title_align="left")


def _badge(label: str, style: str) -> Text:
    return Text(f" {label} ", style=style)


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
    near = state.near_duplicates().get(key)
    if near:
        header.append("  ")
        header.append_text(_badge(f"kept near-duplicate of {near[0]} ({near[1]:.3f})", "black on yellow"))

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
        if "max_sem_same_category" in c:  # near-duplicate rejected before judging: show how close it was
            info.add_row("scores", f"sem {c['sem']:.3f}   max sem in category {c['max_sem_same_category']:.3f}")
        info.add_row("judge", Text(f"not run (rejected before judging: {c['reject_reason']})", style="dim"))
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
        elif "corrected" in j:  # correction-based check: show what the judge would fix
            grammar_row = Text("ungrammatical, judge's correction:\n", style="red")
            grammar_row.append_text(word_diff(c["prompt"], j["corrected"]))
        else:  # judged by the earlier single-call verdict
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
        parts.append(closest_panel(c, state))
        parts.append(Panel(Text(c["reasoning"]), title="Generator plan", title_align="left"))
        if c.get("discarded"):
            drafts = Text()
            for i, d in enumerate(c["discarded"], 1):
                drafts.append(f"{i}. {d['prompt']}\n", style="dim")
                drafts.append(f"   feedback: {d['feedback']}\n")
            parts.append(Panel(drafts, title="Discarded drafts", title_align="left"))
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


KEYS_HELP = ("←/→ move · a accept · r reject · c category · n note · u undo · g unreviewed · d details · "
             "f filter · s sort · ↑/↓ scroll · Esc list · q quit")


def footer_text(state: ReviewState) -> Text:
    t = Text()
    t.append(KEYS_HELP + "\n", style="dim")
    c = state.current()
    if c:  # overall progress is at the top of the screen
        a, r, u = state.counts(c["category"])
        t.append(f"{c['category']}: {a} accepted · {r} rejected · {u} to go")
    return t


# --- list view (review_table_plan.md) -------------------------------------------------------------

LIST_COLUMNS = (("#", 4), ("Key", 20), ("Category", 18), ("Gate", 15), ("Review", 7), ("Sim", 6), ("Prompt", None))


def _cut(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def _sim_text(state: ReviewState, sem: float) -> Text:
    over = state.threshold is not None and sem > state.threshold
    return Text(f"{sem:.3f}", style="red" if over else "")


def list_row(c: dict, state: ReviewState, prompt_width: int) -> list:
    """One table row: number in the run, key, current category, gate, review, closest similarity in the
    category, and the prompt cut to one line."""
    key = candidate_key(c)
    review = state.decisions.get(key)
    current = current_category(c, state.decisions)
    match = state.similarity(c)
    return [
        Text(str(state.number[key]), style="dim"),
        key,
        Text(f"→ {current}", style="yellow") if current != c["category"] else Text(current),
        Text("accept", style="green") if c["accepted"] else Text(reason_group(c) or "reject", style="red"),
        Text("—", style="dim") if review is None else Text(review["decision"], style="green" if review["decision"] == "accept" else "red"),
        Text("—", style="dim") if match is None else _sim_text(state, match[1]),
        _cut(c["prompt"], prompt_width),
    ]


def list_preview(c: dict | None, state: ReviewState) -> Text:
    """Full text of the highlighted row, and its closest match in the category."""
    if c is None:
        return Text(f"No candidates match the filter '{state.filter}'. Press f to change it.", style="dim")
    key = candidate_key(c)
    t = Text()
    t.append(key, style="bold")
    current = current_category(c, state.decisions)
    t.append(f" · {current}" + (" (moved)" if current != c["category"] else ""))
    t.append(" · gates: ")
    t.append("accepted" if c["accepted"] else c["reject_reason"], style="green" if c["accepted"] else "red")
    near = state.near_duplicates().get(key)
    if near:
        t.append(f" · kept near-duplicate of {near[0]}", style="yellow")
    t.append("\n" + c["prompt"] + "\n")
    match = state.similarity(c)
    source = "now" if state.embeddings is not None else "at generation"
    if match is None:
        t.append(f"closest in {current} ({source}): none", style="dim")
    else:
        t.append(f"closest in {current} ({source}): {match[0]} · ", style="dim")
        t.append_text(_sim_text(state, match[1]))
        t.append("\n" + state.by_key[match[0]]["prompt"] if match[0] in state.by_key else "", style="dim")
    return t


def print_summary(run_dir: Path, console: Console | None = None) -> None:
    console = console or Console()
    raw = read_jsonl(run_dir / "candidates.jsonl")
    candidates = load_candidates(run_dir)
    decisions = load_decisions(run_dir / "reviewed.jsonl")
    config = latest_config(run_dir)
    target = config["n_per_category"]
    rows, overrules = summarize(candidates, decisions, categories(run_dir, candidates))

    sessions = 1 + len(list(run_dir.glob("config_*.json")))
    last = datetime.fromtimestamp((run_dir / "candidates.jsonl").stat().st_mtime)
    console.print(
        f"[bold]{run_dir.name}[/]   seed {config['seed']['id']} · {sessions} generation session(s) · "
        f"last candidate {last:%Y-%m-%d %H:%M} · target {target} per category"
    )

    table = Table(show_edge=False, pad_edge=False)
    table.add_column("Category")
    table.add_column("Generated", justify="right")
    for name in ("Auto ✓", "Auto ✗", "Review ✓", "Review ✗", "Unreviewed", "Moved in", "Moved out"):
        table.add_column(name, justify="right")
    table.add_column("Final", justify="right")

    def cells(r: SummaryRow, bold: bool = False) -> list:
        final = Text(str(r.final), style="bold green" if r.final >= target and not bold else "bold")
        return [r.category, str(r.generated), str(r.gate_accepted), str(r.gate_rejected), str(r.review_accepted),
                str(r.review_rejected), str(r.unreviewed), f"+{r.added}", f"−{r.subtracted}", final]

    for r in rows:
        table.add_row(*cells(r))
    total = SummaryRow("Total")
    for r in rows:
        for f in ("generated", "gate_accepted", "gate_rejected", "review_accepted", "review_rejected",
                  "unreviewed", "added", "subtracted"):
            setattr(total, f, getattr(total, f) + getattr(r, f))
    table.add_section()
    table.add_row(*cells(total, bold=True), style="bold")
    console.print(table)

    console.print(
        "Auto = automated gates; Review = manual review, counted under the category generated for "
        "(a move counts as an accept); Final = Review ✓ − moved out + moved in.",
        style="dim",
    )
    reviewed = sum(r.review_accepted + r.review_rejected for r in rows)
    if reviewed:
        n = overrules.gate_rejected_accepted + overrules.gate_accepted_rejected
        console.print(
            f"Manual review overruled the gates on {n} of {reviewed} reviewed candidates: "
            f"{overrules.gate_rejected_accepted} gate-rejected accepted, {overrules.gate_accepted_rejected} gate-accepted rejected."
        )
    embeddings = load_embeddings(run_dir, candidates)
    if embeddings is not None:
        threshold = config["config"]["thresholds"]["near_duplicate_sem"]
        near = kept_near_duplicates(kept(candidates, decisions), embeddings, threshold)
        console.print(f"{len(near)} kept paraphrases have a kept near-duplicate in their category (> {threshold:.3f}).")
    errors = len(raw) - len(candidates)
    if errors:
        console.print(f"{errors} generation error(s) without a paraphrase, not counted above.", style="dim")
