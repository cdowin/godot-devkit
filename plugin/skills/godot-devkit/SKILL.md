---
name: godot-devkit
description: Use before you read, edit or write a Godot .tscn or .tres file, or write a script to do it. Covers moving, adding, removing, renaming or reparenting nodes, setting properties, signal connections, painting or erasing TileMapLayer cells, renaming a class/method/signal or moving a resource path, editor save churn (files the Godot editor re-writes on save), diffing a scene, and code-size stats. Maps each job to its godot-devkit verb; never hand-edit scene text or write an ad-hoc parser.
---

# godot-devkit

godot-devkit reads and edits `.tscn`/`.tres` as text, without booting Godot. Each write verb
touches only what you ask for, refuses rather than mangles, and is idempotent. Every write verb
takes `--dry-run`. Run it as the project pins it (`uv run godot-devkit …`). With no pin, use
`uvx --index https://cdowin.github.io/godot-devkit/simple/ godot-devkit …`.
`godot-devkit --help` and `godot-devkit <verb> --help` give the full contract.

## The rule

When a Godot editor is running with a live MCP bridge (for example godot-ai), edit scenes
through the bridge, so the editor writes the file. Headless agents, generators and CI use devkit
write verbs, then `scene canonicalize --respell --order`, so the editor finds nothing to re-write.
`check canonical` guards both. Never hand-edit scene text with `sed` or a script, and never write
your own `.tscn` parser or compare tool.

## Which verb

| Need | Verb |
|---|---|
| See a scene without reading it | `scene <file> [--paths] [--props]` (node paths are write input) |
| Set a property | `scene set <file> <node-path> <prop> <value>` (`--resource`, `--sub-resource <id>` for `.tres` bodies) |
| Add, remove, rename a node | `scene add <file> <parent> <name> <Type>` (`--instance res://x.tscn`), `scene rm`, `scene rename` |
| Move a node to a new parent | `scene reparent <file> <node-path> <new-parent>` |
| Move a node in space | `scene set <file> <node-path> position "Vector2(x, y)"` |
| Wire a signal | `scene connect` / `scene disconnect <file> <signal> <from> <to> <method>` |
| New scene | `scene new <file> --root <Type>` or `--inherits res://base.tscn` |
| Read a tile grid | `tiles <file> [--layer N] [--cols] [--rows] [--at X,Y] [--region …]` |
| Paint or clear tiles | `tiles paint <file> --layer N (--at X,Y \| --region …) --tile SRC/AX,AY`, `tiles erase …` |
| Editor save churn | `scene canonicalize <file>... --respell --order --elide-defaults` |
| Gate churn in CI | `check canonical` (spelling, order) and `check defaults` (values equal to the `@export` default) |
| Rename a class, method, signal, autoload | `refs --rename <old> <new> [--dry-run]` |
| After `git mv` of a resource | `refs --retarget <old-res-path> <new-res-path>` |
| Find real usages | `refs <symbol> [--tests]` |
| Prove an edit | `scene-diff <file> --git HEAD` |
| Code size | `stats [<dir>...] [--by dir] [--json]` |

## Habits

- Read with `scene --paths`, write with the path it printed, prove with `scene-diff`.
- Exit 0 is pass, 1 is findings or a refusal, 2 is a usage or config error. Read a refusal and
  fix the input; do not work around it by hand.
- A job no verb does is a gap in devkit. Say so in your report; do not script around it.
