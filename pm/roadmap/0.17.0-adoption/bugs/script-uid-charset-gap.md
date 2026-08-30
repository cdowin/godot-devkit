---
id: 0.17.0/bugs/script-uid-charset-gap
milestone: "0.17.0"
name:
status: open
caught_in: "0.17.0"
fix_milestone:
---

# script-uid-charset-gap

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

## Root cause

## Fix

A Script ext_resource whose uid text holds a character outside [0-9a-z] (e.g. `uid://INVALIDUPPER`)
fails CHECK 1's strict UID_ATTR regex and is treated as a path-only ref; CHECK 5 exempts Script
refs; `check tres` sees a uid= attr present and passes. A hand-corrupted Script uid spelling is
invisible to all three gates. Godot never emits such spellings — hand-edit-only drift class.
Fix: census Script refs with the permissive UID_ANY_ATTR and report undecodable ones as INVALID,
mirroring CHECK 5. Found by the v0.16.0 release review (finding 4).
