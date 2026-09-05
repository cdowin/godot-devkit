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

## SHIPPED THEN DELETED, IN THIS SAME MILESTONE — read this before citing the feature

This feature built `tools/consumer_smoke.py`'s release-runner half: install the release candidate's
runners into a throwaway worktree of a live consumer and run the gates there. **`b135b3b` deleted the
whole file.** Chris, 2026-09-04, on why the vehicle was wrong even though the question was right:

> *"devkit should know nothing about its consumers. It should only know what it wants to publish to the
> world. Why are we cross wiring? … That'd be like Google knowing something about my computer and holding
> up releases to their search engine because my browser is out of date."*

The mechanism made two private game repos a precondition for this package's tag, and it asserted their
CONTENT was clean rather than that this tool BEHAVED — so a consumer's in-flight work reddened the
release, and it was silent in CI besides. `CLAUDE.md` rule 8 now forbids the shape.

**The question this feature asked survives; only its answer moved.** "Do the runners the release ships
actually work when installed?" is now answered against `tests/fixtures/` and the fresh-project probe,
which build their own project and read nothing outside the checkout — the `make -n` acceptance half, the
real `make check` run and the real `doctor.sh` hook census all still run. What was lost is SCALE, filed
as `bugs/the-smoke-took-fixture-scale-with-it` with the specific assertions and what each would need
vendored.

This feature stays `done` rather than being reopened or rewritten: it shipped, it was measured, and a
later ruling replaced it. That sequence is the record.

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
