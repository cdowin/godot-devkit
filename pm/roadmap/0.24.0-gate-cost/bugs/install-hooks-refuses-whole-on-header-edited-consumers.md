---
id: 0.24.0/bugs/install-hooks-refuses-whole-on-header-edited-consumers
milestone: "0.24.0"
name: "`install-hooks` refuses whole on a consumer with edited project-config headers, so a new hook cannot be added without `--force` and four re-edits"
status: open
caught_in: "0.24.0"
fix_milestone:
caused_by: 0.23.0/usage-capture
---

# install-hooks-refuses-whole-on-header-edited-consumers

## Symptom

v0.23.0 release review m1. On nullbound and trail `install-hooks --diff` shows the two ledger couriers
as pure additions and five files "already current", but the run refuses whole because four files
differ ONLY in their `project config` headers (`cc-godot-sandbox.sh`, `cc-stop-gate.sh`, `pre-push`,
`prepare-commit-msg`). The way through was `--force` then `git checkout --` the four (nullbound
`c402619eb`), or hand-copying two files out of a uv cache.

## Root cause

`src/godot_devkit/repo/install.py` (~:567-574): one collision anywhere in the roster refuses the whole
roster; additions are not distinguished from replacements, and a header-only difference is not
distinguished from a real one.

## Fix

Write the additions even when other destinations collide; report each collision by file; exit 1 so
the caller knows a replacement was withheld. A header-only diff (the `project config` block is the
only hunk) is reported as such — the CHANGELOG bullet says a consumer with edited headers takes
`--diff` → `--force` → re-edit, or better, the installer preserves the header block on `--force`.
Test: a scratch consumer with an edited header + a missing courier — the courier lands, the header
survives, exit 1 names the edited file.
