---
id: bg-header-ledger-cannot-hold-a-half-header
kind: bug
milestone: "1.1.1"
name: test_shape header_ledger cannot hold a scenario with covers but no Boots because
status: open
caused_by:
changelog:
---

# header-ledger-cannot-hold-a-half-header

GitHub issue #13.

## Symptom

`[test_shape] header_ledger` holds only scenarios with NO header, and a ledgered file with ANY
header line is `HEADED` (drop it from the ledger). A project whose scenarios already carry
`## covers:`, because the runner's `--diff` slicing needs it, but no `## Boots because:` cannot
ledger any of them: unledgered they fail as half-headed, and ledgered they are "grown a header". So
`header = true` cannot be adopted gradually on exactly the trees that already slice by `covers:`.

## Root cause

`src/godot_devkit/godot/checks/test_shape.py`, in the `rel in header_ledger` branch of the header
roster loop: `has_any_header(body)` decides "ratcheted out", when the ledger's question is "does the
file answer BOTH lines yet".

## Fix

A ledgered scenario is held while it lacks either `Boots because:` or `covers:`, and it is `HEADED`
(ratcheted out, validated, drop the entry) only when both are present. Unledgered behaviour is
unchanged. Update the module docstring and the README row that describe `header_ledger`. Amend the
existing test-shape header-ledger case so it covers a covers-only file (held) and a both-lines file
(HEADED); no new test. CHANGELOG bullet, patch.
