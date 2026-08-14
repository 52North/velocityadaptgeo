---
name: handover
description: Write or update the handover folder at the repo root — the durable domain map plus a dated document for the current session (goal, what changed, what was actually verified versus only written, open threads, decisions worth not reversing). Use when the user says handover, hand off, wrap up, "write up where we are", "note this for next time", when work crosses a domain boundary, or when a session ends with work left unfinished.
---

# Handover

`handover/` at the repo root is the single place this repository's specifics are written
down. Nothing else — no agent definition, no instruction file — carries them. It holds two
kinds of document, on two different clocks:

```
handover/
  domain-map.md                     ← durable structure. Stable name. Every agent reads this first.
  2026-08-14-agent-team.md          ← one document per session, newest name sorts last.
  2026-08-11-execution-graph.md
```

- **`domain-map.md`** — durable structure. Which paths belong to which domain, how to run
  and verify things, the couplings that break quietly. Survives every session. **Its
  filename never changes and never carries a date** — agents must reach it without listing
  the directory first. Its date lives in a `Last updated:` line inside.
- **`YYYY-MM-DD-<slug>.md`** — what happened in one session. The dated id *is* the
  filename, repeated in the document's `# Session <id>` heading so it survives a copy-paste.

Keeping those apart is the whole point of the layout. Session state put in the map rots;
structure left in a session file gets deleted by the retention rule in §6.

## Run this inline. Never delegate it.

Do **not** call the Agent tool for any part of this. A handover summarises *this*
conversation, and a subagent cannot see the conversation. Delegating it produces a
fabricated summary based on nothing but the diff, which is worse than no handover at all.

## 1. Gather repo state

Read-only, for the session header and an uncommitted-work warning:

```
git branch --show-current
git log --oneline -5
git status --porcelain
git diff --stat
```

These tell you *where* the work sits. The narrative comes from the conversation, not the diff.

Then look at what is already there: list `handover/` and read the highest-numbered session
file. If today's date already has a file, you are continuing that session — extend it rather
than opening a second file for the same day.

## 2. Update `handover/domain-map.md`

Do this first, and do it whenever this session learned anything durable: a domain boundary
that turned out wrong, a new quiet coupling, a changed command, a path that moved, a service
that was added. Anything an agent had to *infer* this session belongs here — an inferred map
that never gets written down is re-inferred, differently, next time.

If `handover/domain-map.md` does not exist, build it from the repo: read the layout, the
dependency manifests, the compose or deployment config, the entrypoints.

What belongs in it:

- **Domains → paths.** The disjoint territory each specialist owns, as real paths. Name what
  is explicitly *not* in a domain when that is not obvious, and name anything frozen,
  legacy, or not to be extended.
- **How to run and reach things.** Services, ports, entrypoints, which directory a command
  must run from when the repo has more than one dependency tree.
- **How to verify.** What test or check machinery actually exists and what it covers —
  including "none", which is the most important case to state, since a declared test runner
  with no tests reads as coverage.
- **Quiet couplings.** Changes that look complete but do nothing until a second place is
  updated: registration manifests, route tables, allow-lists, generated artifacts, schema
  files that only run on a fresh volume. Each with the file that must also change.
- **Traps and non-obvious facts.** Stubs and scaffolding that are not real implementations,
  paths that are exercised versus paths that merely exist, secret locations by variable name
  only.

Correct it in place and bump its `Last updated:` line — it is a map of the current repo, not
a log of what the map used to say. Keep it dense: an entry earns its line by preventing a
mistake.

## 3. Reconstruct the session

From the conversation itself, establish:

- What the session set out to do, and whether that changed along the way.
- What actually changed, and why — the reasoning, not just the filenames. The diff already
  shows filenames.
- What was **run and observed** versus what was **written and never executed**.
- What was tried and abandoned, and why. This is the highest-value part and the easiest to
  lose: it stops the next session repeating a dead end.
- What is left open, including anything known to be broken.

## 4. Name the session file

`handover/YYYY-MM-DD-<slug>.md`, where the date is today's and the slug is two or three
words for what the session was about — `2026-08-14-sse-payload-contract.md`, not
`2026-08-14-session.md` or `2026-08-14-fixes.md`. The slug is what makes the file findable
without opening it, so it must say something.

The date-first form means a plain name sort puts the newest last; that is how the next agent
finds the current session without an index. Two sessions on one day are distinguished by
their slugs — but first check §1: if the day's work is continuous, extend the existing file
instead.

## 5. Write the session file

````markdown
# Session YYYY-MM-DD-<slug>

**Branch:** <branch> · **HEAD:** <sha> <subject> · **Working tree:** clean | N files uncommitted

## Goal
What this session set out to do. If it changed along the way, say so.

## State
What works now. What is broken or half-finished. If the session ended mid-task, say so plainly.

## Changes
- `path/to/file` — what changed and why.

## Verified vs. assumed
- **Verified:** <command actually run> → <what it output>
- **Assumed:** <written but never executed>

## Open threads
1. Most important next step.
2. …

## Decisions & gotchas
Non-obvious choices and the reasoning behind them, so they don't get silently reversed.
Including what was tried and abandoned.
````

Drop a section rather than pad it. If nothing was abandoned, omit the abandoned notes; an
empty heading is noise.

## 6. Retention

The folder is a working set, not an archive — git is the archive.

- **`domain-map.md` is exempt.** It is never dated, never pruned, never superseded by a
  newer file. It is edited in place when the structure changes, and otherwise left alone.
- **Keep roughly the three most recent session files.** Only the newest is normally read;
  the two behind it exist for "was this already tried?".
- **Before deleting a session file, lift anything durable in it into `domain-map.md`.** That
  is the last chance — this is the step that stops the map decaying into fiction.
- Prune sooner than three when a session is merged and no longer actionable. Prune later
  than three only when an old session still holds a live open thread.

If the folder has grown to a dozen files, the rule was not applied and durable facts are
sitting where nobody reads them.

## 7. Honesty rules

A handover that overstates completion is actively harmful — the next session builds on it
and finds out later.

- Never list a change as working without naming the command that demonstrated it.
- Check what test machinery actually exists rather than assuming; if there is none, the
  domain map must say so.
- "Open threads" must include known-broken things, not just planned features.
- Do not smooth over an unresolved problem or a failed attempt. Write it down.
- No secret values. Reference variable names only — these files are committed.

## 8. Finish

Report the paths you wrote, what you changed in `domain-map.md`, and a two-line summary of
the session you recorded. **Do not commit** unless the user asks.
