# UI (Godot 4.7)

For design, layout contracts and visual proof, use the `godot-ui` skill. This file is the engine
vocabulary.

## Nodes and resources

| Node or resource | Job |
|---|---|
| `Control` | Base of every UI node: rect, anchors, focus, mouse filter, theme |
| Containers (`VBoxContainer`, `HBoxContainer`, `GridContainer`, `MarginContainer`, `PanelContainer`, `ScrollContainer`, ...) | Place and size their children |
| `CanvasLayer` | Draws its children above (or below) the game, unaffected by the camera |
| `Theme` | Fonts, colors, style boxes and constants for every control type |
| `Label`, `RichTextLabel`, `Button`, `TextureRect`, `ProgressBar`, ... | Leaf controls |

## Layout

Inside a container, the container sets the child's position and size. The child says what it
wants with `size_flags_horizontal` / `size_flags_vertical` (fill, expand, shrink) and
`custom_minimum_size`. Outside a container, anchors and offsets place a control relative to its
parent; `set_anchors_preset(Control.PRESET_FULL_RECT)` fills it.

The usual HUD: a `CanvasLayer` > a full-rect `Control` or `MarginContainer` > containers > leaves.
A menu screen: a full-rect root > `CenterContainer` > `PanelContainer` > `VBoxContainer` of
buttons.

## Theme

Set one theme in Project Settings (`gui/theme/custom`) or on the root control; children inherit it.
For a variant ("a danger button", "a header label"), add a type variation in the theme
(`set_type_variation("DangerButton", "Button")`) and set `theme_type_variation` on the node.
`add_theme_color_override()` and friends are for one-off exceptions.

## Focus and input

Keyboard and gamepad navigation uses focus. Set `focus_mode`, call `grab_focus()` on the first
button when a menu opens, and set `focus_neighbor_left/top/right/bottom` and `focus_next` where the
automatic choice is wrong. UI consumes input before `_unhandled_input`, so gameplay input in
`_unhandled_input` does not fire through an open menu. `mouse_filter` decides whether a control
stops, passes or ignores the mouse.

## Custom tooltips

`tooltip_text` gives a plain tooltip. For a rich one, override `_make_custom_tooltip`:

```gdscript
func _make_custom_tooltip(for_text: String) -> Object:
    var card := preload("res://ui/item_tooltip.tscn").instantiate()
    card.set_text(for_text)
    return card
```

`tooltip_text` must be non-empty or no tooltip appears.

## Traps

- Setting `position` or `size` of a container's child from code: the container resets it on the
  next sort. Change size flags or minimum size instead.
- A full-rect control with `mouse_filter = STOP` on top of the game eats every click. Use `IGNORE`
  for layout-only roots.
- UI under a `Camera2D` moves with the world. Put the HUD in a `CanvasLayer`.
- Pause: a pause menu needs `process_mode = PROCESS_MODE_WHEN_PAUSED` or it cannot respond.
- `Label` text that must wrap needs `autowrap_mode` and a width from its container.

## Class reference

- https://docs.godotengine.org/en/4.7/classes/class_control.html
- https://docs.godotengine.org/en/4.7/classes/class_container.html
- https://docs.godotengine.org/en/4.7/classes/class_canvaslayer.html
- https://docs.godotengine.org/en/4.7/classes/class_theme.html
- Manual: https://docs.godotengine.org/en/4.7/tutorials/ui/index.html
