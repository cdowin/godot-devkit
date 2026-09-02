---
id: 0.21.0/ledger/status-flips-stamp-the-ledger
feature: 0.21.0/ledger
milestone: "0.21.0"
name: pm story and feature verbs append a timestamped row to the milestone ledger
status: todo
owner:
depends_on: []
---

# pm story and feature verbs append a timestamped row to the milestone ledger

## Goal
Every `pm story|feature|bug|milestone <status>` and `pm decide` appends `{ts, kind: "status"|"decision", grain, from, to}` to `pm/roadmap/<ms>/ledger.jsonl`, UTC ISO-8601, append-only, stdlib. The verbs' existing output and exit codes do not change (gate semantics stable).
## Gotchas
The ledger is minted on first write like `decisions.md`; `pm validate` / `check pm` ignore it (add the assertion). A verb that is idempotent (same status) still appends — a no-op flip is a fact.
## Verification
`make test` (one test per verb: row shape, ordering, no frontmatter change), `make gates`.
## Commit prefix
`feat(0.21.0/ledger/S1):`
## Size
s
