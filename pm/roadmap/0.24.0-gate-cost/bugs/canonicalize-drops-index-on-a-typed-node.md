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

The 13 are three different things, not one, and only the first is a defect in this package:

| | files | nodes | derivable offline? |
|---|---|---|---|
| an override directly under an INHERITED root, never resolved at all | 2 | 3 | **yes** — fixed below |
| an `index=` on a node the scene CREATES (`type=` / `instance=`) | 10 | 12 | no — authored state |
| an `index=` naming a slot the base cannot reach (`rest_moment.tscn`) | 1 | 1 | no — the file is wrong |

## Root cause

**`_instance_host` (`godot/write/scene_canonicalize.py`) walked a node's ancestors down to
depth 1 and stopped, so it never considered the root** — `range(len(path) - 1, 0, -1)`.
An inherited scene's root IS an instancing ancestor: it is written
`[node name="X" instance=ExtResource(base)]` and its children ARE the base's children.
So an override written `[node name="PaperBg" parent="."]` had no host, lost its `index=`,
and got `UNRESOLVED … no instancing ancestor was found` instead of the ordinal the base
plainly gives it. Live on trail: `scenes/moments/force_resolution.tscn` (`PaperBg` 0,
`Payload` 2) and `scenes/moments/game_over.tscn` (`Payload` 2). nullbound has 10 inherited
scenes — the earlier claim that it has none is wrong — but all 10 are root-only overrides
with no children written at all, which is why nothing there was ever red.

### The other half of the filed diagnosis does not survive its own corpus

The bug read: *Godot writes `index=` on newly ADDED typed nodes in an inherited scene, and
`_restore_indexes` skips any node carrying a `type` attribute.* The skip is real. It is not
what loses those 12 attributes, and removing it does not put them back, because **nothing in
the file says where a created node goes.** A node with `type=` is built by this scene and a
node with `instance=` is instantiated by it; no base places either, so there is no ordinal to
count. Measured over both trees:

- **12 created nodes carry an authored `index=`** — 10 typed bodies directly under an
  inherited root, plus 2 instanced rows under `dossier.tscn`'s wholly-authored
  `DossierBody/Columns/Right`, which no base scene mentions at any depth.
- **No rule reproduces them.** The 6 scenes inheriting `panel_card.tscn` (root: `Card`,
  `MotionPlayer`) say `index="2"`, and `council_position_help.tscn` inheriting
  `side_menu_modal.tscn` (root: `Wash`, `Card`, `MotionPlayer`) says `index="3"` — both the
  base's own child count. But `dossier.tscn`, `settlement_menu.tscn` and
  `settlement_menu_compound.tscn` inherit that same 3-child base and say `index="2"`, a slot
  no count reaches. Not staleness: `Wash` entered the base 2026-05-27, the day before
  `dossier.tscn` was first authored, and never left.
- **The opposite direction is in the same repo, the same week.** 4 structurally identical
  siblings — an added `type=`d node under an inherited root — carry NO index:
  `force_resolution.tscn`'s `MontageView`/`ResultsView`/`Timer` and `game_over.tscn`'s
  `Center`, all appended after their base's 4 root children. A rule that writes the 12 writes
  these 4 too.
- **The editor-written half of the corpus says no.** All 116 trail scenes carry a `;` comment,
  so none has been through `ResourceSaver` since it was written; 0 of nullbound's 194 do. In
  nullbound — every file editor-written — **113 created nodes sit inside an instanced sub-tree
  and not one carries an `index=`.**

So the 12 are authored state, exactly like the `[editable]` marker of the sibling bug, and
restoring them would be that same defect in the same module twice. Measured: a probe that
falls back to the plausible "next free slot" invents **505** `index=` attributes across the
two trees (319 trail, 186 nullbound) — and still gets 3 of the 12 wrong.

What the corpus canNOT settle, and what would need the engine: whether Godot's writer ever
emits `index=` on a created node in an inherited scene. Nothing here depends on the answer —
the tool has no evidence either way, so it writes nothing either way.

## Fix

`_instance_host` considers the root (`range(len(path) - 1, -1, -1)`). The created-node skip
stays and now says what it encodes. Direction census, degrade -> canonicalize over every
tracked scene:

| | authored `index=` | restored | invented | unresolved index losses |
|---|---|---|---|---|
| trail, before | 17 | 1 | 0 | 3 |
| trail, after | 17 | **4** | 0 | **0** |
| nullbound, before/after | 39 | 39 | 0 | 0 |

Round-trip census: trail **13 -> 11** failing of 116, nullbound **0 of 194** throughout.

Five tests in `tests/test_canonicalize.py::AnInheritedRootIsAnInstanceHost`, over an inherited
fixture built on a 3-child base. **3 red against `99cce63`**: an override under an inherited
root, an override of a base GRANDchild counted through the root, and the whole inherited scene
round-tripping byte-for-byte. **2 controls green both sides**: a created node gains no index,
and an override the base does not place is refused by name rather than guessed. The first
control is proven by mutation — an over-correction reds it with `index="0"` on the `type=`d
node and `index="2"` on the instanced one.

## The thirteenth failure — settled from the data, in the counter's favour

`scenes/modals/rest_moment.tscn` says `index="3"` for `Content` under
`Content/PageHost/PageColumn/Page/Inner`, where `Page` instances
`scenes/ui/primitives/parchment_card.tscn`. Three facts, all from the committed files:

1. The base gives `Inner` exactly three children — `Paper`, `InnerBorder`, `Content` — **in
   every commit of its history** (`dd913d9d` 2026-05-26, `d2c7f279` 2026-06-13, `69ab7815`
   2026-07-04). `Content` is ordinal 2.
2. `rest_moment.tscn` adds NO child under `.../Page/Inner`; every other node it writes there
   is a descendant of `Content`. So at load `Inner` has exactly 3 children, indices 0..2.
3. The `index="3"` line entered on 2026-08-23 (`0d6b6668`), a month AFTER the base last
   changed. It is not base drift — the base already looked like this when the line was written.

**There is no arrangement of `Inner`'s load-time children that puts `Content` at 3.** Every
in-range answer is 0, 1 or 2, and the base names 2. So `BaseScenes.child_index` is right and
the committed value is wrong — a hand-authored number in a hand-authored file (see the `;`
comment census above), not a counter defect. **Nothing was changed in trail**: this package
does not write into a consumer, and the repair is trail's to make.

Still an engine question, and it does not move the direction: what Godot DOES with an
out-of-range `index=` at load (clamp, skip, or error).

## The widening is blocked on trail, and it is 11 files, not 1

`make smoke`'s `canonicalize round trip` row stays pinned to one scene per consumer. It can
widen on nullbound (194/194 today) and cannot on trail, where 11 of 116 still fail: 10 for the
authored created-node `index=` above and 1 for `rest_moment.tscn`. An asymmetric row or a
pinned known-fail list is the widening in name only, so the census is reported instead of the
row being weakened to fit it.

Three ways forward, none of them this package's to take alone:

- **trail repairs its 11 files** — drop the 9 created-node indexes that are already the slot
  the loader would pick anyway, decide the 3 that are not, and correct `rest_moment.tscn`'s
  out-of-range 3. Then the row widens on both, unchanged.
- **the row's degradation matches the module's stated claim** — it strips `index=` from every
  `[node ` line, while both the comment above it and the module docstring say the loss is
  `index=` on instance-child overrides. Narrowing it would go green today, and it would remove
  12 nodes from the census on a premise this package cannot prove.
- **an engine answer** on whether `pack()` emits `index=` for a created node, which would
  settle which of the two above is honest.
