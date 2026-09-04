---
id: 0.23.0/bugs/covers-entry-double-slash-passes-the-gate-and-never-slices
milestone: "0.23.0"
name: check test-shape normalizes a covers entry with rstrip('/') while integration.sh strips ONE trailing slash
status: fixed
caught_in: "0.22.1"
fix_milestone: "0.23.0"
---

# covers-entry-double-slash-passes-the-gate-and-never-slices

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

MINOR — check test-shape normalizes a covers entry with rstrip('/') while integration.sh strips ONE trailing slash — systems/alpha// passes the gate (exists) and never selects in the runner (covered() indexes the doubled form). One normalization, shared or identical, in both. From the v0.22.0 release review.

## Root cause

Two normalisations of one declaration. The gate's `read_header` did `rstrip('/')` and `header_defects` tested existence through `Path(root / entry)`, which collapses `//` — so `systems/alpha//` and `systems//alpha` were both a directory that exists. The runner's `scenario_covers` drops ONE slash (`${entry%/}`) and `covered()` compares strings, so the same entry was `systems/alpha/` or `systems//alpha`, a prefix of no path git names. Declared, never selected, never reported.

## Fix

fixed: c5564ee — one grammar, entry for entry: exactly one trailing slash is spelling (dropped by the reader on both sides, `_one_trailing_slash_dropped` / `${entry%/}`), and a slash with nothing after it is an empty segment refused as `carries an empty segment (a doubled slash)` by both `covers_entry_defect`s. Refuse rather than normalise-all: the gate's job is to make the declaration say what the runner reads, and a normalisation the runner does not share is this bug again. In the runner a scenario whose only entry is refused now reads as UNDECLARED and is reported. Red first: 2 matrix rows, 4 corpus MISSes (87 → 91), 1 e2e case.
