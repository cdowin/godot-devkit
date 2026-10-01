---
id: ft-refs-reads-scene-connections
kind: feature
milestone: ms-future-godot-tooling
name: refs reads scene connections
status: planning
reviewed:
depends_on: []
consumed_by: []
changelog:
---

# refs reads scene connections

From the 1.4.0 read-verbs review (M3): `refs` never reads a `.tscn`'s `[connection signal=… method=…]` sections, so a signal and a handler wired in the editor read as zero references, and deleting the handler breaks the connection at runtime with no parse error. The fix is a scene-side scan in `scan_scene_refs` (read/refs.py), not a regex.

## Ship criterion

<!-- What "done" means for this feature. -->

## Proof budget

<!-- Roughly how many test cases this feature should cost, written before it is
     built and compared after. Name the tier and the existing module they land
     in; say what the suite already checks and why that is not enough. -->

  cases:
  tier:
  lands in:
  what already covers this:
