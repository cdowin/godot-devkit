---
id: 0.24.0/consumer-reads-leave-the-unit-suite
milestone: "0.24.0"
name: the tests that read a live consumer checkout are smoke rows, not unit tests
status: planning
reviewed:
phase: 1
depends_on: []
consumed_by: []
---

# the tests that read a live consumer checkout are smoke rows, not unit tests

Five unit modules call `tests/support.available_consumers()` and walk `~/workspace/trail` and
`~/workspace/nullbound` — `test_defaults` (one 12 s test), `test_check_props` (3.4 s), and
`test_canonicalize`, `test_tscn_roundtrip`, `test_uid_codec`. On CI no consumer exists, so they
skip; locally they run on all four interpreters. `tools/consumer_smoke.py` already says it: THE
CONSUMERS ARE THE FIXTURES. When this ships those checks are rows in `make smoke`, run once, and the
unit tier reads nothing outside the repo.

## Existing-construct audit

`consumer_smoke.py` has `smoke(root, report)` with `report.check(name, label, ok, detail)` rows and a
`checkout unchanged` proof — each moved test becomes one row there. `tests/support.CONSUMER_REPOS` +
`available_consumers()` die with their last reader (the last-reader rule); the smoke's own
`CONSUMERS` tuple is the one roster.

## Ship criterion

`grep -rn available_consumers tests/` is empty; `make smoke` prints one new row per moved check with
the same assertion (`test_check_props` pins the finding count; `test_defaults` proves a pure,
idempotent deletion over a COPY — the smoke keeps "checkout unchanged"); `make test` on this machine
drops by the moved tests' sum (~18 s) and never skips for a missing consumer.
