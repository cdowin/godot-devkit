---
id: 0.23.0/ledger-report/yield-rework-escapes-overhead
feature: 0.23.0/ledger-report
milestone: "0.23.0"
name: report prints review yield, rework, escapes and overhead shape per feature and milestone
status: review
owner:
depends_on: []
---

# report prints review yield, rework, escapes and overhead shape per feature and milestone

## Goal
Sections 2–5, all from the ledger, the review records and bug frontmatter: yield per review pass
(from the verdict block), rework per feature (`review → wip` status rows; dispatch rows after a
story's `review` row; verdict distribution), escapes per milestone (bugs with `caused_by:` a `done`
feature, grouped by feature), overhead shape (dispatches per story; `tool_calls_before_first_write`
per dispatch; decision rows per feature and the seconds to the next status row). No git, no
`.gate-reports/`.
## Gotchas
A section with no rows says "no data", never prints zero.
## Verification
`make test` fixtures for each section, `make gates`.
## Commit prefix
`feat(0.23.0/ledger-report/S2):`
## Size
m
