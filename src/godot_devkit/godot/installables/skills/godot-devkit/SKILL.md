---
name: godot-devkit
description: Use before you read, edit or write a Godot .tscn or .tres file, or write a script to do it. Covers reading a scene or tile grid without loading the whole file, changing a scene or resource headless with Godot itself (nodes, properties, signals, tiles, new scenes), the narrow `scene set`/`scene add` writer for inherited scenes with overrides, finding real usages of a class/method/signal/resource, diffing a scene, and code-size stats. Never hand-edit scene text or write an ad-hoc parser.
---

# godot-devkit

godot-devkit reads `.tscn`/`.tres` as text without booting Godot, and ships the gates and
runners a Godot project runs. Godot writes scenes; the devkit keeps one narrow writer,
`scene set` and `scene add`, for the case Godot's headless save gets wrong. Run it as the project pins
it (`uv run godot-devkit …`). With no pin, use
`uvx --index https://cdowin.github.io/godot-devkit/simple/ godot-devkit …`.
`godot-devkit --help` and `godot-devkit <verb> --help` give the full contract.

## The rule

Godot writes its own files. With an editor running and a live MCP bridge (for example
godot-ai), edit through the bridge. With no editor, run a headless GDScript (below), except
on an inherited scene that carries overrides or local materials: there use `scene set` and
`scene add`. Never hand-edit scene text with `sed` or a script, and never write your own
`.tscn` parser or compare tool.

## Change a scene headless with Godot itself

A short GDScript loads the scene, edits nodes, tiles or properties with the normal API, and
saves it with `ResourceSaver`. Godot writes its own format, uids and ordering, so nothing
re-writes it later.

```gdscript
# tools/dev/edit_hud.gd
extends SceneTree

func _initialize() -> void:             # not _init(): autoloads do not exist yet there
    var path := "res://ui/hud.tscn"
    var root := (load(path) as PackedScene).instantiate()
    var ammo := Label.new()
    ammo.name = "Ammo"
    ammo.text = "30"                    # authored sample content
    root.get_node("Margin/Row").add_child(ammo)
    ammo.owner = root                   # a node with no owner is not saved
    # Tiles: root.get_node("Ground").set_cell(Vector2i(4, 2), 0, Vector2i(1, 0))
    var packed := PackedScene.new()
    packed.pack(root)
    var err := ResourceSaver.save(packed, path)
    root.free()
    quit(0 if err == OK else 1)
```

- **Run it through the project's sandboxed engine wrapper** (a `make` target that sources
  `gdk_runners.sh` and calls `gdk_sandbox_home`), never a raw `godot --headless`: the script
  boots the project's autoloads.
- **Fail on `SCRIPT ERROR`.** Godot exits 0 when the edit script does not compile, so the
  wrapper must grep the output for `SCRIPT ERROR` and fail.
- **Make it idempotent.** Find the node before you add it, so a second run changes nothing.
- **The first save normalizes a hand-written scene:** Godot adds or rewrites `unique_id` on
  every node. Expect that diff once; review it apart from your change.
- Prove the result with `scene-diff <file> --git HEAD`. A `.tres` works the same way:
  `load`, change it, `ResourceSaver.save(res, path)`.

| Change | Godot API |
|---|---|
| Set a property | `node.set(&"prop", value)` |
| Add, remove, move a node | `add_child` + `owner = root`, `queue_free`/`remove_child`, `reparent` |
| Wire a signal | `node.connect(&"pressed", target.method, CONNECT_PERSIST)` |
| New scene, inherited scene | `PackedScene.pack(new_root)`; an inherited one instantiates the base with `GEN_EDIT_STATE_MAIN_INHERITED` |
| Paint or clear tiles | `TileMapLayer.set_cell`, `erase_cell`, `set_cells_terrain_connect` |
| Move a resource | the editor's FileSystem dock; headless, refs are uid-in-refs, so Godot finds the moved file by uid and writes the new path at the next save |

## When to use `scene set` and `scene add` instead

A headless load-and-save of an INHERITED scene drops what it overrides: shader parameters
on local materials and tile overrides do not survive `instantiate` → `pack` → save. For
those scenes, change only the lines you mean with the devkit, which edits its own lines and
nothing else:

| Need | Verb |
|---|---|
| Set a property | `scene set <file> <node-path> <prop> <value>` (`--resource`, `--sub-resource <id>`) |
| Add a node | `scene add <file> <parent> <name> <Type>` or `--instance res://x.tscn` |

Both take `--dry-run`, refuse rather than guess, and are no-ops the second time.

## Which verb

| Need | Verb |
|---|---|
| See a scene without reading it | `scene <file> [--paths] [--props]` |
| Read a tile grid | `tiles <file> [--layer N] [--cols] [--rows] [--at X,Y] [--region …]` |
| Find real usages | `refs <symbol> [--tests]` |
| Prove an edit | `scene-diff <file> --git HEAD` |
| Files nothing references | `orphans [--tests]` |
| Code size | `stats [<dir>...] [--by dir] [--json]` |
| Localization template | `pot [--check]` |

## Habits

- Read with `scene --paths`, change with Godot (or `scene set`/`add`), prove with `scene-diff`.
- Exit 0 is pass, 1 is findings, 2 is a usage or config error.
