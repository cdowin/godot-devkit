---
id: {id}
milestone: "{milestone}"
name:
status: open
caught_in: "{milestone}"
fix_milestone:
caused_by:
---

# {slug}

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it.

     `caused_by:` is OPTIONAL and holds one feature id: the CLOSED feature
     whose change produced this bug. `caught_in:` says which milestone FOUND
     it; `caused_by:` says which feature MADE it — different facts, and an
     escape needs both. Set it at scaffold time with `pm new bug <milestone>
     <slug> --caused-by <feature-id>`, or later with `pm set`; `pm validate`
     resolves it the way it resolves `depends_on`. Leave it empty when the
     cause is unknown — an invented attribution is worse than none. -->

## Symptom

## Root cause

## Fix
