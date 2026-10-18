# Testing and debugging (Godot 4.7)

## Tests

Godot has no built-in unit test runner. Use a test framework addon, for example GUT (Godot Unit
Test) or another from the Asset Library. Pick one per project and run it headless in CI. Test a
scene or a resource with the smallest setup that shows the rule: instantiate one scene, add it to
the tree, step it, assert. A test that boots the whole game for one rule is slow and breaks for
reasons unrelated to that rule.

Resources make data rules cheap to test: load the `.tres`, assert its fields, no tree needed.

## Warnings as errors

Project Settings > Debug > GDScript (turn on Advanced Settings to see it). Each warning has a level:
Ignore, Warn or Error. Set the ones you care about to Error, for example
`debug/gdscript/warnings/untyped_declaration` for a typed codebase. Silence one line with
`@warning_ignore("warning_name")`.

## Headless checks

```sh
godot --headless --import --path .            # import every asset, then quit; reports broken resources
godot --headless --path . --quit              # load the main scene, run one frame, quit
godot --headless --check-only --script res://x.gd   # parse one script and quit
```

`--headless` runs with no window and no audio. `--import` implies `--editor` and `--quit`. Treat a
parse or load error in the output as a failure; the exit code alone may be 0. (verify the exit code
behavior for your version)

## The debugger

- Remote scene tree: Scene dock > Remote while the game runs. Inspect and edit live nodes.
- Debug menu: Visible Collision Shapes, Visible Navigation, Visible Paths; turn them on before
  running.
- Debugger > Monitors: FPS, memory, node and object counts, physics; custom monitors from
  `Performance.add_custom_monitor`.
- Debugger > Profiler: script time per function. Visual Profiler: CPU and GPU frame time per
  render step.
- `print_debug()` adds the file and line; `push_warning()` and `push_error()` show in the Debugger's
  Errors tab with a stack.
- `assert(condition, "message")` stops a debug build and is removed from release builds.
- Breakpoints and `breakpoint` keyword in the script editor; step through with the Debugger.

## Strip debug tools from release

```gdscript
func _ready() -> void:
    if not OS.has_feature("debug"):   # or a custom feature tag set in the export preset
        queue_free()
```

`OS.is_debug_build()` does the same check. Custom feature tags are set per export preset
(Features tab) and read with `OS.has_feature("my_tag")`.

## Traps

- An error printed to the console does not stop the game; a run that "works" can hide one. Read the
  Errors tab.
- A test that relies on frame timing is flaky. Await a signal or step physics frames by count.
- Orphan nodes (created, never added to the tree, never freed) leak. Debugger > Monitors >
  Object > Orphan Nodes shows the count; `Node.print_orphan_nodes()` lists them in a debug build.

## Class reference

- https://docs.godotengine.org/en/4.7/classes/class_performance.html
- https://docs.godotengine.org/en/4.7/classes/class_os.html
- https://docs.godotengine.org/en/4.7/classes/class_@gdscript.html
- Manual: https://docs.godotengine.org/en/4.7/tutorials/editor/command_line_tutorial.html
- Manual: https://docs.godotengine.org/en/4.7/tutorials/scripting/gdscript/warning_system.html
- Manual: https://docs.godotengine.org/en/4.7/tutorials/scripting/debug/index.html
- Manual: https://docs.godotengine.org/en/4.7/tutorials/export/feature_tags.html
