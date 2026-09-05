---
id: 0.24.0/bugs/the-release-gate-cannot-run-before-the-close-it-gates
milestone: "0.24.0"
name: "`make milestone` cannot run against a `building` milestone whose features are all done, so the gate that decides whether to ship requires the ship decision first"
status: fixed
caught_in: "0.24.0"
fix_milestone:
caused_by:
---

# the-release-gate-cannot-run-before-the-close-it-gates

## FIXED in 0.24.0 — but read the successor before assuming the class is gone

The deadlock itself is gone: D6 no longer fires on a `building` milestone whose features are all `done`,
`reviewing` exists as the state that silences it, and 0.24.0 is the first release cut through the new
order. Verified on this release — `make milestone` ran green at `reviewing`, which was impossible before.

**The CLASS of mistake was not gone, and the same release proved it.** With the deadlock removed, the gate
became runnable too EARLY instead of too late: `make milestone` ran before the reviewer, twice, and both
runs were void the moment the review asked for fixes. Same error one layer up — a gate ordered against the
wrong thing. Chris, 2026-09-04: *"The make milestone with the full test suite is the LAST thing before
saying 'yeah, this is done'."*

That is fixed in prose here (`SDLC.md` § Close protocol and `.claude/skills/release/SKILL.md` both
re-ordered, with the rule stated: **when a gate and a judgement both bear on one decision, the judgement
runs first and the gate answers for its result**) — and prose is what failed the previous two times.
`0.25.0/the-release-is-a-conveyor` is the structural fix, and this bug is one of the three incidents it
cites as its reason to exist.

## Symptom

Hit closing 0.24.0, 2026-09-04. With all three features `done` and the milestone still `building`,
`make milestone` failed in **1.1 seconds**, at `gates`, before the matrix or the smoke ran at all:

```
DRIFT  milestone 0.24.0 is 'building' but all 3 features are done (should be done)
[check:pm] FAIL — 1 status-drift / integrity violation(s)
[GATES] FAIL (exit 1) — 3 check(s) PASS
make: *** [gates] Error 1
```

So the release gate could not be run until the milestone was flipped `done` — and flipping it `done`
is the decision the gate exists to inform. The only way through was to close first and measure after.

## Root cause

`check pm`'s drift rule "all features done ⇒ the milestone should be done" is correct **bookkeeping**
and wrong as a **precondition for the release gate**. `make milestone` runs `gates`, `gates` runs
`check pm`, and `check pm` refuses the exact state a milestone occupies between "the work is
finished" and "we have decided to ship it".

That in-between state is not drift. It is the state every milestone passes through, and it is
precisely when the ship criterion is supposed to be measured.

## Why it matters

- The gate cannot fail usefully. By the time it can run, the close it was meant to gate has happened.
- It reads as a false negative in a moment when a real red would be indistinguishable — a 1.1-second
  `[GATES] FAIL` looks like a broken build, not a status quibble.
- **It recurs on 0.25.0.** Nothing about 0.24.0 caused it; the next milestone hits it the same way at
  the same point.

## Fix

Options, in the order I would weigh them:

1. **Let the drift rule accept `building` when every feature is done and the milestone is the one
   being gated.** The narrowest change; the rule keeps meaning what it means for every other
   milestone in the tree.
2. **Report rather than refuse.** `check pm` already distinguishes what it refuses (facts about its
   INPUT) from what it reports while doing what it was asked. "All features done, milestone still
   building" is a report — a tree-shaped observation, exactly like D3/D5.
3. **Take `check pm` out of the release gate's `gates` roster** and run it as its own step. Weakest:
   PM integrity genuinely belongs in a release gate; it is only this one rule that inverts.

Test: a fixture tree with every feature `done` and the milestone `building` — `make milestone` runs
its gates through to the matrix rather than exiting at `check pm`.

## Note for whoever fixes it

The close still happened in the right order this time — the review landed, its findings were fixed,
the features closed, and only then was the milestone flipped. Nothing was rubber-stamped to satisfy
the gate. But that is discipline, not enforcement, and this bug is the gap between them.
