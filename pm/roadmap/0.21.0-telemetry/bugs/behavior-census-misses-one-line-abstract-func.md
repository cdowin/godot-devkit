---
id: 0.21.0/bugs/behavior-census-misses-one-line-abstract-func
milestone: "0.21.0"
name: The behavior census regex cannot see `@abstract func x()` written on one line
status: open
caught_in: "0.21.0"
fix_milestone: "0.21.0"
---

# behavior-census-misses-one-line-abstract-func

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

Godot 4.5+ allows `@abstract func run(entity) -> void` on one line. The devkit's behavior census
(`_FUNC_RE`, the regex that lists a base's hooks for the generated catalog) matches only a line
that STARTS with `func`, so a hook annotated inline silently drops out of the catalog. Found
2026-09-02 marking nine bases abstract in a consumer; the workaround was to put `@abstract` on its
own line above every hook.

## Root cause

`_FUNC_RE` anchors on `^\s*func`; it needs to admit `^\s*(@abstract\s+)?(static\s+)?func`. One fixture with both spellings; the catalog must list the hook either way.

## Fix
