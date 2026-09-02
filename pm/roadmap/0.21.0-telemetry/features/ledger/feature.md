---
id: 0.21.0/ledger
milestone: "0.21.0"
name: The ledger — every status flip and every dispatch leaves a timestamped row
status: planning
reviewed:
phase: 1
depends_on: []
consumed_by: ["0.21.0/usage-capture", "0.21.0/ledger-report"]
---

# The ledger — every status flip and every dispatch leaves a timestamped row

What it makes true: `pm/roadmap/<ms>/ledger.jsonl`, append-only, one JSON row per event —
`{ts, kind, grain, ...}` — written by the verbs that already touch the grain (`pm story wip|review|done`,
`pm feature building|done`, `pm bug fixed`, `pm decide`) and by `pm ledger record` for a dispatch
row (`role, agent, tokens, tool_uses, duration_s, verdict?, notes?`). The ledger is DURABLE like
`decisions.md` (survives close; retired with the milestone dir, git is the archive).

## Existing-construct audit

`decisions.md` is prose and append-only — the ledger is its machine sibling, not a second
decisions log. Frontmatter is NOT the home for timestamps (a `claimed_at:` field on every story is
a field the resolvers do not read — the ledger reads it instead). No new autoload-shaped thing; one
file per milestone, JSON lines, stdlib.

## Ship criterion

Every status flip in a milestone appears in its ledger with a UTC timestamp; a hand-recorded
dispatch row round-trips; `pm validate` ignores the ledger; `check pm` never reads it.
