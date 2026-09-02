---
id: 0.20.0/generic-runners/consumers-delete-their-runners
feature: 0.20.0/generic-runners
milestone: "0.20.0"
name: nullbound and trail delete the runners they no longer own
status: todo
owner:
depends_on: []
---

# nullbound and trail delete the runners they no longer own

## Goal
nullbound and trail install the runners and delete their own; verdict lines byte-identical before/after.
## Steps
`godot-devkit install-runners --force` in each; delete `tools/dev/checks/parse.sh|lint.sh|warnings.sh` and `tools/dev/runners/*.sh` that the install replaced; Makefile targets point at the installed paths; `make precommit` (nullbound) / `make check` (trail); `make consumer-smoke`.
## Commit prefix
`feat(0.20.0/generic-runners/S3):`
## Size
s
