---
id: "0.25.0"
name: the Godot kit alone
status: planning
depends_on: []
branch: milestone/0.25.0-the-godot-kit-alone
---

# 0.25.0 — the Godot kit alone

This package sheds its agentic half and becomes what its name says: utilities for working with
Godot projects. It gains a CONSUMER PIN on `agentic-sdlc` for its own SDLC — hooks, PM tree,
release — which is dogfooding, never a library import. A scene parser must not drag in a PM tree.

**Breaking, hence 0.25.0 rather than 0.24.1.** Consumers lose `pm`, `check pm`, every `install-*`,
the hooks, the runners and the CI installables from THIS package, and each must add a second pin.
Hard rule 7 names exactly that as the bar.

## Where the agentic half went

`agentic-sdlc`, extracted at this package's `v0.24.0` and standing alone at its own `0.1.0`. Its
`0.2.0` carries the conveyor, the gate telemetry, the gate-ownership migration and the extraction
clean-up — all four moved there with the code, because a release-protocol feature belongs to the kit
that owns the release protocol.

## What has to be decided here, and it is ONE file

Measured 2026-09-04 across the 44 installables and the four install plans:

| plan | files | Godot |
|---|---|---|
| `install-ci` | 4 | 0 |
| `install-agents` | 13 | 0 |
| `install-hooks` | 11 | **1** — `cc-godot-sandbox.sh` |
| `install-runners` | 13 | **12** |

**`install-runners` is a Godot verb** — every runner, the compile sweep, the sandbox scan — and its
only non-Godot member is `Makefile.devkit`. So the whole plan comes here, `cc-godot-sandbox.sh` comes
with it, and **`Makefile.devkit` is the entire middle tier**: it carries the gate FRAMEWORK
(`gdk_gate`, the standard target skeleton, `[gates] extra` dispatch) and the Godot target ROSTER
(`parse`, `lint`, `unit`, `integration`, `scenario`, `capture`) in one file.

**That is the design problem and it is the only one.** Everything else sorts by inspection.

## Ship criterion

1. `src/godot_devkit/repo/` is gone; `godot/` and a duplicated `core/` remain.
2. `install-runners` and `cc-godot-sandbox.sh` ship from here.
3. `Makefile.devkit` is resolved — the framework half reachable from the agentic kit, the Godot
   targets from this one — or the milestone states in writing why not and what blocks it.
4. This repo pins `agentic-sdlc` and its own gates run through that pin.
5. The eight Godot checks run as this package's own, composed the way any consumer composes gates.

## Risks

1. **The middle tier may not decompose cleanly.** Forcing it would put a Godot roster in the agentic
   kit or a gate framework in this one. State the blocker rather than ship a split that re-creates the
   coupling under new names.
2. **This package cannot green until `agentic-sdlc` is pinnable** — the moment `repo/` goes, `pm`,
   `check pm` and `install-*` go with it, and this repo's own gates use them. Hard ordering, not a
   scheduling preference.
