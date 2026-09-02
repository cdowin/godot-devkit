---
id: "0.20.0"
name: bootstrap
status: building
depends_on: ["0.19.0"]
branch: milestone/0.20.0-bootstrap
---

# bootstrap

Filed 2026-09-02. Measured against nullbound (59 Makefile targets, 27 shell scans, 9 workflows) and
trail (its own Makefile, 3 scans, 4 workflows): the devkit gives a fresh Godot project the TOOLS
(the CLI, the check gates, the PM tree) and the PROCESS (hooks, agents, skills, one CI workflow),
but not the SCAFFOLDING — the Makefile, the Godot/GUT runners, the generic scans, and the CI set
both games actually run. Both consumers re-invented all four; twenty Makefile targets in each are
identical one-line pass-throughs, `auto-tag` / `semver-gate` / `uid-guard` exist twice, and neither
uses the `verify.yml` that `install-ci` writes.

## The ownership rule, applied one layer up

Devkit-owned files are overwritten on `--force`; project-owned files are written once. The
Makefile INCLUDE is devkit-owned; the project's `Makefile` is project-owned and two lines long
plus its own targets. Runners and generic scans are devkit-owned. Project scans (nullbound's 19
architecture scans) stay project-owned and join the gate list by config, never by fork. That is
the "every Godot project is the same" guarantee without a second name for anything.

## Ship criterion

**The fresh game.** An empty Godot 4 project: `godot-devkit init`, then `make doctor` and
`make precommit` are green with zero hand edits. **The existing games.** `godot-devkit install-*
--diff` on nullbound and trail shows exactly the drift each carries, and adopting deletes it — both
consumers' Makefiles shrink to the include plus their own targets, their duplicated workflows and
runners are gone, and `make consumer-smoke` is green on both.

## Risks

- Godot cannot boot in the devkit's own CI — the fresh-game test asserts the written file set and
  `make -n` of every standard target; the real boot is `consumer-smoke`.
- The include must not drag GUT-specific targets into a project without GUT: targets gate on
  `[runners]` config, not on directory presence.
