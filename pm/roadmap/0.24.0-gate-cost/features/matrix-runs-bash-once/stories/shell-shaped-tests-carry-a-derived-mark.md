---
id: 0.24.0/matrix-runs-bash-once/shell-shaped-tests-carry-a-derived-mark
feature: 0.24.0/matrix-runs-bash-once
milestone: "0.24.0"
name: a test module that spawns bash or make is marked shell at collection, by construction
status: review
owner:
depends_on: []
---

# a test module that spawns bash or make is marked shell at collection, by construction

`pytest -m shell --co -q` lists every test in the 24 modules that import `subprocess` (or spawn
through a support helper that does), and `pytest -m "not shell"` lists the other 18 modules — with
no list maintained anywhere: a new `tests/conftest.py` `pytest_collection_modifyitems` reads each
item's module and applies the mark when the module (or `tests/support`) imports `subprocess`. The
mark is declared in `pyproject.toml` beside `fuzz` with a one-line reason in the same voice.

## Acceptance criteria

- `pyproject.toml` markers gains `shell` (derived, never hand-applied; the reason says why).
- `tests/conftest.py` applies it at collection from the module source — `import subprocess`,
  `from subprocess import`, or a `tests.support` helper that spawns (count the helpers, do not guess).
- A hand-written `@pytest.mark.shell` / `pytestmark` in a module that does NOT spawn is a
  collection error naming the file: the mark is a fact, not an opinion.
- A test asserts the census: the marked module count and the unmarked module count, red on a module
  that changes sides.
- `make test` and `make fuzz` are unchanged — they run everything; only `matrix` reads the mark (S2).

## Out of scope

The matrix recipe (S2). Moving any test between tiers. `pytest-xdist`.
