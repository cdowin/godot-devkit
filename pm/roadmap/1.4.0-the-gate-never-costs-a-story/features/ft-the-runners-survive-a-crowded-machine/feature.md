---
id: ft-the-runners-survive-a-crowded-machine
kind: feature
milestone: "1.4.0"
name: the runners survive a crowded machine
status: done
reviewed: docs/reviews/2026-09-29-1.4.0-the-runners-survive-a-crowded-machine.md
depends_on: []
consumed_by: []
changelog:
---

# the runners survive a crowded machine

Issues: #24, #31, #32, #35 (shell side).

Several agent lanes running gates on one machine break the runner library in four ways. None of
them is a code fault in the consumer:

- **#24** `gdk_runners.sh --self-test` (`:861`) builds a scratch git fixture with a bare `git init
  -q .`. Under a git hook, `GIT_DIR`/`GIT_INDEX_FILE` are exported, so the fixture re-initialises
  the HOST repo and writes `core.bare = true` into the shared config. (The same pattern in
  `integration.sh:668` is fixed by the diff-slice lane, which owns that file.)
- **#31** `gdk_pid_is_live 1`: under a macOS seatbelt sandbox, `kill -0` and `ps -p` on a foreign
  pid both fail, so the helper reads a live pid as dead. The self-test's two foreign-pid cases go
  red and every precommit is red for that agent.
- **#32** The unit tier's 180 s `HARD_TIMEOUT` trips when three lanes boot Godot at once, and the
  timeout message does not name `GDK_UNIT_TIMEOUT`, so the agent stops instead of correcting.
- **#35** A gate's `git status`, killed mid-refresh, leaves `.git/index.lock` behind.

## Decided (do not re-plan)

- **Git isolation (#24).** Every git call a self-test makes on a scratch fixture uses `git -C
  "<dir>"` AND runs with `GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR
  GIT_ALTERNATE_OBJECT_DIRECTORIES` unset (`env -u` is not on every platform, so use a subshell
  `unset`). Audit every installable `.sh` in this lane's files for the same pattern. Add a
  self-test case: run the fixture with `GIT_DIR` pointing at a throwaway repo and assert that the
  throwaway's config has no `core.bare = true` afterwards. Report any site in files this lane does
  not own; do not edit it.
- **Liveness (#31).** Treat a pid as dead only on POSITIVE evidence it is gone. Read `kill -0`'s
  error: "No such process" (ESRCH) means dead. Anything else (EPERM, or a sandbox denial) falls
  through to `ps -p`. If `ps` itself cannot see the process table (probe `ps -p $$`; if that fails
  the environment is sandboxed), the answer is LIVE: a reaper that keeps a dead HOME costs disk,
  and one that deletes a live HOME costs data. The self-test's foreign-pid cases stay. When the
  environment cannot observe pid 1 at all, they print a `SKIP — <reason>` line instead of passing
  or failing silently, and the SKIP names the sandbox.
- **Unit timeout (#32).** Two parts:
  1. The HARD_TIMEOUT line names the override: `… exceeded ${N}s, killed — rerun with
     GDK_UNIT_TIMEOUT=<2N> if the machine is loaded`.
  2. The default scales with load. When `GDK_UNIT_TIMEOUT` is unset, the base is 180 s, multiplied
     by `ceil(loadavg_1min / ncpu)` clamped to [1, 3]. Read `sysctl -n vm.loadavg` / `hw.ncpu` on
     macOS and `/proc/loadavg` / `nproc` on Linux, and when the load is unreadable use the base.
     The run's start line prints the chosen value and why (`timeout 360s (load 2.1x)`). An explicit
     `GDK_UNIT_TIMEOUT` is never scaled.
- **Index lock (#35).** `gdk_runners.sh` does `export GIT_OPTIONAL_LOCKS=0` at source time, so
  every runner that sources it reads git without taking the optional index lock. Report any runner
  that runs git BEFORE it sources the library (the owning lane fixes it). The Python side is the
  read-verbs lane's.
- Minor bump: new output shapes (the SKIP line, the timeout start line).

## Ship criterion

- `runners-self-test` green; the new GIT_DIR case fails against HEAD.
- A self-test run with `GIT_DIR` exported to a throwaway repo leaves that repo's config unchanged.
- `gdk_pid_is_live` returns live for a pid whose `kill -0` fails with anything but ESRCH.
- `unit.sh` prints its chosen timeout and names `GDK_UNIT_TIMEOUT` on a HARD_TIMEOUT.

## Proof budget

  cases: 3 (GIT_DIR isolation, EPERM-is-live, timeout scaling arithmetic)
  tier: the runners' own `--self-test` corpora (a temp tree, no Godot)
  lands in: gdk_runners.sh --self-test, unit.sh --self-test
  what already covers this: the pid-1 cases exist and pass on an unsandboxed laptop. That is the bug.
