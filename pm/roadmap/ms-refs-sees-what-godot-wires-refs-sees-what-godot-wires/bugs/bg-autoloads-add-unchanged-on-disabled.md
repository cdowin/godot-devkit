---
id: bg-autoloads-add-unchanged-on-disabled
kind: bug
milestone: "ms-refs-sees-what-godot-wires"
name: MINOR autoloads add reports unchanged over a disabled entry and accepts names the editor refuses
status: open
caused_by: ft-project-verb-edits-autoloads
changelog:
---

# autoloads-add-unchanged-on-disabled

<!-- `milestone:` is the parent, and it is the only binding — a bug nested in a
     milestone must close before it does. Not committing to it now? `pm remove
     <milestone> bg-autoloads-add-unchanged-on-disabled` returns it to the pool, where it gates nothing and is
     counted. `caused_by:` (optional) names the one feature whose change made
     it — set with `--caused-by`, or leave it empty rather than invent one. -->

## Symptom

(a) `autoloads add A res://s/a.gd` over `A="res://s/a.gd"` (no `*`, global variable off) exits 0 `unchanged (already declared)`, though the user asked for an enabled singleton and `A.` still fails to resolve in scripts. (b) `add` writes a name the editor refuses: one colliding with a `class_name` or an engine class/singleton (`Input`, `Node`) passes the ASCII-identifier check; and `res://s//a.gd` is written un-normalised, so a later `add A res://s/a.gd` refuses as a "different path" for the same file. All probed except the class_name collision (read).

## Root cause

src/godot_devkit/godot/write/autoloads_edit.py: `_declared_path` strips `*` before comparing (line ~62), so enabled-ness is lost; `_check_name` is regex-only; `_check_path` does not normalise.

## Fix

(a) refuse (or say `declared disabled`, exit 1) when the existing value lacks `*`; never print `unchanged` over a state that is not what was asked. (b) refuse a name that `refs`' class_name index already holds, and normalise `res://` paths with PurePosixPath before writing/comparing.
