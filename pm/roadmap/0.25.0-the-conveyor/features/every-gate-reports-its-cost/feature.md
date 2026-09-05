---
id: 0.25.0/every-gate-reports-its-cost
milestone: "0.25.0"
name: Every gate records what it cost, so the gate set can be argued from data
status: planning
reviewed:
risk: medium
size: m
phase: 1
depends_on: []
consumed_by: ["0.25.0/the-release-is-a-conveyor"]
labels: ["telemetry", "ledger", "gates", "performance"]
---

# Every gate records what it cost, so the gate set can be argued from data

**Chris, 2026-09-04:**

> *"The gates should probably always be timed and using the ledger the sdlc now provides right? We should
> always be collecting this telemetry. Where do we do this so we can get better?"*

## Why — the measurement that prompted it took a hand-rolled loop, and that is the problem

A consumer's `make check` had grown to feel like "many minutes". Nobody knew which gate, because nothing
records it. Timing all twenty by hand, once, produced this:

| gate | s |
|---|---|
| `pm-shape-scan` | **34.8** |
| `loot-category-dispatch-scan` | **12.4** |
| `runners-self-test` | 8.0 |
| `signal-emitter-scan` | 5.8 |
| `hooks-self-test` | 3.4 |
| the other 15 together | ~5.6 |

**70 s total, and two gates are 47 s of it — 67%.** Fourteen of the twenty are under one second.

Two things fell out immediately, and neither was guessable:

- **`z-layer-scan`, the one suspected by name of being bloat, is 0.2 s** — among the cheapest in the set.
  A name is not evidence.
- **`pm-shape-scan`'s 34.8 s is an implementation defect, not work.** Its `_doc_lines` spawns four
  subprocesses per file (`wc`, `head`, `awk`, `head`) across 683 markdown files, called from several
  patterns — thousands of spawns to count lines and skip frontmatter. One `awk` pass does it in under a
  second.

**A one-off hand measurement cannot catch a gate getting slower.** It caught this one because someone
finally asked; nothing would have caught the drift that produced it.

## Where it goes — there is exactly one funnel, and it already exists

`gdk_gate` in `installables/Makefile.devkit` is the single wrapper every gate runs through: it already
owns the verdict line, the summary function and the `.gate-reports/<name>.log` transcript. **Instrument
there and every gate is covered for free, including gates that do not exist yet** — which is the whole
argument for putting it in the funnel rather than in each gate.

The ledger is already shipped (`pm ledger record`, the two courier hooks, `pm ledger report`). A gate row
is a new `kind`, not a new mechanism.

Record per run: gate name, wall duration, verdict, and enough tree identity to compare like with like
(a gate's cost scales with the corpus it walks, so a duration without a census is not comparable across
repos or across a year of growth).

## What it makes possible, and what it must not become

- **A gate getting slower becomes visible** instead of being discovered when someone complains.
- **The gate set becomes arguable from data** — "these fourteen cost 5.6 s together, this one costs 34.8"
  is a different conversation from "check feels slow".
- **`0.25.0/the-release-is-a-conveyor` consumes it.** Its `adopt` step list exists because adoption should
  not pay for a project's own gates; deciding what a step is allowed to cost needs the numbers.

**Not a budget that fails a build.** A gate that reds because it got 200 ms slower on somebody's laptop
is a gate people disable. This REPORTS; whether a ceiling is ever enforced is a separate decision with
its own argument.

## Risks

1. **Timing the funnel changes the funnel.** `gdk_gate` is on the path of every gate in every consumer;
   a bug here reds everything. It has to be additive and fail open — a ledger write that cannot happen is
   not a gate failure, exactly as the two couriers already rule for themselves.
2. **Duration without a census invites the wrong conclusion.** The same gate is legitimately slower on a
   bigger tree; the row needs the corpus size beside the seconds or someone will "optimise" a gate that
   is simply doing more.
3. **Telemetry nobody reads is cost with no benefit.** If `pm ledger report` does not grow a view that
   answers "what got slower", this is a write-only table and should not ship.
