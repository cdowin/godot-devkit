---
id: bg-rename-misses-builtin-scripts-and-nodepaths
kind: bug
milestone: "ms-refs-sees-what-godot-wires"
name: refs --rename misses built-in scripts and NodePaths
status: closed
caused_by: ft-refs-renames-a-symbol
changelog: none
---

# rename-misses-builtin-scripts-and-nodepaths

<!-- `milestone:` is the parent, and it is the only binding — a bug nested in a
     milestone must close before it does. Not committing to it now? `pm remove
     <milestone> bg-rename-misses-builtin-scripts-and-nodepaths` returns it to the pool, where it gates nothing and is
     counted. `caused_by:` (optional) names the one feature whose change made
     it — set with `--caused-by`, or leave it empty rather than invent one. -->

## Symptom

MAJOR (release review M1). A built-in script (`[sub_resource type="GDScript"]` `script/source = "..."`) and a scene `NodePath("/root/<Autoload>")` are never checked: `--rename Jukebox Radio` / `--rename GameState Gs` print "0 blocked", exit 0, and leave the old name there.

## Root cause

refs_rename.py `_plan_scene` (:239-263) only looks at the connection attrs it rewrites.

## Fix

In `_plan_scene`, any `.tscn`/`.tres` line holding `<old>` as a word that is not a rewritten connection attr BLOCKS the plan, named. One test.
