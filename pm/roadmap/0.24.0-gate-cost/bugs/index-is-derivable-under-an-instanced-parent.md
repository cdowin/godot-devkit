---
id: 0.24.0/bugs/index-is-derivable-under-an-instanced-parent
milestone: "0.24.0"
name: "a created node whose PARENT is an instanced subtree takes a derivable `index=`, and canonicalize drops it"
status: open
caught_in: "0.24.0"
fix_milestone:
caused_by: 0.24.0/bugs/canonicalize-drops-index-on-a-typed-node
---

# index-is-derivable-under-an-instanced-parent

## This supersedes a conclusion in its sibling

`bugs/canonicalize-drops-index-on-a-typed-node.md` fixed a real defect (`_instance_host` never
considered the root) and then concluded that the remaining 12 created-node `index=` attributes are
**authored state that no rule reproduces**, so the tool must write nothing. **That conclusion is
wrong for 7 of them, and the corpus says so.** The fix that landed stays; this adds the restoration
that analysis ruled out.

The error was reading the twelve as one population. They inherit three different bases, and the
mismatches cluster entirely in one of them.

## The measurement

Every trail scene carrying a root-level `index=`, against its own base's root child count:

| base | root children | inheritors | index claimed | verdict |
|---|---|---|---|---|
| `panel_card.tscn` | 2 | `dispatches`, `lineage_record`, `expedition`, `quartermaster`, `field_journal`, `trail_council` | `2` | **append-correct** |
| `side_menu_modal.tscn` | 3 | `council_position_help` | `3` | **append-correct** |
| `side_menu_modal.tscn` | 3 | `dossier`, `settlement_menu`, `settlement_menu_compound` | `2` | **mismatch — an append is 3** |

So a rule reproduces **7 of the 10** exactly. The sibling bug's "no rule reproduces them" rested on
the three mismatches and generalised from them to the whole set.

## Root cause

The discriminator is not *"is this node created?"* — it is *"is this node's parent an instanced
subtree?"* A node the scene creates under a plain local parent has no ordinal, because no base
places its siblings. A node the scene creates under an **instanced** parent is positioned among that
base's own children, and the ordinal is derivable from the base.

`_restore_indexes` skips on `type=`/`instance=` presence, which conflates the two.

## The three mismatches are trail's data, not this package's defect

`dossier`, `settlement_menu` and `settlement_menu_compound` claim `index="2"` against a 3-child
base. `2` is exactly the append value for `panel_card.tscn`, which strongly suggests they were
copied from one of the six panel_card siblings and re-pointed at `side_menu_modal` without updating
the number — `Wash` entered that base the day before `dossier.tscn` was first authored.

Same class as `scenes/modals/rest_moment.tscn`, which trail already repaired (`77f0f051`). **Do not
"correct" them from here** — this package does not write into a consumer, and a tool that rewrites a
number it disagrees with is the invention failure this whole line of bugs is about. They are trail's
to repair, and the widening waits on that.

## The one thing the corpus cannot settle

Four structurally similar nodes carry NO index — `force_resolution.tscn`'s
`MontageView`/`ResultsView`/`Timer` and `game_over.tscn`'s `Center`. Both files are now green (the
`_instance_host` fix), so they are not among the ten, but they are an argument that the engine does
not *always* emit `index=` in this position.

**Confirm before the rule ships**: re-save one of the seven append-correct scenes in the Godot editor
and check that its `index=` survives. That is a one-minute check a human runs and neither package
can. If it does not survive, this bug is wrong and the sibling's conclusion was right after all.

## Fix

Key `index=` restoration off whether the node's parent is an instanced subtree, not off whether the
node carries `type=`/`instance=`. Correct when: the 7 append-correct files round-trip, the 3
mismatches still fail (they are data bugs and must stay visible), nullbound's 194 stay green, and
**nothing gains an `index=` it did not have** — the sibling bug measured a naive "next free slot"
fallback inventing 505 attributes across the two trees, which is the failure mode to stay clear of.

Then the round-trip smoke row widens to every tracked scene on both consumers, once trail's three
land.
