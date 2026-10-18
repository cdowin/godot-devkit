# Physics and collision (Godot 4.7, 2D)

## Nodes and resources

| Node | Job |
|---|---|
| `CharacterBody2D` | A body your script moves: player, enemy. `velocity` + `move_and_slide()` |
| `RigidBody2D` | A body the physics engine moves: crates, debris. Forces and impulses |
| `StaticBody2D` | A body that does not move: walls, floors |
| `AnimatableBody2D` | A body moved by animation or code that pushes others: platforms, doors |
| `Area2D` | Detects overlap; does not collide: triggers, hurtboxes, pickups |
| `CollisionShape2D` / `CollisionPolygon2D` | The shape of the parent body or area (a `Shape2D` resource) |
| `RayCast2D` / `ShapeCast2D` | A persistent probe along a line or swept shape |

Each body or area needs at least one collision shape child. 3D: the same names with `3D`.

## Layers and masks

`collision_layer` says what the object *is*; `collision_mask` says what it *looks for*. Two
objects interact when one's mask contains the other's layer. Name the layers in Project Settings >
Layer Names > 2D Physics (`layer_names/2d_physics/layer_1` ...): "world", "player", "enemy",
"pickup". The inspector then shows names, not numbers.

```gdscript
set_collision_mask_value(3, true)   # layer numbers are 1-based here
```

## Movement

```gdscript
extends CharacterBody2D

@export var speed := 200.0
@export var jump_velocity := -400.0
var gravity: float = ProjectSettings.get_setting("physics/2d/default_gravity")

func _physics_process(delta: float) -> void:
    if not is_on_floor():
        velocity.y += gravity * delta
    if Input.is_action_just_pressed("jump") and is_on_floor():
        velocity.y = jump_velocity
    velocity.x = Input.get_axis("left", "right") * speed
    move_and_slide()
```

For top-down movement: `velocity = Input.get_vector("left", "right", "up", "down") * speed` and set
`motion_mode` to floating.

## Overlap: Area2D signals

```gdscript
func _ready() -> void:
    body_entered.connect(_on_body_entered)

func _on_body_entered(body: Node2D) -> void:
    if body.is_in_group("player"):
        body.collect(self)
```

Use the signals for enter and exit. Use `get_overlapping_bodies()` or `has_overlapping_bodies()`
when you need "who is inside now" at one moment. Both depend on the layers and masks.

## Probes: RayCast2D and ShapeCast2D

A child `RayCast2D` with `target_position` set in the inspector is checked each physics frame.
Read it with `is_colliding()`, `get_collider()`, `get_collision_point()`. Call
`force_raycast_update()` if you move it and need the result in the same frame. `ShapeCast2D` does
the same with a shape and can return several hits (`get_collision_count()`).

## One-off queries

For a check that happens once (a shot, a spawn test), query the space state:

```gdscript
var space := get_world_2d().direct_space_state
var query := PhysicsRayQueryParameters2D.create(global_position, target, collision_mask)
var hit := space.intersect_ray(query)   # Dictionary; empty when nothing is hit
```

`intersect_shape` and `intersect_point` work the same way. Call them in `_physics_process`.

## Traps

- Moving a body by setting `position` skips collision. Use `move_and_slide()` (character) or
  forces and impulses such as `apply_central_impulse()` (rigid).
- Setting a `RigidBody2D` transform each frame fights the solver. Use `freeze` to take it over.
- A shape scaled through a non-uniform parent scale behaves badly. Size the shape resource.
- Two scenes that share one `Shape2D` resource share its size. Make it unique before you edit it.
- Changing physics state from inside a physics callback can fail. Use `set_deferred()` or
  `call_deferred()` (for example `$CollisionShape2D.set_deferred("disabled", true)`).
- Debug > Visible Collision Shapes shows every shape at runtime.

## Class reference

- https://docs.godotengine.org/en/4.7/classes/class_characterbody2d.html
- https://docs.godotengine.org/en/4.7/classes/class_rigidbody2d.html
- https://docs.godotengine.org/en/4.7/classes/class_area2d.html
- https://docs.godotengine.org/en/4.7/classes/class_collisionobject2d.html
- https://docs.godotengine.org/en/4.7/classes/class_raycast2d.html
- https://docs.godotengine.org/en/4.7/classes/class_shapecast2d.html
- https://docs.godotengine.org/en/4.7/classes/class_physicsdirectspacestate2d.html
- Manual: https://docs.godotengine.org/en/4.7/tutorials/physics/physics_introduction.html
