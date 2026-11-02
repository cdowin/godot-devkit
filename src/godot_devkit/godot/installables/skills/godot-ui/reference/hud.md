# HUD

## Purpose

Show the state the player needs mid-action, without taking the eyes off the world.

## Vocabulary

- Non-diegetic: drawn over the game, outside the fiction (health bar, ammo).
- Diegetic: part of the world (a gauge on a weapon).
- Spatial: tied to a world position (a marker over an enemy, a name tag).
- Meta: reacts to state the character does not know (a red vignette when hurt).

Pick one kind per piece of information and keep it.

## Regions

One fixed anchor per kind of info: vitals, map, objective, alerts. The project's screen map
says which edge or corner each one takes. Do not invent positions here. Two kinds never share
an anchor.

## What may move and what may not

- Readouts never shift. A value change never moves its neighbours. Reserve the widest slot
  (see `readouts-and-text.md`).
- An empty state keeps its slot. Hiding a child can collapse a container; use
  `modulate.a` or a placeholder instead.
- May move: spatial markers, and a damage flash on its own layer. Honour a Reduce Motion setting.

## Overflow policy

A HUD slot never grows. Long text truncates with an ellipsis and the full text goes to a menu
or tooltip. Alerts queue; the stack limit is in `transient.md`.

## Focus and input

The HUD takes no focus and sets `mouse_filter = IGNORE`. Show button prompts for the active
input device, and never rely on colour alone: pair it with an icon, shape or text.

## Proof to capture

- Capture at full, low and zero values: anchors and slot bounds must be identical.
- Capture with the longest realistic text and with enlarged text.
- Report each slot's rectangle before and after a value change; they must match.

## Sources

- Godot: CanvasLayer, Control anchors (https://docs.godotengine.org/en/stable/classes/class_canvaslayer.html)
- Game Accessibility Guidelines: do not rely on colour alone; allow HUD scaling and clear text
- Xbox Accessibility Guidelines 101 (text display), 103 (contrast)
- Diegetic / non-diegetic / spatial / meta: Fagerholt and Lorentzon, "Beyond the HUD" (2009)
- Material: tokens, components, patterns (https://m3.material.io)
