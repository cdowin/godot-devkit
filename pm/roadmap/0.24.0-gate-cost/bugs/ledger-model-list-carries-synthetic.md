---
id: 0.24.0/bugs/ledger-model-list-carries-synthetic
milestone: "0.24.0"
name: "a ledger row's `model` list carries `<synthetic>` from an orchestrator transcript""
status: fixed
caught_in: "0.24.0"
fix_milestone: "0.24.0"
caused_by: 0.23.0/ledger
---

# ledger-model-list-carries-synthetic

## Symptom

v0.23.0 release review n2. A real orchestrator transcript sums to
`model: ["claude-fable-5-1", "<synthetic>"]`.

## Root cause

`src/godot_devkit/repo/pm/ledger.py` (~:318) copies every `message.model` raw — D4-correct (never
interpret) — and Claude Code emits `<synthetic>` on system-generated assistant records.

## Fix

Decide once, in `ledger`'s `decisions.md`: keep raw (and teach a future by-model grouping to skip
the bracketed pseudo-name), or drop `<synthetic>` at record time as a spelling, not a judgement.
Then a test pinning the choice.
