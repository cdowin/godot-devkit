---
id: 0.18.0/bugs/lone-cr-skew-wrong-line
milestone: "0.18.0"
name:
status: open
caught_in: "0.18.0"
fix_milestone:
---

# lone-cr-skew-wrong-line

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

## Root cause

## Fix

uid --fix's lone-CR out-of-range guard handles the skewed-out-of-range case, but a lone CR BEFORE
the target can yield a skewed-but-in-range index whose raw line holds the same stale needle (two
Script refs sharing one stale uid) — the wrong line gets the repair. The next scan re-reports it,
so the gate never greens over it. Harden: match rewrites by needle-within-file, not translated
index. v0.17.0 release review finding 1 (checks/uid.py ~255).
