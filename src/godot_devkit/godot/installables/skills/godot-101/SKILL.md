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
- Offline: the editor help (F1), or dump the reference as XML (section 9).

When Godot moves to a new minor, re-check sections 5 to 7 and the reference files against the
new class reference and the links in sections 2 and 3, then change the version line above.

## 2. Learn it from the source

Learn from the engine's own material, in this order, before tutorials or training data:

1. [Step by step](https://docs.godotengine.org/en/4.7/getting_started/step_by_step/index.html): nodes, scenes, scripts, signals.
2. [Your first 2D game](https://docs.godotengine.org/en/4.7/getting_started/first_2d_game/index.html).
3. The [best practices](https://docs.godotengine.org/en/4.7/tutorials/best_practices/index.html) pages (section 3).
4. [Godot 4 Recipes](https://kidscancode.org/godot_recipes/4.x/) by domain, and the manual's [tutorials](https://docs.godotengine.org/en/4.7/tutorials/index.html).
   Some Recipes pages still carry Godot 3 code; check each name against section 6.
5. The official demo for the domain, in [godot-demo-projects](https://github.com/godotengine/godot-demo-projects) (folders in section 7).
   Pin the branch to the engine version where one exists (`4.0` to `4.3` match releases);
   `master` tracks the next 4.x and can use API your engine does not have.
6. The [class reference](https://docs.godotengine.org/en/4.7/classes/index.html) for every class you use.
7. [Game Programming Patterns](https://gameprogrammingpatterns.com/contents.html), through section 4.
8. [Upgrading from Godot 3 to 4](https://docs.godotengine.org/en/4.7/tutorials/migrating/upgrading_to_godot_4.html) for older snippets and projects.

## 3. Best practices the engine already wrote down

- [scene_organization](https://docs.godotengine.org/en/4.7/tutorials/best_practices/scene_organization.html): children loosely coupled, an ancestor mediates; signals up, calls down.
- [autoloads_versus_regular_nodes](https://docs.godotengine.org/en/4.7/tutorials/best_practices/autoloads_versus_regular_nodes.html):
  "Other engines can encourage the use of creating manager classes, singletons that organize a lot
  of functionality into a globally accessible object. Godot offers many ways to avoid global state
  thanks to the node tree and signals." The fix: each scene owns its nodes, for example its own
  `AudioStreamPlayer`.
- [godot_interfaces](https://docs.godotengine.org/en/4.7/tutorials/best_practices/godot_interfaces.html): reach other objects through the tree, groups, duck typing and Callables.
- [godot_notifications](https://docs.godotengine.org/en/4.7/tutorials/best_practices/godot_notifications.html): which callback or notification runs when.
- [node_alternatives](https://docs.godotengine.org/en/4.7/tutorials/best_practices/node_alternatives.html): `Object`, `RefCounted` or `Resource` for data that needs no node.
- [data_preferences](https://docs.godotengine.org/en/4.7/tutorials/best_practices/data_preferences.html): Array, Dictionary, Object and their costs. Its banner says it is not yet updated for 4.7.
- [logic_preferences](https://docs.godotengine.org/en/4.7/tutorials/best_practices/logic_preferences.html): preload or load, static or dynamic levels; big dynamic-level systems add technical debt.

## 4. Game Programming Patterns, the Godot way

This mapping is this skill's guidance, not a quote from the book. Read the pattern in
[Game Programming Patterns](https://gameprogrammingpatterns.com/contents.html), then use the Godot feature.

| Pattern | Godot feature |
|---|---|
| Observer | Signals |
| State | State nodes (demo `2d/finite_state_machine`) |
| Component | Child nodes |
| Prototype | `PackedScene.instantiate()`, `duplicate()` |
| Flyweight | Shared Resources |
| Update method | `_process`, `_physics_process` |
| Game loop | The engine's main loop; you do not write one |
| Singleton, service locator | Autoload, only for a true app service (section 3, autoloads page) |
| Object pool | Only after the profiler shows an allocation cost |
| Command, event queue | Usually signals |
| Spatial partition | The physics server (`Area2D`, space queries) and `TileMapLayer` |
| Dirty flag | Notifications and property setters |
| Type object | A `Resource` subclass as the data type |

## 5. The mental model

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

**Lifecycle.** `_init`, `_enter_tree`, `_ready` (children before parents), `_exit_tree`,
`NOTIFICATION_PREDELETE`. The trap: `remove_child()` and `reparent()` also fire `_exit_tree()`, so
teardown for "destroyed" goes in `NOTIFICATION_PREDELETE`. Detail: `reference/scenes-and-lifecycle.md`.

**Autoloads are the exception.** An autoload is a node the engine adds above the main scene and
keeps for the whole run. Use one only for a true app-wide service: settings, the save slot, scene
change, music that plays across scenes. Gameplay state in an autoload is a global that every scene
depends on and no scene can be tested without (section 3, the autoloads page).

## 6. Godot 3 habits that break in Godot 4

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

## 7. Pattern index

Each row: the game need, the engine feature, the usual way, the trap, and where to learn it. The
reference file for the domain has the detail. In "Learn from": `2d/x` is a folder of
[godot-demo-projects](https://github.com/godotengine/godot-demo-projects) (on the branch for your
version, section 2); `t x` is `https://docs.godotengine.org/en/4.7/tutorials/x/`; `bp x` is a best
practices page (section 3) under `.../en/4.7/tutorials/best_practices/x.html`; `class X` is the class reference page; GUT is
https://gut.readthedocs.io/en/latest/ (documented for 4.6, not checked on 4.7).

| Need | Engine feature | Usual way | Trap | Learn from |
|---|---|---|---|---|
| A reusable thing | Scene (`.tscn`) + `PackedScene.instantiate()` | One scene per thing; `@export var scene: PackedScene` where it is spawned | A giant scene built in code; nodes added with no `owner` are not saved | `2d/instancing`; t `scripting` |
| Camera follow | `Camera2D` | Child of the player; position smoothing, drag margins, `limit_*`; shake by tweening `offset` | A camera script that copies the player position every frame | t `2d` |
| Input | Input Map actions | `Input.get_vector("left", "right", "up", "down")`; `event.is_action_pressed("jump")` | Hard-coded keys; gameplay presses read in `_input`, so a menu cannot consume them first | t `inputs` |
| Movement | `CharacterBody2D` | Set `velocity`, call `move_and_slide()` in `_physics_process`; `is_on_floor()` | Moving `position` directly, which skips collision | `2d/kinematic_character`; t `physics` |
| Physics objects | `RigidBody2D`, `StaticBody2D`, `AnimatableBody2D` | Forces and impulses on rigid bodies; moving platforms are `AnimatableBody2D` | Setting a rigid body's `position` each frame | `2d/physics_platformer`; t `physics` |
| Overlap and triggers | `Area2D` | `body_entered` / `area_entered` signals; layers named in Project Settings | Polling distance to every enemy each frame | `2d/physics_tests`; t `physics` |
| Line of sight, ground probe | `RayCast2D`, `ShapeCast2D` | A child node that stays enabled; `is_colliding()` | Building a space-state query each frame for a probe that never moves relative to the body | t `physics` |
| Pathfinding | `NavigationRegion2D`, `NavigationAgent2D`, `NavigationLink2D` | Bake a region; set `target_position`, follow `get_next_path_position()` | Hand-written A* over the level; `AStarGrid2D` is the native choice for grid or platformer routes | `2d/navigation`, `2d/navigation_astar`; t `navigation` |
| Sprite animation | `AnimatedSprite2D` + `SpriteFrames` | One animation per state, `play("run")` | Frame-stepping code over a sprite sheet | t `2d`, `animation` |
| Keyed animation | `AnimationPlayer` | Key several properties, call methods from tracks | Animating with many tweens that must stay in step | t `animation` |
| Blending | `AnimationTree` | Blend spaces and an animation state machine over an `AnimationPlayer` | Using `AnimationTree` as the gameplay state machine | `2d/skeleton`; t `animation` |
| Gameplay states | State nodes | One child node per state, the parent switches the active one | A long `match state` in one `_physics_process` | `2d/finite_state_machine` |
| Delays, cooldowns | `Timer`, `SceneTreeTimer` | A `Timer` child for repeats; `await get_tree().create_timer(0.5).timeout` for one shot | Reading `Time.get_ticks_msec()` in gameplay; it ignores pause and time scale | class `Timer` |
| Smooth change | `Tween` | `create_tween().tween_property(self, "modulate:a", 0.0, 0.3)` | A manual lerp counter in `_process` | `2d/tween` |
| Sound | `AudioStreamPlayer2D` on the emitter, buses | The emitter owns its player; buses for volume and effects | A global sound manager that plays everything at one place | t `audio` |
| Music | `AudioStreamPlaylist`, `AudioStreamInteractive` | One player, the stream switches clips | Two players crossfaded by hand | t `audio` |
| Particles | `GPUParticles2D` | One scene per effect, `one_shot`, free on `finished` | A pool manager before you measure a cost | `2d/particles`; t `2d` |
| Look and light | Shaders, `CanvasModulate`, `PointLight2D` + `LightOccluder2D` | Material on the node; occluders on the tiles | Darkening every sprite from code | `2d/lights_and_shadows`, `2d/glow`; t `shaders` |
| UI layout | `Control`, Containers, anchors | Containers place children; `CanvasLayer` for the HUD | Pixel positions set from code | t `ui` |
| UI style | `Theme`, type variations | One project theme; `theme_type_variation` for a variant | Per-node overrides everywhere | t `ui` |
| Data and catalogs | `Resource` subclasses in `.tres` | `@export var items: Array[ItemData]` on a catalog resource | A registry singleton with a dictionary of IDs | bp `node_alternatives` |
| Save game | `ResourceSaver`, `ResourceLoader`, `user://` | A save resource with `@export` fields | Saving to `res://`; JSON for a save the game alone reads | t `io` |
| Settings | `ConfigFile` | `user://settings.cfg`, applied at start | Settings inside the save game | class `ConfigFile` |
| Levels and tiles | `TileMapLayer`, `TileSet` | Terrains for autotiling; collision and navigation in the TileSet; custom data per tile | Autotile code; one `StaticBody2D` per wall tile | `2d/dynamic_tilemap_layers`; t `2d` |
| Big levels | `ResourceLoader.load_threaded_request`, `VisibleOnScreenEnabler2D` | Load the next area on a thread; switch off far nodes | Loading on the main thread mid-play | t `io`, `performance` |
| Heavy work | `WorkerThreadPool` | `add_task` for work that does not touch the tree | Changing nodes from a worker thread | `2d/bullet_shower`; t `performance` |
| Localization | `tr()`, gettext `.po` | Keys or source strings through `tr()`; POT from the Localization tab | Concatenated translated fragments | t `i18n` |
| Debugging | Debugger: Monitors, Profiler, remote tree | `Performance.add_custom_monitor`; Debug menu: Visible Collision Shapes, Visible Navigation | A home-made overlay for numbers the Monitors show | t `scripting/debug` |
| Testing | A test framework (for example GUT), warnings, headless parse | Warnings set to Error in Project Settings; `godot --headless --import` as a parse check | Tests that boot the whole game for one rule | GUT docs |
| Export | Export presets, feature tags | `OS.has_feature("debug")` or a custom tag to strip debug tools | A build flag in a script you must edit before export | t `export` |

3D: most rows have a `3D` twin (`CharacterBody3D`, `Area3D`, `RayCast3D`, `NavigationAgent3D`,
`AudioStreamPlayer3D`, `GPUParticles3D`, `Camera3D`).

## 8. When custom code is right

Write a custom system only when one of these is true:

- The class reference has no feature that covers the behavior.
- The engine feature is measured too slow for the case. Keep the measurement with the code.

A node that wraps one engine call is neither. Before you name a new manager, service, registry or
system, ask what the engine calls it, and look it up in section 7.

When you compare a project with the engine's docs or demos, grade the project against the engine:
ask "what would the engine do here?". Never grade the engine against the project. Research framed
to defend the existing code finds nothing to change.

## 9. For agents

- The docs site has no `llms.txt`. Do not guess an API from training data. Dump the installed
  engine's class reference and grep it: `godot --headless --doctool <dir>` writes one XML file per
  class. Add `--gdscript-docs <path>` to document the project's own scripts instead, and
  `--dump-extension-api-with-docs` writes the API as JSON with descriptions.
- Run these in the project's own environment. This toolkit never boots Godot, so it does not run them.
- Treat every Godot 3 snippet as suspect (section 6).
- Pin doc URLs (`/en/4.7/`) and demo branches to the project's engine version.

## 10. Where to go next

Reference files, one per domain (read the one for your task):

- `reference/scenes-and-lifecycle.md`: callbacks in order, leaving the tree versus being freed
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
