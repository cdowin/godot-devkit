---
id: 0.24.0/smoke-proves-the-runners-the-release-ships
milestone: "0.24.0"
name: the consumer smoke installs the release candidate's runners into a throwaway worktree
status: done
reviewed: pm/roadmap/0.24.0-gate-cost/review.md
phase: 2
depends_on: []
consumed_by: []
---

# the consumer smoke installs the release candidate's runners into a throwaway worktree

The smoke runs the working tree's checks IN PLACE against the consumer's INSTALLED runners — the
combination a consumer lives in for the minutes between a pin bump and `install-runners --force`,
and never the combination a release ships. v0.23.0's release found it: `check test-shape` asks the
roster through `make integration-list`, nullbound had opted into the header rule, its runners were
v0.22.0, and the smoke was red on a consumer state the release's own adoption note says to leave
(nullbound `0.90.3.2` M48 — the fix was to advance the fixture by hand, ahead of the pin). When
this ships the smoke proves each consumer against the runners the working tree would install,
inside a git worktree of that consumer, and the main checkout stays untouched.

## Existing-construct audit

`consumer_smoke.py` already imports `godot_devkit.repo.install` for the fresh project; the same
installer targets the worktree. `git worktree add <tmp> HEAD` on the consumer costs seconds and
needs no copy. The `checkout unchanged` row keeps meaning the MAIN checkout.

## Ship criterion

`make smoke` on a consumer whose installed `Makefile.devkit` lacks a target the working tree's
checks ask for is GREEN when the working tree's installer supplies it, and the smoke log says so in
one row (`runners: N file(s) ahead of the consumer's install`); the consumer's own `git status` is
byte-identical before and after; `git worktree list` on the consumer shows nothing left behind.
