---
id: 1.1.0/every-config-key-shows-its-shape
milestone: "1.1.0"
name: Every config key shows its own shape in the README
status: done
reviewed: docs/reviews/2026-09-12-1.1.0-every-config-key-shows-its-shape.md
phase:
depends_on: []
consumed_by: []
changelog: The README devkit.toml block shows every key the kit reads, held by a census test.
---


# Every config key shows its own shape in the README

**The finding.** `[unit_disk] forbidden_literals` must be a reason-to-patterns TABLE. The
neighbouring `exclude_prefixes` is a LIST. The README's configuration block shows
`exclude_prefixes` as a list and `forbidden_calls` as a table, and **never shows
`forbidden_literals` at all**; `check unit-disk --help` names the key in prose without its shape.

An adopting consumer wrote `forbidden_literals = ["user://saves/", "user://settings.json"]` — the
obvious reading, matching the list-shaped key three lines above — and got
`[unit_disk] forbidden_literals must be a table, got [...]`. The error is good; it arrives after
the guess, because there was nothing to copy.

This is a small defect with an outsized cost: the README block is the only place a consumer looks
before writing config, and a key that is absent from it will be guessed at.

## Ship criterion

Every key the kit reads appears in the README's `devkit.toml` block with one example of its own
shape, table-valued keys included — a census test walks the config readers and fails on a key
with no example, so the block cannot drift out of date the next time a key is added.

## Proof budget

  cases: 1-2
  tier: pyunit
  lands in: the existing config/README census module
  what already covers this: there is a census test for gates and one for slot names; neither
    relates the set of keys the readers accept to the set the README documents.
