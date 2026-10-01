---
id: st-refs-indexes-godot-wiring
kind: story
feature: ft-refs-reads-scene-connections
milestone: "ms-refs-sees-what-godot-wires"
name: refs indexes what Godot wires
status: building
owner:
depends_on: []
changelog:
---

# refs indexes what Godot wires

`refs <symbol>` lists every place Godot itself wires the symbol, so a handler connected in the
editor, an autoload used by name, or a signal named as an argument never reads as unreferenced.
All in `src/godot_devkit/godot/read/refs.py`; the README `refs` row (line ~142) says so.

1. **Scene connections.** `scan_scene_refs` also walks `[connection]` sections (already parsed by
   `format/tscn.py`). A symbol equal to the `signal=` or `method=` attr is a hit in a new typed
   bucket, label `scene connections`, line text
   `[connection] signal=<s> from=<f> to=<t> method=<m>`. Typed, not dynamic: the scene names it
   exactly.
2. **Autoload names.** A name declared in `project.godot`'s `[autoload]` (use
   `read.autoloads.list_autoloads`, do not parse the file again) is indexed like a `class_name`:
   the `project.godot` line is its definition, and `Name.` / `Name)` / `Name,` uses in `.gd` are
   typed refs in the bucket a `class_name` use lands in. No `project.godot` → no autoload arm,
   no error (refs works in a non-Godot dir today; keep that).
3. **Named as an argument.** `is_connected("sig"`, `has_signal("sig"`, `has_user_signal("sig"`
   and `Signal(<expr>, "sig"` go to the dynamic bucket (string spellings). A bare identifier as
   the callable argument of `is_connected(…, name)` / `disconnect(…, name)` goes where
   `.connect(name` goes today.

## Acceptance criteria

1. A handler wired only by a `[connection]` shows under `scene connections`; the zero verdict
   does not print.
2. `refs <Autoload>` lists the `project.godot` definition and each `.gd` use; exit 0.
3. Each spelling in 3 lands in its named bucket.
4. A symbol with no reference still prints `(no references found)`.
5. `refs --retarget` output on its existing cases is byte-unchanged.

## How this is proven

| criterion | tier | the case that proves it | existing? |
|---|---|---|---|
| 1–4 | unit | `tests/test_read_verbs.py` refs cases over `tests/fixtures/read_repo/`: add one `[connection]`, one autoload use, the three argument spellings to the fixture; one case per criterion | amend |
| 5 | unit | `tests/test_refs_retarget.py` as it stands | yes |

## Out of scope

`refs --rename` (st- under ft-refs-renames-a-symbol, next batch) builds on these buckets. No
CHANGELOG edit — report the sentence; the integrator writes it. No `cli.py` change.
