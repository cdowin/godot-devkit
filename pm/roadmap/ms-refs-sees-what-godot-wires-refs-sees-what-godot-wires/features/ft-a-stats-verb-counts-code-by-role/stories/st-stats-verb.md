---
id: st-stats-verb
kind: story
feature: ft-a-stats-verb-counts-code-by-role
milestone: "ms-refs-sees-what-godot-wires"
name: the stats verb
status: done
owner:
depends_on: []
changelog: none
---

# the stats verb

Issue #18 is the ask. `godot-devkit stats [<dir>...] [--by dir] [--json]` answers "how much code
is in this project, and where", over git-known files (tracked + untracked-not-ignored, the set
`orphans` scans), enumerated through `core/walk.py` — the one enumerator.

Default output, one row per bucket: `bucket  files  lines  code`, then a census line naming
the files scanned and the dirs. Buckets: `game .gd`, `tests .gd`, `tools .gd`,
`vendored .gd`, `.gdshader`, `.tscn`, `.tres`. Code lines (`.gd`, `.gdshader`) are non-blank and
not a comment line (`#` for .gd, `//` for shaders; a `"""` docstring block counts as comment);
`.tscn`/`.tres` have no code column. Under `tests .gd`, one indented row per immediate subdir of
each tests prefix (`unit`, `integration`, …) with a `func test_` count.

Roles come from a new `[stats]` section, every key through `core/config.py`'s `str_tuple`:
`tests = ["tests/"]`, `tools = ["tools/"]`, `vendored = ["addons/"]`; anything else is game. A
consumer moves its own addon out of `vendored` by listing only the vendored ones. Same defaults
with or without a devkit.toml, byte-identical (rule 5).

`--by dir` adds, for the game bucket, one row per top-level dir. `--json` prints the same
numbers as one object. Zero files scanned → census line, exit 1 (rule 4); else exit 0. A bad
`[stats]` value exits 2.

Files: new `src/godot_devkit/godot/read/stats.py`; in `src/godot_devkit/cli.py` a `stats` branch
after `autoloads`, and one docstring line under Introspection after `autoloads`; one README row
after the `autoloads` row (~line 144) and a `[stats]` block beside the `[orphans]` one (~line 274).

## Acceptance criteria

1. Over a temp tree with known files, each bucket's files/lines/code equal hand-counted values.
2. A path under `vendored`, `tests` or `tools` lands in that bucket and nowhere else.
3. `func test_` count and the per-tier rows match the temp tree.
4. `--json` carries the same numbers as the table.
5. An empty tree exits 1 with census 0; `[stats] tests = "tests/"` (a bare string) exits 2.

## How this is proven

| criterion | tier | the case that proves it | existing? |
|---|---|---|---|
| 1–5 | unit | new `tests/test_stats.py`, `main(argv)` over a temp git tree | new: no verb counts lines today |

## Out of scope

Node/sub-resource counts per scene (the issue's bonus); complexity, churn, history. Never name a
consuming project in code, docs or tests (rule 8). CHANGELOG: report the sentence. Do not touch
`read/refs.py` or the `autoloads` branch of `cli.py` (other lanes).
