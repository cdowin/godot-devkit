---
id: 0.23.0/usage-capture
milestone: "0.23.0"
name: Dispatch usage is captured by a hook, never by hand
status: review
reviewed:
phase: 2
depends_on: ["0.23.0/ledger"]
consumed_by: ["0.23.0/ledger-report"]
---

# Dispatch usage is captured by a hook, never by hand

What it makes true: two installable Claude Code hooks beside the four `cc-*` hooks —
`cc-ledger-subagent.sh` on `SubagentStop` and `cc-ledger-session.sh` on `Stop` — each a thin shell
that reads the event JSON from stdin and calls `pm ledger record --from-transcript` with the
transcript path the event carries (`agent_transcript_path` for a subagent, `transcript_path` for
the session), plus `agent_id`, `agent_type`, `session_id` (D4). The row carries the tree's live
state at that instant (D3). Zero orchestrator effort; the 2026-09-02 hand-tally is the thing this
deletes.

## Existing-construct audit

`install-hooks` already writes hooks and `setup-hooks.sh` arms them; these are two more installables
on that verb. `pm ledger record` (ledger S2) owns the row shape — the hooks never write the file.
The `Stop` hook runs in the orchestrator's main session, which `cc-stop-gate.sh` deliberately exempts
from gating; this one is not a gate, is `async: true`, and exits 0 unconditionally.

## Ship criterion

A dispatch in an installed consumer produces a ledger row without anyone typing it; a `Stop` in the
orchestrator session produces a `session` row; a hook failure is logged to stderr and never blocks
the stop.
