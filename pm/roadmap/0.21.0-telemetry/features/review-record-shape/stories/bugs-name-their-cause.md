---
id: 0.21.0/review-record-shape/bugs-name-their-cause
feature: 0.21.0/review-record-shape
milestone: "0.21.0"
name: a bug can name the closed feature that caused it so escapes count
status: todo
owner:
depends_on: []
---

# a bug can name the closed feature that caused it so escapes count

## Goal
`caused_by:` (optional, a feature id) on the bug template; `pm new bug <ms> <slug> --caused-by <feature-id>`; `pm validate` resolves it like `depends_on`. `check pm` unchanged.
## Verification
`make test`, `make gates`.
## Commit prefix
`feat(0.21.0/review-record-shape/S2):`
## Size
xs
