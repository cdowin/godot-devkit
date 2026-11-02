# Transient UI (toast, tooltip, context menu)

## Purpose

Short-lived information or choices that appear over a surface and then leave.

## Regions

- Toast: one fixed anchor, on the edge the project's screen map names.
- Tooltip: next to its owner, clamped inside the safe area.
- Context menu: next to the item that opened it, clamped inside the safe area.

## What may move and what may not

- A toast keeps its anchor; new toasts stack in one direction. Older ones do not jump.
- A tooltip or menu may flip sides to stay on screen. It does not resize.
- They never cover: the item that owns them, the focused control, the player, or the action bar.

## Overflow policy

- Stack limit: show at most 3 toasts; queue the rest, drop the oldest low-priority ones.
- Long text wraps to a fixed maximum width. It never grows past it.
- A context menu with many entries scrolls.

## Lifetime

- A toast lasts long enough to read, and the player can review it later; critical alerts wait for
  dismissal. Honour a setting for display time.
- A tooltip appears on hover or focus and leaves on blur. Set `tooltip_text`; it must be non-empty.
- A context menu closes on `ui_cancel`, on a choice, or on losing focus.

## Focus and input

A toast never steals focus. A context menu takes focus, and `ui_cancel` returns focus to the
control that opened it. Tooltips must also appear for focus, not only for the mouse.

## Proof to capture

- Capture a full stack at the limit, and a tooltip at each screen edge.
- Check that no transient rectangle intersects the owner, the focus or the action bar.

## Sources

- Godot: `Control.tooltip_text`, `_make_custom_tooltip`, PopupMenu
  (https://docs.godotengine.org/en/stable/classes/class_popupmenu.html)
- Xbox Accessibility Guidelines 101 (text), 108 (timing)
- Game Accessibility Guidelines: allow time limits to be adjusted or removed
- Material: snackbar and tooltip patterns (https://m3.material.io)
