---
id: 0.22.1/bugs/header-rule-census-differs-from-the-runner-roster
milestone: "0.22.1"
name: check test-shape scans git ls-files tests/integration minus infra basenames (160 on nullbound) while integration.sh discovers via find minus
status: open
caught_in: "0.22.1"
fix_milestone:
---

# header-rule-census-differs-from-the-runner-roster

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

MINOR — check test-shape scans git ls-files tests/integration minus infra basenames (160 on nullbound) while integration.sh discovers via find minus */support/* and _capture$ (137) — the opt-in header rule demands Boots-because/covers on 22 *_capture.gd tools and a support stub that --diff can never slice to. One roster, owned by one place, read by both. From the v0.22.0 release review.

## Root cause

## Fix
