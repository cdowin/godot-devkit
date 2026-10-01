---
id: roadmap
kind: roadmap
order:
  - "ms-build-wide-integrate-once"
---

# The release plan

The order releases ship in. It is a DECISION, not a sort: `order` lists the
MILESTONE IDS, in sequence, and each milestone's own `version:` says which
release it is — so a milestone that re-versions never touches this file.

`make pm ARGS='add <this-id> <milestone-id>'` schedules one, exactly as it
sequences a feature under a milestone or a story under a feature. Authoring and
scheduling stay separate acts: a milestone declares `version:` without joining
the plan.
