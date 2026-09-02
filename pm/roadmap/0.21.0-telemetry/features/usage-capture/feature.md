---
id: 0.21.0/usage-capture
milestone: "0.21.0"
name: Dispatch usage is captured by a hook, never by hand
status: planning
reviewed:
phase: 2
depends_on: ["0.21.0/ledger"]
consumed_by: ["0.21.0/ledger-report"]
---

# Dispatch usage is captured by a hook, never by hand

What it makes true: an installable Claude Code `SubagentStop` hook (beside the four `cc-*` hooks)
appends a dispatch row to the active milestone's ledger — tokens, tool calls, duration, agent name,
role (from the agent type), and the grain — with zero orchestrator effort. The orchestrator's
hand-tally of reports (2026-09-02: 30+ rows copied by hand) is the thing this deletes.

## Existing-construct audit

`install-hooks` already writes hooks; this is one more installable on that verb. `pm ledger record`
(ledger S2) is the verb the hook calls — the hook never writes the file itself, so the row shape has
one owner.

## Ship criterion

A dispatch in an installed consumer produces a ledger row without anyone typing it; a dispatch the
hook cannot attribute lands as `grain: ?` and is listed by the report, never dropped.
