---
id: 0.19.0/install-runners/sandbox-home-and-project-file
feature: 0.19.0/install-runners
milestone: "0.19.0"
name: A headless run gets a self-destroying HOME and project.godot comes back
status: todo
owner:
depends_on: []
---

# A headless run gets a self-destroying HOME and project.godot comes back

## Goal

A headless run gets a per-run self-destroying sandbox HOME, and a `project.godot` the engine
re-serialised comes back unless the consumer deliberately edited it.

## Port from nullbound `tools/dev/_common.sh` (`271baf4ec`)

`nullbound_sandbox_home`, `nullbound_on_exit` + `_nullbound_run_exit_hooks`,
`_nullbound_destroy_run_home`, `_nullbound_reap_stale_run_homes`, `nullbound_sandbox_tmpfile`,
`nullbound_timeout_is_hang`, `nullbound_run_bounded`, `_nullbound_snapshot_project_file`,
`_nullbound_normalize_project_file`, `nullbound_restore_project_file` → `gdk_*`. The restore
compares normalised content against `git show HEAD:project.godot` and leaves a real edit alone,
printing one line either way. trail's `trail_sandbox_home` / `trail_run_bounded` are the ancestor —
the ported shape must cover both callers.

## Gotcha

`cc-godot-sandbox.sh` (an installable) refuses a bare engine boot outside the sandbox function;
the function NAME it admits must be the new `gdk_sandbox_home`, with the consumer-prefixed names
gone — update the hook's admit list and its corpus in the same story.

## Verification

`make test`, `make gates`, `bash installables/cc-godot-sandbox.sh --self-test`.

## Commit prefix

`feat(0.19.0/install-runners/S2):`

## Size

m
