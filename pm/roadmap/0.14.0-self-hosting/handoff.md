Cold-start only. Never restate what `pm status` computes.

# 0.14.0 self hosting — handoff

## 1. Where the work lives

| | |
|---|---|
| **Branch** | `main`. This package has no integration branch — it ships from the trunk, which is why D10 skips it and D8 does not apply. |
| **Version** | `0.13.0` until the release commit. The version is bumped at CLOSE here, not at start. |
| **Tree** | `~/workspace/godot-devkit`, single checkout. `uv.lock` is untracked build residue — never stage it. |

## 2. Where to pick up

Everything in `check all` and `check pm` is green. The next action is the
release itself: `/release`, which now renders the CHANGELOG section rather than
asking anyone to write one.

## 3. Traps this milestone has already sprung

- `[uid] exclude_prefixes` scoped only CHECK 1. Excluding the fixture tree
  looked like it worked and CHECK 2 kept reporting every `.gd` in it. One
  documented key must scope the whole gate.
- Excluding the fixtures leaves the Godot-family gates with a 0-file census,
  which rule 4 reddens — correctly. `check all` is green because `[checks] all`
  names the gates that apply here, NOT because any gate was softened.
- `story_file` globbed one directory while `story_files` walked recursively, so
  `check pm` could report a story that `pm story wip` then said did not exist.
  Two functions answering the same question need one implementation.
