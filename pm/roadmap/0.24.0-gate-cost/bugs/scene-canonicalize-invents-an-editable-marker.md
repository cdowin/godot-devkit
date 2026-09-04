---
id: 0.24.0/bugs/scene-canonicalize-invents-an-editable-marker
milestone: "0.24.0"
name: "`scene canonicalize` adds an `[editable path=…]` the original file did not carry, on 21 of 304 tracked consumer scenes"
status: fixed
caught_in: "0.24.0"
fix_milestone: "0.24.0"
caused_by:
---

# scene-canonicalize-invents-an-editable-marker

## Symptom

Found 2026-09-04 while moving the consumer-tree tests into `make smoke`
(`0.24.0/consumer-reads-leave-the-unit-suite`). Generalising the new
`canonicalize round trip` smoke row from one scene to ALL tracked scenes fails on **21 of 304**
— 13 in trail, 8 in nullbound. In each, canonicalizing a degraded copy produces a file carrying an
`[editable path="…"]` section the original did not have. Example: nullbound
`systems/processes/process_widget.tscn` gains `[editable path="Layout/Header"]`.

## Root cause

**A writer that does not distinguish "this instance has overrides" from "this instance is
editable", deriving the marker from the node tree.** `_restore_editable_markers`
(`godot/write/scene_canonicalize.py`) took as its rule *"an instance whose children are overridden
is an editable instance"*. That rule is false, and nothing in a packed scene is evidence for it.

`[editable path=]` records exactly one thing: the editor's per-instance **Editable Children**
toggle. In the engine (`scene/resources/packed_scene.cpp`, 4.3):

- **emitted** only from the live flag — `if (p_node != p_owner && !p_node->get_scene_file_path().is_empty() && p_owner->is_editable_instance(p_node)) editable_instances.push_back(...)`. No child override is consulted.
- **applied** LAST on load, after every node and property already exists: `for (...) ret_nodes[0]->set_editable_instance(ei, true);`. Nothing about applying an override reads it.
- a type-less override entry is emitted when `states_stack` is non-empty **or** the node is part of an editable instance — two independent routes, so instance-child overrides are written with no marker involved.

Both consumers' trees say the same thing without the engine, and say it in **both** directions —
which no derivation rule can produce:

| | count |
|---|---|
| instance hosts with an overridden child, NO marker (the invention) | 26 across 10 files |
| `[editable]` markers on hosts with NO overridden child at all | 14 |

So the marker is authored state, not a `pack()` loss: `pack()` preserves it whenever the flag was
set, and an offline authoring script that never called `set_editable_instance` has nothing to
restore. The module's own docstring enumerates three losses and never listed this one — the
restoration contradicted both the docstring and the module's stated contract, *"restored from
evidence, never invented."*

## Why it matters more than 21 files

`scene canonicalize` is the tool a consumer reaches for to normalise a scene, and the property the
round-trip row exists to protect is that it **derives, never invents**. A marker that appears from
nowhere is the failure mode that property is written to catch, and `[editable]` is not cosmetic —
it controls whether an instanced sub-tree's overrides are editable and saved. Inventing one changes
what the editor will let a human do to that scene and what gets written back.

## Scope note

The smoke row shipped pinned to ONE scene per consumer — the one the degradation costs the most
lines, chosen by a rule fixed before any restoration runs so it cannot be a pick that passes. That
row is green and is not affected. Widening it to all tracked scenes is the natural test for this
bug and must wait for the fix.

`0.24.0/consumer-reads-leave-the-unit-suite`'s story puts "any change to what those checks assert"
out of scope, which is why the row was left narrow and this filed instead of the row being quietly
weakened to accommodate it.

## Fix

`_restore_editable_markers` is deleted with its constant. `scene canonicalize` no longer reads or
writes `[editable]` at all: it neither invents one nor removes one. Measured over the live trees —
26 invented markers (25 nullbound, 1 trail) before, **0** after, with **0** `[editable]` lines
removed anywhere.

## The widening is blocked by a SECOND, different defect

Re-measured after the fix, with the smoke row's own degradation and comparison, over every tracked
scene:

- **nullbound 194 scenes, 0 failures.** The row can widen there today.
- **trail 116 scenes, 13 failures** — and none of them is the marker. Two shapes:
  - **12: `index=` is never restored on a node that carries `type=`.** All 12 are INHERITED scenes
    (root is `[node name="X" instance=ExtResource(base)]`), where Godot writes `index=` on newly
    ADDED typed nodes too — `[node name="HelpBody" type="VBoxContainer" parent="." index="3"]`.
    `_restore_indexes` skips any node with a `type` attribute, so the attribute is dropped and
    never put back. nullbound has no inherited scenes, which is why this is trail-only.
  - **1: a disagreement, not a loss.** `scenes/modals/rest_moment.tscn` says
    `index="3"` for `Content` under `.../Page/Inner`; the base scene `parchment_card.tscn` gives
    `Inner` three children (`Paper`, `InnerBorder`, `Content`), so the counted answer is `2`. Either
    the file is stale or the count is wrong; settling it needs the engine, which this package never
    boots.

So the round-trip row widens to every tracked scene on nullbound now, and on trail only after the
inherited-scene `index=` case is fixed. That is a separate bug, not part of this one.
