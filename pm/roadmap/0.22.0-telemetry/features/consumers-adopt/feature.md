---
id: 0.22.0/consumers-adopt
milestone: "0.22.0"
name: nullbound and trail install the ledger hooks and their next milestone is the baseline
status: planning
reviewed:
phase: 4
depends_on: ["0.22.0/ledger-report"]
consumed_by: []
---

# nullbound and trail install the ledger hooks and their next milestone is the baseline

What it makes true: both consumers run `install-hooks` at the new pin, add the two hook entries to
`.claude/settings.json`, and their next milestone is captured end to end with no hand entry. No
backfill of earlier self-reported numbers (D5): the first captured milestone is the baseline.

## Ship criterion

`pm ledger report <ms>` prints from live capture in both consumers.
