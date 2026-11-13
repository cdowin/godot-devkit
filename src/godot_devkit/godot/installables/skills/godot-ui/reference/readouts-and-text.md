# Readouts and text

## Purpose

Rows of label and value, numbers and long text that stay legible and keep their place.

## Regions

A row is a label on the left and a value on the right. Units live in 1 place: in the label,
or in a fixed unit slot beside the value, never mixed.

## What may move and what may not

- The label column and the value column keep their widths while values change.
- Numbers use tabular (fixed-width) figures so digits do not jitter. Right-align values.
- The slot never grows with its text. Content changes; geometry does not.

## Overflow policy

Choose 1 policy per slot and write it down:

- Ellipsis plus tooltip: `text_overrun_behavior = OVERRUN_TRIM_ELLIPSIS`, full text in
  `tooltip_text` and in a detail view. The Label needs a bounded width; set
  `clip_text = true` or give it `custom_minimum_size`, and `size_flags_horizontal` to fill.
- Wrap: `autowrap_mode = AUTOWRAP_WORD_SMART` with a width from the container, and a fixed
  maximum height with a scroll.

A Label with neither is a defect. These are Label properties; a Theme cannot supply them.

## Focus and input

Labels take no focus (`focus_mode = NONE`). A readout the player must inspect gets a focusable
parent that shows the full text on focus. Do not rely on colour alone to show state.

## Proof to capture

- Capture shortest, typical and longest values, and enlarged text.
- Report slot rectangles for each: identical.
- Confirm full text is reachable for every truncated slot.

## Sources

- Godot: Label `text_overrun_behavior`, `autowrap_mode`, `clip_text`; FontVariation OpenType
  features for tabular figures (`tnum`)
  (https://docs.godotengine.org/en/stable/classes/class_label.html)
- Xbox Accessibility Guidelines 101 (text display), 103 (contrast)
- Game Accessibility Guidelines: text size, contrast, do not rely on colour
- Material: tokens for type and spacing (https://m3.material.io)
