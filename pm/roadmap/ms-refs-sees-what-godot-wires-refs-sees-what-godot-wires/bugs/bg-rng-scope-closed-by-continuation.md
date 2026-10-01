---
id: bg-rng-scope-closed-by-continuation
kind: bug
milestone: "ms-refs-sees-what-godot-wires"
name: MINOR rng shadow scope closes on a column-0 bracket continuation and hides a draw
status: closed
caused_by: ft-the-1-4-0-carry-forwards
changelog: none
---

# rng-scope-closed-by-continuation

<!-- `milestone:` is the parent, and it is the only binding — a bug nested in a
     milestone must close before it does. Not committing to it now? `pm remove
     <milestone> bg-rng-scope-closed-by-continuation` returns it to the pool, where it gates nothing and is
     counted. `caused_by:` (optional) names the one feature whose change made
     it — set with `--caused-by`, or leave it empty rather than invent one. -->

## Symptom

In a script that declares `func randf()` at column 0, an inner class whose body holds a bracket continuation at column 0 (`\tvar table = [` / `1, 2,` / `]`, legal GDScript) has its scope closed by that line; a later inner `return randf()` (the GLOBAL draw, inner classes do not inherit outer methods) is attributed to scope 0, stripped as a shadowed call, and `check rng` passes over it. Probed: s/a.gd line 11 unreported while the same draw in s/b.gd (no shadow) is BARE-RNG.

## Root cause

src/godot_devkit/godot/checks/rng.py `_scopes` pops the class stack on any code line at or left of the header indent, without tracking open brackets/strings.

## Fix

Track bracket depth (and multi-line strings) in `_scopes` and skip the pop while depth > 0. One case in tests/test_check_rng.py.
