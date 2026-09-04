---
id: 0.24.0/bugs/index-is-derivable-under-an-instanced-parent
milestone: "0.24.0"
name: "a created node whose PARENT is an instanced subtree takes a derivable `index=`, and canonicalize drops it"
status: closed
caught_in: "0.24.0"
fix_milestone:
caused_by:
---

# index-is-derivable-under-an-instanced-parent

## Verdict: the ordinal is derivable, the attribute is not — and they are different claims

Re-measured 2026-09-04 against the corpus as it stands. **The rule this bug asks for cannot
ship**, and the sibling bug's conclusion survives, though not for the reason it gave. Everything
below is a census, not a reading: the numbers are reproduced by `make smoke`'s
`canonicalize invents no index` row, which landed with this investigation.

A created node appended under an instanced parent DOES land after that base's own children, so the
ordinal is countable offline. Whether Godot's writer EMITS `index=` there is a separate question,
and the corpus answers it in both directions at once.

## What the measurement says now — the filed numbers are stale

**trail repaired the three mismatches** at `55e52a79` ("three stale body indices against
side_menu_modal (2 -> 3)"), the day after they were filed. So the table in this bug's own opening
no longer describes any file: all 10 root-level created bodies are append-correct today, and there
are no mismatches left to keep visible. Round-trip census at that HEAD, degrade -> canonicalize
over every tracked scene:

| | scenes | round-trip failures | authored `index=` | restored | invented | not derivable |
|---|---|---|---|---|---|---|
| trail | 116 | **10** | 17 | 5 | 0 | 12 |
| nullbound | 194 | **0** | 39 | 39 | 0 | 0 |

## Why no discriminator exists

The bug reads the ten indexed nodes as a population and asks what rule reproduces them. Resolving
each created node's parent THROUGH nested instances into the base tree — which the filed analysis
did not do — turns up twice as many siblings as it knew about:

| position | scenes | carries `index=` |
|---|---|---|
| created node directly under an inherited root, base root places 2 or 3 children | 10 | **yes**, always the append value |
| created node directly under an inherited root, base root places 4 children | 4 | **no** (`force_resolution` ×3, `game_over` ×1) |
| created node appending into a base container the base leaves EMPTY | 6 | **no** (all `Card/Inner/Content/Body`) |
| created node under a node the scene itself built, inside an instanced subtree | 190 | **no** — except 2 hand-typed ones in `dossier.tscn`, whose 18 siblings carry none |

Ten for, ten against, same repo, same position, nothing structural between them. And trail cannot
arbitrate its own inconsistency: **all 116 of its scenes carry a `;` comment**, so not one has been
through `ResourceSaver` since it was written. Every one of the 21 inherited-scenes-with-children in
the entire reachable corpus — both consumers plus this package's own fixtures — is hand-authored.

**nullbound is the engine-written half and it says no, loudly, where it can speak: 194 scenes, 1008
created nodes, NOT ONE carrying an `index=`** — including 87 whose parent is a node the base
provides. It has no inherited scene with a written child, so it cannot speak to the position in
dispute, and that is the whole gap.

## The rules, measured rather than argued

Each was implemented against the real pipeline and run over both trees:

| rule | trail failing | trail invented | nullbound failing | nullbound invented |
|---|---|---|---|---|
| ship today | 10 | **0** | 0 | **0** |
| as filed — "the parent is an instanced subtree" | 16 | 38 | **26** | 87 |
| …with the next-free-slot fallback | — | 314 | — | 186 |
| narrowed to inherited scenes | 3 | 4 | 0 | 0 |
| …and to a base that places ≥1 child | 3 | 4 | 0 | 0 |

The rule **as this bug states it** takes nullbound from 0 failing scenes to 26 and invents 125
attributes; with the plausible fallback it invents 500, which is the 505 the sibling bug measured.
The narrowest form buys trail 10 failures -> 3 and invents exactly the four this bug named as its
own stop signal — `MontageView` -> `4`, `ResultsView` -> `5`, `Timer` -> `6`, `Center` -> `4`.

**Prediction for the four, asked for explicitly: every rule that restores the ten gives all four an
index.** There is no version of the discriminator that separates them, so the bug's own stop
condition is met and the restoration is refused.

## What landed instead

- `make smoke` gains **`canonicalize invents no index`**, over every tracked scene on both consumers
  rather than the one the round-trip row picks. Green today at 310/310, and proven by mutation to
  red on the filed rule (500 inventions), on the narrowest form (4), and to name the culprits.
  The round-trip counts ride in that row's detail — reported, never gated, so they cannot go stale
  again the way this bug's opening did.
- Seven cases in `tests/test_canonicalize.py::ACreatedNodeGainsNoIndexWhateverItsParentIs`, one per
  shape the inventions came from, each proven red under the rule it refuses, with the override in
  both fixtures still restored so none can pass on a tool that does nothing.
- `_restore_indexes` keeps the skip and its stated reason is now the census above; the previous
  comment cited the three mismatches trail has since repaired.

## The one experiment that settles it, and the best file to run it on

Still an engine question and nothing in the corpus can answer it: **does `pack()` emit `index=` for
a created node in an inherited scene?**

Re-save **`trail/scenes/moments/force_resolution.tscn`** in the Godot editor — better than one of
the ten, because it holds all three positions at once and separates all four outcomes in one
save. Revert afterwards; nothing needs committing.

| what the re-saved file does | what it means |
|---|---|
| `PaperBg`/`Payload` keep `index=`; `MontageView`/`ResultsView`/`Timer` gain `4`/`5`/`6`; the nodes under `MontageVBox` gain indexes too | the engine indexes EVERY non-root node of an inherited scene. This bug is real and much larger than filed: trail's inherited scenes are ~200 attributes short, and the tool should write all of them. |
| the three gain `4`/`5`/`6`, deeper created nodes gain nothing | the narrowest rule is right and the four are trail data bugs. Restore, and trail repairs those two files. |
| nothing changes | the ten indexed bodies are hand-authored noise, the tool is right as it stands, and this bug closes. |
| `PaperBg`/`Payload` LOSE their `index=` | the sibling bug's premise is wrong too and the whole restoration needs re-deriving. |

## The widening is still blocked, and now on one thing

`make smoke`'s `canonicalize round trip` row stays one scene per consumer. It can widen on nullbound
(194/194) and cannot on trail, where 10 of 116 fail — all ten of them a created node's authored
`index=`, none of them a defect this package can fix. If trail dropped those ten attributes the row
would widen unchanged on both consumers; if the engine answer says the attribute belongs there, the
row widens once the tool writes it. Either way it is one decision, not three.

## Disposition for 0.24.0 — PARKED, deliberately, and here is the posture

**Parked, not fixed.** The investigation is complete; the restoration was refused on measurement, and
what shipped instead is a guard in the direction that matters.

**Why this is a defensible release posture:**

- **The tool is correct today by the only evidence available.** nullbound is the engine-written half
  of the reachable corpus — **1065 created nodes, zero carrying an `index=`** — and canonicalize
  invents zero across both consumers.
- **The direction is now gated, not merely believed.** `make smoke` carries
  `canonicalize invents no index` over all 310 tracked scenes on both consumers, mutation-proven to
  redden at 500 inventions under the filed rule and at 4 under the narrowest one, naming each culprit.
  A regression toward invention is caught by a gate rather than by someone re-deriving this census.
- **The refused change was the risky one.** Implementing the rule as filed took nullbound from 0
  failing scenes to 26 and invented 87 attributes. Shipping nothing is strictly safer than shipping
  that, and the cost of waiting is one narrow smoke row staying pinned to one scene per consumer.
- **The open question cannot be answered by this package.** It never boots Godot, and no reachable
  corpus contains an engine-written inherited scene with children — all 21 are hand-authored. Waiting
  on an experiment is honest; guessing to close a bug before a release is not.

**What unparks it:** the editor experiment above, on
`trail/scenes/moments/force_resolution.tscn`. Its four outcomes are already mapped to four different
answers, so whoever runs it does not need to re-read this bug to know what it means.

**What must NOT happen in the meantime:** do not "fix" `BaseScenes.child_index` to agree with a
file, or a file to agree with the counter. A tool that rewrites a number it disagrees with is the
invention failure this whole line of bugs is about.
