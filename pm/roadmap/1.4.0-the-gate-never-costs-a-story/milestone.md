---
id: "1.4.0"
kind: milestone
name: the gate never costs a story
status: packaging
depends_on: []
branch: milestone/1.4.0-the-gate-never-costs-a-story
mode: parallel
version: 1.4.0
changelog:
reviewed: docs/reviews/2026-09-29-1.4.0-milestone.md
---


# 1.4.0 — the gate never costs a story

Filed from NullBound 0.91–0.93.7 (2026-09-17 → 2026-09-29): parallel agent lanes on one machine
turned the gate itself into the thing that stopped stories. Examples: a self-test that
re-initialised the host repo, a liveness probe a sandbox fooled, a unit timeout a loaded machine
tripped, load flakes reported red, a fixture edit that booted 166 scenarios, a stale uid index
after every merge, an import pass that rewrote authored `.tres`, and a capture window that stole
focus. GitHub #16 #17 #19 #20 #23 #24 #28 #30 #31 #32 #33 #34 #35 #36 #37, and #38 (the kit ships as a locked wheel), added 2026-09-30.

Out of this package (closed with a pointer): #21 (a uid pre-commit hook), #22 (a codex generator),
#25 (a loc hook). Deferred to 1.5.0: #18 (`stats` verb). #36 (warm-process integration tier) was pulled in mid-milestone so #36 and #37 ship on one pin.

## Ship criterion

- Every runner self-test run with `GIT_DIR` exported to a throwaway repo leaves that repo's config
  untouched.
- `integration.sh --diff` boots only the scenarios that reach a touched fixture, reruns a failure
  alone once, and repairs a stale import cache once before the sweep.
- `make import-cache` never writes a tracked file in the working tree.
- `make milestone` green on this tree.

## Risks

- The import copy doubles disk for a large project. Mitigated by clone/reflink copies; a plain `cp`
  fallback is slow but correct.
- An off-screen window may be clamped on-screen by macOS. That lane reports what it could not
  prove without a display.
