---
id: bg-stats-prefix-not-path-aware
kind: bug
milestone: "ms-refs-sees-what-godot-wires"
name: MINOR stats prefixes match by string so tests matches testsuite
status: closed
caused_by: ft-a-stats-verb-counts-code-by-role
changelog: none
---

# stats-prefix-not-path-aware

<!-- `milestone:` is the parent, and it is the only binding — a bug nested in a
     milestone must close before it does. Not committing to it now? `pm remove
     <milestone> bg-stats-prefix-not-path-aware` returns it to the pool, where it gates nothing and is
     counted. `caused_by:` (optional) names the one feature whose change made
     it — set with `--caused-by`, or leave it empty rather than invent one. -->

## Symptom

With `[stats] tests = ["tests"]` (no trailing slash, accepted by config) `testsuite/x.gd` is counted as tests and labelled `tests/uite/`. Repro (probed): scratch git repo with `tests/unit/t.gd` and `testsuite/x.gd`, that devkit.toml, `godot-devkit stats` -> rows `tests/uite/ 1` and `tests/unit/ 1`.

## Root cause

src/godot_devkit/godot/read/stats.py `_under` uses `rel.startswith(prefix)`; `_subdir_label` then slices the prefix off mid-name.

## Fix

Normalise every configured prefix to end with `/` in `load_settings` (or match `rel == p or rel.startswith(p.rstrip('/') + '/')`). Amend test_stats' config case with a slashless value.
