---
id: "1.2.0"
kind: milestone
name: the runner fails fast
status: building
depends_on: []
branch: milestone/1.1.1-the-runner-fails-fast
mode:
version: 1.2.0
changelog: The scenario runner fails fast on a parse error, and the header ratchet adopts gradually.
---

# 1.2.0 — the runner fails fast

Two defects found by a consumer adopting v1.0.0's scenario tier and `[test_shape] header`, filed as
GitHub #12 and #13. Both cost real time in the loop an agent runs most: a parse error that reads as
a 60s hang, and a ratchet that cannot be adopted on a tree that already slices by `covers:`.

## Ship criterion

- A scenario whose script does not parse FAILS within seconds, and its verdict names the parse error.
- `[test_shape] header_ledger` can hold a scenario that carries one of the two header lines, and
  releases it only when it carries both.
