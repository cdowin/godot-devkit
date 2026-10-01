---
id: ft-project-verb-edits-autoloads
kind: feature
milestone: "ms-refs-sees-what-godot-wires"
name: the project verb edits autoloads
status: done
reviewed:
depends_on: []
consumed_by: []
changelog: New autoloads add and autoloads rm declare or remove one project.godot autoload, editing only that line.
---

# the project verb edits autoloads

`project.godot` is the third text file a Godot developer edits by hand, and the only one with no
write verb. `autoloads` reads it (`read/autoloads.py`), nothing writes it. Start with the edit
agents make most: `autoloads add <Name> <res://path>` and `autoloads rm <Name>` (the read noun, as `scene` and `tiles` do),
through `core/apply`, same `--dry-run` diff contract as `scene`. Other sections wait for a real ask.

Proposed in a DeepWiki design review of the repo (suggestion 2):
https://deepwiki.com/search/are-there-improvements-you-wou_13405135-c567-462c-baf2-cd2dca92dd81

## Ship criterion

Add and remove each touch only the `[autoload]` section (creating it when absent), keep every other
byte, refuse a duplicate name or a path that does not exist, and are idempotent; `autoloads` reads
the result back.

## Proof budget

<!-- Roughly how many test cases this feature should cost, written before it is
     built and compared after. Name the tier and the existing module they land
     in; say what the suite already checks and why that is not enough. -->

  cases:
  tier:
  lands in:
  what already covers this:
