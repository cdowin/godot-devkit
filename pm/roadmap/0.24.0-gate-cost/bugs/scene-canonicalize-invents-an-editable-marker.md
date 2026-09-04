---
id: 0.24.0/bugs/scene-canonicalize-invents-an-editable-marker
milestone: "0.24.0"
name: "`scene canonicalize` adds an `[editable path=…]` the original file did not carry, on 21 of 304 tracked consumer scenes"
status: open
caught_in: "0.24.0"
fix_milestone:
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

Not diagnosed. The shape of it is that canonicalization is deriving the editable-instance markers
from the node tree rather than preserving what the source stated — so a scene that instances another
and does NOT mark a child editable gets one anyway.

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

Diagnose first — 21 real files across two consumers is a good corpus, and the question to answer is
whether the marker is derived from the node tree, copied from a stale index, or added by a writer
that does not distinguish "this instance has overrides" from "this instance is editable".

Then: the round-trip test widens from one scene to every tracked scene, and stays there.
