---
id: 0.23.0/ledger-report
milestone: "0.23.0"
name: pm ledger report answers the five questions from raw rows in one table
status: done
reviewed: pm/roadmap/0.23.0-telemetry/features/ledger-report/review.md
phase: 3
depends_on: ["0.23.0/ledger", "0.23.0/usage-capture", "0.23.0/review-record-shape"]
consumed_by: []
---

# pm ledger report answers the five questions from raw rows in one table

What it makes true: `pm ledger report [<milestone>] [--json]` prints the five questions as one quiet
table (a heading, the table, one summary line) from `pm/roadmap/<ms>/ledger.jsonl`, the review records and the bug frontmatter — and, for a retired milestone,
the same files out of git at the prune-log anchor (`--from <anchor>`, D6). No `.gate-reports/`, no
weights (D5). Spend per
grain by agent type with `size:` as a column; yield per review pass; rework from `review → wip` rows
and dispatches after a story's `review` row; escapes from `caused_by:`; overhead shape from dispatch
counts, `tool_calls_before_first_write`, and decision rows against the next status row. Rows whose
`tree` lists are empty are listed as unattributed. Never exits non-zero on a number; exit 2 only on a
malformed ledger row.

## Existing-construct audit

`pm status` is the scoreboard of WHAT is done; the report is the scoreboard of what it COST in
tokens, tool calls and time. Neither hand-copies the other. Trend lines come from running it per
milestone, live or `--from` an anchor; git is the archive.

## Ship criterion

The table answers each of the milestone's five questions for a real captured milestone, and a reader
with no context can say which agent type's spend went where.
