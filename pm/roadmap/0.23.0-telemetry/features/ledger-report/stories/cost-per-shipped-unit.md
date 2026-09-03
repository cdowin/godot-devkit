---
id: 0.23.0/ledger-report/cost-per-shipped-unit
feature: 0.23.0/ledger-report
milestone: "0.23.0"
name: report prints raw tokens, tool calls, dispatches and wall-clock per story, feature and bug, by agent type
status: review
owner:
depends_on: []
---

# report prints raw tokens, tool calls, dispatches and wall-clock per story, feature and bug, by agent type

## Goal
`pm ledger report <ms>` section 1: per story / feature / bug — sum of `usage.*`, `tool_calls`,
dispatch count and `duration_s` from the dispatch rows whose `tree` names the grain, split by
`agent_type`; `size:` printed as a column, never used as a divisor (D5); wall-clock per state from the status rows
(seconds in `todo`, `wip`, `review`; bugs in `open`, `fixed`), and first-row to terminal-row total; rows with empty `tree` lists at the bottom as unattributed, never
dropped. Quiet table; `--json`.
## Verification
`make test` on a fixture ledger + PM tree; `make gates`.
## Commit prefix
`feat(0.23.0/ledger-report/S1):`
## Size
m
