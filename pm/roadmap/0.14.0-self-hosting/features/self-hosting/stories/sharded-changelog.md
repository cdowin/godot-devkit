---
id: 0.14.0/self-hosting/sharded-changelog
feature: 0.14.0/self-hosting
milestone: "0.14.0"
name: the CHANGELOG is rendered from the tree
status: wip
owner:
estimate:
depends_on: []
labels: []
---

# the CHANGELOG is rendered from the tree

The 0.14.0 section of CHANGELOG.md is `pm changelog --render` output. Nobody
types a release note into that file again.

## Acceptance criteria

- Every 0.14.0 entry appended through `pm changelog`, one sentence a consumer
  would recognise plus a commit hash as `Evidence:`.
- Rationale that had a rejected alternative lives in `decisions.md` instead.
- Three consecutive renders are byte-identical to what is committed.
- `## v0.13.0` and everything below it is untouched, under a stated boundary
  saying why the halves are different.

## Out of scope

Migrating the frozen history. It was written before the tooling existed and
re-deriving entries for it would be invention, not a migration.
