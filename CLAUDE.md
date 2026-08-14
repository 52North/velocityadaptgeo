# How work is organised here

This file describes *how* to work in this repo. It deliberately contains no repo
specifics — paths, commands, services, and couplings live in one place only:
**`handover/domain-map.md`**, in the `handover/` folder at the repo root. Alongside it sits
one dated document per session, `handover/YYYY-MM-DD-<slug>.md`; the newest is the one that
sorts last.

Read `handover/domain-map.md` before acting on anything non-trivial, and the newest session
document when you need to know where things were left. If the map is missing or contradicts
what you find, establish the truth from the repo, say that you inferred it, and record it
(see below).

## Working as a team

The work is split into three disjoint domains, each owned by a specialist agent. The
domain map says which paths belong to which.

- **`database`** — persistence: schema, migrations, ingest, indexing, queries.
- **`backend`** — server side: APIs and their contracts, application logic, execution.
- **`frontend`** — client side: UI, client state, consumption of what the server sends.

**Route non-trivial work through the `architect` agent by default.** It fixes the
cross-domain contract before either side is built, then delegates and integrates. Go
direct to a specialist only when the task is unambiguously inside one domain and already
decided. Answer trivial questions yourself.

The agents are generic role definitions and carry no knowledge of this repository — they
learn it from the domain map. Keep them that way: when something here surprises you, the
fix goes in `handover/`, never into an agent file.

Specialists stop at their boundary and report it rather than reaching into another
domain. That report is the cue to delegate onward — not a failure.

## Handover

Invoke the `handover` skill:

- **When work leaves the domain it has been in.** A domain switch is where context gets
  lost: what was decided, what was actually run, and which dead ends are already spent
  do not survive the crossing on their own. Use it at the boundary — not on routine hops
  while a single contract is being wired up.
- **When a session ends** outside the domain it started in, or with work unfinished.
- **When anything durable about the structure is learned** — a wrong boundary, a new
  coupling, a moved path, a changed command. This is what stops `handover/domain-map.md`
  decaying into fiction, and it is the only mechanism that does.

Run it inline. Never delegate a handover: a subagent cannot see the conversation and
will reconstruct a plausible fiction from the diff.

## Verified vs. assumed

Never state something works without naming the command that showed it. Check what test
machinery actually exists before relying on it — a declared test runner is not a test
suite. When integrating, never upgrade a specialist's "not verified" into "working".
