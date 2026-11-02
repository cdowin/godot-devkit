# Playfield and safe area

## Purpose

The playfield is the world the player acts in. UI may cover it only when the player chose to open
it. Everything else stays at the edges, inside the safe area.

## Regions

- Playfield: the centre. Nothing permanent covers it.
- Safe area: the screen inset by a margin on every edge, so TVs and notched phones do not clip UI.
- Edge bands: where the HUD lives (see `hud.md`).

## What may move and what may not

- The safe-area margin is one value for the whole project. Set it once on the root
  `MarginContainer`; never per widget.
- Edge bands keep their size. The playfield does not resize when a HUD element appears.
- A screen the player opened (menu, info screen, modal) may cover the playfield. A toast,
  tooltip or readout may not cover the player, targets or interactables.

## Overflow policy

Content that does not fit scrolls inside its own region. It never pushes a band wider or
spills past the safe area. Use `DisplayServer.get_display_safe_area()` for the inset on devices
that report one, and a fixed default margin elsewhere.

## Focus and input

An open surface takes focus and consumes `ui_accept` and `ui_cancel`. A layout-only root uses
`mouse_filter = IGNORE` so it never eats clicks meant for the world. Gameplay input in
`_unhandled_input` stays quiet while a surface is open.

## Proof to capture

- Native capture at the target viewport and at the smallest supported one, with the safe-area
  margin visible.
- Check that no HUD rectangle intersects the safe-area border and that the centre stays clear.
- Capture with enlarged text: bands must hold, content must scroll.

## Sources

- Godot: Size and anchors, Containers, `DisplayServer.get_display_safe_area`
  (https://docs.godotengine.org/en/stable/tutorials/ui/index.html)
- Xbox Accessibility Guidelines 101 (UI), safe-area and text-size guidance
  (https://learn.microsoft.com/gaming/accessibility/guidelines)
- Game Accessibility Guidelines: "Ensure that all text is large and clear"
  (https://gameaccessibilityguidelines.com)
- Material Design layering: tokens, components, patterns (https://m3.material.io)
