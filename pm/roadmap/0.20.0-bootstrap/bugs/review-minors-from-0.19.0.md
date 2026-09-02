---
id: 0.20.0/bugs/review-minors-from-0.19.0
milestone: "0.20.0"
name: The 0.19.0 release review's 8 MINOR + 4 NIT findings on gdk_runners.sh, import_cache.sh and the sandbox hook
status: open
caught_in: "0.20.0"
fix_milestone: "0.20.0"
---

# review-minors-from-0.19.0

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

`pm/roadmap/0.19.0-runners/review.md` (RELEASE-WITH-FIXES; MAJOR-1 landed before the tag) lists
12 findings that shipped in v0.19.0: `gdk_restore_project_file` reverts a same-line-set reorder made
during the run; `gdk_gate_capture` under `set -euo pipefail` exits with no verdict; the hook still
false-BLOCKs a quoted multi-line string; `stale_cache_artifacts` is second-granular on bash 3.2;
`gdk_rebuild_import_cache` runs unbounded with no timeout binary; `import_cache.sh` never checks
`project.godot` exists at its root; the CHANGELOG's folded 0.18.1 bullet carries a stale corpus count;
installed runners lack the exec bit; `kill -0` EPERM reaps another user's HOME; the `.uid` churn split
is an unanchored substring; the sandbox root is `$PWD`-relative. The record is the source of truth.

## Root cause

Each is its own; fix them as `generic-runners` touches the library (S1/S2) and close this bug in the same feature, one test per finding.

## Fix
