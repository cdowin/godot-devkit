---
id: bg-refs-autoload-bare-uses-missed
kind: bug
milestone: "ms-refs-sees-what-godot-wires"
name: MAJOR refs on an autoload name misses bare and /root uses and reads definition-only
status: open
caused_by: ft-refs-reads-scene-connections
changelog:
---

# refs-autoload-bare-uses-missed

<!-- `milestone:` is the parent, and it is the only binding — a bug nested in a
     milestone must close before it does. Not committing to it now? `pm remove
     <milestone> bg-refs-autoload-bare-uses-missed` returns it to the pool, where it gates nothing and is
     counted. `caused_by:` (optional) names the one feature whose change made
     it — set with `--caused-by`, or leave it empty rather than invent one. -->

## Symptom

`refs GameState` on a project whose script says `var g = GameState`, `if Bus:` or `get_node("/root/Hud")` prints only the `project.godot` definition and no typed or dynamic hit: the definition-only shape is the "unused, delete it" verdict (rule 4). Repro: `[autoload] GameState="*res://s/gs.gd"`, `s/user.gd` with `\tvar g = GameState`; `PYTHONPATH=src python3 -m godot_devkit.cli refs GameState` -> `## definitions (1)` and nothing else (probed).

## Root cause

`_typed_ref_pattern(autoload=True)` (src/godot_devkit/godot/read/refs.py:126) only adds `Name\s*[.),]`; a bare value at end of line, before `:`/`]`/`[`/`==`/`;`, and the `/root/Name` node-path string are not matched by any bucket. The story's criterion lists only `.`/`)`/`,`, so it meets the letter and misses the intent.

## Fix

Match the autoload name as a whole word not preceded by `.` and not followed by `(` or `:=`/`=` declaration (e.g. `(?<![\w.])Name\b(?!\s*\()`) for the typed arm, and add `["']/root/Name\b` (and `$"/root/Name"` / `%`-less node paths) to the dynamic pattern. Amend the existing read_repo fixture case with `var g = Name` and `get_node("/root/Name")`.
