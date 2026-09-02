---
id: 0.21.0/consumers-adopt
milestone: "0.21.0"
name: nullbound and trail install the ledger and this session's numbers are the baseline
status: planning
reviewed:
phase: 4
depends_on: ["0.21.0/ledger-report"]
consumed_by: []
---

# nullbound and trail install the ledger and this session's numbers are the baseline

What it makes true: both consumers run the ledger. Nullbound backfills 2026-09-02's dispatches
from the agent reports the orchestrator holds (tokens / tool calls / duration / grain / verdict for
~30 rows across `derivation-*`, `resist-derivation-convergence`, `damage-producer`,
`impulse-behavior-consolidation`, the 0.90.4 POs, and the devkit 0.19.0/0.20.0 work) as the
BASELINE the before/after is read against; trail's first milestone reports from a hook-captured
ledger with no hand entry.

## Ship criterion

`pm ledger report 0.90.3` prints the five questions with the backfilled baseline marked as such;
trail's report prints from live capture.
