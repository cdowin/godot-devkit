---
id: 0.24.0/bugs/ci-verify-installs-no-godot
milestone: "0.24.0"
name: "the installed verify.yml runs make milestone with uv and no Godot, so a Godot consumer is red on every PR"
status: open
caught_in: "0.24.0"
fix_milestone:
caused_by:
---

# ci-verify-installs-no-godot

## Symptom

Found by trail adopting v0.23.0 (2026-09-04): `install-ci`'s `verify.yml` is checkout → `setup-uv`
→ `make milestone`. A consumer's `make milestone` boots the engine (`parse`, `warnings`, `unit`,
`integration-all`) and shells out to gdlint/shellcheck, none of which the runner has — red on every
PR, and the red says nothing about the consumer's code. nullbound's copy works only because it was
hand-edited after install (`.github/workflows/verify.yml:36` — `chickensoft-games/setup-godot@v2`
with `version: "4.6.2"`, plus `uv tool install gdtoolkit` and `apt-get shellcheck`), which is the
"the file is yours now" escape doing the job the installable should.

## Root cause

`src/godot_devkit/repo/installables/ci-verify.yml` is this package's OWN CI shape (a Python package
that needs uv and nothing else), self-installed here and then shipped unchanged to consumers whose
`make milestone` is a Godot gate. Chris: "does that mean the godot devkit isn't shipping with the idea
of godot in mind?" — for this one file, yes.

## Fix

The installable carries the consumer's toolchain, keyed off the project, so the same file is right in
both trees: a `setup-godot` step (nullbound's shape) whose version is a project-config value at the
head of the file — default derived from `project.godot` `config/features` (`"4.6"`) with the patch
level as the one knob a consumer edits — and whose `if:` is `hashFiles('project.godot') != ''`, so
this repo (no `project.godot`) skips it; the gdlint + shellcheck install the same way. `tests/
test_ci_workflows.py` already runs the installables' steps under bash — add the case: a fresh Godot
project's rendered `verify.yml` has the Godot step, this repo's does not. The consumer follow-up is
`install-ci --diff` → `--force` and re-applying nothing (nullbound's hand edit becomes the shipped
text). A minor bump: a new step in a shipped file, nothing a consumer must edit to survive.
