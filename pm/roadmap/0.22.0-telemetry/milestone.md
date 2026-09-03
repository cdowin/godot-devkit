---
id: "0.22.0"
name: telemetry
status: planning
depends_on: ["0.20.0"]
branch: milestone/0.22.0-telemetry
risk: medium
---

# telemetry

Filed 2026-09-02 (Chris: *"Our goal is efficiency towards the goal, not necessarily no tokens
spent."*). Re-scoped 2026-09-03 (D1–D7 in `decisions.md`; D6/D7 supersede D1/D2): raw data, written at the moment of the
work, kept forever. After the 0.19.0/0.20.0 efficiency work the only evidence that it helped was the
orchestrator tallying agent reports by hand — small N, self-reported, features of different size.
This milestone makes the devkit record what every dispatch and every status flip cost in tokens,
tool calls and wall-clock, so the trend is a report and not an anecdote, across milestones and
across consumers.

## What gets recorded, and by whom

- Every status flip and every decision → one row with a full UTC timestamp, appended by the `pm`
  verb that made it. The grain itself carries `started_at:` and `ended_at:` on frontmatter, stamped by
  the same verbs and cascading through `feature done` (D7).
- Every subagent dispatch → one row from the agent's own transcript: tokens in/out/cache, tool calls
  by name, first and last timestamp, model, agent type — appended by an installed `SubagentStop`
  hook through `pm ledger record` (D4). The orchestrator session's own totals land the same way
  from a `Stop` hook.
- The tree's live state at the moment the hook fires — which milestone is building, which stories
  are `wip` or `review` — verbatim on the row (D3). Attribution is the report's job.
- All of it in `pm/roadmap/<ms>/ledger.jsonl`, owned by the milestone and retired with it; a retired
  milestone is read from git through the prune-log anchor (D6).

## The questions the report answers, each from raw rows

1. **Spend per grain** — tokens, tool calls, dispatches and wall-clock per story, feature and bug,
   split by agent type, with `size:` shown as a column.
2. **Yield per review pass** — findings by severity and disposition from the verdict block.
3. **Rework** — `review → wip` rows, dispatches after a story's `review` row, verdict distribution.
4. **Escapes** — bugs whose `caused_by:` names a `done` feature.
5. **Overhead shape** — dispatches per story, tool calls before the first write, decisions per
   feature and the time to the next status row.

## What this is NOT

Not a budget, not a gate, not a leaderboard, not an estimate. No size weights, no dollar figures,
no backfill (D5). The devkit informs and never enforces; `pm ledger report` prints one quiet table
and nothing exits non-zero on a number.

## Ship criterion

In an installed consumer, a milestone worked with the hooks armed and no hand entry yields
`pm ledger report <ms>` printing the five sections from `pm/roadmap/<ms>/ledger.jsonl`; every closed
story, feature and the milestone carry `started_at`/`ended_at`; `pm ledger report --from <anchor>`
prints the same for a retired milestone out of git.

## Risks

- The transcript JSONL shape is an interface we read, not one we own: a fixture pins the fields
  and a shape change fails the parser loudly (exit 2), never silently records zeros.
- A `Stop` hook fires on every orchestrator turn; the append is async and must never block a stop.
- Two milestones building in parallel each write their own directory's file; the union merge
  attribute covers the one file they could share.
