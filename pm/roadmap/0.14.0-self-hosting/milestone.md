---
id: "0.14.0"
name: self hosting
status: building
theme: devkit uses its own system
target_date:
actual_date:
depends_on: []
risk: low
track:
branch: main
labels: []
---

# 0.14.0 — self hosting

This release is the one where the toolkit starts running on itself. A consumer
adopting `check pm` or `pm changelog` can now read the author's own tree as the
worked example, and every rule shipped OFF-by-default is proven at least once
against a tree that has to keep passing it.

## Ship criterion

- `godot-devkit check all` exits 0 inside godot-devkit.
- `check pm` exits 0 with D1-D18 minus D8 enabled.
- CHANGELOG.md's 0.14.0 section is `pm changelog --render` output, reproducible
  byte-for-byte, with the pre-0.14.0 text frozen below a stated boundary.

## Risks

- The Godot-family gates have no content to scan here. Answered by `[checks]
  all`, not by softening a gate — see `decisions.md` D3.
- D8 encodes bump-at-start and this package bumps at close. Left off; the rule
  is right and does not apply (`decisions.md` D2).
