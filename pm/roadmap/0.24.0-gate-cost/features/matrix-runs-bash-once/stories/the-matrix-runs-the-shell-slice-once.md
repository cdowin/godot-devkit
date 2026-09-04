---
id: 0.24.0/matrix-runs-bash-once/the-matrix-runs-the-shell-slice-once
feature: 0.24.0/matrix-runs-bash-once
milestone: "0.24.0"
name: the floor interpreter runs everything; the others run not-shell
status: review
owner:
depends_on: []
---

# the floor interpreter runs everything; the others run not-shell

`make matrix` runs the full suite on `PY_FLOOR` and `-m "not shell"` on every other interpreter in
`PY_MATRIX`; `matrix.log` shows per interpreter what ran; the verdict line is byte-identical to
today's (`[MATRIX] PASS on 3.11 3.12 3.13 3.14`) — the consumer-visible shape does not move, and
CI's `verify.yml` needs no edit.

## Acceptance criteria

- Makefile `matrix` recipe: the first iteration whose version equals `PY_FLOOR` gets `$(PYTEST_Q)`,
  every other gets `$(PYTEST_Q) -m "not shell"`; `PY_FLOOR` absent from `PY_MATRIX` is a refusal
  naming both (never a matrix with no full pass).
- `tests/test_makefile_gates.py` (or the file that already proves the Makefile's own recipes) gains
  a case that runs the recipe against a stand-in pytest and asserts which interpreter got the full
  argv — red on HEAD.
- `make help`'s matrix line and CLAUDE.md's `make milestone` sentence say what the matrix proves.
- CHANGELOG `## Unreleased` bullet (internal to this repo's gate, still consumer-visible as CI time).
- Measured on the release commit: `[MATRIX]` wall clock before and after, in the story's close block.

## Out of scope

Parallelising interpreters; the smoke.

## Done

done: 91e5cac — the first iteration whose version equals `PY_FLOOR` is handed `$(PYTEST_Q)` and
every other `$(PYTEST_Q) -m "not shell"`; `matrix.log`'s per-interpreter header names the slice
(`=== python 3.12 (-m "not shell") ===`) so a count that dropped because of the slice is not read as
tests going missing; `PY_FLOOR` outside `PY_MATRIX` refuses by name — `[MATRIX] REFUSED: PY_FLOOR
"3.99" is not in PY_MATRIX "3.11 3.12 3.13 3.14", so no interpreter would run the whole suite`, exit
2, zero interpreters spawned. Membership is decided by the same word splitting the loop uses, so the
guard and the run cannot disagree; a `case` pattern would have called a 3.1 floor a member of a 3.11
matrix.

**Measured: 1045 s → 459 s** (17:25 → 7:39), `make matrix` end to end on all four interpreters, each
run in its own fresh worktree — a12df69 before, 91e5cac after. Per interpreter, pytest's own totals:
before 1551 tests in 263.85 s (3.11) / 184.53 s (3.12) / 272.26 s (3.13) / 320.30 s (3.14) = 1041 s;
after 1590 tests in 260.60 s (3.11) and 249 tests in 8.14 s / 6.96 s / 6.25 s = 282 s. The floor is
the control and barely moved (263.85 → 260.60) while carrying 39 tests the before tree did not have
— 13 of this story's own and 26 from ea0be66 — so the after number is if anything pessimistic. The
459 s wall carries ~177 s of uv environment setup for four interpreters in a cold worktree, measured
while two agents in another repo were running a parallel headless-Godot sweep on the same machine;
the before run paid ~4 s for the same setup on a quiet one. Under the milestone's 8-minute criterion
either way, and the remaining cost is now uv, not pytest.

The verdict line did not move: `[MATRIX] PASS on 3.11 3.12 3.13 3.14`, byte for byte, so
`verify.yml` needed no edit. `make test` is untouched and still runs everything — 1590 passed, 1
skipped, 3747 subtests. `-m shell` selects 1342 of 1591, `-m "not shell"` the other 249.

`tests/test_makefile_gates.py` gains 13 cases run against a stand-in `uv` that records the argv it
was handed: which interpreter got which command is the one question a census over the Makefile text
cannot answer, because `-m "not shell"` has to survive make's expansion, a continued recipe line and
word splitting as ONE argv element — a grep for the string in the recipe would pass on a recipe that
hands pytest `-m not` and a positional path called `shell`. Seven of the 13 are the refusal matrix
(the floor bumped without the matrix, an empty matrix, an empty floor, a floor that is only a prefix
or only a suffix of a listed version, two versions glued together, a glob), each asserting exit 2
AND that nothing was spawned. 11 of the 13 are red on a12df69; the two green ones are the
verdict-shape pins that must not move.

`make help`'s matrix line and CLAUDE.md's `make milestone` paragraph both say what the matrix proves.
The CHANGELOG `## Unreleased` bullet is written but landed in **ea0be66**, not 91e5cac: the peer
working `ci-verify-installs-no-godot` committed `CHANGELOG.md` by pathspec while this story's bullet
was uncommitted in the shared worktree, and a pathspec commit takes the worktree content.
