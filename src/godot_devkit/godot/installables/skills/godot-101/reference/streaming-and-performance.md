# Streaming and performance (Godot 4.7, 2D)

Measure before you optimize. The Debugger's Monitors and Profiler tabs tell you whether the cost is
script, physics, rendering or loading. Keep the measurement with the change.

## Loading scenes

`preload()` loads at script parse time; `load()` loads when called, on the main thread. Both block.
For a level or a large area, load on a background thread:

```gdscript
const NEXT := "res://levels/forest.tscn"

func begin() -> void:
    ResourceLoader.load_threaded_request(NEXT)

func _process(_delta: float) -> void:
    var progress := []
    match ResourceLoader.load_threaded_get_status(NEXT, progress):
        ResourceLoader.THREAD_LOAD_IN_PROGRESS:
            $Bar.value = progress[0] * 100.0
        ResourceLoader.THREAD_LOAD_LOADED:
            var scene: PackedScene = ResourceLoader.load_threaded_get(NEXT)
            get_tree().change_scene_to_packed(scene)
```

Add the instance to the tree on the main thread. For a seamless world, keep the player scene and
add or remove area scenes as children of a level root.

## Switching off what is far away

- `VisibleOnScreenEnabler2D`: a child that disables its target node (`enable_node_path`) while it is
  off screen. `enable_mode` chooses how.
- `VisibleOnScreenNotifier2D`: emits `screen_entered` / `screen_exited`; you decide what to do.
- `process_mode = PROCESS_MODE_DISABLED` stops a subtree's processing.

## Many objects

- Same sprite many times: `MultiMeshInstance2D`, or a `GPUParticles2D` for effects. Measure the
  node version first.
- Tiles: one `TileMapLayer` draws and collides cheaper than one node per tile.
- Physics: fewer, simpler shapes; tune the layers and masks so pairs that never interact are never
  tested.
- Pooling nodes is rarely needed in Godot 4; measure `queue_free` and instantiate cost first.

## Threads

`WorkerThreadPool.add_task(callable)` runs work that does not touch the scene tree (path search
over data, procedural generation, parsing). Collect the result and apply it on the main thread with
`call_deferred()`.

```gdscript
var task_id := WorkerThreadPool.add_task(_generate.bind(seed))
# later, on the main thread:
if WorkerThreadPool.is_task_completed(task_id):
    WorkerThreadPool.wait_for_task_completion(task_id)   # required once per task
```

## Monitors

```gdscript
Performance.add_custom_monitor("game/enemies", func(): return get_tree().get_nodes_in_group("enemies").size())
```

The value shows in Debugger > Monitors next to the engine monitors (FPS, object and node counts,
physics). `Performance.get_monitor(Performance.TIME_FPS)` reads one from code.

## Traps

- Changing nodes in the tree from a worker thread is not safe. Hand the result back.
- `load()` of a big scene in the middle of play is a hitch. Request it earlier.
- A `_process` on thousands of nodes costs more than one manager loop; but first check whether the
  nodes need `_process` at all (signals, Timers, disabling off-screen).
- Profile an exported release build for real numbers; the editor and debug builds are slower.

## Class reference

- https://docs.godotengine.org/en/4.7/classes/class_resourceloader.html
- https://docs.godotengine.org/en/4.7/classes/class_visibleonscreenenabler2d.html
- https://docs.godotengine.org/en/4.7/classes/class_visibleonscreennotifier2d.html
- https://docs.godotengine.org/en/4.7/classes/class_workerthreadpool.html
- https://docs.godotengine.org/en/4.7/classes/class_performance.html
- Manual: https://docs.godotengine.org/en/4.7/tutorials/performance/index.html
