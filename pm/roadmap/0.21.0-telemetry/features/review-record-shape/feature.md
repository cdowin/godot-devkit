---
id: 0.21.0/review-record-shape
milestone: "0.21.0"
name: A review record carries a machine-readable verdict block
status: planning
reviewed:
phase: 1
depends_on: []
consumed_by: ["0.21.0/ledger-report"]
---

# A review record carries a machine-readable verdict block

What it makes true: yield, rework and escapes are computable. (a) A review record (`review.md`)
carries ONE parseable block per pass — `verdict: SHIP-WITH-FIXES`, then a table of findings
`id | severity | disposition (landed <hash> / rejected: <why> / deferred: <feature-id>)` — written by
the installed `reviewer` / `simplifier` / `code-reviewer` / `milestone-reviewer` agent definitions
(`install-agents` updates them) and read by the report. (b) A bug gains an optional `caused_by:`
frontmatter field naming the closed feature whose change produced it; `pm new bug --caused-by <id>`
sets it and `pm validate` resolves it like any ref.

## Existing-construct audit

`reviewed:` on a feature already points at the record — the block goes IN that record, no new
file. `caught_in:` says which milestone found the bug; `caused_by:` says which feature made it —
different facts, both needed for an escape.

## Ship criterion

`pm ledger report` computes yield from a record written by the installed agents with no hand
editing; an escape (a bug with `caused_by:` a `done` feature) counts against that feature.
