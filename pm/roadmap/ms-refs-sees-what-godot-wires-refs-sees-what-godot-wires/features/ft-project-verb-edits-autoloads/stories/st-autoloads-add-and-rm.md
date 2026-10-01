---
id: st-autoloads-add-and-rm
kind: story
feature: ft-project-verb-edits-autoloads
milestone: "ms-refs-sees-what-godot-wires"
name: autoloads add and rm
status: done
owner:
depends_on: []
changelog:
---

# autoloads add and rm

Decided: the write verbs share the read verb's noun, the way `scene` and `tiles` do — not a new
`project` command. `autoloads` with no subverb stays the census.

    godot-devkit autoloads add <Name> <res://path> [--dry-run]
    godot-devkit autoloads rm  <Name>              [--dry-run]

`add` appends `Name="*res://path"` (the `*` = enabled singleton, what the editor writes) as the
last line of `[autoload]` in `project.godot`, creating the section at the end of the file when
absent. `rm` deletes that one line, and the section header too only when it was the last entry.
Every other byte is kept. Writes go through `core/apply` with `write/__init__.py`'s
`render_diff` for `--dry-run`, as `scene_edit.py` does.

Refusals (exit 1, nothing written, reason named): `add` a name already declared (same path:
no-op exit 0 — idempotent); `add` a path whose file does not exist; `add` a name that is not a
valid identifier; `rm` a name not declared (no-op exit 0 — idempotent, says so); a
`project.godot` that is not UTF-8 or not found (exit 2).

Files: new `src/godot_devkit/godot/write/autoloads_edit.py` (VERBS + main(argv)); in
`src/godot_devkit/cli.py` the `autoloads` branch routes `rest[0] in autoloads_edit.VERBS` to it
(the `tiles` branch is the pattern) plus two lines in the module docstring under "Scene
surgery"; one README row after the `refs --retarget` row (~line 160).

## Acceptance criteria

1. `add` then `autoloads` (read) lists the new entry; the file diff is exactly one line (plus a
   section header when it was absent).
2. `rm` removes exactly that line; `add` then `rm` restores the file byte-identically.
3. Each refusal above leaves the file byte-identical and exits as stated.
4. The same `add` or `rm` twice: the second is a no-op, exit 0.
5. `--dry-run` prints the diff and writes nothing.

## How this is proven

| criterion | tier | the case that proves it | existing? |
|---|---|---|---|
| 1–5 | unit | new `tests/test_autoloads_edit.py`, `main(argv)` calls over a temp copy of `tests/fixtures/read_repo/` — never the fixture in place | new: no write-verb test covers project.godot |

## Out of scope

Other `project.godot` sections; reordering autoloads; CHANGELOG (report the sentence). Do not
touch `read/refs.py` (another lane).
