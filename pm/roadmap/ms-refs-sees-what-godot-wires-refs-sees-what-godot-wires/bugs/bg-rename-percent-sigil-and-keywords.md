---
id: bg-rename-percent-sigil-and-keywords
kind: bug
milestone: "ms-refs-sees-what-godot-wires"
name: refs --rename treats a modulo as a node sigil and accepts keywords
status: open
caused_by: ft-refs-renames-a-symbol
changelog:
---

# rename-percent-sigil-and-keywords

<!-- `milestone:` is the parent, and it is the only binding — a bug nested in a
     milestone must close before it does. Not committing to it now? `pm remove
     <milestone> bg-rename-percent-sigil-and-keywords` returns it to the pool, where it gates nothing and is
     counted. `caused_by:` (optional) names the one feature whose change made
     it — set with `--caused-by`, or leave it empty rather than invent one. -->

## Symptom

NIT (release review n1). `%` directly before the name is taken as a unique-node sigil, so `10%Player.MAX` is neither rewritten nor blocked; `<new>` is not checked against GDScript keywords (`var`, `self`).

## Root cause

refs_rename.py:225 and refs.py:135 treat any `%` before the token as a sigil.

## Fix

A `%` sigil only when it starts an expression (preceded by start, whitespace, `(`, `,`, `=` or an operator other than an operand); refuse a `<new>` that is a GDScript keyword (exit 2).
