---
id: 0.22.0/consumers-adopt/nullbound-baseline
feature: 0.22.0/consumers-adopt
milestone: "0.22.0"
name: nullbound installs the ledger and this session's reports are backfilled as the baseline
status: todo
owner:
depends_on: []
---

# nullbound installs the ledger and this session's reports are backfilled as the baseline

## Goal
Nullbound at the pin: `install-hooks --force` (the subagent hook), `pm ledger record` backfill of 2026-09-02's ~30 dispatch rows from the orchestrator's held reports with `notes: baseline (pre-hook, self-reported)`, then `pm ledger report 0.90.3` prints all five sections.
## Commit prefix
`feat(0.22.0/consumers-adopt/S1):`
## Size
s
