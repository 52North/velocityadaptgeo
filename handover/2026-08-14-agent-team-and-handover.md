# Session 2026-08-14-agent-team-and-handover

**Branch:** `refactor/multi-agent-system` · **HEAD:** 5e29355 Merge fixed ·
**Working tree:** `.gitignore` modified; `.claude/`, `CLAUDE.md`, `handover/` untracked

## Goal

Replace the `researcher`/`reviewer`/`implementer` agent set with a team structure —
`database`, `backend`, `frontend` specialists plus an `architect` as the default entry
point — and move all repository-specific knowledge out of the agent definitions.

Extended mid-session: split the single `HANDOVER.md` into a `handover/` folder of separate
dated documents.

## State

Complete as a configuration change. The four agents are registered and generic; the
`handover/` folder now carries the domain knowledge they read. **None of it has been
exercised** — no task has yet been run through the `architect` → specialist path.

One thing is known broken: `.claude/settings.json` configures a `SessionStart` hook
(`.claude/hooks/inject_handover.py`) and a `PreCompact` hook
(`.claude/hooks/handover_due.py`), and **neither script exists** — `.claude/hooks/` is
absent entirely. The handover is therefore never auto-injected and no reminder fires before
compaction. Agents find the map only because their prompts tell them to read it.

## Changes

- `.claude/agents/{architect,database,backend,frontend}.md` — new. Generic role
  definitions: layer ownership, method, boundary protocol, verified-vs-assumed reporting.
  Each begins by reading `handover/domain-map.md`.
- `.claude/agents/{researcher,reviewer,implementer}.md` — deleted. They were untracked, so
  git has no copy.
- `.claude/skills/handover/SKILL.md` — genericised, then rewritten for the folder layout:
  one durable `domain-map.md` plus one dated file per session, with a retention rule in
  place of the old in-file compression policy.
- `CLAUDE.md` — new. Routing rule (`architect` by default), the handover triggers, and the
  rule that repo specifics go in the handover folder rather than into an agent file.
- `handover/domain-map.md` — new. The specifics stripped from the agent files.
- `handover/2026-08-14-agent-team-and-handover.md` — new (this file).
- `HANDOVER.md` — deleted; its two halves became the two files above.

## Verified vs. assumed

- **Verified:** the four agents are registered and the old three are gone (the harness
  re-listed the available agent types after the files were written).
- **Verified:** the domain map's factual claims were checked against the repo —
  `ALLOWED_ACTIONS`/`MANAGER_SYSTEM` at `management.py:25,30`; 17 processes; graph edges in
  `workflow.py:43-72`; routes in `app.py`; `pytest` declared only in
  `LangGraph/pyproject.toml:21` with no application tests present.
- **Verified:** no repository specifics remain in the agent definitions, the skill, or
  `CLAUDE.md` — grepped those files for 18 repo-specific terms (`langgraph`, `pygeoapi`,
  `pgvector`, `ollama`, `postgres`, `fastapi`, `ogc`, `docker`, `mcp`, `8000`, `5432`,
  `nomic`, `app.js`, `workflow.py`, …); zero hits, the only matches being the substring
  `sse` inside the word "compressed".
- **Verified:** `.claude/hooks/` does not exist — `ls .claude/hooks` →
  `No such file or directory`, so both configured hooks are dead.
- **Assumed:** that the `architect` can spawn the three specialists when it is *itself*
  running as a subagent. Subagent nesting depth was never tested. Delegation is only
  certain when the main loop adopts the architect role via `CLAUDE.md`.
- **Assumed:** that a generic agent reliably reads the domain map before acting. The
  instruction is first in each agent's prompt but has not been observed in practice.
- **Assumed:** that agents pick the right session file by name-sorting `handover/`. The new
  discovery rule has not been exercised by an actual agent.

## Open threads

1. Decide the fate of the two dead hooks: write `inject_handover.py` and
   `handover_due.py`, or drop the `hooks` block from `.claude/settings.json`. Leaving
   config pointing at missing scripts is the worst of the three.
2. Nothing here is committed — `.claude/`, `CLAUDE.md` and `handover/` are all untracked,
   so none of it survives a clone. The skill's "no secret values, this file is committed"
   rule assumes it will be.
3. Run one real cross-domain task through `architect` and check that the specialists
   actually read the domain map and stop at their boundaries.
4. Test whether `architect` invoked as a subagent can delegate; if it cannot, the routing
   rule in `CLAUDE.md` is the only path that works and should say so explicitly.
5. Review dropped: there is no longer a dedicated read-only reviewer agent. Review now
   sits with `architect` at the seam. Decide whether that is enough.

## Decisions & gotchas

- **Repo specifics live only in `handover/domain-map.md`.** Agent definitions are generic
  on purpose, so they do not go stale when paths move. Putting a path back into an agent
  file reverses this decision.
- **`domain-map.md` is the one file in the folder with no dated id.** Every agent must
  reach it without listing the directory first; a dated name would force a glob-and-sort on
  the one file that must always be findable. Its date lives in a `Last updated` line.
- **The map is exempt from the retention rule.** Session files are pruned; the map is not.
  Durable facts must be lifted *into* it before a session file is deleted, or they are lost.
- **The folder replaced in-file compression.** With one document, old sessions had to be
  squashed to one line because everything got loaded at once. With one file per session
  only the newest is read, so history can simply be pruned when it stops being actionable —
  git keeps it.
- Three layouts were considered and rejected: keeping the map in `CLAUDE.md`; per-domain
  context files under `.claude/context/`; and an `index.md` listing the session files. The
  index was dropped because a name-sorted directory cannot go stale and an index can.
