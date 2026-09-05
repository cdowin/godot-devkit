---
id: 0.24.0/bugs/self-hosting-has-no-arm-or-verify-target
milestone: "0.24.0"
name: '"install-hooks IS self-hosted" has no target that arms or verifies it'
status: fixed
caught_in: "0.24.0"
fix_milestone: 0.24.0
caused_by: 0.23.0/usage-capture
---

# self-hosting-has-no-arm-or-verify-target

## Symptom

v0.23.0 release review m2. `CLAUDE.md` says the hook corpus is self-hosted, but `core.hooksPath` was
unset in every checkout until 2026-09-04 (armed by hand: `bash tools/setup-hooks.sh` in the main
checkout), this repo's Makefile has no `hooks`/`doctor` target, and nothing in `make precommit`
notices an unarmed tree.

## Root cause

The claim is a sentence; the consumers got `make doctor` from `Makefile.devkit`, this repo never
grew the equivalent.

## Fix

A `make hooks` target (`bash tools/setup-hooks.sh`) and a doctor-style check that `core.hooksPath`
points at `tools/hooks` with every entry executable, reported as one verdict line and part of
`make gates`, so an unarmed checkout is a red line, not a surprise at the first push of `main`.

## Resolution

`make hooks` (`bash tools/setup-hooks.sh`) is the repair; `check hooks` is the report, in this repo's
`[checks] all` so it runs inside `make gates`, `precommit` and `milestone`. Registered stock-OFF, so
no consumer's gate changes on a pin bump — arming is a decision each makes once, and reddening a repo
that has not made it is the roster being wrong for the repo.

The gate asks three questions, not one. `core.hooksPath` resolving to `tools/hooks` is the first;
every entry carrying an exec bit is the second (git skips one without it in silence). The third is
that the hook still RUNS, because ARMED is not WORKING: `install.py`'s own measurement showed a
0.16.0 project-config header under a current body dropping four keys the body reads under `set -u`,
so the hook dies on `unbound variable` and exits 1 where only 2 is a BLOCK — on disk, executable, and
stopping nothing. Each `cc-*.sh` is fed a payload it cannot read and must fail OPEN at 0, which
executes the whole file, header included; anything else in the directory is a git hook whose argv
contract is git's, so it is parsed and the verdict says that is all that was asked.

Four states measured against a scratch clone at `aaec4bd`, never this checkout:

| state | verdict |
|---|---|
| unarmed, at `aaec4bd` | `[GATES] 3 check(s) PASS` — nothing looks; `make hooks` does not exist |
| unarmed, with the fix | `UNARMED  core.hooksPath is unset …` — exit 1 |
| armed, one entry not executable | `NOT EXECUTABLE tools/hooks/pre-push — core.hooksPath skips it in silence` |
| armed, executable, dead header | `DEAD tools/hooks/cc-godot-sandbox.sh exited 1 … it is installed and it stops nothing: … unbound variable` |
| armed and whole | `[GATES] 4 check(s) PASS` |
