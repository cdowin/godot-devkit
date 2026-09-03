---
id: 0.22.0/ledger/status-flips-stamp-the-ledger
feature: 0.22.0/ledger
milestone: "0.22.0"
name: pm story and feature verbs append a timestamped row to the milestone ledger
status: todo
owner:
depends_on: []
---

# pm story and feature verbs append a timestamped row to the milestone ledger

## Goal
Every `pm story|feature|bug|milestone <status>` appends `{ts, kind: "status", grain, from, to}` and
`pm decide` appends `{ts, kind: "decision", grain, entry, title}` to `pm/roadmap/<ms>/ledger.jsonl`
(D6), `ts` full UTC ISO-8601 seconds, append-only, stdlib. The directory is the grain's own
milestone directory (a story under `0.22.0/…` writes `0.22.0-telemetry/ledger.jsonl`).
The verbs' existing output and exit codes do not change.
## Gotchas
The file and the directory are minted on first write, like `decisions.md`. A no-op flip (same
status) still appends — a no-op is a fact. The row is written AFTER the frontmatter write succeeds,
never before; a refused flip leaves the ledger untouched. `pm validate` / `check pm` ignore
`ledger.jsonl` (it is not a grain doc — the slot walker must skip it, add the assertion) and
`retire` removes it with the directory. Ship `.gitattributes` `pm/roadmap/*/ledger.jsonl merge=union`
through `init` and `pm init`.
## Verification
`make test` (one test per verb: row shape, `ts` parses as UTC, ordering, no frontmatter change
beyond `status:`; retire removes the ledger with the dir; a refused flip appends nothing), `make gates`.
## Commit prefix
`feat(0.22.0/ledger/S1):`
## Size
s
