---
id: 0.24.0/matrix-runs-bash-once
milestone: "0.24.0"
name: the matrix proves Python on every interpreter and bash once
status: done
reviewed: pm/roadmap/0.24.0-gate-cost/review.md
phase: 1
depends_on: []
consumed_by: []
---

# the matrix proves Python on every interpreter and bash once

The suite is 42 test modules, and the ones that spawn `bash`, `make`, `git` or the installed hook
corpora carry ~85% of the wall clock (`test_hooks_payloads` 66 s, `test_runners_installable` 30 s,
`test_fresh_project` 18 s, `test_makefile_include` 16 s …). None of that is interpreter-sensitive,
and `make matrix` replays it on 3.11, 3.12, 3.13 and 3.14 in series. When this ships the floor
interpreter (`PY_FLOOR`) runs the whole suite and the other three run only what Python can change —
the same verdict line, ~16 min → ~6.

**Measured at S1 (supersedes the "24 of 42" this feature was shaped on):** the derived census is
**35 marked / 8 unmarked of 43 modules**. `24` was what `grep -l subprocess tests/test_*.py` answers,
and that grep is wrong twice — it over-counts `test_boundaries.py` (the word is in a docstring;
it spawns nothing) and under-counts by **eleven** modules that spawn only through a `tests/support`
helper and never name `subprocess` (`test_canonicalize`, `test_check_rng`, `test_check_tres_comment`,
`test_check_unit_disk`, the five `test_pm_ledger*`, `test_scene_edit`, `test_uid_index`). Under
`sys.addaudithook` those eleven make **975 real process spawns in 41.85 s** — the slice a
list-maintained census would have kept replaying on all four interpreters. Derivation beats a grep
here, which is the reason the mark is derived rather than authored.

## Existing-construct audit

`[tool.pytest.ini_options] markers` already holds `fuzz` — the second mark joins it. There is no
`tests/conftest.py`; the derivation lands there. `PY_FLOOR` already names the interpreter `make test`
runs — the matrix's full pass is that one, not a new variable.

## Ship criterion

`make matrix` prints `[MATRIX] PASS on 3.11 3.12 3.13 3.14` in under 7 minutes where it printed it
in 16; the floor interpreter's line in `matrix.log` shows the full count and each other interpreter's
line shows the full count minus the `shell` slice; a test in a spawning module that is NOT marked is
a collection-time refusal, never a silent run on all four.
