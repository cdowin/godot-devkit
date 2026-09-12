---
id: 1.1.0/every-tier-files-its-cost
milestone: "1.1.0"
name: Every tier files a cost row, including the cheap ones
status: done
reviewed: docs/reviews/2026-09-12-1.1.0-every-tier-files-its-cost.md
phase:
depends_on: []
consumed_by: []
changelog: parse, lint, warnings and unit file a ledger cost row; unit files its test count as the census (#7, #8).
---

# Every tier files a cost row, including the cheap ones

`the-tiers-cost-is-boots` gives `integration.sh` a census line the budget gate can grade. This is
the other half of the same northstar: **four tiers file no ledger row at all**, so no ceiling can
be put on them and no ladder rung can report what it costs.

**The measurement**, NullBound adopting v1.0.0 on 2026-09-06. `make unit` is **41.8s for 1,479
cases with no engine boot in it**, and appends nothing:

```
$ before=$(wc -l < …/ledger.jsonl); make unit; after=$(wc -l < …/ledger.jsonl)
ledger rows:      155 ->      155
```

**Why.** `gdk_gate.sh`'s `_gdk_ledger_close` needs a verdict it can name — from a
`gdk_gate_capture` fault line, or from `GDK_GATE_VERDICT`. `unit.sh` reports through
`gdk_gate_publish` and sets `GDK_GATE_VERDICT` zero times, so the close is a no-op with a stderr
note nobody reads. `Makefile.tiers` does not wrap `parse`, `lint`, `warnings` or `unit` in
`gdk_gate`, and **its reasoning is right** — its own header says a gate wrapped twice reports the
wrapper's summary and files the runner's verdict in a log nobody opens. The rule is correct; the
consequence was not intended.

**What it costs a consumer.** The four cheapest, most-run tiers are exactly the ones
`agentic-sdlc check budget` is structurally blind to. On NullBound that is the tier that ran away:

```
                    2026-08-27      2026-09-06      change
unit                    30,677          45,041        +47%
integration             45,241          39,814        -12%
```

`test-shape` capped integration scenario size, so integration shrank; nothing could see unit, so
unit grew, and the suite grew 12% overall while every gate stayed green. The consumer declared
`[tests] budget` for the four gates that DO file rows and had to write in its own config that the
unit tier has no ceiling and cannot be given one. `verify --plan` shows the same hole from the
other end:

```
  story      make unit                 unknown   [the edit]
  feature    make precommit            123587 ms (PASS)   [the feature]
```

**The story rung — the one an agent runs after every edit, the one a dispatch is supposed to name
with its measured cost — is the one rung that has no number.**

## Ship criterion

`unit.sh`, `parse.sh`, `lint.sh` and `warnings.sh` each export `GDK_GATE_VERDICT` alongside the
verdict they already publish, so the ledger can name the outcome without a second wrapper and the
double-wrap rule stands untouched. A failing run files FAIL, never PASS. `agentic-sdlc check
budget` can then take a ceiling on `unit`, and `verify --plan` prints a number for every rung it
declares.

GitHub #7 (no row) and the `unit` half of #8 (no census): `unit.sh` also exports its test count as
the census `gdk_gate` files on the row (the fifth-argument value the pytest tiers pass as
`SUM_CASES`), so a consumer on agentic-sdlc >= 0.7.0 can declare `[tests] cases` on `unit`.

## Proof budget

  cases: 2
  tier: pyunit against the runner corpus — one that a published PASS files a PASS row, one that a
    published FAIL files FAIL and not PASS
  lands in: `tests/test_runners_installable.py`, beside the existing per-runner corpus cases
  what already covers this: the runners' verdict LINES are covered; nothing asserts that a run
    leaves a ledger row, because the ledger is the other package's file and no case has ever
    looked at it.

## Out of scope

Wrapping the four tiers in `gdk_gate`. That is the fix this feature exists to avoid — the header's
reasoning against it is correct, and one exported variable gets the same result without it.
