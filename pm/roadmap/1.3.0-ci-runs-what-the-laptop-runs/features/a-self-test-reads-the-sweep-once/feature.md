---
id: 1.3.0/a-self-test-reads-the-sweep-once
milestone: "1.3.0"
name: a self-test reads the sweep once
status: building
reviewed:
phase:
depends_on: []
consumed_by: []
changelog: integration.sh --self-test reads the sweep once and matches it with no pipe, so a keep-listed gate is no longer reported missing on Linux; warnings.sh gets the same fix (#27).
---

# a self-test reads the sweep once

Issues: #27.

`integration.sh` runs `set -uo pipefail`. In `self_test`, `discover_all | grep -qx "$name"`: grep
exits on the match, `discover_all`'s `sort` takes SIGPIPE, the pipeline returns non-zero, and the
case MISSES on a gate that is in the sweep. macOS passes (the list fits the pipe buffer first);
the Linux runner fails 3 of 105. nullbound carries the consumer fix on #75.

## Decided (do not re-plan)

- `src/godot_devkit/godot/installables/integration.sh`: before the keep-list loop,
  `local swept; swept="$(discover_all)"`; in the loop, `grep -qxF -- "$name" <<<"$swept"`. Keep a
  two-line comment saying why (pipefail + early grep exit = SIGPIPE on Linux).
- `warnings.sh:164`: `promotion_block | grep -qxF "$PROMOTION_SECTION"` gets the same shape:
  capture once, match with a here-string.
- Leave the `printf … | grep -q` sites: one write, not seen to fail.

## Ship criterion

- The keep-list cases pass when `grep -q` exits before the producer finishes. A corpus row forces
  it: a `discover_all` stub that prints the name first and then more lines than a pipe buffer holds.
- `bash integration.sh --self-test` and `bash warnings.sh --self-test` pass.

## Proof budget

  cases: 1 corpus row in integration.sh's own --self-test
  tier: the runner's --self-test (replayed by runners-self-test)
  lands in: src/godot_devkit/godot/installables/integration.sh
  what already covers this: the keep-list loop; nothing forces the early exit.
