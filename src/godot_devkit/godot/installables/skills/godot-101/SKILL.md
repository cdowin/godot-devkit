---
name: godot-101
description: Learn Godot before you build in it. The scene and node model, the Godot 3 habits that break in Godot 4, and for each common game need the engine feature that does the job and how it is usually set up. Use when you start a Godot project, onboard to one, learn Godot, or are about to design a new game system; not for a small edit inside a system that already exists.
---

# Godot 101: scenes, nodes and the feature for each need

Godot already has a node, a resource or a project setting for most of what a game needs. Learn the
model first, then find the feature for the need, then build on it. This file is the entry level.
Each domain has a reference file under `reference/` with the setup, snippets and traps.

## 1. Version

Written for **Godot 4.7** (4.7.2-stable is the current release). Check the project's version first
(`config/features` in `project.godot`, or `godot --version`). If it differs, the class reference for
that version wins over this file.

- Manual, pinned: https://docs.godotengine.org/en/4.7/
- Class reference, pinned: https://docs.godotengine.org/en/4.7/classes/index.html
- Latest stable 4.x: https://docs.godotengine.org/en/stable/ (change `4.7` to `stable` in any link)
- Offline: the editor help (F1), or `godot --doctool <path>` to dump the reference as XML.

When Godot moves to a new minor, re-check sections 3 and 4 and the reference files against the new
class reference, then change the version line above.

## 2. The mental model

**Scenes and nodes.** A node does one job: draw a sprite, collide, play a sound, run a timer. A
scene is a saved tree of nodes (`.tscn`) and it is the unit of reuse. You *instance* a scene into
another scene, as often as you need. An *inherited scene* takes a base scene and changes some
properties. The `owner` of a node is the root of the scene that saved it; only nodes with that owner
are saved in that scene file. A node you add from code with no owner is not saved.

**Composition.** Build a thing from child nodes, each with one job: a `CharacterBody2D` root, a
`CollisionShape2D`, an `AnimatedSprite2D`, an `Area2D` hurtbox, a `Timer`. Prefer a child node over
a script that does the same job.

**Communication: signals up, calls down, groups for all of a kind.**
- A parent calls methods on its children; it knows them.
- A child emits a signal; it does not know who listens. Declare typed signals
  (`signal health_changed(value: int)`), connect with `health_changed.connect(_on_health_changed)`.
- Siblings talk through their common parent, which connects one to the other.
- "Every enemy" is a group: `add_to_group("enemies")` or the Groups tab, then
  `get_tree().call_group("enemies", "alert")` or `get_tree().get_nodes_in_group("enemies")`.

**Resources are data.** A `Resource` subclass with `@export` properties is a data type that the
inspector edits and that saves as a `.tres`. A loaded resource is *shared by reference*: every
scene that loads `sword.tres` gets the same object, so a change at runtime changes it for all of
them. For per-instance state, set `resource_local_to_scene` on the resource, or call
`duplicate()` (`duplicate_deep()` for nested resources) before you change it.

**Processing.** `_process(delta)` runs once per rendered frame: visuals, UI, input polling.
`_physics_process(delta)` runs at the fixed physics rate (60 Hz by default): movement, collision,
anything that must be deterministic. Input events arrive in `_input` / `_unhandled_input`; gameplay
input usually goes in `_unhandled_input` so the UI can consume an event first.

**Pause.** `get_tree().paused = true` stops every node whose `process_mode` is `PAUSABLE` (the
default, inherited from the parent). Set the pause menu to `PROCESS_MODE_WHEN_PAUSED` and the
music or a debug overlay to `PROCESS_MODE_ALWAYS`. No pause flags in each script.

**Lifecycle.**

| Callback | When |
|---|---|
| `_init()` | the object is created; no tree, no children yet |
| `_enter_tree()` | the node enters the scene tree; runs again on each re-entry |
| `_ready()` | once, after all children are ready (children before parents) |
| `_exit_tree()` | the node leaves the tree, for any reason |
| `NOTIFICATION_PREDELETE` | the object is about to be freed (handle it in `_notification`) |

The trap: `remove_child()` and `reparent()` also fire `_exit_tree()` (and `_enter_tree()` again on
the new parent). Teardown that must run only when the node is destroyed (release a slot, stop a
stream, unregister) goes in `NOTIFICATION_PREDELETE`, or in an explicit `release()` that the owner
calls before `queue_free()`. Use `_exit_tree` only for "I left the tree".

```gdscript
func _notification(what: int) -> void:
    if what == NOTIFICATION_PREDELETE:
        _release_slot()
```

**Autoloads are the exception.** An autoload is a node the engine adds above the main scene and
keeps for the whole run. Use one only for a true app-wide service: settings, the save slot, scene
change, music that plays across scenes. Gameplay state in an autoload is a global that every scene
depends on and no scene can be tested without.

## 3. Godot 3 habits that break in Godot 4

Most training data and tutorials are Godot 3. These are the common mistakes.

| Godot 3 | Godot 4 |
|---|---|
| `KinematicBody2D`, `move_and_slide(velocity, up)` | `CharacterBody2D`; set the `velocity` property, call `move_and_slide()` with no arguments |
| `yield(obj, "signal")` | `await obj.signal` |
| `export var`, `onready var`, `tool` | `@export var`, `@onready var`, `@tool` |
| `setget` | `var x: int: set = _set_x, get = _get_x` or an inline `set(value):` block |
| `connect("sig", obj, "method")` | `sig.connect(obj.method)` (a Callable); `emit_signal("sig")` still works, `sig.emit()` is usual |
| `scene.instance()` | `scene.instantiate()` |
| `TileMap` | one `TileMapLayer` node per layer (`TileMap` is deprecated) |
| `Spatial`, `Position2D`, `Particles2D` | `Node3D`, `Marker2D`, `GPUParticles2D` |
| `VisibilityNotifier2D` | `VisibleOnScreenNotifier2D` |
| `Tween` node | `create_tween()` (Tweens are not nodes) |
| `rand_range`, `deg2rad`, `stepify` | `randf_range`, `deg_to_rad`, `snapped` |
| `File`, `Directory` | `FileAccess`, `DirAccess` (static `open` methods) |
| `OS.get_ticks_msec()` | `Time.get_ticks_msec()` |
| `change_scene("res://x.tscn")` | `get_tree().change_scene_to_file("res://x.tscn")` |
| `update()` on a CanvasItem | `queue_redraw()` |
| `rect_size`, `rect_position` on Control | `size`, `position` |
| `BUTTON_LEFT`, `KEY_` scancodes | `MOUSE_BUTTON_LEFT`, `KEY_` keycodes (`physical_keycode` for layout-free keys) |
| `PoolStringArray` and the other pools | `PackedStringArray`, `PackedVector2Array`, ... |
| `funcref(obj, "m")` | `obj.m` (Callable), `.bind(arg)` for extra arguments |

When you are unsure, open the class in the 4.7 class reference. A name that is not there is a
Godot 3 name.

## 4. Pattern index

Each row: the game need, the engine feature, the usual way, the trap. The reference file for the
domain has the detail.

| Need | Engine feature | Usual way | Trap |
|---|---|---|---|
| A reusable thing | Scene (`.tscn`) + `PackedScene.instantiate()` | One scene per thing; `@export var scene: PackedScene` where it is spawned | A giant scene built in code; nodes added with no `owner` are not saved |
| Camera follow | `Camera2D` | Child of the player; position smoothing, drag margins, `limit_*`; shake by tweening `offset` | A camera script that copies the player position every frame |
| Input | Input Map actions | `Input.get_vector("left", "right", "up", "down")`; `event.is_action_pressed("jump")` | Hard-coded keys; gameplay presses read in `_input`, so a menu cannot consume them first |
| Movement | `CharacterBody2D` | Set `velocity`, call `move_and_slide()` in `_physics_process`; `is_on_floor()` | Moving `position` directly, which skips collision |
| Physics objects | `RigidBody2D`, `StaticBody2D`, `AnimatableBody2D` | Forces and impulses on rigid bodies; moving platforms are `AnimatableBody2D` | Setting a rigid body's `position` each frame |
| Overlap and triggers | `Area2D` | `body_entered` / `area_entered` signals; layers named in Project Settings | Polling distance to every enemy each frame |
| Line of sight, ground probe | `RayCast2D`, `ShapeCast2D` | A child node that stays enabled; `is_colliding()` | Building a space-state query each frame for a probe that never moves relative to the body |
| Pathfinding | `NavigationRegion2D`, `NavigationAgent2D`, `NavigationLink2D` | Bake a region; set `target_position`, follow `get_next_path_position()` | Hand-written A* over the level; `AStarGrid2D` is the native choice for grid or platformer routes |
| Sprite animation | `AnimatedSprite2D` + `SpriteFrames` | One animation per state, `play("run")` | Frame-stepping code over a sprite sheet |
| Keyed animation | `AnimationPlayer` | Key several properties, call methods from tracks | Animating with many tweens that must stay in step |
| Blending | `AnimationTree` | Blend spaces and an animation state machine over an `AnimationPlayer` | Using `AnimationTree` as the gameplay state machine |
| Gameplay states | State nodes | One child node per state, the parent switches the active one | A long `match state` in one `_physics_process` |
| Delays, cooldowns | `Timer`, `SceneTreeTimer` | A `Timer` child for repeats; `await get_tree().create_timer(0.5).timeout` for one shot | Reading `Time.get_ticks_msec()` in gameplay; it ignores pause and time scale |
| Smooth change | `Tween` | `create_tween().tween_property(self, "modulate:a", 0.0, 0.3)` | A manual lerp counter in `_process` |
| Sound | `AudioStreamPlayer2D` on the emitter, buses | The emitter owns its player; buses for volume and effects | A global sound manager that plays everything at one place |
| Music | `AudioStreamPlaylist`, `AudioStreamInteractive` | One player, the stream switches clips | Two players crossfaded by hand |
| Particles | `GPUParticles2D` | One scene per effect, `one_shot`, free on `finished` | A pool manager before you measure a cost |
| Look and light | Shaders, `CanvasModulate`, `PointLight2D` + `LightOccluder2D` | Material on the node; occluders on the tiles | Darkening every sprite from code |
| UI layout | `Control`, Containers, anchors | Containers place children; `CanvasLayer` for the HUD | Pixel positions set from code |
| UI style | `Theme`, type variations | One project theme; `theme_type_variation` for a variant | Per-node overrides everywhere |
| Data and catalogs | `Resource` subclasses in `.tres` | `@export var items: Array[ItemData]` on a catalog resource | A registry singleton with a dictionary of IDs |
| Save game | `ResourceSaver`, `ResourceLoader`, `user://` | A save resource with `@export` fields | Saving to `res://`; JSON for a save the game alone reads |
| Settings | `ConfigFile` | `user://settings.cfg`, applied at start | Settings inside the save game |
| Levels and tiles | `TileMapLayer`, `TileSet` | Terrains for autotiling; collision and navigation in the TileSet; custom data per tile | Autotile code; one `StaticBody2D` per wall tile |
| Big levels | `ResourceLoader.load_threaded_request`, `VisibleOnScreenEnabler2D` | Load the next area on a thread; switch off far nodes | Loading on the main thread mid-play |
| Heavy work | `WorkerThreadPool` | `add_task` for work that does not touch the tree | Changing nodes from a worker thread |
| Localization | `tr()`, gettext `.po` | Keys or source strings through `tr()`; POT from the Localization tab | Concatenated translated fragments |
| Debugging | Debugger: Monitors, Profiler, remote tree | `Performance.add_custom_monitor`; Debug menu: Visible Collision Shapes, Visible Navigation | A home-made overlay for numbers the Monitors show |
| Testing | A test framework (for example GUT), warnings, headless parse | Warnings set to Error in Project Settings; `godot --headless --import` as a parse check | Tests that boot the whole game for one rule |
| Export | Export presets, feature tags | `OS.has_feature("debug")` or a custom tag to strip debug tools | A build flag in a script you must edit before export |

3D: most rows have a `3D` twin (`CharacterBody3D`, `Area3D`, `RayCast3D`, `NavigationAgent3D`,
`AudioStreamPlayer3D`, `GPUParticles3D`, `Camera3D`).

## 5. When custom code is right

Write a custom system only when one of these is true:

- The class reference has no feature that covers the behavior.
- The engine feature is measured too slow for the case. Keep the measurement with the code.

A node that wraps one engine call is neither. Before you name a new manager, service, registry or
system, ask what the engine calls it, and look it up in section 4.

## 6. Where to go next

Reference files, one per domain (read the one for your task):

- `reference/physics-and-collision.md`: bodies, layers and masks, areas, casts, space queries
- `reference/animation.md`: AnimatedSprite2D, AnimationPlayer, AnimationTree, state nodes
- `reference/audio.md`: players, buses, listener, randomizer, playlists, interactive music
- `reference/ui.md`: Control, containers, themes, focus, CanvasLayer, tooltips
- `reference/saving-and-data.md`: Resources, `.tres` catalogs, saves, settings, JSON
- `reference/streaming-and-performance.md`: threaded loading, notifiers, worker threads, monitors
- `reference/testing-and-debugging.md`: test frameworks, warnings, headless checks, the debugger

Expert skills:

- `godot-ui`: design, build or review a menu, HUD, dialog or Control layout.
- `godot-native-first`: the tripwire when a request names a manager, service, registry or bus.
