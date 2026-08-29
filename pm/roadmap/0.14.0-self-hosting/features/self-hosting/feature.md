---
id: 0.14.0/self-hosting
milestone: "0.14.0"
name: devkit runs its own gates on its own tree
status: building
reviewed:
risk: medium
size: m
phase:
depends_on: []
consumed_by: []
labels: []
---

# devkit runs its own gates on its own tree

A toolkit whose own repo cannot pass its own gates is a toolkit nobody should
trust. This stands up the PM tree, points every rule at it, and moves the
release notes out of a hand-written 200-line CHANGELOG section into per-entry
appends the tooling writes.

It earns its slot for a reason a demo repo could not: the gates have to keep
passing here on every future commit, so a rule that only works on the author's
imagination gets found the day it lands rather than in a consumer's CI.

## Ship criterion

`check all` and `check pm` both exit 0 at the repo root, the 0.14.0 CHANGELOG
section is rendered rather than typed, and every rule that turned out not to
fit is recorded in `decisions.md` with what was rejected — not quietly dropped
from the config.
