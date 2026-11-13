---
name: godot-ui
description: Design, implement, or review native Godot menus, HUDs, dialogs, cards, and Control layouts. Translate approved wireframes into reusable scenes with explicit layout contracts and native visual proof. Use for resizing, clipping, overlap, scrolling, and selection-state layout defects; not simulation-only work or browser-only UI.
---

# Godot UI: component contract to native proof

## Principles

1. **Godot native first.** Use the editor's building blocks (scenes, containers, themes,
   resources) before code.
2. **A `.tscn` is the layout**, with authored sample content, so it opens in the editor and
   renders on its own. Code only binds live data into the nodes the scene already has.
3. **"Data-driven" means data the editor writes** (scenes and resources), never UI trees built
   in code. `add_child` and `.new()` in a UI script are for real lists of runtime items only.

Treat the user's task and approved wireframe as the design input. Identify the spatial and
interaction intent before changing a dimension. A stable panel that obscures the task still fails.
Use this workflow for the affected surface; reuse existing contracts for a small edit.

## Start here

1. Read the project instructions, the UI/theme contract and the installed Godot version.
2. Read the project's screen map: the rule file the project names, for example
   `.claude/rules/screen-map.md`. If there is none, ask the owner before you place anything.
   The pages below give rules, never project positions.
3. Name the surface, then read only its page in `reference/`:

| Surface | Page |
| --- | --- |
| What UI may cover the world; safe area | `reference/playfield-and-safe-area.md` |
| HUD | `reference/hud.md` |
| Title, pause, settings | `reference/menu-screen.md` |
| Character, inventory, codex | `reference/info-screen.md` |
| Modal dialog, action bar | `reference/modal-dialog.md` |
| Toast, tooltip, context menu | `reference/transient.md` |
| Label/value rows, long text, numbers | `reference/readouts-and-text.md` |

4. Reuse the nearest native shell, row, theme and gallery before you add a component.
5. Optional skills `ui-patterns`, `visual-layout` and `usability-review` add principles and audits.
   Their web capture sizes do not replace the project's Godot viewports and input modes.
6. Enforcement: the opt-in `godot-devkit check ui-layout` fails an action button outside the action
   bar, a button inside a modal scroll, and a Label with no overflow policy. Configure it in
   `godot-devkit.toml` under `[ui_layout]`. It is static; it does not prove fit or usability.
7. A game keeps its parts gallery at `<ui folder>/gallery/` and runs `make ui-fit` on it: each
   scene boots pseudolocalized at the smallest and largest window and reports `spills` and `cut`.

## Define the component contract

Record a compact contract in the existing issue or design record, not a new documentation system:

| Field | Define |
| --- | --- |
| Purpose | What the player needs to see or do; which approved design expresses it. |
| Composition | Named regions and reusable child components; map each to its native scene/node. |
| Reading and events | Data supplied by the presenter, derived counts, selection state, and emitted intents. Keep simulation facts in their existing owners. |
| Geometry owner | Which parent allocates each region; reserved identity lines and control slots; viewport/text-scale reflow rules. |
| Overflow | Which interior scrolls, wraps or truncates; how full text remains available; what must stay visible and pinned. |
| States | Relevant empty/populated, selected/unselected, long-content and enabled/disabled cases. |
| Motion and overlays | What may intentionally move, permitted overlays, and Reduce Motion behavior. |
| Evidence | State fixture and native check/capture that can refute each important claim. |

Persistent chrome keeps its bounds across content and selection changes. Natural-height content
rows may grow inside their allocated scroller. A selected graph node may intentionally recenter
inside its graph region. Distinguish these cases instead of forbidding every size or position change.

## Translate into Godot deliberately

- Author the node tree in the `.tscn` (principle 2). In a `Container`, the parent manages child
  positions and sizes; hand-set offsets are not a substitute for the right hierarchy.
- `custom_minimum_size` is a floor, not a fixed rectangle. Content, fonts and visible children can
  contribute a larger minimum. `Expand`/`Fill` alone do not establish a bounded scroll viewport.
- Choose the sizing/minimum-propagation behavior for each allocated region. Put scroll boundaries
  around content that may exceed that region; keep pinned headers, filters and actions outside it.
  Use the project's existing bounded-region primitive when there is one.
- Reserve the same structural slots for empty and populated states. Hiding a child can remove its
  contribution to a container's minimum size. Check name wrapping, portrait alignment and empty
  versus filled controls without allowing their incidental minima to rearrange the whole surface.
- Use actual Theme font metrics and spacing. MarginContainer/StyleBox margins and container
  separation are distinct; an arbitrary margin override on a BoxContainer does not create padding.
- Keep the wireframe's visual hierarchy, tokens, identity composition and information density.
  Explicitly account for native scrollbar width, safe areas, focus, text scale and touch targets.
- Custom-drawn graph labels and marks still need allocated space and measurable bounds. A sibling
  inside the outer card may obscure them. Report those bounds through a read-only probe if needed.

## Build and prove the affected slice

Use the approved fixture in the real components/gallery, then representative stress states from
real domain readings. Preserve real counts, roles and supported types; example wireframe data does
not establish a simulation feature. Scale proof to the change rather than multiplying boot runs.

Extend the existing appropriate journey or component proof. Check relevant claims such as stable
region bounds across selection/content transitions, disjoint primary regions, required-visible
labels/actions, reserved slots, and scroll ownership. Account for declared overlays and intentionally
offscreen scroll rows. An outer-card containment check alone cannot establish these claims.

Capture the native surface at the project's target viewport and representative enlarged text state.
Confirm the effective viewport/text scale, not just the requested window size. Use real controls or
the project's supported input signals; activating an invisible button does not prove a usable path.

Read the actual scenario result and error count as well as the capture result. A PNG being written
only proves that an image exists; some capture runners deliberately use that as their success
criterion. Keep “image produced,” “scenario passed,” and “visually accepted” as separate claims.

Compare the native capture to the approved design and walk the player's task. Inspect empty and
populated transitions, long names, scrolling, focus and relevant touch behavior. Reject unintended
movement, obscured content and misleading counts even when structural tests pass. State missing
render/input evidence as unverified; do not certify appearance from markup or headless output.

Keep a small evidence handoff: requirement → component/state → check or capture → result.
Name material deviations and unresolved limits. Apply independent review when required by the
project or the change's risk; no blanket approval step is added by this skill.
