---
name: godot-native-first
description: Before adding a manager, service, registry, bus or system to a Godot project, find the engine node, resource or feature that already does the job. Use when a request names a new custom system, autoload or per-frame polling code; not for pure content or art work.
---

# Godot native first: ask what the engine calls it

Before you name a new manager, service, registry or system, ask what the engine calls it, and use
that node or resource. Register reusable script types with `class_name`; let scenes own their nodes
and connect them with typed signals. Shared data can live in a Resource catalog, and shared
stateless behavior in a static helper. An autoload needs a concrete app-wide lifecycle requirement;
settings data alone does not require one. A custom layer over an existing feature takes code to
maintain, test and explain, and hides the engine's editor tooling, docs and fixes.

## Workflow

1. Restate the request as a behavior ("play a sound at a place", not "SoundManager").
2. Look it up in the table below, then in the class reference for the installed Godot version
   (the editor help or matching online manual) before you search the project. The class reference
   is the source of truth for what the engine offers.
3. Check the project for an existing use of that feature and follow it.
4. Build on the engine feature. Configure it in the scene or in a `.tres`; write script only for
   what the engine cannot express.

## Request to engine feature

| Request | Engine feature |
|---|---|
| camera rig | Camera2D smoothing, drag margins, limits; Tween on `offset` |
| sound manager | AudioStreamPlayer2D on the emitter, buses, AudioStreamInteractive |
| effects manager | one GPUParticles2D scene per effect |
| save manager | Resource + ResourceSaver/ResourceLoader |
| settings | ConfigFile |
| event bus | typed signals |
| registry | `class_name` Resource catalog (`.tres`) referenced by its consumers |
| state machine | state nodes (one child node per state); AnimationTree only blends animation |
| pause | `get_tree().paused` + `process_mode` |
| cursor manager | `Input.set_custom_mouse_cursor` |
| debug overlay | `Performance.add_custom_monitor` |
| overlap check every frame | Area2D signals |
| autotile code | TileSet terrains |
| pose code | AnimatedSprite2D + SpriteFrames for sprite sheets; AnimationPlayer to key properties, AnimationTree to blend |

## When a custom node is right

- The class reference has no feature that covers the behavior.
- The engine feature is measured too slow for the case. Keep the measurement with the code.

Say which of the two applies in the change description. A custom node that wraps one engine call
is neither.

## Where to go next

- `godot-101`: the scene and node model, the Godot 3 habits that break in Godot 4, and the engine
  feature for each common game need, with a reference file per domain. Read it when you start a
  project or design a new system.
- `godot-ui`: menus, HUDs, dialogs and Control layouts.
