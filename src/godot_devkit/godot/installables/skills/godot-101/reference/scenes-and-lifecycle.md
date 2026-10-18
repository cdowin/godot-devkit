# Scenes and lifecycle (Godot 4.7)

Source pages: [godot_notifications](https://docs.godotengine.org/en/4.7/tutorials/best_practices/godot_notifications.html)
and the `Node` and `Object` class reference.

## Callbacks in order

| Callback | When |
|---|---|
| `_init()` | the object is created; no tree, no children yet |
| `_enter_tree()` | the node enters the scene tree; runs again on each re-entry |
| `_ready()` | once, after all children are ready (children before parents) |
| `_exit_tree()` | the node leaves the tree, for any reason |
| `NOTIFICATION_PREDELETE` | the object is about to be freed (handle it in `_notification`) |

## The trap: leaving the tree is not being freed

`remove_child()` and `reparent()` also fire `_exit_tree()` (and `_enter_tree()` again on the new
parent). Teardown that must run only when the node is destroyed (release a slot, stop a stream,
unregister) goes in `NOTIFICATION_PREDELETE`, or in an explicit `release()` that the owner calls
before `queue_free()`. Use `_exit_tree` only for "I left the tree".

```gdscript
func _notification(what: int) -> void:
    if what == NOTIFICATION_PREDELETE:
        _release_slot()
```
