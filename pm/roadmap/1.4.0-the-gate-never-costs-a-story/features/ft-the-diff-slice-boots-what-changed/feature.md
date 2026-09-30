---
id: ft-the-diff-slice-boots-what-changed
kind: feature
milestone: "1.4.0"
name: the diff slice boots what changed
status: done
reviewed: docs/reviews/2026-09-29-1.4.0-the-diff-slice-boots-what-changed.md
depends_on: []
consumed_by: []
changelog:
---

# the diff slice boots what changed

Issues: #16, #33, #34, #24 (the `integration.sh` site).

`integration.sh --diff` is the merge-batch gate, and it spent most of a working day (NullBound
0.93.7) on boots that did not need to happen:

- **#33** Any edit under `tests/support/` matches `GDK_SCENARIO_SUBSTRATE_RE` and boots all 166
  scenarios. One case was a fixture that 2 scenarios load: 2,222 s of CPU.
- **#34** 9 of 9 red scenarios in one day were load flakes, and each one passed when rerun alone.
  Agents stopped whole stories on them.
- **#16** After merging worktree lanes, every scenario fails with `uid index is STALE, not cold`.
  The repair (`import-cache`) runs inside the parallel sweep, where it cannot remove the shared
  `.godot/`, instead of once before the sweep.
- **#24** `integration.sh:668`: the self-test's `mono` fixture runs a bare `git init -q .` that
  re-initialises the host repo under a git hook. See the runners lane for the isolation rule.

## Decided (do not re-plan)

- **Fixture slicing (#33).** The default `GDK_SCENARIO_SUBSTRATE_RE` drops `^tests/support/`. What
  stays whole-tier ground is the runners and the scenario base/runner scripts. Name them in the new
  default, and read the base's path from the existing config if it has one. A new env var,
  `GDK_SCENARIO_FIXTURE_DIR` (default `tests/support/`), marks the fixture root. A touched file
  under it selects every scenario that references it, TRANSITIVELY: a textual scan of
  `preload("res://…")` / `load("res://…")` / `extends "res://…"` and of `ext_resource path=` in
  `.tscn`/`.tres`, followed through the fixture root. This is pure text; nothing boots.
  **Rule 4:** a touched fixture that NO scenario references falls back to the whole tier, with one
  line saying why (`fixture <path> is referenced by no scenario — booting the tier`), because a
  reference the scan cannot see (a built path) must not become a silent zero. A consumer that
  overrides `GDK_SCENARIO_SUBSTRATE_RE` keeps its value. The selection prints its census: how many
  scenarios each fixture selected.
- **Rerun alone once (#34).** After the parallel sweep, each FAILED scenario is rerun once, alone,
  serially. If it passes alone, it counts green and prints `  FLAKE  <name> — failed in the sweep,
  passed alone`. If it fails again, it is red as today. The rerun is on by default for `--diff`;
  `--all` and named runs do not rerun. `--no-rerun` turns it off, and so does
  `GDK_INTEGRATION_RERUN=0`. The verdict line counts flakes (`N passed (K flaky)`). No ledger row:
  the ledger is agentic-sdlc's, and the FLAKE line is the grep-able record.
- **Repair before the sweep (#16).** Before a `--diff`/`--all` sweep boots anything, the runner
  checks whether the import cache is stale: `.godot/uid_cache.bin` is missing, or any tracked
  `*.uid`, `*.import` or `project.godot` is newer than it. If so, it runs the sanctioned entry point
  (`import_cache.sh`, the installed sibling) ONCE, serially, and prints one line saying it did and
  why. If that fails, the sweep does not start (exit 1, naming the repair). The in-sweep detection
  stays as the backstop. Contract with the import lane: `import_cache.sh` keeps its CLI and exit
  codes (0 refreshed, 1 not, 2 harness error).
- **#24 site.** `git -C "$mono"` for every call, with the git environment unset in the subshell
  (the same rule as the runners lane), plus the same kind of assertion in this file's self-test.
- Minor bump: a new flag, a new env var, the FLAKE line, and a changed default.

## Ship criterion

- `integration.sh --self-test` covers: a fixture referenced by 1 of 3 scenarios selects exactly that
  one; a transitive (fixture → fixture → scenario) reference selects it; an unreferenced fixture
  falls back to the whole tier with its line; a flaky stub (fails first, passes second) prints
  FLAKE and counts green; a stub that fails twice stays red; `--no-rerun` reports it red at once.
- The stale-cache precheck is proven with stub timestamps, booting no Godot.
- The `mono` fixture leaves a `GIT_DIR`-exported host repo untouched.

## Proof budget

  cases: ~7, all in integration.sh --self-test (stubbed godot, temp trees)
  tier: the runner's self-test corpus
  lands in: src/godot_devkit/godot/installables/integration.sh
  what already covers this: the substrate regex and slice cases; amend them rather than adding new ones
