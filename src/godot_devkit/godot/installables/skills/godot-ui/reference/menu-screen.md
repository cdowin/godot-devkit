# Menu screen (title, pause, settings)

## Purpose

Let the player choose one action from a short list, by pad, keyboard or pointer.

## Regions

Title or heading on top, a column of rows in the middle, a hint line (button prompts) at the
bottom. Settings adds a scrolling row list between heading and footer.

## What may move and what may not

- Back is `ui_cancel` and sits in 1 place on every menu, per the project's screen map.
- Row heights are fixed. Focus or hover never changes a row's size, only its look.
- The column keeps its position when a row is disabled or hidden-by-state; disabled rows stay in
  place.
- May move: the focus highlight.

## Overflow policy

Rows do not grow. A long label truncates with an ellipsis and the full text is in the detail or a
tooltip. A long list scrolls inside a `ScrollContainer`; heading and hint line stay pinned outside.

## Focus and input

- Call `grab_focus()` on the first row when the menu opens, or on the last-used row on return.
- Focus is always visible: a themed focus StyleBox with contrast against the row.
- `ui_accept` activates, `ui_cancel` goes back one level. Set `focus_neighbor_*` where automatic
  order is wrong. Wrap top and bottom.
- Show prompts for the active device. A pause menu needs `process_mode = WHEN_PAUSED`.
- Every action works with pad, keyboard and pointer.

## Proof to capture

- Capture each menu with focus on the first, a middle and the last row.
- Report row rectangles with focus on each row: all equal.
- Drive `ui_cancel` through the real input path and confirm it goes back.

## Sources

- Godot: Using the UI focus system, `Control.focus_neighbor_*`, InputMap `ui_accept`, `ui_cancel`
  (https://docs.godotengine.org/en/stable/tutorials/ui/gui_navigation.html)
- Xbox Accessibility Guidelines 107 (input), 112 (UI navigation)
- Game Accessibility Guidelines: simple menu navigation; show a clear focus
- Material: layering of patterns over components (https://m3.material.io)
