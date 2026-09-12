---
id: 1.1.0/the-tiers-cost-is-boots
milestone: "1.1.0"
name: The scenario tier is graded on boots, which is what it costs
status: building
reviewed:
phase:
depends_on: []
consumed_by: []
---


# The scenario tier is graded on boots, which is what it costs

**The measurement.** On a consumer with 272 scenarios: 241.9s wall, 748s CPU. Per file, ~2.75s
CPU and ~0.89s wall at the achieved parallelism. Scenarios of 114, 358 and 325 lines each cost
~3.3s standalone — **the line count does not move the number at all.** `integration.sh` states
the reason in its own header: "one scenario.sh, one fresh engine", and that process boundary is
the isolation contract, so it is not a bug to be fixed. It is the cost model, and nothing in the
kit names it.

**Why that matters more than it sounds.** `test-shape` is the kit's only opinion about the
scenario tier, and it caps lines. On that consumer it could not see 84% of the files. Its cap
also pushes the wrong way: the way to satisfy a 300-line cap is to split the file, and a split
adds a boot. A consumer that follows the gate faithfully makes the tier slower.

## Ship criterion

`test-shape --help` says plainly that it is a readability gate — it stops a scenario becoming a
grab-bag — and names what governs cost instead. `integration.sh` reports its boot count and total
boot cost as a census line, in a shape `agentic-sdlc check budget` can grade, so a consumer's
ceiling can be expressed in the unit it actually pays. The README's testing section carries the
cost model in one sentence: merging two scenarios saves a boot, trimming lines saves nothing.

GitHub #8, `integration` half: `integration`, `integration-all` and `integration-diff` pass
`gdk_gate` its fifth argument, the count of scenarios the run booted, so the `gate` row carries a
census and `[tests] cases` on those tiers grades instead of FAILing UNCOUNTED. That census IS the
boot count — no second gate here; agentic-sdlc's `[tests] cases` is the ceiling (the milestone's
first risk, decided).

## Proof budget

  cases: 2-3
  tier: pyunit for the help text and the census line shape; the existing runner self-test corpus
    for the count itself
  lands in: `tests/test_runners_installable.py` and the test-shape gate module
  what already covers this: nothing. `test-shape` is well covered for what it measures; there is
    no assertion anywhere about what the tier COSTS, because the kit has never had that concept.
