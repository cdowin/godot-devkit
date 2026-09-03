---
id: 0.21.0/release-gates
milestone: "0.21.0"
name: the semver gate admits a closed milestone or a hotfix, and D8 admits a hotfix
status: done
reviewed: pm/roadmap/0.21.0-release-integrity/features/release-gates/decisions.md
phase:
depends_on: []
consumed_by: []
---

# the semver gate admits a closed milestone or a hotfix, and D8 admits a hotfix

What it makes true: the shipped `ci-semver-gate.yml` compares versions component-wise at any length
(a missing component is 0, a non-numeric component refuses) and admits exactly two things on a merge
to the mainline — the id of a `done` milestone under `PM_ROADMAP`, or main's version plus one hotfix
component — with a done milestone outranking the hotfix reading of the same string. `check pm` D8
accepts `<milestone id>.N` for an id in the tree beside the building milestone's own id, so a
hotfix branch cut from main passes the pre-push gate.

Why: nullbound's 0.90.2 release reached main wearing `0.90.3` — the next milestone's bump-at-start
landed before the close merged — Auto-Tag named the wrong thing, and the three-field gate then
refused the hotfix that had to follow. The compare step is RUN under bash in the suite against a
scratch PM tree, 11 rows, that PR among the refused.
