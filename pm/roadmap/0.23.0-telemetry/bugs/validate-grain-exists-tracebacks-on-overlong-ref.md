---
id: 0.23.0/bugs/validate-grain-exists-tracebacks-on-overlong-ref
milestone: "0.23.0"
name: validate._grain_exists raises OSError from Path.is_dir on an over-long hand-typed depends_on entry (3.11–3.13) and answers False on 3.14
status: open
caught_in: "0.23.0"
fix_milestone:
caused_by:
severity: low
---

## Symptom

A `depends_on:` entry long enough to exceed the filesystem's name limit makes `pm validate` traceback
on Python 3.11–3.13 (`OSError` out of `Path.is_dir()`) and quietly answer "does not exist" on 3.14.
The same split is what `cli._exists` was written to close for the write verbs. Found 2026-09-03
while building `0.23.0/review-record-shape/S2`, whose own `_feature_exists` is guarded; the twin in
`validate.py` (`_grain_exists`, ~line 87) is not.

## Root cause

`_grain_exists` calls `Path.is_dir()` / `Path.is_file()` on an unchecked, possibly over-long path.

## Fix

Route it through the same guarded existence helper `cli._exists` uses (or move that helper into
`model.py` and call it from both), with a test that an over-long entry reports as a dangling ref on
every supported Python rather than crashing or passing.
