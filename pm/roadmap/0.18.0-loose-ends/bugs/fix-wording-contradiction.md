---
id: 0.18.0/bugs/fix-wording-contradiction
milestone: "0.18.0"
name:
status: open
caught_in: "0.18.0"
fix_milestone:
---

# fix-wording-contradiction

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

## Root cause

## Fix

A lone-CR-only tree prints `DRIFT ... should be X` and `FIX — nothing to repair; no fixable uid
drift found` in one run: `fixable` judged by the scan, `repaired` by the write. Exit 1 preserved —
wording lie only. v0.17.0 release review finding 2 (checks/uid.py ~426).
