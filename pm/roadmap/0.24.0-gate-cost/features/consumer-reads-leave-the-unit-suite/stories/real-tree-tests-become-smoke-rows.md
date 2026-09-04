---
id: 0.24.0/consumer-reads-leave-the-unit-suite/real-tree-tests-become-smoke-rows
feature: 0.24.0/consumer-reads-leave-the-unit-suite
milestone: "0.24.0"
name: the two real-consumer-tree tests move into consumer_smoke.py
status: done
owner:
depends_on: []
---

# the two real-consumer-tree tests move into consumer_smoke.py

Every reader of `available_consumers()` — `test_defaults.ConsumerCorpus`,
`test_check_props.NoFalsePositivesOnRealRepos`, and the consumer-walking cases in
`test_canonicalize`, `test_tscn_roundtrip`, `test_uid_codec` — becomes a `report.check` row inside
`smoke(root, report)` in `tools/consumer_smoke.py`, with the assertion it made (the pinned props
count, deletion-only + idempotent over a copied tree, the round-trip/uid census) and the same
"checkout unchanged" guarantee. `tests/support.available_consumers` and `CONSUMER_REPOS` are deleted
with their last reader.

## Acceptance criteria

- `grep -rn 'available_consumers\|CONSUMER_REPOS' tests/` returns nothing.
- `make smoke` shows the new rows under each consumer; a write verb still runs over a COPY
  (`tempfile`), and the trailing `checkout unchanged` row still passes.
- `make test` passes with no skip line mentioning a consumer; count the tests that left, name them
  in the close block with the seconds they cost (from `--durations`).
- CHANGELOG `## Unreleased` bullet.

## Out of scope

Any change to what those checks assert. The fresh-project probe (it is already smoke).
