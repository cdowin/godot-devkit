---
id: 0.19.0/install-runners/consumers-adopt
feature: 0.19.0/install-runners
milestone: "0.19.0"
name: nullbound and trail install the library and delete their forks
status: wip
owner: developer
depends_on: []
---

# nullbound and trail install the library and delete their forks

## Goal

nullbound and trail install the library, delete their forks, and every gate verdict line is
byte-identical before and after.

## Steps

1. `install-runners` verb (mirrors `install-hooks`: write once, then the file is the repo's;
   `--diff` shows drift). README + `install-*` help updated; CHANGELOG entry.
2. nullbound: `tools/dev/_common.sh` and `tools/dev/runners/import_cache.sh` deleted; the
   Makefile and every `tools/dev/runners/*.sh` call `gdk_*`; `make precommit` green; verdict
   lines diffed against a pre-adoption run.
3. trail: `tools/dev/_common.sh` deleted; its Makefile targets call `gdk_*`; `make check` green.
4. `make consumer-smoke` green on both.

## Out of scope

Anything either consumer's Makefile does beyond calling the library.

## Commit prefix

`feat(0.19.0/install-runners/S4):`

## Size

m
