---
id: 0.22.0/bugs/boundaries-misses-path-open-mode
milestone: "0.22.0"
name: test_boundaries reads the open() mode from the wrong argument for Path.open, so any p.open('w') in src/ passes the one-writer gate
status: fixed
caught_in: "0.22.0"
fix_milestone:
severity: medium
---
## Symptom

`tests/test_boundaries.py::_is_write_open` takes the mode from `node.args[1]`. That is right for the
builtin `open(path, 'w')` and wrong for `Path.open('w')`, where the mode is `args[0]`. Any
`p.open('w')` or `p.open('a')` anywhere under `src/` therefore passes the "only `core/apply.py`
writes" boundary today. Found 2026-09-03 while building `0.22.0/ledger/S1`, whose `ledger.append_row`
uses `p.open('a')` deliberately (feature decision D1) — named rather than quietly benefited from.

## Root cause

One AST branch: when `node.func` is an `ast.Attribute` named `open`, the mode is the first
positional argument (or the `mode=` keyword), not the second.

## Fix

Read `args[0]` / `mode=` for the attribute form; then add the one sanctioned exception the ledger
decision names — `repo/pm/ledger.py` may open in append mode (`'a'` only, never `'w'`) — with a test
that a `'w'` in `ledger.py` and an `'a'` anywhere else both redden the gate. Mutate it: prove the
gate FAILS on a scratch `p.open('w')` before calling it fixed.
