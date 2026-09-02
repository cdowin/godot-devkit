---
id: 0.21.0/ledger-report
milestone: "0.21.0"
name: pm ledger report answers the five efficiency questions in one table
status: planning
reviewed:
phase: 3
depends_on: ["0.21.0/ledger", "0.21.0/usage-capture", "0.21.0/review-record-shape"]
consumed_by: ["0.21.0/consumers-adopt"]
---

# pm ledger report answers the five efficiency questions in one table

What it makes true: `pm ledger report [<milestone>] [--json]` prints the five questions as one
quiet table (verdict-line convention: a heading, the table, one summary line): cost per shipped
unit by size and role; yield per review pass; rework per feature; escapes per milestone with the
causing feature; overhead shape (dispatches per story, orientation tool calls, gate re-runs,
NEEDS-YOU count + latency). Reads the ledger, the review records, the bug frontmatter, and git
(commit prefixes `type(<grain>/S<n>)`, fixup commits) — nothing else. Never exits non-zero on a
number; exit 2 only on a malformed ledger row.

## Existing-construct audit

`pm status` is the scoreboard of WHAT is done; the report is the scoreboard of what it COST and
what it BOUGHT. Neither hand-copies the other. Trend lines come from running it per milestone; no
cross-milestone cache.

## Ship criterion

The table answers each of the milestone's five questions for `0.90.3` from real data, and a reader
with no context can say which role's spend bought the least per shipped story.
