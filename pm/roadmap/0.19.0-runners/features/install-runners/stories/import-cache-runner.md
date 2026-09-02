---
id: 0.19.0/install-runners/import-cache-runner
feature: 0.19.0/install-runners
milestone: "0.19.0"
name: The import-cache rebuild is a bounded runner with an outcome check
status: todo
owner:
depends_on: []
---

# The import-cache rebuild is a bounded runner with an outcome check

## Goal

`make import-cache` in a consumer rebuilds the Godot import cache inside the sandbox, bounded,
with an outcome check and a churn report.

## Port from nullbound (`271baf4ec`)

`tools/dev/runners/import_cache.sh` (143 lines) + `nullbound_rebuild_import_cache` → an
installable `import_cache.sh` calling `gdk_*`. Keeps: the 300s bound (env-overridable), the
outcome check (both `.godot/uid_cache.bin` and `global_script_class_cache.cfg` must come out
newer — the engine's exit code is swallowed), the churn report splitting `.gd.uid` sidecars
(commit) from re-serialised `.tres`/`.tscn`/`project.godot` (revert), listing only paths this run
dirtied.

## Verification

`make test`; a consumer-smoke probe that runs `make import-cache` in both checkouts and asserts a
clean `git status` after.

## Commit prefix

`feat(0.19.0/install-runners/S3):`

## Size

s
