---
id: 0.21.0/ci-green
milestone: "0.21.0"
name: make milestone is green where CI runs it
status: done
reviewed: pm/roadmap/0.21.0-release-integrity/features/ci-green/decisions.md
phase:
depends_on: []
consumed_by: []
---

# make milestone is green where CI runs it

What it makes true: `make milestone` — the target `verify.yml` runs — is green under `make` and with
shellcheck on PATH, which is the environment `ubuntu-latest` provides. The makefile tests no longer
inherit the parent recipe's `MAKELEVEL`/`MAKEFLAGS` into the make they spawn, and the six shellcheck
findings across three installables are cleared at the source.

Why: `verify.yml` was red on v0.19.0 and v0.20.0. Green under bare pytest on a Mac without
shellcheck, red under the one target CI runs — a gate whose verdict depends on how it was invoked.
