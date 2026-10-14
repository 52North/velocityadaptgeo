"""Full-screen manual review of a run's candidates: the key loop."""

from pathlib import Path

from rich.console import Console

from prompt_review.data import candidate_key, categories, first_config, latest_config, load_candidates, load_decisions, save
from prompt_review.render import footer_text, render
from prompt_review.similarity import load_embeddings
from prompt_review.state import ReviewState


def review(run_dir: Path) -> None:
    import readchar
    from readchar import key as k

    candidates = load_candidates(run_dir)
    seed_text = first_config(run_dir)["seed"]["text"]
    path = run_dir / "reviewed.jsonl"
    embeddings = load_embeddings(run_dir, candidates)
    threshold = latest_config(run_dir)["config"]["thresholds"]["near_duplicate_sem"]
    state = ReviewState(candidates, load_decisions(path), embeddings, threshold)
    category_keys = categories(run_dir, candidates)
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
                    choices = "  ".join(f"{i} {name}" for i, name in enumerate(category_keys, 1))
                    screen.update(render(state, seed_text, details, footer_text(state, f"Move to category: {choices}  (Esc to cancel)")))
                    pick = readchar.readkey()
                    if pick.isdigit() and 1 <= int(pick) <= len(category_keys):
                        state.decide("accept", category_keys[int(pick) - 1])
                elif ch == "n":
                    key = candidate_key(state.current())
                    existing = state.decisions.get(key, {}).get("note") or state.pending_notes.get(key, "")
                    note = read_line(screen, "Note", existing)
                    if note is not None:
                        state.set_note(note)
                save(path, state)

    a, r, u = state.counts()
    if embeddings is not None and embeddings.warnings:
        console.print(f"{len(embeddings.warnings)} candidate(s) without a usable stored embedding (no live similarities):", style="yellow")
        for w in embeddings.warnings:
            console.print("  " + w)
    console.print(f"Saved {a + r} reviews to {path} ({a} accepted, {r} rejected, {u} unreviewed).")
