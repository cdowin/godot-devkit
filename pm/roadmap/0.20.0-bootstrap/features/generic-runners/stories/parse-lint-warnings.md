---
id: 0.20.0/generic-runners/parse-lint-warnings
feature: 0.20.0/generic-runners
milestone: "0.20.0"
name: parse, lint and warnings run through the installed runners
status: todo
owner:
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
