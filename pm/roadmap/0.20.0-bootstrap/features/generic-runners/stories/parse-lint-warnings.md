---
id: 0.20.0/generic-runners/parse-lint-warnings
feature: 0.20.0/generic-runners
milestone: "0.20.0"
name: parse, lint and warnings run through the installed runners
status: review
owner: developer
depends_on: []
---

# parse, lint and warnings run through the installed runners

## Goal
`parse.sh`, `lint.sh`, `warnings.sh` are installables on `gdk_*`; a consumer's `make parse|lint|warnings` prints one verdict line each.
## Port
nullbound `tools/dev/checks/parse.sh` (boot-clean sweep + `compile_sweep.gd`), `lint.sh` (gdlint), `warnings.sh` — consumer names → `GDK_*` variables with defaults. The `.gd` sweep script travels as an installable too.
## Verification
`make test`; `bash installables/parse.sh --help` exits 0; `--self-test` on argument handling.
## Commit prefix
`feat(0.20.0/generic-runners/S1):`
## Size
s
## Done
`parse.sh` (+ `compile_sweep.gd`), `lint.sh`, `warnings.sh` ship on `gdk_runners.sh`, wired into
`install-runners` at `tools/dev/runners/` — the sweep script beside its runner, addressed as
`GDK_PARSE_SWEEP_SCRIPT`. Self-tests: parse 10, lint 8, warnings 8 cases; zero `nullbound`/`trail`
strings; `shellcheck -x` clean (asserted per-runner in `tests/test_runners_installable.py`).
Also fixed 11 of the 12 `review-minors-from-0.19.0` findings plus the SC2031 consumer-lint leak.
