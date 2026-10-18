# Saving and data (Godot 4.7)

## Data is a Resource

A custom `Resource` with `@export` properties is a data type. The inspector edits it, it saves as
a `.tres` text file, and it diffs well.

```gdscript
# item_data.gd
class_name ItemData
extends Resource

@export var id: StringName
@export var display_name: String
@export var icon: Texture2D
@export var price := 10
```

A catalog is a resource that holds others:

```gdscript
class_name ItemCatalog
extends Resource

@export var items: Array[ItemData] = []

func find(id: StringName) -> ItemData:
    for item in items:
        if item.id == id:
            return item
    return null
```

A scene that needs the catalog exports it: `@export var catalog: ItemCatalog`. No registry
autoload, no string table. A designer adds an item by adding a `.tres` and dragging it into the
catalog.

## Shared by reference

`load("res://items/sword.tres")` returns the same object to every caller (the resource cache).
Changing a field at runtime changes it everywhere. For per-instance state:

- set `resource_local_to_scene` on a resource embedded in a scene, so each instance gets a copy;
- or `var mine := shared.duplicate()` (`duplicate_deep()` copies nested resources too).

## Save games

Write a save resource to `user://` with `ResourceSaver`, read it with `ResourceLoader`.

```gdscript
class_name SaveGame
extends Resource

@export var level: StringName
@export var player_position: Vector2
@export var inventory: Array[ItemData] = []

const PATH := "user://save_1.tres"

func write() -> Error:
    return ResourceSaver.save(self, PATH)

static func read() -> SaveGame:
    if not ResourceLoader.exists(PATH):
        return null
    return ResourceLoader.load(PATH, "", ResourceLoader.CACHE_MODE_IGNORE) as SaveGame
```

`user://` is the per-user data folder (`OS.get_user_data_dir()`); `res://` is read-only in an
exported game. A `.tres` can hold a script reference, so loading a save file from an untrusted
source can run code; for saves a player shares, write your own format (see JSON below).

## Settings

`ConfigFile` reads and writes INI-style sections. Keep settings apart from the save game.

```gdscript
var cfg := ConfigFile.new()
cfg.load("user://settings.cfg")   # an error code when the file is missing; defaults apply
var volume: float = cfg.get_value("audio", "music", 0.8)
cfg.set_value("audio", "music", volume)
cfg.save("user://settings.cfg")
```

## JSON

Use `JSON.stringify()` and `JSON.parse_string()` for interchange with other tools or a server.
JSON has no `Vector2`, `Color` or resource types, and every number comes back as a float, so it is
the wrong default for a save only the game reads.

## Files and folders

`FileAccess.open(path, FileAccess.WRITE)` and `DirAccess.make_dir_recursive_absolute(path)` for raw
files. Most game data never needs them.

## Traps

- A runtime change to a loaded `.tres` leaks into every user of it. Duplicate first.
- `@export` of a custom resource type needs `class_name` on the resource script.
- Renaming a resource script's property breaks old saves silently (the value is dropped). Keep a
  version field and migrate.
- `ResourceLoader.load` caches; pass `CACHE_MODE_IGNORE` to re-read a save from disk.
- The cache holds a resource only while something references it. A shared catalog accessor that
  returns `load(PATH)` and keeps no reference re-reads the file on every call once the last user
  drops it. Hold it: `static var _shared: MyCatalog` set on first use (or `preload` into a const).

## Class reference

- https://docs.godotengine.org/en/4.7/classes/class_resource.html
- https://docs.godotengine.org/en/4.7/classes/class_resourcesaver.html
- https://docs.godotengine.org/en/4.7/classes/class_resourceloader.html
- https://docs.godotengine.org/en/4.7/classes/class_configfile.html
- https://docs.godotengine.org/en/4.7/classes/class_json.html
- https://docs.godotengine.org/en/4.7/classes/class_fileaccess.html
- Manual: https://docs.godotengine.org/en/4.7/tutorials/io/saving_games.html
- Manual: https://docs.godotengine.org/en/4.7/tutorials/scripting/resources.html
