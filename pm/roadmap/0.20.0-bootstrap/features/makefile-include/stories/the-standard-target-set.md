---
id: 0.20.0/makefile-include/the-standard-target-set
feature: 0.20.0/makefile-include
milestone: "0.20.0"
name: Makefile.devkit carries the standard targets and the quiet-by-default convention
status: todo
owner:
depends_on: []
---

# Makefile.devkit carries the standard targets and the quiet-by-default convention

## Goal
`installables/Makefile.devkit` exists with the standard target set and the quiet convention; `make -n <every target>` succeeds on a fixture project.
## Shape
Targets delegate to the installed runners and the devkit CLI exactly as both consumers' Makefiles do today (lift, do not design). The `DEVKIT_VERSION` pin stays in the PROJECT Makefile (it is the one line that must differ per project). `check` composes the devkit gates + `[gates] extra`.
## Verification
`make test` (a test renders a fixture project and runs `make -n` per target); `make gates`.
## Commit prefix
`feat(0.20.0/makefile-include/S1):`
## Size
m
