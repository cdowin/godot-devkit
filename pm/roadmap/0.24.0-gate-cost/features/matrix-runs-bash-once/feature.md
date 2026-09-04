---
id: 0.24.0/matrix-runs-bash-once
milestone: "0.24.0"
name: the matrix proves Python on every interpreter and bash once
status: planning
reviewed:
phase: 1
depends_on: []
consumed_by: []
---

# the matrix proves Python on every interpreter and bash once

The suite is 42 test modules; 24 of them spawn `bash`, `make`, `git` or the installed hook corpora
through `subprocess`, and those 24 carry ~85% of the wall clock (`test_hooks_payloads` 66 s,
`test_runners_installable` 30 s, `test_fresh_project` 18 s, `test_makefile_include` 16 s …). None of
that is interpreter-sensitive, and `make matrix` replays it on 3.11, 3.12, 3.13 and 3.14 in series.
When this ships the floor interpreter (`PY_FLOOR`) runs the whole suite and the other three run only
what Python can change — the same verdict line, ~16 min → ~6.

## Existing-construct audit

`[tool.pytest.ini_options] markers` already holds `fuzz` — the second mark joins it. There is no
`tests/conftest.py`; the derivation lands there. `PY_FLOOR` already names the interpreter `make test`
runs — the matrix's full pass is that one, not a new variable.

## Ship criterion

`make matrix` prints `[MATRIX] PASS on 3.11 3.12 3.13 3.14` in under 7 minutes where it printed it
in 16; the floor interpreter's line in `matrix.log` shows the full count and each other interpreter's
line shows the full count minus the `shell` slice; a test in a spawning module that is NOT marked is
a collection-time refusal, never a silent run on all four.
