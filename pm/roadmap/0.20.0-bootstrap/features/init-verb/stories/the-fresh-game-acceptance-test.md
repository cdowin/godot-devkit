---
id: 0.20.0/init-verb/the-fresh-game-acceptance-test
feature: 0.20.0/init-verb
milestone: "0.20.0"
name: a blank project after init passes make doctor and make precommit with zero hand edits
status: todo
owner:
depends_on: []
---

# a blank project after init passes make doctor and make precommit with zero hand edits

## Goal
The milestone's ship criterion as a gate: a test builds an empty Godot 4 project (a `project.godot` + `icon.svg`), runs `init`, and asserts `make -n doctor`, `make -n precommit`, and `make -n` of every standard target succeed with zero hand edits; `consumer-smoke` gains a "fresh project" probe that does the real `make doctor` where Godot is present.
## Commit prefix
`feat(0.20.0/init-verb/S2):`
## Size
s
