---
id: 0.20.0/init-verb/the-fresh-game-acceptance-test
feature: 0.20.0/init-verb
milestone: "0.20.0"
name: a blank project after init passes make doctor and make precommit with zero hand edits
status: review
owner: developer
depends_on: []
---

# a blank project after init passes make doctor and make precommit with zero hand edits

## Goal
The milestone's ship criterion as a gate: a test builds an empty Godot 4 project (a `project.godot` + `icon.svg`), runs `init`, and asserts `make -n doctor`, `make -n precommit`, and `make -n` of every standard target succeed with zero hand edits; `consumer-smoke` gains a "fresh project" probe that does the real `make doctor` where Godot is present.
## Commit prefix
`feat(0.20.0/init-verb/S2):`
## Size
s

## Done

done: 30908b6 — `tests/test_fresh_project.py`: an empty Godot 4 project, `init`,
then `make -n` over the whole standard set read off the INSTALLED include (26,
count asserted), `make -n doctor` / `precommit` named separately because they
ARE the criterion, the default goal, `make help`, and `[gates] extra` on a real
init'd tree. A file census before and after proves the dry runs stayed dry —
nothing written, no `.gate-reports/`, the stock uvx `DEVKIT` never resolved.

`make smoke` gained `fresh_project()`: init in scratch (never in a consumer
checkout), then the REAL `make doctor`. It splits the verdict — an init-owned
FAIL (hooks unarmed, git not pointed at them, a short hook census) is the
probe's finding; a missing godot/gdlint/uv is the host's and is NAMED, not
counted. `godot` absent is a loud NOT RUN. Measured here: doctor exits 0 on a
just-init'd project, 6/6 hooks armed. 6 cases; suite 1034 passed.
