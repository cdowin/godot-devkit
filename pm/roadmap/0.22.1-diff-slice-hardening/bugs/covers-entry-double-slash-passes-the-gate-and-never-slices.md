---
id: 0.22.1/bugs/covers-entry-double-slash-passes-the-gate-and-never-slices
milestone: "0.22.1"
name: check test-shape normalizes a covers entry with rstrip('/') while integration.sh strips ONE trailing slash
status: open
caught_in: "0.22.1"
fix_milestone:
---

# covers-entry-double-slash-passes-the-gate-and-never-slices

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

MINOR — check test-shape normalizes a covers entry with rstrip('/') while integration.sh strips ONE trailing slash — systems/alpha// passes the gate (exists) and never selects in the runner (covered() indexes the doubled form). One normalization, shared or identical, in both. From the v0.22.0 release review.

## Root cause

## Fix
