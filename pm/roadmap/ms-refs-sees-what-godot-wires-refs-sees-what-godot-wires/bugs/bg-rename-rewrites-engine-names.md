---
id: bg-rename-rewrites-engine-names
kind: bug
milestone: "ms-refs-sees-what-godot-wires"
name: refs --rename rewrites engine methods and signals
status: open
caused_by: ft-refs-renames-a-symbol
changelog:
---

# rename-rewrites-engine-names

<!-- `milestone:` is the parent, and it is the only binding — a bug nested in a
     milestone must close before it does. Not committing to it now? `pm remove
     <milestone> bg-rename-rewrites-engine-names` returns it to the pool, where it gates nothing and is
     counted. `caused_by:` (optional) names the one feature whose change made
     it — set with `--caused-by`, or leave it empty rather than invent one. -->

## Symptom

BLOCKER (2.1.0 release review B1, rule 4 write side). `refs --rename` writes a legitimate-looking wrong diff, exit 0, when `<old>` is also an engine method or signal. Repros: (1) `func play()` + `sfx.play()` on an AudioStreamPlayer + `$Anim.play()` → `--rename play play_track` rewrites all three, "0 blocked". (2) `signal pressed` in card.gd + a Button `[connection signal="pressed" from="Btn"]` in menu.tscn → `--rename pressed clicked` rewrites the Button's connection; the button goes dead. (3) `--rename _ready _ready2` rewrites `func _ready(` though the module docstring (:23-24) says it refuses.

## Root cause

refs_rename.py:212, :239-263 trust `refs.typed_spans`, which matches `.old(` on any receiver and every `[connection]` attr; the only engine guard is "defined nowhere" (:366).

## Fix

Vendor engine METHOD and SIGNAL names into `data/classdb.json` (regenerate with tools/gen_classdb.py from Godot 4.6.2's `--dump-extension-api`; additive keys). Then REFUSE when `<old>` or `<new>` is an engine method or signal name on any class (the name is ambiguous without types). One test per repro.
