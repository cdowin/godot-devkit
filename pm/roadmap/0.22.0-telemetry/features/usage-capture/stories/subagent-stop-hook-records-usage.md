---
id: 0.22.0/usage-capture/subagent-stop-hook-records-usage
feature: 0.22.0/usage-capture
milestone: "0.22.0"
name: an installed SubagentStop hook records tokens, tool calls, duration and the grain per dispatch
status: wip
owner:
depends_on: []
---

# an installed SubagentStop hook records tokens, tool calls, duration and the tree state per dispatch

## Goal
`installables/cc-ledger-subagent.sh` (SubagentStop) and `installables/cc-ledger-session.sh` (Stop):
read the event JSON on stdin with a real JSON parser (python3 -c, as `cc-commit-pathspec.sh` does),
take `agent_transcript_path` / `transcript_path`, `agent_id`, `agent_type`, `session_id`, and exec
`pm ledger record --from-transcript … --event …` via the project's `make pm` vehicle. Exit 0 always;
errors to stderr. Wired by `install-hooks` + `setup-hooks.sh` like the other four, and the
`.claude/settings.json` snippet `install-hooks` prints gains both entries with `"async": true`.
## Gotchas
Never block a stop; never boot the engine. The `Stop` hook fires on every orchestrator turn — the
transcript can be tens of MB, so the parse must stay off the turn (`async`). If the event carries no
transcript path (older Claude Code), log and exit 0 — no row, no invented row. Respect the re-entrancy
field `stop_hook_active` only to avoid double rows: one row per stop.
## Verification
`make test` (hook corpus: a SubagentStop payload + transcript fixture → one `dispatch` row; a Stop
payload → one `session` row; a payload without a path → no row, exit 0; a malformed payload → exit 0
with stderr), `--self-test` like the sibling hooks, `shellcheck -x`.
## Commit prefix
`feat(0.22.0/usage-capture/S1):`
## Size
m
