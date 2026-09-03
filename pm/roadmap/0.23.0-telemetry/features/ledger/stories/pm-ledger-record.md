---
id: 0.23.0/ledger/pm-ledger-record
feature: 0.23.0/ledger
milestone: "0.23.0"
name: pm ledger record files a dispatch row by hand when no hook can
status: review
owner:
depends_on: []
---

# pm ledger record files a dispatch row, from a transcript or by hand, and pm ledger show reads one grain

## Goal
`pm ledger record --from-transcript <path> --event SubagentStop|Stop [--agent-id X --agent-type Y
--session-id Z]` parses the Claude Code transcript JSONL (stdlib `json`): sums `message.usage`
over `type == "assistant"` records (`input_tokens`, `output_tokens`, `cache_creation_input_tokens`,
`cache_read_input_tokens`), counts `tool_use` content blocks by `name`, counts tool calls before the
first `Edit|Write|MultiEdit|NotebookEdit`, takes the first and last `timestamp` as
`started_at`/`ended_at` (+ `duration_s`), reads `message.model`, snapshots the tree (D3), and appends
a `dispatch` (SubagentStop) or `session` (Stop) row to the building milestone's
`ledger.jsonl` (D6). A field the
transcript lacks is omitted, never invented. Hand entry stays possible: `pm ledger record --grain <id>
--agent-type <t> --tokens-in N --tokens-out N --tool-calls N --duration-s N` for a dispatch no hook
saw. `pm ledger show <grain-id>` prints that grain's rows oldest first with the seconds between
consecutive status rows (time in each state) and, at the end, first-row to terminal-row total;
`--json` for the raw lines.
## Gotchas
The transcript shape is pinned by a fixture (a scrubbed real subagent transcript); a record without
`message.usage` counts as a message and contributes zero, and a file with NO assistant records is a
refusal (exit 2), not a row of zeros. Which milestone file: the building milestone(s) from the tree;
none building → refuse (exit 2) and say so. Refusal matrix: bad numbers, a path that is not a file,
a non-JSON line, an unknown `--event`.
## Verification
`make test` (transcript fixture → exact row; hand row round-trips; every refusal), `make gates`.
## Commit prefix
`feat(0.23.0/ledger/S2):`
## Size
m
