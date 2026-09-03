---
id: 0.22.0/usage-capture/the-grain-is-the-trees-live-state
feature: 0.22.0/usage-capture
milestone: "0.22.0"
name: the dispatch row carries the tree's live state at the hook, never an inferred grain
status: todo
owner:
depends_on: []
---

# the dispatch row carries the tree's live state at the hook, never an inferred grain

## Goal
`pm ledger record` snapshots the tree at write time into `tree: {milestones_building,
features_building, features_review, stories_wip, stories_review}` — every id, verbatim, from the
frontmatter the verbs wrote (D3). No prompt parsing, no commit-prefix search, no `?`. Empty lists are
recorded as empty lists. `pm ledger show <grain-id>` matches a grain anywhere in `tree` as well as in
`grain`.
## Gotchas
The snapshot reads the ACTIVE tree only (excluding `zz_archive/`), through the same walkers
`check pm` uses. A row with every list empty is legitimate and is what the report surfaces as
"unattributed", never dropped.
## Verification
`make test` (fixture tree with one wip story and one review feature → exact lists; an empty tree →
empty lists, exit 0).
## Commit prefix
`feat(0.22.0/usage-capture/S2):`
## Size
s
