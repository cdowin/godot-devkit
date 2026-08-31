---
id: 0.17.0/bugs/absolute-milestone-id-crash
milestone: "0.17.0"
name:
status: closed
caught_in: "0.17.0"
fix_milestone:
---

# absolute-milestone-id-crash

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

## Root cause

## Fix

`pm milestone ready /etc/hosts` (any absolute milestone id) raises
`NotImplementedError: Non-relative patterns are unsupported` from `Path.glob` in
`model.milestone_dir` — a traceback where exit 2 belongs. Found and pinned by
tests/test_fuzz_inputs.py.
