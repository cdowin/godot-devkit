# Animation (Godot 4.7, 2D)

Pick the node by what moves:

| Need | Node |
|---|---|
| Frames from a sprite sheet | `AnimatedSprite2D` + a `SpriteFrames` resource |
| Several properties keyed on one timeline (sprite, hitbox, sound, method calls) | `AnimationPlayer` |
| Blending or transitions between animations | `AnimationTree` over an `AnimationPlayer` |
| One property from A to B, once | `Tween` (`create_tween()`) |
| Which behavior the character is in (idle, chase, attack) | State nodes, not an animation node |

## AnimatedSprite2D

Create a `SpriteFrames` resource in the inspector, add one animation per state ("idle", "run"),
and add frames from the sheet with "Add frames from sprite sheet". Set the speed (FPS) and loop per
animation.

```gdscript
@onready var sprite: AnimatedSprite2D = $AnimatedSprite2D

func _physics_process(_delta: float) -> void:
    sprite.play("run" if velocity.x != 0.0 else "idle")   # play() of the current animation does not restart it
    sprite.flip_h = velocity.x < 0.0
```

Signals: `animation_finished` (non-looping animations), `frame_changed` (a footstep on frame 3).

## AnimationPlayer

Keys any property of any node under its root, plus Call Method and Audio tracks. Animations live in
an `AnimationLibrary`. Use it for an attack that turns on a hitbox on frame 4, a door that moves and
plays a sound, a UI panel that slides in.

```gdscript
$AnimationPlayer.play("attack")
await $AnimationPlayer.animation_finished
```

`queue("idle")` plays an animation after the current one. `play_backwards()` and `speed_scale`
change direction and speed. A "RESET" animation holds the default values the editor restores.

## AnimationTree

Assign `anim_player` and a `tree_root` (often an `AnimationNodeStateMachine` or a blend space),
then set `active = true`. Drive it with parameters:

```gdscript
@onready var tree: AnimationTree = $AnimationTree
@onready var playback: AnimationNodeStateMachinePlayback = tree.get("parameters/playback")

func _physics_process(_delta: float) -> void:
    tree.set("parameters/Move/blend_position", velocity.normalized())
    if attacking:
        playback.travel("Attack")
```

The parameter paths depend on the node names in your tree; copy them from the inspector.

## Gameplay states are nodes

The animation state machine chooses *which clip plays*. The gameplay state machine chooses *what
the character does*. Keep them apart. The usual shape: a `StateMachine` node with one child node
per state, each state a script with `enter()`, `exit()`, `physics_update(delta)`; the machine calls
the active state from its own `_physics_process` and switches on a signal or return value. A state
may call `playback.travel()` or `sprite.play()`; the animation never decides gameplay.

## Traps

- Two systems animating the same property (a Tween and an AnimationPlayer) fight. One owner per
  property.
- An `AnimationPlayer` track path is relative to its `root_node`. Renaming or moving a node breaks
  the track without an error until it plays.
- While an `AnimationTree` is active, drive the tree, not its `AnimationPlayer`: do not call
  `play()` on the player as well.
- `animation_finished` does not fire for looping animations (`AnimatedSprite2D` has
  `animation_looped`).
- For per-frame events on a sprite sheet, prefer `frame_changed` or an AnimationPlayer method track
  over a timer that guesses the frame.

## Class reference

- https://docs.godotengine.org/en/4.7/classes/class_animatedsprite2d.html
- https://docs.godotengine.org/en/4.7/classes/class_spriteframes.html
- https://docs.godotengine.org/en/4.7/classes/class_animationplayer.html
- https://docs.godotengine.org/en/4.7/classes/class_animationmixer.html
- https://docs.godotengine.org/en/4.7/classes/class_animationtree.html
- https://docs.godotengine.org/en/4.7/classes/class_animationnodestatemachineplayback.html
- https://docs.godotengine.org/en/4.7/classes/class_tween.html
- Manual: https://docs.godotengine.org/en/4.7/tutorials/animation/index.html
