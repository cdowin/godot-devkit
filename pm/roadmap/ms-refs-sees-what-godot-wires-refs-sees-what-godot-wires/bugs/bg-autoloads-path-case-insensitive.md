---
id: bg-autoloads-path-case-insensitive
kind: bug
milestone: "ms-refs-sees-what-godot-wires"
name: autoloads add accepts a wrong-case path on macOS
status: open
caused_by: ft-project-verb-edits-autoloads
changelog:
---

# autoloads-path-case-insensitive

<!-- `milestone:` is the parent, and it is the only binding — a bug nested in a
     milestone must close before it does. Not committing to it now? `pm remove
     <milestone> bg-autoloads-path-case-insensitive` returns it to the pool, where it gates nothing and is
     counted. `caused_by:` (optional) names the one feature whose change made
     it — set with `--caused-by`, or leave it empty rather than invent one. -->

## Symptom

MINOR (release review m2). On a case-insensitive filesystem `autoloads add GM2 res://a/other.gd` is accepted when the file is `a/Other.gd`; a case-sensitive export then fails.

## Root cause

autoloads_edit.py:111 `file_exists` follows the filesystem's case rules.

## Fix

Check each path component against the real directory listing (exact case); refuse naming the on-disk spelling. One test (passes on any FS).
