---
id: ft-project-verb-edits-autoloads
kind: feature
milestone: "ms-future-godot-tooling"
name: the project verb edits autoloads
status: planning
reviewed:
depends_on: []
consumed_by: []
changelog:
---

# the project verb edits autoloads

`project.godot` is the third text file a Godot developer edits by hand, and the only one with no
write verb. `autoloads` reads it (`read/autoloads.py`), nothing writes it. Start with the edit
agents make most: `project autoload add <Name> <res://path>` and `project autoload remove <Name>`,
through `core/apply`, same `--dry-run` diff contract as `scene`. Other sections wait for a real ask.

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
