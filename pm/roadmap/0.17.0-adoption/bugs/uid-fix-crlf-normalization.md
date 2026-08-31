---
id: 0.17.0/bugs/uid-fix-crlf-normalization
milestone: "0.17.0"
name:
status: fixed
caught_in: "0.17.0"
fix_milestone:
---

# uid-fix-crlf-normalization

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

## Root cause

## Fix

`check uid --fix` reads via universal-newline `read_text` and writes via `apply.write_translated`
(newline=None), so on a CRLF/mixed-endings `.tres` a fix rewrites EVERY line ending — contradicting
the module's "byte-surgical: only the uid= attribute on the reported line changes" claim. Zero
real-world exposure today (neither consumer has any CRLF resource, measured), but the invariant is
false for the cross-platform case. Fix: route `_apply` through `read_scene_text` + `apply.write`
(newline='') like the write verbs. Found by the v0.16.0 release review (finding 3).
