---
id: 0.21.0/usage-capture/subagent-stop-hook-records-usage
feature: 0.21.0/usage-capture
milestone: "0.21.0"
name: an installed SubagentStop hook records tokens, tool calls, duration and the grain per dispatch
status: todo
owner:
depends_on: []
---

# an installed SubagentStop hook records tokens, tool calls, duration and the grain per dispatch

## Goal
SPIKE FIRST, then build: what does a Claude Code `SubagentStop` hook receive — usage (input/output tokens), the agent type/name, the dispatch prompt, duration? Record the answer in the story's close block. Then `installables/cc-subagent-ledger.sh` calls `pm ledger record` with whatever is available; fields it cannot see are omitted, never invented. Wired by `install-hooks` + `setup-hooks.sh` like the other four.
## Gotchas
The hook must never fail the stop (exit 0 always; log to stderr). Respect the sandbox hook: no engine boot. If `SubagentStop` exposes no usage at all, the story closes with that finding and `pm ledger record` stays the path — say so, do not scrape transcripts.
## Verification
`make test` (hook corpus: a fixture payload → one row; missing fields → row without them), `--self-test` like the sibling hooks, `shellcheck -x`.
## Commit prefix
`feat(0.21.0/usage-capture/S1):`
## Size
m
