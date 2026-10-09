# godot-devkit

**godot-devkit** is scene tooling and eight static gates for Godot 4.x projects, shipped as a
**pinned-tag, stdlib-only** Python package. It reads `.tscn`/`.tres` files without loading them,
edits them without reformatting them, and gates the silent-failure classes Godot drops without a
word — renamed exports, uid drift, path-only refs. Nothing here boots Godot: every verb is pure text
parsing, safe anywhere, anytime, in parallel.

> **Any change you can make to a scene by hand, you should be able to make through one
> deterministic command that touches nothing else — and prove it, without ever reading the file.**

For a human, the editor stops being mandatory for mechanical work and diffs stay reviewable. For an
LLM: a small stable vocabulary of verbs instead of a bespoke `sed`; determinism, because a tool that
reformats what it was not asked to touch hides its damage inside a legitimate diff; and token
reduction, because a tile-heavy scene costs 100k+ tokens to read where `scene` costs a few hundred
and a write verb costs zero. The commitments: **refuse rather than mangle** (the worst outcome is
never an error, it is silent partial success); **read output is write input**; **idempotence**,
because models retry; **bounded blast radius**; and **`scene-diff`**, so an edit is provable
without re-reading the file.

Docs: https://github.com/cdowin/godot-devkit/wiki (verbs, gates, configuration, CI recipes, migration from 2.x).

## Install

```sh
uv add --dev godot-devkit==X.Y.Z --index cdowin=https://cdowin.github.io/godot-devkit/simple/
# then add `explicit = true` to the [[tool.uv.index]] table `uv add` wrote
uv run godot-devkit install-gates     # Makefile.gates + tools/dev/gdk_gate.sh
uv run godot-devkit install-runners   # Makefile.tiers + the runners
```

Pin it and read the rest: [Installing and pinning](https://github.com/cdowin/godot-devkit/wiki/Installing-and-pinning).

## Quickstart

```sh
godot-devkit scene scenes/world/hub.tscn                  # node tree, ext_resources, a few hundred tokens
godot-devkit scene set scenes/world/hub.tscn Player/Camera zoom "Vector2(2, 2)"
godot-devkit scene-diff scenes/world/hub.tscn --git HEAD  # the one line that changed, and nothing else
godot-devkit check all                                    # the eight gates, one census and verdict each
```

Every write verb takes `--dry-run` and is idempotent. More: [Quickstart](https://github.com/cdowin/godot-devkit/wiki/Quickstart), [Verb reference](https://github.com/cdowin/godot-devkit/wiki/Verb-reference).

## Pattern rules

A project can forbid its own code patterns. The devkit ships no rule. Declare rules in `godot-devkit.toml`, then name `patterns` in `[roster] checks` or run `godot-devkit check patterns`.

```toml
[[patterns.rule]]
id = "no-print"                  # letters, digits, _ and -
regex = "\\bprint\\("            # Python regex, matched per line
paths = ["src/**/*.gd"]          # globs over tracked files; ** crosses folders
exclude = ["src/debug/**"]       # optional
message = "Use the logger."
```

Each hit prints `path:line: no-print: Use the logger.` and the exit code is 1. A line opts out with a comment: `# lint-allow: no-print`. A rule whose paths match no file fails. With no rules the check does nothing.

## Requirements

Python 3.11+ (stdlib only) and git. Godot 4.4+ text-resource format for the uid/tres gates; the
parser handles any Godot 4.x `.tscn`/`.tres`.

## License

MIT — see [LICENSE](LICENSE).
