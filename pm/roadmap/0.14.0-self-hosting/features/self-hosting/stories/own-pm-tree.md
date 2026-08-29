---
id: 0.14.0/self-hosting/own-pm-tree
feature: 0.14.0/self-hosting
milestone: "0.14.0"
name: devkit grows a PM tree
status: done
owner:
estimate:
depends_on: []
labels: []
---

# devkit grows a PM tree

`pm/roadmap/0.14.0-self-hosting/` exists, was scaffolded by `pm new milestone`
and `pm new feature` rather than by hand, and `devkit.toml` turns on every rule
this package ships.

## Acceptance criteria

- Every canonical slot present, minted by the tool's own scaffolder.
- `[pm] checks` names D1-D18 except D8, plus V1-V6, with no grandfather ledger
  in any of the three ledger keys.
- `check pm` exits 0 and its census names a real tree, not an empty one.

## Out of scope

D8. It encodes bump-at-START and this package bumps at close; switching it on
would mean publishing a version that does not exist yet.
