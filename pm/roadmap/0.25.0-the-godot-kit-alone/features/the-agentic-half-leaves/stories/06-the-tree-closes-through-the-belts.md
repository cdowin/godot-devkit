---
id: 0.25.0/the-agentic-half-leaves/06-the-tree-closes-through-the-belts
feature: 0.25.0/the-agentic-half-leaves
milestone: "0.25.0"
name: Every story, this feature and the milestone close through the pinned belts
status: building
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

## Close

done: a02620b 69109b5 69cc01f 1049759 4c4fc74 3dbb02f — stories 01–05 each closed through `agentic-sdlc close story`, every one after its own `[verify] story` (`make pyunit`) run by the belt, never by hand. Story 04 was closed twice: once at 5901e99's pass and again at 4c4fc74 after being reopened for the deeper trim, so the ledger carries its `done -> building -> done` round trip rather than a silent rewrite.

Ordering note, because the belts force it. This story cannot record its own feature and milestone closes: `close feature` refuses while any story is outside the `done` category, so 06 must reach `done` first and the two outer belts run immediately after it. What proves those is the ledger, which is criterion 2's evidence and not this file's — `pm ledger show 0.25.0` carries one belt-written status row per grain, and `pm status 0.25.0` is the live read. Nothing here is hand-copied from either (D-rule: never a second scoreboard).

The review that `close feature` consumes is `pm/roadmap/0.25.0-the-godot-kit-alone/review.md` — RELEASE-WITH-FIXES, eleven findings, all landed in f5ccf8946 and dispositioned in its verdict block. Criterion 1 said push, PR, merge and tag were Chris's; he delegated them in-session on 2026-09-06, so they run from here through `gh` on his account.
