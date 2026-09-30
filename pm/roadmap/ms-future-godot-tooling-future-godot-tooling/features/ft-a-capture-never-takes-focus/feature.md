---
id: ft-a-capture-never-takes-focus
kind: feature
milestone: ms-future-godot-tooling
name: a capture never takes focus
status: planning
reviewed:
depends_on: []
consumed_by: []
changelog:
---

# a capture never takes focus

The rest of #37. 1.4.0 PLACES the capture window off screen (`--position`), but macOS and Windows may clamp it back to the edge, and Godot 4 has no command-line flag to stop it taking focus: the documented mechanism is the project setting `display/window/size/no_focus`. Decide how the kit applies that without writing the consumer's project files (for example a documented `override.cfg` contract, or a macOS background launch), and prove it on a real display.

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
