---
id: "1.1.0"
name: the gate measures what it costs
status: building
depends_on: []
branch: milestone/1.1.0-the-gate-measures-what-it-costs
---

# 1.1.0 — the gate measures what it costs

> ## Northstar: **a gate that grades the wrong variable is worse than no gate**, because it
> reads as coverage. `test-shape` caps LINES; a Godot scenario tier costs BOOTS. A consumer that
> satisfies the cap by splitting a file has paid time to look tidier.

Measured on The Appalachian Trail, 2026-09-06, adopting v1.0.0. Its integration tier is **272
scenarios, 241.9s wall / 748s CPU**, against a unit tier of 334 tests in **0.635s** — ~99.7% of
that project's whole test cost. Three scenarios of 114, 358 and 325 lines each cost **~3.3s
standalone**, because `integration.sh` gives every scenario FILE a fresh engine: that process
boundary IS the isolation contract, and it means the tier costs `files x boot / jobs` while the
assertions inside a file are free.

So the shape of the tier is the file count, and `test-shape`'s line cap cannot see it: **229 of
274 files (84%) are already under the 300-line cap**, including all 17 `pace_*` scenarios at a
mean of 117 lines. 131 files are under 150 lines — 48% of the files, 26% of the lines, ~117s of
wall clock. The cap's only pressure is to SPLIT a long file, which adds a boot.

A second adoption the same day, NullBound, hit the other end of the same idea: `unit`, `parse`,
`lint` and `warnings` file no ledger row at all, so the four cheapest tiers cannot be budgeted and
`verify --plan` has no number for the story rung — the one an agent runs after every edit. On that
tree the integration tier shrank 12% under `test-shape` while the unbudgetable unit tier grew
47%, and every gate stayed green. Same milestone, same sentence: the kit grades what it can see.

The milestone is five admissions. The tier's cost is boots and the kit should say so and grade
it. A gate that arrives red on every mature consumer needs the baseline mechanism `test-shape`
already has, or consumers just leave it off — which is what Trail did with `defaults`, `rng` and
`tres-comment`. And a config key whose shape appears in no example is exit 2 waiting to happen.

## Ship criterion

A consumer can ask this kit what ANY tier costs and get a number — boots for the scenario tier, a
ledger row for every other — rather than lines;
`test-shape`'s own `--help` says it is a readability gate and names the one that governs cost;
each of the eight gates can be turned on frozen at a consumer's current findings and ratcheted
down; and every documented config key has one example of its own shape.

## Risks

- **A boot-count gate overlaps `[tests] cases` in agentic-sdlc**, which already grades a tier's
  case count from the ledger. The answer is probably NOT a second gate here but a census line
  from `integration.sh` that the existing budget gate can read — decide before building.
- **A universal baseline mechanism is a way to never fix anything.** `test-shape`'s ledger works
  because it only shrinks and each entry names a file. A baseline that is a bare count, or that
  can grow, is worse than the gate being off and honest about it.
