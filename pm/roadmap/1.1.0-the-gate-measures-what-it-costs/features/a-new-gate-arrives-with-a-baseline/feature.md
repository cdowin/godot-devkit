---
id: 1.1.0/a-new-gate-arrives-with-a-baseline
milestone: "1.1.0"
name: A new gate can be adopted frozen, then shrunk
status: planning
reviewed:
phase:
depends_on: []
consumed_by: []
---


# A new gate can be adopted frozen, then shrunk

**The finding.** v1.0.0 shipped eight gates. On a mature consumer adopting them at once, five
were red on the first run: `defaults` (6 findings), `rng`, `tres-comment`, `unit-disk` (3) and
`test-shape` (47). Only `test-shape` had a way to say "this is my debt, freeze it here" — its
`[test_shape] ledger`, which records each over-cap file at its current size and only ever
shrinks. That gate went green the same afternoon and now ratchets.

The other four had no such mechanism, so the consumer's only choices were "fix everything now" or
"leave the gate off". It narrowed `unit-disk` (defensible — a config key existed) and **left
`defaults`, `rng` and `tres-comment` off**, with a comment naming what each had found. A gate
that is off is worth nothing, and this is the predictable outcome for every consumer with an
existing codebase.

`test-shape`'s ledger is the pattern and it is already proven in this repo. The ask is to
generalise it.

## Ship criterion

Every gate that can produce a per-file finding accepts a baseline in `devkit.toml` in the shape
`test-shape` already uses — an entry per file, at its current measurement, which may only shrink
— so a consumer can adopt the gate frozen on day one and pay the debt down deliberately. A gate
run reports its baselined count as a named line, every run, so frozen debt is visible rather than
quiet.

## Proof budget

  cases: 4-6 (one per gate that gains a baseline, plus a shrink-only case and a growth case)
  tier: pyunit
  lands in: each gate's existing test module; the shrink-only semantics get one shared case
  what already covers this: `test-shape`'s ledger is covered end to end and is the template. The
    other gates have no baseline concept to test.
