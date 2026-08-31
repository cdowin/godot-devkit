---
id: 0.18.0/bugs/defaults-tracked-but-deleted
milestone: "0.18.0"
name:
status: open
caught_in: "0.18.0"
fix_milestone:
---

# defaults-tracked-but-deleted

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

## Root cause

## Fix

check defaults still raises FileNotFoundError on a tracked-but-deleted resource (reads via
format/tscn.py:186) — the drift class 0.17.0 fixed in uid/tres/props. Loud crash, never false
PASS; opt-in gate outside `check all` stock. Mirror the UNVERIFIED skip bucket. v0.17.0 release
review finding 3.
