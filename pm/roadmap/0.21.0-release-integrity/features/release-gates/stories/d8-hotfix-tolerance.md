---
id: 0.21.0/release-gates/d8-hotfix-tolerance
feature: 0.21.0/release-gates
milestone: "0.21.0"
name: check pm D8 accepts a hotfix id.N for an id in the tree
status: done
owner:
depends_on: []
---

# check pm D8 accepts a hotfix id.N for an id in the tree

In `repo/checks/pm.py`, D8 passes when the shipped version is `<id>.N` for any milestone id in the tree (`model.known_milestones`). Proof: `tests/test_pm_gate.py` — a hotfix of the building id passes, a `.N` on an id not in the tree fails, a letter suffix fails.
