---
id: 0.25.0/the-agentic-half-leaves/06-the-tree-closes-through-the-belts
feature: 0.25.0/the-agentic-half-leaves
milestone: "0.25.0"
name: Every story, this feature and the milestone close through the pinned belts
status: planning
owner:
depends_on: []
---

# Every story, this feature and the milestone close through the pinned belts

## Acceptance criteria

- Stories 01–05 close through `close story` (each right after its own `make unit`), this feature through `close feature` against its review record, the milestone through `agentic-sdlc release 0.25.0` up to the push; push, PR, merge, tag and the artifact proof are Chris's.
- The ledger carries a status row from a belt for every grain.

## How this is proven

| criterion | tier | the case that proves it | existing? |
|---|---|---|---|
| 1 | n/a | `pm status 0.25.0` and `pm ledger show` | the tree |

## Out of scope

Closing anything by hand.
