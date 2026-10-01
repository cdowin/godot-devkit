---
id: bg-autoloads-classname-scan-ignores-excludes
kind: bug
milestone: "ms-refs-sees-what-godot-wires"
name: autoloads add class_name scan ignores refs excludes
status: closed
caused_by: ft-project-verb-edits-autoloads
changelog: none
---

# autoloads-classname-scan-ignores-excludes

<!-- `milestone:` is the parent, and it is the only binding — a bug nested in a
     milestone must close before it does. Not committing to it now? `pm remove
     <milestone> bg-autoloads-classname-scan-ignores-excludes` returns it to the pool, where it gates nothing and is
     counted. `caused_by:` (optional) names the one feature whose change made
     it — set with `--caused-by`, or leave it empty rather than invent one. -->

## Symptom

MINOR (release review m1). The class_name clash check walks every `.gd`, ignoring `[refs] exclude_prefixes`: a `class_name Foo` under `.claude/worktrees/` makes `autoloads add Foo …` refuse.

## Root cause

autoloads_edit.py:86 walks the whole tree.

## Fix

Filter the walk with `refs.exclude_prefixes()`. One refusal-table row.
