---
id: "0.24.0"
name: gate-cost
status: packaging
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

## Measured on the release commit — 2026-09-04

`make milestone` at `ef08c3e`, quiet machine: **3:36 total**, against a criterion of under 8 minutes
and a starting point of ~20.

```
[GATES]  4 check(s) PASS
[HOOKS]  3 hook(s) SELF-TEST OK
[MATRIX] PASS on 3.11 3.12 3.13 3.14
[SMOKE]  PASS — 43 check(s) across 2 consumer(s) + the fresh project, every census matched an
         independent count, the gates run against the release's own runners, both checkouts
         unchanged and no worktree left behind
```

The matrix is where it went, and the shape is exactly what the milestone argued for:

| interpreter | ran | wall |
|---|---|---|
| 3.11 (floor) | 1714 passed, 1 skipped, 3901 subtests | **172.4 s** |
| 3.12 | 265 passed, 1450 deselected | 3.1 s |
| 3.13 | 265 passed, 1450 deselected | 3.1 s |
| 3.14 | 265 passed, 1450 deselected | 3.0 s |

The floor carries the whole suite; the other three carry only what Python can change, and cost
**9 seconds between them** where they used to cost ~13 minutes. The verdict line is byte-identical to
the one this milestone opened with — a consumer sees no change except the clock.

**No test was deleted**: 1714 collected on the floor, up from 1560 at the start of the milestone. The
five modules that left `tests/` are `make smoke` rows, and the one test NAME that went missing along
the way (grafted into a sibling) was restored at `3c9f0b4` after the review found it.
