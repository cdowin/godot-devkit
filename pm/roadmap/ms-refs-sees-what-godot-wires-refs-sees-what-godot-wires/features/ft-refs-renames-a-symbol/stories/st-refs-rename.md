---
id: st-refs-rename
kind: story
feature: ft-refs-renames-a-symbol
milestone: "ms-refs-sees-what-godot-wires"
name: refs --rename
status: done
owner:
depends_on: ["st-refs-indexes-godot-wiring"]
changelog: none
---

# refs --rename

    godot-devkit refs --rename <old> <new> [--tests] [--dry-run]

Renames a `class_name`, method, signal or autoload across `.gd`, `.tscn`, `.tres` and (for an
autoload) `project.godot`, as ONE `core/apply` plan. The hit set is `refs <old>`'s, after
st-refs-indexes-godot-wiring: definitions, typed refs, call/emit sites, scene connections
(`signal=`/`method=` attrs), autoload declaration and uses.

Decided — unlike `--retarget`, which writes the provable hits and SKIPs the rest, a rename is
all or nothing: a stranded old name is a runtime break with no parse error. So:

- any dynamic-bucket hit, any hit inside a string literal or comment on a `.gd` line, or any
  hit whose line also carries `<new>` already → REFUSE the whole plan, exit 1, every blocking
  site named, nothing written;
- `<new>` already defined anywhere (a `class_name`, func, signal or autoload of that name)
  while `<old>` still has hits → refuse, exit 1;
- `<new>` not a valid identifier → exit 2;
- a rewrite replaces only the identifier token at the hit (word-bounded), never the line;
- zero hits of `<old>` and `<new>` defined → `already renamed`, exit 0 (the retry);
- zero hits of `<old>` and `<new>` undefined → exit 1 with the census (nothing to rename).

Files: new `src/godot_devkit/godot/write/refs_rename.py`; in `cli.py` the `refs` branch routes
`--rename` the way it routes `--retarget`, plus a docstring entry beside `--retarget`; README row
after the `refs --retarget` row.

## Acceptance criteria

1. A rename over a temp copy of `tests/fixtures/read_repo/` rewrites every typed hit, including a
   `[connection] method=` and an autoload, and `refs <new>` afterwards finds the same count
   `refs <old>` found before; `refs <old>` then finds none.
2. Each refusal leaves every file byte-identical and names every blocking site.
3. The same rename twice: the second finds zero hits of `<old>` with `<new>` defined, prints
   `already renamed`, exits 0 and touches nothing (rule 3: a retry is a no-op).
4. `--dry-run` prints the diff and writes nothing.
5. A corpus scene with a hit round-trips byte-identical outside the renamed token.

## How this is proven

| criterion | tier | the case that proves it | existing? |
|---|---|---|---|
| 1–5 | unit | new `tests/test_refs_rename.py`, `main(argv)` over temp copies | new: retarget's cases prove paths, not symbols |

## Out of scope

Renaming files or resource paths (`--retarget`); `.gd` member access on an untyped receiver
(dynamic → refusal is the answer). CHANGELOG: report the sentence.
