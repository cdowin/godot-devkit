---
id: ft-the-1-4-0-carry-forwards
kind: feature
milestone: ms-future-godot-tooling
name: the 1.4.0 carry forwards
status: planning
reviewed:
depends_on: []
consumed_by: []
changelog:
---

# the 1.4.0 carry forwards

The MINOR/NIT findings the 1.4.0 lane reviews deferred, each named with its record in the disposition table of docs/reviews/2026-09-29-1.4.0-*.md (`deferred: 1.6.0`). Sweep them in one lane.

Two amendments since the reviews:

- **Moved out:** the read-verbs review's N3 (the `refs` dynamic-bucket spellings) is part of
  ft-refs-reads-scene-connections now.
- **Added:** `pyproject.toml`'s `description` still advertises `doc`, `shell`, `repo-hygiene` and the
  PM tracker, which left in 0.25.0. It is the package's PyPI-facing summary; make it say what ships.

## Ship criterion

<!-- What "done" means for this feature. -->

## Proof budget

<!-- Roughly how many test cases this feature should cost, written before it is
     built and compared after. Name the tier and the existing module they land
     in; say what the suite already checks and why that is not enough. -->

  cases:
  tier:
  lands in:
  what already covers this:
