---
id: 0.21.0/ledger-report/yield-rework-escapes-overhead
feature: 0.21.0/ledger-report
milestone: "0.21.0"
name: report prints review yield, rework, escapes and overhead shape per feature and milestone
status: todo
owner:
depends_on: []
---

# report prints review yield, rework, escapes and overhead shape per feature and milestone

## Goal
Sections 2–5: yield per review pass (from the verdict block), rework per feature (commits after the story's `review` row via git prefixes; fixup commits; verdict distribution; reopened stories = `done`→anything rows), escapes per milestone (bugs with `caused_by:` a `done` feature, grouped by feature), overhead shape (dispatches per story, gate re-runs from `.gate-reports/` timestamps if present, NEEDS-YOU count and latency from `decisions.md` "Would have asked? YES" entries and the next status row).
## Gotchas
Git is read through one helper; a branch with no prefixed commits reports "no rework data", never zero.
## Verification
`make test` fixtures for each section, `make gates`.
## Commit prefix
`feat(0.21.0/ledger-report/S2):`
## Size
m
