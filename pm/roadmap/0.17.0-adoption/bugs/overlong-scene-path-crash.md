---
id: 0.17.0/bugs/overlong-scene-path-crash
milestone: "0.17.0"
name:
status: fixed
caught_in: "0.17.0"
fix_milestone:
---

# overlong-scene-path-crash

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

## Root cause

## Fix

`scene set <300-char-name>.tscn . text '"x"'` raises raw OSError ENAMETOOLONG — the scene plane
lacks the `_exists` guard pm/cli.py grew for exactly this. Applies across scene verbs. Found and
pinned by tests/test_fuzz_inputs.py.
