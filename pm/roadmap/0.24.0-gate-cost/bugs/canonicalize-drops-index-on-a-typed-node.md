---
id: 0.24.0/bugs/canonicalize-drops-index-on-a-typed-node
milestone: "0.24.0"
name: "`scene canonicalize` never restores `index=` on a node that also carries `type=`, so every inherited scene loses child ordering"
status: open
caught_in: "0.24.0"
fix_milestone:
caused_by:
---

# canonicalize-drops-index-on-a-typed-node

## Symptom

Found 2026-09-04 re-measuring the `canonicalize round trip` smoke row after
`scene-canonicalize-invents-an-editable-marker` was fixed. Over every tracked scene:

- **nullbound: 194 scenes, 0 failures.** The row widens there today.
- **trail: 116 scenes, 13 failures**, none of them the marker.

Twelve of the thirteen are one shape: a node written as
`[node name="HelpBody" type="VBoxContainer" parent="." index="3"]` loses its `index=` and never gets
it back (trail `scenes/modals/council_position_help.tscn:33` is the example).

All twelve are **inherited scenes** — the root is `[node name="X" instance=ExtResource(base)]`.
Godot writes `index=` on newly ADDED typed nodes in an inherited scene, not only on overridden
instance children. nullbound has no inherited scenes, which is the whole reason this is trail-only
and why one consumer is not enough of a corpus.

## Root cause

`_restore_indexes` (`src/godot_devkit/godot/write/scene_canonicalize.py`) skips any node carrying a
`type` attribute. The rule encodes "typed node ⇒ not an instance child ⇒ no index", which holds in a
plain scene and is false in an inherited one, where child ordering is authored against the base's
children and a newly added typed node takes an index among them.

## Fix

`index=` restoration must key off whether the node's parent's children are base-ordered, not off
whether the node carries `type=`. The 12 trail files are the corpus; a fix is right when all 12
round-trip and nullbound's 194 stay green.

Then the smoke row widens to every tracked scene on **both** consumers and stays there —
that widening is the test, and it is the reason this bug exists rather than a pinned known-fail list.

## The thirteenth failure is a different question, and it needs the engine

`scenes/modals/rest_moment.tscn` says `index="3"` for `Content` under `.../Page/Inner`. The base
`scenes/ui/primitives/parchment_card.tscn` gives `Inner` exactly three children (`Paper`,
`InnerBorder`, `Content`), so the counted answer is `2`. Either the committed file is stale or
`BaseScenes.child_index` is wrong.

This package never boots Godot, so it cannot settle which. Do NOT "fix" the counter to agree with
the file or edit the file to agree with the counter — establish which is right first, in the editor,
and record the answer here. Guessing turns a disagreement into a silent wrong answer, which is the
same class of defect as the invented marker this bug is a sibling to.
