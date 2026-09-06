---
id: 0.25.0/the-agentic-half-leaves/03-the-eight-godot-checks-are-this-packages-own
feature: 0.25.0/the-agentic-half-leaves
milestone: "0.25.0"
name: check all is the Godot roster, and a consumer joins it to make check by config
status: done
owner: claude
depends_on: []
---

# check all is the Godot roster, and a consumer joins it to make check by config

## Acceptance criteria

- `godot-devkit check all` runs the eight Godot gates (`uid`, `tres`, `props`, `defaults`, `rng`, `tres-comment`, `unit-disk`, `test-shape`) with stock defaults; a repo with no `devkit.toml` gets byte-identical output to one declaring them; `[checks] all` narrows the roster; a name outside it exits 2.
- `install-runners` writes a `godot-check` target into `Makefile.tiers` that runs `check all` through the pinned kit, and the seed devkit.toml comment shows `[gates] extra = ["godot-check"]`.
- This repo's `make check` therefore runs agentic-sdlc's roster and then its own eight, through that same mechanism.

## How this is proven

| criterion | tier | the case that proves it | existing? |
|---|---|---|---|
| 1 | unit | roster equals dispatch; stock == declared; unknown name exits 2 | amend the existing gate-roster case |
| 2 | integration | `make check` here runs both rosters | amend tests/test_makefile_gates.py |

## Out of scope

New gates. Eight ship; eight stay.

## Close

done: d951259 — check all is the eight Godot gates stock, narrowed by `[checks] godot` (not `all`: that key is agentic-sdlc's in the same file), unknown name exit 2, stock == declared byte-identical on tests/fixtures/godot_project; this repo's make check runs the pinned roster then godot-check ([gates] extra) over that committed clean project via tools/dev/godot_devkit_on_fixture.sh — [CHECK] 4 then [GODOT] 8.
