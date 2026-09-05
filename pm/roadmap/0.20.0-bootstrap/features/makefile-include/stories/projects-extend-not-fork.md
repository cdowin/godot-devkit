---
id: 0.20.0/makefile-include/projects-extend-not-fork
feature: 0.20.0/makefile-include
milestone: "0.20.0"
name: a project Makefile is an include plus its own targets, extra gates come from devkit.toml
status: ready
owner:
depends_on: []
---

# a project Makefile is an include plus its own targets, extra gates come from devkit.toml

## Goal
nullbound's and trail's Makefiles become `include Makefile.devkit` + their own targets; nullbound's 19 scans join `check` via `[gates] extra`; `make help` shows both sets; `make precommit` green in both; `consumer-smoke` green.
## Commit prefix
`feat(0.20.0/makefile-include/S2):`
## Size
m
