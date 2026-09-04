---
id: "0.24.0"
name: gate-cost
status: building
depends_on: []
branch: milestone/0.24.0-gate-cost
---

# 0.24.0 — gate-cost

`make milestone` costs ~20 minutes on a toolkit whose whole test suite is 4.7 minutes on one
interpreter, because the matrix replays that suite on four interpreters serially and most of its
weight is `bash` and `make` — which no interpreter changes — and because a handful of unit tests read
the live consumer checkouts that `make smoke` already owns as fixtures. When this ships a release
runs the Python on every claimed interpreter and the shell once, the consumer reads live where the
consumers are the fixtures, and the smoke proves the runners a release actually ships rather than the
runners a consumer happens to have installed. Measured 2026-09-04 at v0.23.0, python 3.14, quiet
machine: 1539 tests / 280 s; 48 tests over 1 s sum 124 s (44%); the five heaviest files are 52% —
`test_hooks_payloads` 66 s, `test_runners_installable` 30 s, `test_fresh_project` 18 s,
`test_makefile_include` 16 s, `test_defaults` 13.5 s (one test: 12 s over a real consumer tree).
Chris, 2026-09-04: "This is a pretty straightforward/simple toolkit. 20+ minutes of testing twice
just to release a milestone!?" — and the choice A + C, both.

## Ship criterion

`make milestone` on the release commit finishes in under 8 minutes on the same machine with the
same verdict lines it prints today (`[MATRIX] PASS on 3.11 3.12 3.13 3.14` still names every
interpreter; `[SMOKE]` still reports every census), no test deleted — every test that leaves
`tests/` reappears as a smoke row — and every bug under `bugs/` fixed or explicitly parked.

## Risks

- A `shell` mark derived from `import subprocess` is over-inclusive (a pure-Python test in a
  spawning module rides the floor interpreter only). Accepted: the three extra interpreters lose a
  little Python coverage; the floor keeps all of it, and the floor is the interpreter that matters.
- The smoke's worktree install (phase 2) touches a consumer's `.git/worktrees`; the "checkout
  unchanged" row must keep proving the main checkout untouched.
