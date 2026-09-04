---
id: 0.24.0/matrix-runs-bash-once/the-matrix-runs-the-shell-slice-once
feature: 0.24.0/matrix-runs-bash-once
milestone: "0.24.0"
name: the floor interpreter runs everything; the others run not-shell
status: todo
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
