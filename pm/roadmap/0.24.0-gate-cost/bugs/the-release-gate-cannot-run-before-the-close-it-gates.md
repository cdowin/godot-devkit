---
id: 0.24.0/bugs/the-release-gate-cannot-run-before-the-close-it-gates
milestone: "0.24.0"
name: "`make milestone` cannot run against a `building` milestone whose features are all done, so the gate that decides whether to ship requires the ship decision first"
status: open
caught_in: "0.24.0"
fix_milestone:
caused_by:
---

# the-release-gate-cannot-run-before-the-close-it-gates

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
