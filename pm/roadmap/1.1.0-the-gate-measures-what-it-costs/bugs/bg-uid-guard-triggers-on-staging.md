---
id: bg-uid-guard-triggers-on-staging
kind: bug
milestone: "1.1.0"
name: uid-guard.yml triggers on staging, a flow agentic-sdlc does not have
status: closed
caused_by:
changelog:
---

# uid-guard-triggers-on-staging

GitHub issue #9.

## Symptom

`install-ci` writes `.github/workflows/uid-guard.yml` triggering on `pull_request: [main]` and
`push: [staging]`, and its header says that is "the flow this toolkit's SDLC declares (staging ->
main)". agentic-sdlc has no `staging`: work lives on `milestone/<id>` branches and the release belt
opens the PR from that branch to the mainline. So the push half of the guard never fires on a
consumer following the kit's flow. A consumer had to find this out and hand-edit the trigger.

## Root cause

`src/godot_devkit/godot/installables/ci-uid-guard.yml` (header + `push.branches`) and the prose in
`install.py` describing it were written against a flow this package no longer pairs with.

## Fix

Push trigger `branches: ["milestone/**"]` — the branch convention agentic-sdlc's `milestone.md`
`branch:` field uses — with a comment saying it is a project-edited list. Drop the `staging -> main`
claim from the installable header and from `install.py`. Amend the existing installable test to hold
the new trigger; no new test. CHANGELOG bullet (a consumer re-installing with `--force` gets the new
trigger; the file is theirs after write, so no one is forced).
