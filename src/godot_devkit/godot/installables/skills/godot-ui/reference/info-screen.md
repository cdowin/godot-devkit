# Info screen (character, inventory, codex)

## Purpose

Let the player read and compare many things, then act on one.

## Regions

Tabs on top. Below them a list pane and a detail pane side by side. A footer line holds hints
and pinned actions.

## What may move and what may not

- Tabs stay on top, same order, same size, whatever the content.
- The list pane and the detail pane keep their widths. Selecting an item never resizes a pane.
- The detail pane reserves its slots (name, art, stats, text) for an empty selection too.
- May move: list rows inside their scroller; a selected graph node may recenter inside its own
  graph region.

## Overflow policy

Each pane scrolls inside its own `ScrollContainer`. Tabs, headers, filters and footer actions
stay outside the scroll. Long names truncate with an ellipsis in the list and wrap in the detail.

## Focus and input

- Shoulder buttons or `ui_focus_next` / `ui_focus_prev` switch tabs. `ui_cancel` closes.
- On open, focus the first list row. Moving through the list updates the detail; `ui_accept`
  moves focus into the detail or runs its primary action.
- Keep a visible focus in both panes. Show prompts for the active device.

## Proof to capture

- Capture empty, one item, many items, and an item with a very long name.
- Report pane rectangles before and after selecting a different item: they must match.
- Capture with enlarged text and confirm panes scroll instead of overlapping.

## Sources

- Godot: TabContainer, ScrollContainer, SplitContainer
  (https://docs.godotengine.org/en/stable/classes/class_tabcontainer.html)
- Xbox Accessibility Guidelines 101 (text), 112 (navigation)
- Game Accessibility Guidelines: allow navigation without precise input; clear text
- Material: components inside patterns (https://m3.material.io)
