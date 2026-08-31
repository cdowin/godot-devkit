---
id: 0.18.0/bugs/canonicalize-writes-before-usage-error
milestone: "0.18.0"
name:
status: open
caught_in: "0.18.0"
fix_milestone:
---

# canonicalize-writes-before-usage-error

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

## Root cause

## Fix

`scene canonicalize good.tscn missing.tscn` writes the good file, then exits 2 on the missing one
— per-file existence check inside the processing loop, so a usage error can follow a write.
Pre-existing; SDLC §5's first customer: decide the whole argv before the first write.
v0.17.0 release review finding 4 (write/scene_canonicalize.py ~236).
