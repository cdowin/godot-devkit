---
id: 0.24.0/bugs/self-hosting-has-no-arm-or-verify-target
milestone: "0.24.0"
name: '"install-hooks IS self-hosted" has no target that arms or verifies it'
status: open
caught_in: "0.24.0"
fix_milestone:
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
