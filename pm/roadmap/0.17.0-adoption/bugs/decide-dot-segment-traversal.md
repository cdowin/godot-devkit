---
id: 0.17.0/bugs/decide-dot-segment-traversal
milestone: "0.17.0"
name:
status: closed
caught_in: "0.17.0"
fix_milestone:
---

# decide-dot-segment-traversal

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

## Root cause

## Fix

`pm decide '0.1/..' t` exits 0 and writes the MILESTONE's decisions.md via `features/..`;
`pm decide '0.1/.' t` mints `features/decisions.md` — a slot the schema doesn't have.
`feature_dir` joins the slug unguarded (only `id_is_literal`'s glob check runs). Same class as
the v0.16.0 release blocker, one resolver over. Found and pinned by tests/test_fuzz_inputs.py —
the pin fails loudly on fix, instructing deletion of pin + carve-out flag.
