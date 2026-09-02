---
id: "0.19.0"
name: runners
status: building
depends_on: []
branch: milestone/0.19.0-runners
---

# 0.19.0 — runners

The sandboxed headless-run shell library every consumer re-invents becomes a devkit installable.
Filed 2026-09-02 from nullbound: its `tools/dev/_common.sh` grew to 433 lines of project-agnostic
shell this week (quiet gate capture + one-line verdicts naming a full log, a per-run self-destroying
sandbox HOME with exit hooks and stale-home reaping, `project.godot` snapshot/restore, a bounded
import-cache runner with an outcome check and a churn report) while trail's copy is the 115-line
ancestor with the same four seed functions. A consumer with no scripted verification path makes
every agent invent one — measured at 2.3M tokens on trail — and a consumer that forks the library
strands the next fix (the sandbox-hook quoting fix shipped as a consumer fork and needed 0.18.1).

## Ship criterion

`godot-devkit install-runners` writes one prefix-parameterised shell library + the import-cache
runner into a consumer; nullbound and trail both install it, delete their forks, and their
`make parse/unit/scenario/smoke/import-cache` targets run through it with byte-identical verdict
lines. The library carries `--self-test` like the hooks do.

## Risks

- Shell portability (macOS bash 3.2 vs Linux) — the installables already hold that line; the
  library must too, under `shellcheck`.
- The prefix: nullbound's functions are `nullbound_*`, trail's `trail_*`; the installable exposes
  `gdk_*` and the consumer's Makefile calls those. A consumer keeping its old names is a second
  name for the same fact and is not supported.
